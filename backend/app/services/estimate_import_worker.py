from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models import (
    Estimate,
    EstimateBatch,
    EstimateQuantityProjection,
    StageInstanceProjectionSummary,
)
from app.models.stage10 import EstimateImportJob, EstimatePreviewRow, EstimatePreviewSession, TransactionalOutbox
from app.services.dynamic_floor_feature_flag import DynamicFloorFeatureGate
from app.services.canonical_json_service import CanonicalJsonServiceV2
from app.services.floor_structure_service import build_stage_instances, validate_building_params
from app.services.semantic_options_service import (
    STRICT_STAGE_OPTION_CONTRACT_VERSION,
    StageOptionValidationError,
    generate_semantic_operation_projections,
    resolve_semantic_options,
    validate_required_stage_options,
)
from app.services.source_identity_service import resolve_work_scope_key
from app.services.taxonomy_snapshot_service import load_immutable_taxonomy_snapshot


OUTBOX_MAX_PUBLICATION_ATTEMPTS = 6
MATERIALIZATION_ROW_BATCH_SIZE = 250
SEMANTIC_RESOLUTION_FAILURE = "semantic_stage_option_resolution_failed"
GENERIC_IMPORT_FAILURE = "estimate_import_failed"
DATABASE_IMPORT_FAILURE = "estimate_import_database_error"
DATABASE_INTEGRITY_FAILURE = "estimate_import_integrity_error"

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _exception_reason_code(exc: Exception) -> str:
    """Return a stable DB-safe reason code; keep verbose diagnostics in reason_details."""
    if isinstance(exc, IntegrityError):
        return DATABASE_INTEGRITY_FAILURE
    if isinstance(exc, DBAPIError):
        return DATABASE_IMPORT_FAILURE
    for attribute in ("reason_code", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()[:128]
    message = str(exc).strip()
    if message == SEMANTIC_RESOLUTION_FAILURE:
        return SEMANTIC_RESOLUTION_FAILURE
    if message and len(message) <= 128 and re.fullmatch(r"[a-z0-9][a-z0-9_.:-]*", message):
        return message
    return GENERIC_IMPORT_FAILURE


@dataclass(frozen=True)
class WorkerRunResult:
    job_id: str
    status: str
    reason_code: str | None = None
    materialized_estimate_count: int = 0


class EstimateImportCommandConsumer:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def enqueue(self, payload: dict[str, Any], *, outbox_record_id: str | None = None) -> EstimateImportJob:
        idempotency_key = str(payload.get("idempotency_key") or "")
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        existing = await self.db.scalar(
            select(EstimateImportJob).where(EstimateImportJob.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing
        now = utcnow()
        job = EstimateImportJob(
            id=str(uuid4()),
            preview_session_id=str(payload["preview_session_id"]),
            estimate_batch_id=str(payload["estimate_batch_id"]),
            outbox_record_id=outbox_record_id,
            idempotency_key=idempotency_key,
            status="queued",
            attempt_count=0,
            snapshot_payload_version=payload.get("snapshot_payload_version"),
            snapshot_hash_algorithm=payload.get("snapshot_hash_algorithm"),
            snapshot_hash=payload.get("snapshot_hash"),
            queued_at=now,
            created_at=now,
            updated_at=now,
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)
        return job


class TransactionalOutboxPublisher:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def publish_due(self, *, limit: int = 100) -> int:
        now = utcnow()
        rows = list(
            await self.db.scalars(
                select(TransactionalOutbox)
                .where(TransactionalOutbox.status.in_(("pending", "publishing")))
                .where(or_(TransactionalOutbox.next_attempt_at.is_(None), TransactionalOutbox.next_attempt_at <= now))
                .order_by(TransactionalOutbox.created_at, TransactionalOutbox.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        consumer = EstimateImportCommandConsumer(self.db)
        published = 0
        for row in rows:
            row.status = "publishing"
            row.attempt_count = int(row.attempt_count or 0) + 1
            row.updated_at = utcnow()
            await self.db.flush()
            try:
                await consumer.enqueue(row.payload, outbox_record_id=row.id)
            except Exception as exc:
                row.last_error_code = "import_job_publication_failed"
                row.last_error_details = {"exception_type": type(exc).__name__, "message": str(exc)}
                if row.attempt_count >= OUTBOX_MAX_PUBLICATION_ATTEMPTS:
                    row.status = "dead_letter"
                    row.dead_lettered_at = utcnow()
                else:
                    row.status = "pending"
                    delay_seconds = min(300, 2 ** row.attempt_count)
                    row.next_attempt_at = utcnow() + timedelta(seconds=delay_seconds)
            else:
                row.status = "published"
                row.published_at = utcnow()
                row.next_attempt_at = None
                row.last_error_code = None
                row.last_error_details = None
                published += 1
            row.updated_at = utcnow()
        await self.db.commit()
        return published

    async def replay_dead_letter(self, outbox_record_id: str) -> TransactionalOutbox:
        row = await self.db.get(TransactionalOutbox, str(outbox_record_id))
        if row is None:
            raise KeyError("outbox_record_not_found")
        if row.status != "dead_letter":
            raise ValueError("outbox_record_not_dead_letter")
        row.status = "pending"
        row.attempt_count = 0
        row.next_attempt_at = utcnow()
        row.last_error_code = None
        row.dead_lettered_at = None
        row.updated_at = utcnow()
        await self.db.commit()
        await self.db.refresh(row)
        return row


def _hierarchy_selection_from_batch(batch: EstimateBatch) -> dict[str, Any]:
    snapshot = batch.taxonomy_snapshot if isinstance(batch.taxonomy_snapshot, dict) else {}
    estimate_type_snapshot = snapshot.get("estimate_type") if isinstance(snapshot.get("estimate_type"), dict) else {}
    variant_snapshot = snapshot.get("variant") if isinstance(snapshot.get("variant"), dict) else {}
    return {
        "estimate_kind": batch.estimate_kind or estimate_type_snapshot.get("estimate_kind"),
        "estimate_type_id": batch.estimate_type_id or estimate_type_snapshot.get("id"),
        "estimate_type_title": batch.estimate_type_title or estimate_type_snapshot.get("title"),
        "estimate_type_number": batch.estimate_type_number or estimate_type_snapshot.get("number"),
        "project_variant_id": batch.project_variant_id or snapshot.get("project_variant_id") or variant_snapshot.get("id"),
        "project_variant_title": batch.project_variant_title or variant_snapshot.get("title"),
        "project_variant_number": batch.project_variant_number or variant_snapshot.get("number"),
        "taxonomy_dictionary_version": batch.taxonomy_dictionary_version or snapshot.get("source_dictionary_version"),
    }


def _resolve_import_semantic_context(
    *,
    session: EstimatePreviewSession,
    batch: EstimateBatch,
    job: EstimateImportJob,
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    snapshot_payload = session.snapshot_payload if isinstance(session.snapshot_payload, dict) else None
    if not snapshot_payload:
        raise RuntimeError(SEMANTIC_RESOLUTION_FAILURE)
    actual_payload_hash = hashlib.sha256(
        CanonicalJsonServiceV2.dump_bytes(snapshot_payload)
    ).hexdigest()
    if actual_payload_hash != session.snapshot_hash or actual_payload_hash != job.snapshot_hash:
        raise RuntimeError(SEMANTIC_RESOLUTION_FAILURE)

    snapshot = batch.taxonomy_snapshot if isinstance(batch.taxonomy_snapshot, dict) else None
    if not snapshot:
        raise RuntimeError(SEMANTIC_RESOLUTION_FAILURE)
    try:
        immutable = load_immutable_taxonomy_snapshot(snapshot)
        immutable.assert_integrity(snapshot)
    except Exception as exc:  # noqa: BLE001 - normalized import integrity failure
        raise RuntimeError(SEMANTIC_RESOLUTION_FAILURE) from exc
    variant = snapshot.get("variant") if isinstance(snapshot.get("variant"), dict) else None
    if not variant:
        raise RuntimeError(SEMANTIC_RESOLUTION_FAILURE)

    payload_options = snapshot_payload.get("project_structure_options")
    payload_building = snapshot_payload.get("building_params")
    batch_options = batch.project_structure_options if isinstance(batch.project_structure_options, dict) else {}
    batch_building = batch.building_params if isinstance(batch.building_params, dict) else {}
    if payload_options != session.project_structure_options or payload_options != batch_options:
        raise RuntimeError(SEMANTIC_RESOLUTION_FAILURE)
    if payload_building != session.building_params or payload_building != batch_building:
        raise RuntimeError(SEMANTIC_RESOLUTION_FAILURE)

    try:
        params = validate_building_params(batch_building, variant)
        stages = build_stage_instances(variant, params)
        strict_contract = str(variant.get("stage_option_selection_contract_version") or "") == STRICT_STAGE_OPTION_CONTRACT_VERSION
        if strict_contract:
            stage_by_id = {
                str(stage.get("canonical_stage_id") or ""): stage
                for stage in variant.get("stages") or []
                if isinstance(stage, dict)
            }
            for group in variant.get("branch_groups") or []:
                if not isinstance(group, dict):
                    raise RuntimeError(SEMANTIC_RESOLUTION_FAILURE)
                stage = stage_by_id.get(str(group.get("canonical_stage_id") or ""))
                allowed = {
                    str(option.get("id") or "")
                    for option in (stage or {}).get("stage_options") or []
                    if isinstance(option, dict)
                }
                if stage is None or not set(map(str, group.get("option_ids") or [])).issubset(allowed):
                    raise RuntimeError(SEMANTIC_RESOLUTION_FAILURE)
            validation = validate_required_stage_options(
                variant=variant,
                stage_instances=stages,
                building_params=batch_building,
                submitted_project_structure_options=batch_options,
            )
            if validation.normalized_options != batch_options:
                raise RuntimeError(SEMANTIC_RESOLUTION_FAILURE)
            report = resolve_semantic_options(
                variant,
                stages,
                project_structure_options=batch_options,
            )
            if not report.valid:
                raise RuntimeError(SEMANTIC_RESOLUTION_FAILURE)
            for stage in stages:
                mode = str(stage.get("stage_options_mode") or "none")
                if mode == "selectable_one":
                    singular = stage.get("semantic_stage_option_id")
                    plural = stage.get("semantic_stage_option_ids") or []
                    if (
                        plural != ([singular] if singular else [])
                        or not singular
                        or not stage.get("semantic_stage_option_title")
                        or stage.get("stage_option_source") not in {
                            "project_structure_options",
                            "auto_single_allowed_option",
                        }
                    ):
                        raise RuntimeError(SEMANTIC_RESOLUTION_FAILURE)
    except (StageOptionValidationError, ValueError, TypeError, KeyError) as exc:
        raise RuntimeError(SEMANTIC_RESOLUTION_FAILURE) from exc
    return dict(variant), stages, strict_contract


def _apply_confirmed_stage_options(
    rows: list[SimpleNamespace],
    *,
    variant: dict[str, Any],
    resolved_stages: list[dict[str, Any]],
) -> None:
    stage_by_instance = {
        str(stage.get("stage_instance_id") or ""): stage for stage in resolved_stages
    }
    stage_by_canonical: dict[str, dict[str, Any]] = {}
    for stage in resolved_stages:
        stage_by_canonical.setdefault(str(stage.get("canonical_stage_id") or ""), stage)
    option_ids_by_stage = {
        str(stage.get("canonical_stage_id") or ""): {
            str(option.get("id") or "")
            for option in stage.get("stage_options") or []
            if isinstance(option, dict)
        }
        for stage in variant.get("stages") or []
        if isinstance(stage, dict)
    }
    facade_stage_id = "residential_construction.naruzhnaya_fasadnaya_otdelka"

    for row in rows:
        raw = row.raw_data if isinstance(row.raw_data, dict) else {}
        stage = stage_by_instance.get(str(raw.get("stage_instance_id") or ""))
        if stage is None:
            stage = stage_by_canonical.get(str(raw.get("canonical_stage_id") or ""))
        if stage is None or str(stage.get("stage_options_mode") or "none") != "selectable_one":
            continue
        selected = stage.get("semantic_stage_option_id")
        if not selected:
            raise RuntimeError(SEMANTIC_RESOLUTION_FAILURE)
        canonical_stage_id = str(stage.get("canonical_stage_id") or "")
        raw_detected = raw.get("semantic_stage_option_id") or raw.get("stage_option_id")
        detected = str(raw_detected) if raw_detected in option_ids_by_stage.get(canonical_stage_id, set()) else None
        conflict = bool(detected and detected != selected)
        if selected == "no_finish" and canonical_stage_id == facade_stage_id and raw.get("row_role", "work") == "work":
            conflict = True

        raw["selected_semantic_stage_option_id"] = selected
        raw["detected_semantic_stage_option_id"] = detected
        raw["semantic_stage_option_id"] = selected
        raw["semantic_stage_option_ids"] = [selected]
        raw["semantic_stage_option_title"] = stage.get("semantic_stage_option_title")
        raw["stage_option_id"] = selected
        raw["stage_option_title"] = stage.get("semantic_stage_option_title")
        raw["stage_option_source"] = "project_structure_options"
        raw["stage_option_conflict"] = conflict
        raw["execution_applicability"] = stage.get("execution_applicability", "applicable")
        if conflict:
            raw["needs_review"] = True
            raw["operator_review_required"] = True
            raw["review_reason"] = "stage_option_conflicts_with_project_selection"
            raw["operator_review_reason"] = "stage_option_conflicts_with_project_selection"
            raw["resolution_status"] = "needs_review"
            raw["calculation_blocked"] = True
            raw["reason_code"] = "stage_option_conflicts_with_project_selection"
        else:
            raw.setdefault("resolution_status", "resolved")
            raw.setdefault("calculation_blocked", False)
        row.raw_data = raw


def _prepare_stage10_rows_for_materialization(
    snapshot_rows: list[dict[str, Any]],
    batch: EstimateBatch,
    *,
    variant: dict[str, Any] | None = None,
    resolved_stages: list[dict[str, Any]] | None = None,
) -> list[SimpleNamespace]:
    materialized_rows: list[SimpleNamespace] = []
    for index, row in enumerate(snapshot_rows):
        if row.get("confirmation_approved") is False:
            continue
        parsed = row.get("parsed_data") if isinstance(row.get("parsed_data"), dict) else {}
        raw = dict(parsed.get("raw_data") if isinstance(parsed.get("raw_data"), dict) else {})
        raw.update(row.get("classification_result") if isinstance(row.get("classification_result"), dict) else {})
        raw.setdefault("source_row_key", row.get("source_row_key"))
        raw.setdefault("source_scope_id", row.get("source_scope_id"))
        raw.setdefault("source_row_index", row.get("source_row_index", index))
        raw.setdefault("item_type", raw.get("item_type") or "work")
        materialized_rows.append(
            SimpleNamespace(
                section=parsed.get("section"),
                work_name=parsed.get("work_name") or row.get("source_text") or "Imported row",
                unit=parsed.get("unit"),
                quantity=parsed.get("quantity"),
                unit_price=parsed.get("unit_price"),
                total_price=parsed.get("total_price"),
                materials=parsed.get("materials"),
                raw_data=raw,
                stage10_snapshot_row=row,
            )
        )

    if materialized_rows:
        from app.services.upload_service import (
            _enrich_work_stages_sync,
            _enrich_work_subtypes_sync,
        )

        hierarchy_selection = _hierarchy_selection_from_batch(batch)
        _ensure_stage10_building_params(batch, materialized_rows)
        preclassified = _enrich_work_subtypes_sync(materialized_rows, hierarchy_selection)
        if resolved_stages is None:
            _enrich_work_stages_sync(
                materialized_rows,
                hierarchy_selection,
                preclassified,
                batch.building_params if isinstance(batch.building_params, dict) else None,
            )
        else:
            from app.services.stage_classifier import StageClassifier
            from app.services.work_taxonomy_service import get_sequential_scoring_policy

            classifier = StageClassifier(get_sequential_scoring_policy())
            for row in materialized_rows:
                raw = row.raw_data if isinstance(row.raw_data, dict) else {}
                match = classifier.classify_row_to_stage(
                    " ".join(str(value or "") for value in (row.section, row.work_name)),
                    str(raw.get("row_role") or "work"),
                    resolved_stages,
                    estimate_profile_id=str(hierarchy_selection.get("estimate_type_id") or ""),
                )
                raw.update(match.as_raw_data(
                    estimate_type_id=str(hierarchy_selection.get("estimate_type_id") or ""),
                    estimate_type_number=str(hierarchy_selection.get("estimate_type_number") or ""),
                    project_variant_id=str(hierarchy_selection.get("project_variant_id") or ""),
                    project_variant_number=str(hierarchy_selection.get("project_variant_number") or ""),
                    row_role=str(raw.get("row_role") or "work"),
                ))
                row.raw_data = raw
        _apply_stage10_text_overrides(materialized_rows, batch, stages=resolved_stages)
        if variant is not None and resolved_stages is not None:
            _apply_confirmed_stage_options(
                materialized_rows,
                variant=variant,
                resolved_stages=resolved_stages,
            )
            from app.services.quantity_projection_service import enrich_quantity_projections

            evidence: list[dict[str, Any]] = []
            for row in materialized_rows:
                raw = row.raw_data if isinstance(row.raw_data, dict) else {}
                if raw.get("calculation_blocked") or not raw.get("operation_code"):
                    continue
                evidence.append({
                    "stage_instance_id": raw.get("stage_instance_id"),
                    "semantic_stage_option_id": raw.get("semantic_stage_option_id"),
                    "operation_code": raw.get("operation_code"),
                    "operation_package_code": raw.get("operation_package_code"),
                    "source_row_key": raw.get("source_row_key"),
                    "work_scope_key": raw.get("work_scope_key") or resolve_work_scope_key(raw.get("source_row_key")),
                    "applicability_hash": raw.get("applicability_hash"),
                    "applicability_hash_version": raw.get("applicability_hash_version"),
                    "applicability_schema_version": raw.get("applicability_schema_version"),
                    "quantity": row.quantity,
                    "unit_code": row.unit,
                    "quantity_source": "explicit",
                    "materialization_source": "matched_to_source_row",
                })
            generate_semantic_operation_projections(
                variant, resolved_stages, evidence=evidence
            )
            enrich_quantity_projections(
                materialized_rows,
                variant=variant,
                stage_instances=resolved_stages,
            )
    return materialized_rows


def _snapshot_row_from_preview_row(row: EstimatePreviewRow) -> dict[str, Any]:
    return {
        "source_row_key": row.source_row_key,
        "source_scope_id": row.source_scope_id,
        "source_row_index": row.source_row_index,
        "source_text": row.source_text,
        "parsed_data": row.parsed_data,
        "classification_result": row.classification_result,
        "confirmation_approved": row.confirmation_approved,
        "confirmation_manual_override": row.confirmation_manual_override,
    }


def _estimate_insert_values(est: Estimate) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for column in Estimate.__table__.columns:
        value = getattr(est, column.name)
        if value is None and (column.default is not None or column.server_default is not None):
            continue
        values[column.name] = value
    return values


_FLOOR_WORDS: dict[str, int] = {
    "перв": 1,
    "втор": 2,
    "трет": 3,
    "четверт": 4,
    "пят": 5,
    "шест": 6,
    "седьм": 7,
    "восьм": 8,
    "девят": 9,
    "десят": 10,
}


def _valid_stage10_building_params(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("floors_count"), int)
        and not isinstance(value.get("floors_count"), bool)
        and value.get("floors_count") > 0
        and isinstance(value.get("has_basement", False), bool)
        and isinstance(value.get("has_mansard", False), bool)
    )


def _infer_stage10_building_params(rows: list[SimpleNamespace]) -> dict[str, Any]:
    text = "\n".join(
        " ".join(
            str(part or "")
            for part in (
                getattr(row, "section", None),
                getattr(row, "work_name", None),
                (row.raw_data or {}).get("section_title") if isinstance(row.raw_data, dict) else None,
                (row.raw_data or {}).get("section_description") if isinstance(row.raw_data, dict) else None,
            )
        )
        for row in rows
    ).lower().replace("ё", "е")
    has_basement = bool(re.search(r"\b(цокол|цоколь|подвал|подземн)\w*", text))
    has_mansard = bool(re.search(r"\bмансард\w*", text))
    floors: set[int] = set()
    for match in re.finditer(r"\b(\d{1,2})\s*(?:[-–]?\s*(?:го|й|ый|ой|его|ем|ом))?\s+(?:мансардн\w+\s+)?этаж", text):
        number = int(match.group(1))
        if number > 0:
            floors.add(number)
    for stem, number in _FLOOR_WORDS.items():
        if re.search(rf"\b{stem}\w*\s+(?:мансардн\w+\s+)?этаж", text):
            floors.add(number)
    floors_count = max(floors) if floors else (1 if has_mansard else 0)
    if floors_count <= 0:
        floors_count = 1
    return {
        "floors_count": floors_count,
        "has_basement": has_basement,
        "has_mansard": has_mansard,
    }


def _ensure_stage10_building_params(batch: EstimateBatch, rows: list[SimpleNamespace]) -> None:
    if _valid_stage10_building_params(batch.building_params):
        return
    inferred = _infer_stage10_building_params(rows)
    batch.building_params = inferred


def _stage10_floor_number(text: str, building_params: dict[str, Any]) -> int | None:
    if re.search(r"\b(цокол|цоколь|подвал)\w*", text):
        return 0
    if re.search(r"\bмансард\w*", text):
        return int(building_params.get("floors_count") or 1)
    digit = re.search(r"\b(\d{1,2})\s*(?:[-–]?\s*(?:го|й|ый|ой|его|ем|ом))?\s+этаж", text)
    if digit:
        return int(digit.group(1))
    for stem, number in _FLOOR_WORDS.items():
        if re.search(rf"\b{stem}\w*\s+этаж", text):
            return number
    return None


def _stage10_text_stage_number(text: str, building_params: dict[str, Any]) -> tuple[str | None, bool]:
    floor = _stage10_floor_number(text, building_params)
    if re.search(r"\b(геодез|разбивк|оси здания)\w*", text):
        return "2.7.1", False
    if re.search(r"(обратн\w*\s+отсыпк|засыпк\w*\s+пазух)", text):
        return "2.7.6", False
    if re.search(r"\bотсечн\w*\s+гидроизоляц\w*", text) and re.search(r"\b(кирпич|стен|цокол|цоколь)\w*", text):
        return "2.7.3", False
    if re.search(r"\b(сборн\w*\s+)?железобетонн\w*\s+перемыч", text) and re.search(r"\b(цокол|цоколь|подвал)\w*", text):
        return "2.7.9", False
    if re.search(r"\b(кладк\w*\s+)?(?:внутренн\w*\s+)?перегород", text) and re.search(r"\b(цокол|цоколь|подвал)\w*", text):
        return "2.7.11", False
    if re.search(r"\b(стропил|кровл|пароизоляц|гидроветр|металлочереп|мембран)\w*", text):
        return f"2.7.T{int(building_params.get('floors_count') or 1)}.60", False
    if re.search(r"\b(утеплен|утепл)\w*", text) and re.search(r"(фасад|наружн\w*\s+кирпичн\w*\s+стен)", text):
        return "2.7.13", False
    if re.search(r"\b(гидроизоляц)\w*", text) or (
        re.search(r"\b(утеплен|утепл)\w*", text) and re.search(r"\b(фундамент|цокол|цоколь)\w*", text)
    ):
        return "2.7.5", False
    if re.search(r"\b(котлован|грунт|песчан|фундаментн\w*\s+плит|опалубк|армирован|бетонирован)\w*", text) and floor is None:
        return "2.7.2", False
    if re.search(r"\b(цокол|цоколь)\w*", text):
        if re.search(r"\b(перекрыт|плит\w*\s+перекрыт|стяжк|между плит)\w*", text):
            return "2.7.B0.20", False
        return "2.7.B0.10", False
    if re.search(r"\b(армопояс|мауэрлат)\w*", text):
        return f"2.7.T{int(building_params.get('floors_count') or 1)}.50", False
    if re.search(r"\b(облицовк|фасадн\w*\s+отделк|расшивк)\w*", text):
        return "2.7.16", False
    if re.search(r"\b(перемычк)\w*", text):
        if floor and floor > 0:
            return f"2.7.F{floor}.20", False
        return "2.7.F1.20", True
    if re.search(r"\b(перекрыт)\w*", text):
        if floor and floor > 0:
            return f"2.7.F{floor}.30", False
        return "2.7.F1.30", True
    if re.search(r"\b(перегород)\w*", text):
        if floor and floor > 0:
            return f"2.7.F{floor}.40", False
        return "2.7.F1.40", True
    if re.search(r"\b(кладк|стен|вентиляционн\w*\s+канал|деформационн\w*\s+шв)\w*", text):
        if floor and floor > 0:
            return f"2.7.F{floor}.10", False
        return "2.7.F1.10", True
    return None, False


def _stage10_text_subtype_code(text: str) -> str | None:
    if re.search(r"\b(геодез|разбивк)\w*", text):
        return "earthworks/terrain_reshaping"
    if re.search(r"(обратн\w*\s+отсыпк|засыпк\w*\s+пазух)", text):
        return "earthworks/backfill"
    if re.search(r"\b(котлован|доработк\w*\s+грунт)\w*", text):
        return "earthworks/excavation_pit_trench"
    if re.search(r"\b(песчан\w*\s+подготов)\w*", text):
        return "foundation/foundation_preparation_layers"
    if re.search(r"\b(опалубк|армирован|бетонирован)\w*", text) and re.search(r"\b(фундаментн\w*\s+плит|фундамент)\w*", text):
        return "foundation/slab_foundation"
    if re.search(r"\b(гидроизоляц|отсечн\w*\s+гидроизоляц)\w*", text):
        return "waterproofing/underground_structure_waterproofing"
    if re.search(r"\b(пароизоляц|гидроветр|утеплен\w*\s+скатн\w*\s+кровл|утепл\w*\s+кровл)\w*", text):
        return "roofing/roof_insulation_vapor_barrier"
    if re.search(r"\b(утеплен|утепл)\w*", text) and re.search(r"(фасад|наружн\w*\s+кирпичн\w*\s+стен)", text):
        return "insulation/facade_wall_insulation"
    if re.search(r"\b(утеплен|утепл)\w*", text) and re.search(r"\b(цокол|фундамент)\w*", text):
        return "insulation/foundation_plinth_insulation"
    if re.search(r"\b(перемычк|армопояс)\w*", text):
        return "load_bearing_walls/arm_belts_lintels"
    if re.search(r"\b(перегород)\w*", text) and re.search(r"\b(газобетон|блок)\w*", text):
        return "partitions/block_partitions"
    if re.search(r"\b(перегород)\w*", text):
        return "partitions/brick_partitions"
    if re.search(r"\b(плит\w*\s+перекрыт|сборн\w*\s+железобетонн\w*\s+плит)\w*", text):
        return "floor_slabs/precast_rc_slabs"
    if re.search(r"\b(монолитн\w*\s+железобетонн\w*\s+перекрыт|монолитн\w*\s+перекрыт)\w*", text):
        return "floor_slabs/monolithic_slab"
    if re.search(r"\b(стяжк\w*\s+по грунт)\w*", text):
        return "floor_screed/concrete_floor_on_ground"
    if re.search(r"\b(вентиляционн\w*\s+канал)\w*", text):
        return "load_bearing_walls/vent_shafts_masonry"
    if re.search(r"\b(кладк|стен)\w*", text) and re.search(r"\b(кирпич|силикат)\w*", text):
        return "load_bearing_walls/brick_masonry"
    if re.search(r"\b(мауэрлат)\w*", text):
        return "rafters/mauerlat_embeds"
    if re.search(r"\b(стропил)\w*", text):
        return "rafters/rafters_installation"
    if re.search(r"\b(кровл|металлочереп)\w*", text):
        return "roofing/pitched_roof_covering"
    if re.search(r"\b(облицовк|фасадн\w*\s+отделк|расшивк)\w*", text):
        return "interior_finishing/facade_finishing"
    if re.search(r"\b(деформационн\w*\s+шв)\w*", text):
        return "load_bearing_walls/brick_masonry"
    return None


def _subtype_titles() -> dict[str, str]:
    from app.services.work_taxonomy_service import _load_dictionary

    titles: dict[str, str] = {}
    payload = _load_dictionary()
    for section in payload.get("sections") or []:
        section_id = str(section.get("id") or "")
        for subtype in section.get("subtypes") or []:
            code = f"{section_id}/{subtype.get('id')}"
            titles[code] = str(subtype.get("title") or "")
    return titles


def _apply_stage10_text_overrides(
    rows: list[SimpleNamespace],
    batch: EstimateBatch,
    *,
    stages: list[dict[str, Any]] | None = None,
) -> None:
    building_params = batch.building_params if isinstance(batch.building_params, dict) else {}
    hierarchy = _hierarchy_selection_from_batch(batch)
    if stages is None:
        from app.services.work_taxonomy_service import get_project_variant_stage_instances

        stages = get_project_variant_stage_instances(
            str(hierarchy["estimate_type_id"]),
            str(hierarchy["project_variant_id"]),
            building_params,
        )
    stage_by_number = {str(stage.get("number") or ""): stage for stage in stages}
    subtype_names = _subtype_titles()
    for row in rows:
        raw = row.raw_data if isinstance(row.raw_data, dict) else {}
        text = " ".join(str(part or "") for part in (row.section, row.work_name)).lower().replace("ё", "е")
        stage_number, floor_defaulted = _stage10_text_stage_number(text, building_params)
        stage = stage_by_number.get(stage_number or "")
        if stage:
            raw.update(
                {
                    "estimate_type_id": hierarchy.get("estimate_type_id"),
                    "estimate_type_number": hierarchy.get("estimate_type_number"),
                    "project_variant_id": hierarchy.get("project_variant_id"),
                    "project_variant_number": hierarchy.get("project_variant_number"),
                    "canonical_stage_id": stage.get("canonical_stage_id"),
                    "stage_instance_id": stage.get("stage_instance_id"),
                    "template_stage_number": stage.get("template_stage_number"),
                    "floor_number": stage.get("floor_number"),
                    "floor_kind": stage.get("floor_kind"),
                    "floor_label": stage.get("floor_label"),
                    "floor_component": stage.get("floor_component"),
                    "component_role": stage.get("component_role"),
                    "stage_sort_order": stage.get("sort_order"),
                    "work_stage_number": stage.get("number"),
                    "work_stage_title": stage.get("title"),
                    "stage_occurrence_index": stage.get("occurrence_index"),
                    "stage_occurrence_label": stage.get("occurrence_label"),
                    "stage_options_mode": stage.get("stage_options_mode") or "none",
                    "stage_match_type": "stage10_text_rule",
                    "stage_confidence": "high" if not floor_defaulted else "medium",
                }
            )
            if floor_defaulted:
                raw["needs_review"] = True
                raw["review_reason"] = raw.get("review_reason") or "floor_context_inferred_default"
            elif raw.get("review_reason") in {
                "stage_candidates_ambiguous",
                "stage_weak_partial_text_match",
                "stage_option_required_for_autofill",
            }:
                raw["review_reason"] = None
            if re.search(r"\b(цокол|цоколь|подвал)\w*", text) and stage_number in {"2.7.9", "2.7.11"}:
                raw["floor_number"] = 0
                raw["floor_kind"] = "basement"
            if stage_number == "2.7.9" and re.search(r"\bперемыч", text):
                raw["semantic_stage_option_id"] = "precast_reinforced_concrete"
                raw["stage_option_source"] = "stage10_text_rule"
            if stage_number == "2.7.11" and re.search(r"\b(газобетон|блок)\w*", text):
                raw["semantic_stage_option_id"] = "aerated_concrete_block"
                raw["stage_option_source"] = "stage10_text_rule"
            if stage_number == "2.7.3" and re.search(r"\bотсечн\w*\s+гидроизоляц\w*", text):
                raw["semantic_stage_option_id"] = "brick"
                raw["stage_option_source"] = "stage10_text_rule"
                raw["operation_code"] = "cutoff_waterproofing_installation"

        subtype_code = _stage10_text_subtype_code(text)
        if subtype_code:
            section_id, subtype_id = subtype_code.split("/", 1)
            raw.update(
                {
                    "section_id": section_id,
                    "subtype_id": subtype_id,
                    "work_section_code": section_id,
                    "work_subtype_code": subtype_code,
                    "work_subtype_name": subtype_names.get(subtype_code),
                    "work_type_confidence": "high",
                    "classification_source": "stage10_text_rule",
                    "classification_needs_review": False,
                }
            )
            if raw.get("operator_review_reason") in {
                "multi_operation_row_requires_package_or_split",
                "work_operation_ambiguous",
            }:
                raw["operator_review_reason"] = None
        raw["row_role"] = "work"
        raw["work_type_applicable"] = True
        raw["gpr_included"] = True


def _estimate_from_stage10_row(
    item: SimpleNamespace,
    *,
    row: dict[str, Any],
    raw: dict[str, Any],
    batch: EstimateBatch,
    row_order: int,
    source_row_key: str | None,
) -> Estimate:
    return Estimate(
        id=str(uuid4()),
        project_id=batch.project_id,
        estimate_batch_id=batch.id,
        section=item.section,
        work_name=item.work_name,
        unit=item.unit,
        quantity=item.quantity,
        unit_price=item.unit_price,
        total_price=item.total_price,
        materials=getattr(item, "materials", None) or None,
        row_order=row_order,
        raw_data=raw,
        source_row_key=source_row_key,
        source_scope_id=row.get("source_scope_id"),
        work_scope_key=resolve_work_scope_key(source_row_key),
        applicability=raw.get("applicability") or {},
        applicability_hash=raw.get("applicability_hash"),
        applicability_hash_version=raw.get("applicability_hash_version") or batch.applicability_hash_version,
        applicability_schema_version=raw.get("applicability_schema_version") or batch.applicability_schema_version,
        taxonomy_snapshot=batch.taxonomy_snapshot,
        taxonomy_locked=True,
        dictionary_version=raw.get("dictionary_version") or batch.taxonomy_dictionary_version,
        work_section_code=raw.get("work_section_code"),
        work_section_name=raw.get("work_section_name"),
        work_subtype_code=raw.get("work_subtype_code") or raw.get("subtype_code"),
        work_subtype_name=raw.get("work_subtype_name") or raw.get("subtype_name"),
        estimate_type_id=raw.get("estimate_type_id") or batch.estimate_type_id,
        estimate_type_number=raw.get("estimate_type_number") or batch.estimate_type_number,
        project_variant_id=raw.get("project_variant_id") or batch.project_variant_id,
        project_variant_number=raw.get("project_variant_number") or batch.project_variant_number,
        canonical_stage_id=raw.get("canonical_stage_id"),
        stage_instance_id=raw.get("stage_instance_id"),
        template_stage_number=raw.get("template_stage_number"),
        floor_number=raw.get("floor_number"),
        floor_kind=raw.get("floor_kind"),
        floor_label=raw.get("floor_label"),
        floor_component=raw.get("floor_component"),
        component_role=raw.get("component_role"),
        work_stage_number=raw.get("work_stage_number"),
        work_stage_title=raw.get("work_stage_title"),
        stage_occurrence_index=raw.get("stage_occurrence_index"),
        stage_occurrence_label=raw.get("stage_occurrence_label"),
        stage_options_mode=raw.get("stage_options_mode"),
        stage_option_id=raw.get("stage_option_id"),
        stage_option_title=raw.get("stage_option_title"),
        stage_option_source=raw.get("stage_option_source"),
        section_id=raw.get("section_id"),
        subtype_id=raw.get("subtype_id"),
        row_role=raw.get("row_role"),
        parent_row_id=raw.get("parent_row_id"),
        inherited_from_row_id=raw.get("inherited_from_row_id"),
        stage_confidence=raw.get("stage_confidence"),
        work_type_confidence=raw.get("work_type_confidence"),
        autofill_enabled=raw.get("autofill_enabled"),
        needs_review=bool(raw.get("needs_review")),
        review_reason=raw.get("review_reason"),
        stage_match_type=raw.get("stage_match_type"),
        stage_match_score_json=raw.get("stage_match_score_json"),
        work_type_match_score_json=raw.get("work_type_match_score_json"),
        classification_score=raw.get("classification_score"),
        classification_confidence=raw.get("classification_confidence"),
        classification_needs_review=bool(raw.get("classification_needs_review")),
        classification_source=raw.get("classification_source"),
        classification_candidates=raw.get("classification_candidates"),
        classification_matched_terms=raw.get("classification_matched_terms"),
        operator_review_required=bool(raw.get("operator_review_required")),
        operator_review_status=raw.get("operator_review_status"),
        operator_review_reason=raw.get("operator_review_reason"),
        prompt_version=raw.get("prompt_version"),
        manual_override=bool(raw.get("manual_override")),
        variant_schema_version=raw.get("variant_schema_version") or batch.variant_schema_version,
        calculation_trace=raw.get("calculation_trace"),
        projection_json=raw.get("projection_json"),
    )


class EstimateImportWorker:
    def __init__(self, db: AsyncSession, feature_gate: DynamicFloorFeatureGate | None = None):
        self.db = db
        self.feature_gate = feature_gate or DynamicFloorFeatureGate()

    async def run_job(self, job_id: str) -> WorkerRunResult:
        job = await self.db.scalar(
            select(EstimateImportJob).where(EstimateImportJob.id == str(job_id)).with_for_update()
        )
        if job is None:
            raise KeyError("estimate_import_job_not_found")
        if job.status == "completed":
            return WorkerRunResult(job.id, job.status, materialized_estimate_count=0)
        now = utcnow()
        job.status = "running"
        job.started_at = now
        job.updated_at = now
        await self.db.flush()

        session = await self.db.scalar(
            select(EstimatePreviewSession)
            .where(EstimatePreviewSession.id == job.preview_session_id)
            .with_for_update()
        )
        batch = await self.db.scalar(
            select(EstimateBatch)
            .where(EstimateBatch.id == job.estimate_batch_id)
            .with_for_update()
        )
        try:
            if session is None or batch is None or session.status != "confirmed":
                raise RuntimeError("preview_session_not_confirmed")
            self.feature_gate.ensure_allowed(project_variant_id=session.project_variant_id, user_id=session.owner_user_id)
            if not session.snapshot_hash or session.snapshot_hash != job.snapshot_hash:
                raise RuntimeError(SEMANTIC_RESOLUTION_FAILURE)
            variant, resolved_stages, strict_semantic_contract = _resolve_import_semantic_context(
                session=session,
                batch=batch,
                job=job,
            )
            existing_count = len(
                list(
                    await self.db.scalars(
                        select(Estimate.id).where(Estimate.estimate_batch_id == batch.id).limit(1)
                    )
                )
            )
            created = 0
            if existing_count == 0:
                immutable_rows = session.snapshot_payload.get("rows") if isinstance(session.snapshot_payload, dict) else None
                if not isinstance(immutable_rows, list):
                    raise RuntimeError(SEMANTIC_RESOLUTION_FAILURE)
                for offset in range(0, len(immutable_rows), MATERIALIZATION_ROW_BATCH_SIZE):
                    snapshot_rows = immutable_rows[offset : offset + MATERIALIZATION_ROW_BATCH_SIZE]
                    if not all(isinstance(row, dict) for row in snapshot_rows):
                        raise RuntimeError(SEMANTIC_RESOLUTION_FAILURE)
                    materialized_rows = _prepare_stage10_rows_for_materialization(
                        snapshot_rows,
                        batch,
                        variant=variant if strict_semantic_contract else None,
                        resolved_stages=resolved_stages if strict_semantic_contract else None,
                    )
                    values: list[dict[str, Any]] = []
                    projection_values: list[dict[str, Any]] = []
                    for item in materialized_rows:
                        row = item.stage10_snapshot_row
                        raw = item.raw_data if isinstance(item.raw_data, dict) else {}
                        source_row_key = row.get("source_row_key")
                        est = _estimate_from_stage10_row(
                            item,
                            row=row,
                            raw=raw,
                            batch=batch,
                            row_order=created,
                            source_row_key=source_row_key,
                        )
                        values.append(_estimate_insert_values(est))
                        for projection in raw.get("ktp_quantity_projections") or []:
                            if not isinstance(projection, dict) or not projection.get("projection_id"):
                                continue
                            projection_values.append({
                                "id": str(uuid4()),
                                "estimate_batch_id": batch.id,
                                "estimate_id": est.id,
                                "source_row_key": source_row_key,
                                "projection_id": projection.get("projection_id"),
                                "stage_instance_id": projection.get("target_stage_instance_id"),
                                "operation_code": projection.get("operation_code"),
                                "operation_package_code": projection.get("operation_package_code"),
                                "semantic_stage_option_id": projection.get("semantic_stage_option_id"),
                                "work_scope_key": projection.get("work_scope_key"),
                                "applicability": raw.get("applicability") or {},
                                "applicability_hash": projection.get("applicability_hash"),
                                "applicability_hash_version": projection.get("applicability_hash_version"),
                                "applicability_schema_version": projection.get("applicability_schema_version"),
                                "quantity": projection.get("quantity"),
                                "unit_code": projection.get("unit_code"),
                                "resolution_status": projection.get("resolution_status") or "resolved",
                                "reason_code": projection.get("reason_code"),
                                "metadata_json": projection,
                                "created_at": utcnow(),
                            })
                        created += 1
                    if values:
                        await self.db.execute(insert(Estimate), values)
                        await self.db.flush()
                    if projection_values:
                        await self.db.execute(insert(EstimateQuantityProjection), projection_values)
                        await self.db.flush()
                if created == 0:
                    raise RuntimeError("preview_rows_missing")
                if strict_semantic_contract:
                    summaries = [
                        {
                            "id": str(uuid4()),
                            "estimate_batch_id": batch.id,
                            "stage_instance_id": str(stage.get("stage_instance_id") or ""),
                            "projection_generation_status": str(
                                stage.get("projection_generation_status") or "pending"
                            ),
                            "failure_code": stage.get("projection_generation_failure_code"),
                            "metadata_json": stage,
                            "created_at": utcnow(),
                        }
                        for stage in resolved_stages
                        if stage.get("stage_instance_id")
                    ]
                    if summaries:
                        await self.db.execute(insert(StageInstanceProjectionSummary), summaries)
            await self.db.execute(
                EstimateBatch.__table__.update()
                .where(EstimateBatch.project_id == batch.project_id)
                .where(EstimateBatch.id != batch.id)
                .where(EstimateBatch.is_active.is_(True))
                .values(is_active=False)
            )
            batch.import_status = "completed"
            batch.calculation_status = "calculated"
            batch.is_active = True
            job.status = "completed"
            job.finished_at = utcnow()
            job.updated_at = utcnow()
            await self.db.commit()
            return WorkerRunResult(job.id, "completed", materialized_estimate_count=created)
        except Exception as exc:
            await self.db.rollback()
            job = await self.db.get(EstimateImportJob, str(job_id))
            batch = await self.db.get(EstimateBatch, str(job.estimate_batch_id)) if job is not None else None
            reason_code = _exception_reason_code(exc)
            original = getattr(exc, "orig", None)
            logger.exception(
                "estimate import job %s blocked: reason=%s exception=%s original=%s",
                job_id,
                reason_code,
                type(exc).__name__,
                type(original).__name__ if original is not None else None,
            )
            if batch is not None:
                batch.import_status = "blocked"
                batch.calculation_status = "blocked"
                batch.calculation_block_reason = reason_code
                batch.is_active = False
            job.status = "blocked"
            job.reason_code = reason_code
            job.reason_details = {
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "dbapi_original_type": type(original).__name__ if original is not None else None,
                "dbapi_original_message": str(original) if original is not None else None,
            }
            job.finished_at = utcnow()
            job.updated_at = utcnow()
            await self.db.commit()
            return WorkerRunResult(job.id, "blocked", reason_code=reason_code)
