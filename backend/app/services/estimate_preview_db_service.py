from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping
from uuid import uuid4

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import EstimateBatch, ProjectMember
from app.models.stage10 import EstimatePreviewRow, EstimatePreviewSession, TransactionalOutbox
from app.services.canonical_json_service import CanonicalJsonServiceV2
from app.services.dynamic_floor_feature_flag import (
    DYNAMIC_FLOOR_VARIANT_ID,
    DynamicFloorFeatureGate,
    FeatureFlagError,
)
from app.services.source_file_fingerprint_service import SourceFileFingerprintError, fingerprint_raw_bytes
from app.services.source_identity_service import new_source_row_key
from app.services.semantic_options_service import normalize_project_structure_options
from app.services.taxonomy_snapshot_service import (
    build_immutable_taxonomy_snapshot,
    load_target_dictionary,
    work_rate_catalog_hash,
)
from app.services.work_taxonomy_service import (
    get_project_variant_definition,
    validate_project_hierarchy_selection,
    validate_project_variant_building_params,
)


PREVIEW_CONTENT_HASH_PAYLOAD_VERSION = 1
SNAPSHOT_PAYLOAD_VERSION = 1
HASH_ALGORITHM = "sha256"
BASEMENT_TOP_SLAB_STAGE_ID = "residential_construction.ustroystvo_perekrytiy_cokolya"
BASEMENT_TOP_SLAB_OPTION_IDS = frozenset({"precast_rc", "monolithic_rc", "slab_on_grade"})
BASEMENT_BRANCH_STAGE_IDS = frozenset({
    "residential_construction.vysokiy_cokol",
    BASEMENT_TOP_SLAB_STAGE_ID,
})
PREVIEW_ROW_INSERT_BATCH_SIZE = 250

STATUS_PROCESSING = "processing"
STATUS_ACTIVE = "active"
STATUS_CONFIRMING = "confirming"
STATUS_CONFIRMED = "confirmed"
STATUS_EXPIRED = "expired"
STATUS_CANCELLED = "cancelled"
STATUS_FAILED = "failed"


class PreviewDomainError(ValueError):
    def __init__(self, code: str, http_status: int, *, details: Any = None):
        super().__init__(code)
        self.code = code
        self.http_status = http_status
        self.details = details


@dataclass(frozen=True)
class ConfirmResult:
    preview_session_id: str
    estimate_batch_id: str
    outbox_record_id: str
    idempotency_key: str
    snapshot_hash: str

    def as_dict(self) -> dict[str, str]:
        return self.__dict__.copy()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _snapshot_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(CanonicalJsonServiceV2.dump_bytes(payload)).hexdigest()


def _row_hash_payload(row: EstimatePreviewRow | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return {
            "source_row_key": row.get("source_row_key"),
            "source_scope_id": row.get("source_scope_id"),
            "source_row_index": row.get("source_row_index"),
            "source_text": row.get("source_text"),
            "parsed_data": row.get("parsed_data"),
            "classification_result": row.get("classification_result"),
        }
    return {
        "source_row_key": row.source_row_key,
        "source_scope_id": row.source_scope_id,
        "source_row_index": row.source_row_index,
        "source_text": row.source_text,
        "parsed_data": row.parsed_data,
        "classification_result": row.classification_result,
    }


def _preview_hash_payload(session: EstimatePreviewSession, rows: Iterable[EstimatePreviewRow | Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "payload_version": PREVIEW_CONTENT_HASH_PAYLOAD_VERSION,
        "preview_session_id": session.id,
        "project_id": session.project_id,
        "owner_user_id": session.owner_user_id,
        "project_variant_id": session.project_variant_id,
        "taxonomy_dictionary_version": session.taxonomy_dictionary_version,
        "building_params": session.building_params,
        "project_structure_options": session.project_structure_options,
        "rows": [_row_hash_payload(row) for row in rows],
    }


def _preview_content_hash(session: EstimatePreviewSession, rows: Iterable[EstimatePreviewRow | Mapping[str, Any]]) -> str:
    return _snapshot_hash(_preview_hash_payload(session, rows))


def _dynamic_taxonomy_version() -> str:
    dictionary, _hash = load_target_dictionary()
    return str(dictionary.get("dictionary_version") or "construction_work_dictionary_v6_5_1")


def _coerce_stage10_radio_options(
    variant: Mapping[str, Any],
    project_structure_options: Mapping[str, Any],
) -> dict[str, Any]:
    stage_by_id: dict[str, Mapping[str, Any]] = {}
    for stage in variant.get("stages") or []:
        if not isinstance(stage, Mapping):
            continue
        stage_id = str(stage.get("canonical_stage_id") or "").strip()
        if stage_id:
            stage_by_id[stage_id] = stage

    coerced: dict[str, Any] = {}
    for raw_stage_id, raw_value in project_structure_options.items():
        stage_id = str(raw_stage_id).strip()
        stage = stage_by_id.get(stage_id)
        mode = str(stage.get("stage_options_mode") or "none") if stage else "none"

        if mode == "selectable_one":
            if isinstance(raw_value, (list, tuple)):
                selected = [str(item).strip() for item in raw_value if str(item or "").strip()]
                if len(selected) == 1:
                    coerced[stage_id] = selected[0]
                    continue
            coerced[stage_id] = raw_value
        elif mode == "selectable_many":
            if isinstance(raw_value, str):
                value = raw_value.strip()
                if value:
                    coerced[stage_id] = [value]
                continue
            if isinstance(raw_value, (list, tuple)):
                selected = [str(item).strip() for item in raw_value if str(item or "").strip()]
                if len(selected) <= 1:
                    coerced[stage_id] = selected
                    continue
                raise PreviewDomainError(
                    "too_many_stage_options_selected",
                    422,
                    details={"stage": stage_id, "selected_count": len(selected), "max_selected": 1},
                )
            coerced[stage_id] = raw_value
        else:
            coerced[stage_id] = raw_value
    return coerced


def _validate_stage10_preview_metadata(
    *,
    estimate_type_id: str,
    project_variant_id: str,
    building_params: dict[str, Any],
    project_structure_options: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        params = validate_project_variant_building_params(
            estimate_type_id,
            project_variant_id,
            building_params,
        )
    except Exception as exc:  # noqa: BLE001 - normalize domain validation errors to preview contract
        raise PreviewDomainError(
            getattr(exc, "code", "invalid_building_params"),
            422,
            details={"error": getattr(exc, "message", str(exc))},
        ) from exc

    normalized_building_params = {
        "floors_count": int(params.floors_count),
        "has_basement": bool(params.has_basement),
        "has_mansard": bool(params.has_mansard),
    }

    if not isinstance(project_structure_options, Mapping):
        raise PreviewDomainError("invalid_stage_option", 422)

    variant = get_project_variant_definition(estimate_type_id, project_variant_id)
    coerced_options = _coerce_stage10_radio_options(variant, project_structure_options)
    normalized_options, issues, _trace = normalize_project_structure_options(
        variant,
        coerced_options,
    )
    if issues:
        issue = issues[0]
        raise PreviewDomainError(issue.code, 422, details=issue.as_dict())
    if not normalized_building_params["has_basement"]:
        for stage_id in BASEMENT_BRANCH_STAGE_IDS:
            normalized_options.pop(stage_id, None)
    if normalized_building_params["has_basement"]:
        selected_value = normalized_options.get(BASEMENT_TOP_SLAB_STAGE_ID)
        if not selected_value:
            raise PreviewDomainError("basement_top_slab_option_required", 422)
        selected = (
            selected_value[0]
            if isinstance(selected_value, list) and len(selected_value) == 1
            else selected_value
        )
        if selected not in BASEMENT_TOP_SLAB_OPTION_IDS:
            raise PreviewDomainError(
                "invalid_stage_option",
                422,
                details={"stage": BASEMENT_TOP_SLAB_STAGE_ID, "option": selected},
            )
    return normalized_building_params, normalized_options


def _batch_taxonomy_snapshot(project_variant_id: str) -> dict[str, Any]:
    return build_immutable_taxonomy_snapshot(project_variant_id=project_variant_id).to_json()


def _row_from_any(item: Any, index: int) -> dict[str, Any]:
    if isinstance(item, dict):
        raw = item
        raw_data = raw.get("raw_data") if isinstance(raw.get("raw_data"), dict) else raw
        text = raw.get("source_text") or raw.get("work_name") or raw_data.get("work_name") or ""
        parsed = raw.get("parsed_data") if isinstance(raw.get("parsed_data"), dict) else raw_data
        classification = raw.get("classification_result") if isinstance(raw.get("classification_result"), dict) else raw_data
    else:
        raw_data = getattr(item, "raw_data", None) if isinstance(getattr(item, "raw_data", None), dict) else {}
        text = getattr(item, "work_name", None) or raw_data.get("work_name") or ""
        parsed = {
            "section": getattr(item, "section", None),
            "work_name": getattr(item, "work_name", None),
            "unit": getattr(item, "unit", None),
            "quantity": getattr(item, "quantity", None),
            "unit_price": getattr(item, "unit_price", None),
            "total_price": getattr(item, "total_price", None),
            "raw_data": raw_data,
        }
        classification = raw_data
    return {
        "source_row_key": str(raw_data.get("source_row_key") or new_source_row_key()),
        "source_scope_id": raw_data.get("source_scope_id"),
        "source_row_index": int(raw_data.get("source_row_index", index) if isinstance(raw_data, dict) else index),
        "source_text": str(text).strip() or f"row-{index}",
        "parsed_data": _jsonable(parsed or {}),
        "classification_result": _jsonable(classification or {}),
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(child) for child in value]
    return value


class EstimatePreviewService:
    def __init__(self, *, db: AsyncSession, feature_gate: DynamicFloorFeatureGate | None = None):
        self.db = db
        self.feature_gate = feature_gate or DynamicFloorFeatureGate()

    async def _ensure_project_member(self, project_id: str, user_id: str) -> ProjectMember:
        member = await self.db.scalar(
            select(ProjectMember)
            .where(ProjectMember.project_id == str(project_id))
            .where(ProjectMember.user_id == str(user_id))
        )
        if member is None:
            raise PreviewDomainError("project_not_found", 404)
        return member

    async def create_and_activate_preview(
        self,
        *,
        owner_user_id: str,
        project_id: str,
        estimate_type_id: str,
        project_variant_id: str,
        building_params: dict[str, Any],
        project_structure_options: dict[str, Any],
        raw_uploaded_bytes: bytes,
        parsed_rows: Iterable[Any],
    ) -> dict[str, Any]:
        try:
            hierarchy_selection = validate_project_hierarchy_selection(estimate_type_id, project_variant_id)
        except ValueError as exc:
            raise PreviewDomainError(
                "invalid_project_hierarchy_selection",
                422,
                details={"error": str(exc)},
            ) from exc
        project_variant_id = str(hierarchy_selection["project_variant_id"])
        if project_variant_id != DYNAMIC_FLOOR_VARIANT_ID:
            raise PreviewDomainError("dynamic_floor_structure_2_7_required", 422)
        building_params, project_structure_options = _validate_stage10_preview_metadata(
            estimate_type_id=str(hierarchy_selection["estimate_type_id"]),
            project_variant_id=project_variant_id,
            building_params=dict(building_params or {}),
            project_structure_options=dict(project_structure_options or {}),
        )
        await self._ensure_project_member(project_id, owner_user_id)
        self.feature_gate.ensure_allowed(project_variant_id=project_variant_id, user_id=owner_user_id)
        fingerprint = fingerprint_raw_bytes(raw_uploaded_bytes)
        now = utcnow()
        session = EstimatePreviewSession(
            id=str(uuid4()),
            owner_user_id=str(owner_user_id),
            project_id=str(project_id),
            project_variant_id=project_variant_id,
            taxonomy_dictionary_version=_dynamic_taxonomy_version(),
            building_params=dict(building_params or {}),
            project_structure_options=dict(project_structure_options or {}),
            source_file_fingerprint_algorithm=HASH_ALGORITHM,
            source_file_fingerprint=fingerprint.fingerprint,
            source_file_size_bytes=fingerprint.size_bytes,
            status=STATUS_PROCESSING,
            created_at=now,
            processing_deadline_at=now + timedelta(minutes=settings.ESTIMATE_PREVIEW_PROCESSING_TIMEOUT_MINUTES),
            preview_content_hash_payload_version=PREVIEW_CONTENT_HASH_PAYLOAD_VERSION,
            preview_content_hash_algorithm=HASH_ALGORITHM,
        )
        self.db.add(session)
        await self.db.flush()
        await self.db.commit()

        row_count = 0
        batch: list[dict[str, Any]] = []
        hash_rows: list[dict[str, Any]] = []
        try:
            for index, item in enumerate(parsed_rows):
                payload = _row_from_any(item, index)
                record = {
                    "id": str(uuid4()),
                    "preview_session_id": session.id,
                    "source_row_key": payload["source_row_key"],
                    "source_scope_id": payload.get("source_scope_id"),
                    "source_row_index": payload["source_row_index"],
                    "source_text": payload["source_text"],
                    "parsed_data": payload["parsed_data"],
                    "classification_result": payload["classification_result"],
                    "created_at": now,
                }
                batch.append(record)
                hash_rows.append(_row_hash_payload(record))
                row_count += 1
                if len(batch) >= PREVIEW_ROW_INSERT_BATCH_SIZE:
                    await self.db.execute(insert(EstimatePreviewRow), batch)
                    await self.db.commit()
                    batch.clear()
            if batch:
                await self.db.execute(insert(EstimatePreviewRow), batch)
                await self.db.commit()
                batch.clear()
        except Exception:
            await self.db.rollback()
            failed = await self.db.get(EstimatePreviewSession, session.id)
            if failed is not None:
                failed.status = STATUS_FAILED
                failed.failed_at = utcnow()
                failed.failure_code = "preview_processing_failed"
                await self.db.commit()
            raise

        if row_count == 0:
            session.status = STATUS_FAILED
            session.failed_at = now
            session.failure_code = "preview_processing_failed"
            await self.db.commit()
            raise PreviewDomainError("preview_rows_empty", 422)

        hash_rows.sort(key=lambda row: (int(row.get("source_row_index") or 0), str(row.get("source_row_key") or "")))
        session.status = STATUS_ACTIVE
        session.activated_at = now
        session.expires_at = now + timedelta(minutes=settings.ESTIMATE_PREVIEW_TTL_MINUTES)
        session.preview_content_hash = _preview_content_hash(session, hash_rows)
        await self.db.commit()
        return await self.get_preview(owner_user_id=owner_user_id, preview_session_id=session.id)

    async def get_preview(self, *, owner_user_id: str, preview_session_id: str) -> dict[str, Any]:
        session = await self.db.get(EstimatePreviewSession, str(preview_session_id))
        if session is None or session.owner_user_id != str(owner_user_id):
            raise PreviewDomainError("preview_session_not_found", 404)
        await self._lazy_expire(session)
        rows = await self._rows(session.id)
        return {
            "preview_session_id": session.id,
            "project_id": session.project_id,
            "project_variant_id": session.project_variant_id,
            "status": session.status,
            "preview_content_hash": session.preview_content_hash,
            "expires_at": session.expires_at.isoformat() if session.expires_at else None,
            "rows": [
                {
                    "source_row_key": row.source_row_key,
                    "source_row_index": row.source_row_index,
                    "source_text": row.source_text,
                    "parsed_data": row.parsed_data,
                    "classification_result": row.classification_result,
                    "confirmation_approved": row.confirmation_approved,
                    "confirmation_manual_override": row.confirmation_manual_override,
                }
                for row in rows
            ],
        }

    async def cancel_preview(self, *, owner_user_id: str, preview_session_id: str) -> None:
        session = await self.db.get(EstimatePreviewSession, str(preview_session_id))
        if session is None or session.owner_user_id != str(owner_user_id):
            raise PreviewDomainError("preview_session_not_found", 404)
        if session.status not in {STATUS_ACTIVE, STATUS_PROCESSING}:
            raise PreviewDomainError("preview_session_terminal", 409)
        session.status = STATUS_CANCELLED
        session.cancelled_at = utcnow()
        await self.db.commit()

    async def confirm_preview(
        self,
        *,
        owner_user_id: str,
        preview_session_id: str,
        expected_preview_content_hash: str,
        row_decisions: list[dict[str, Any]],
    ) -> ConfirmResult:
        now = utcnow()
        await self._claim_confirming(
            owner_user_id=owner_user_id,
            preview_session_id=preview_session_id,
            now=now,
        )
        try:
            session = await self.db.scalar(
                select(EstimatePreviewSession)
                .where(EstimatePreviewSession.id == str(preview_session_id))
                .with_for_update()
            )
            if session is None or session.owner_user_id != str(owner_user_id):
                raise PreviewDomainError("preview_session_not_found", 404)
            if session.status != STATUS_CONFIRMING:
                raise PreviewDomainError("preview_session_not_active", 409)
            if not session.project_id:
                raise PreviewDomainError("project_not_found", 404)
            await self._ensure_project_member(session.project_id, owner_user_id)
            self.feature_gate.ensure_allowed(project_variant_id=session.project_variant_id, user_id=owner_user_id)

            rows = await self._rows(session.id, for_update=bool(row_decisions))
            actual_hash = _preview_content_hash(session, rows)
            if actual_hash != session.preview_content_hash or actual_hash != expected_preview_content_hash:
                raise PreviewDomainError("preview_content_hash_mismatch", 409)

            row_by_key = {str(row.source_row_key): row for row in rows}
            seen: set[str] = set()
            for decision in row_decisions:
                key = str(decision.get("source_row_key") or "")
                if not key or key in seen or key not in row_by_key:
                    raise PreviewDomainError("invalid_row_decision", 422)
                seen.add(key)
                row = row_by_key[key]
                if "approved" in decision:
                    row.confirmation_approved = decision.get("approved")
                if "manual_override" in decision:
                    row.confirmation_manual_override = decision.get("manual_override")

            snapshot_payload = self._snapshot_payload(session, rows)
            snapshot_hash = _snapshot_hash(snapshot_payload)
            batch_id = str(uuid4())
            idempotency_key = f"estimate-import:{session.id}:{batch_id}"
            taxonomy_snapshot = snapshot_payload["taxonomy_snapshot"]
            estimate_type_snapshot = taxonomy_snapshot.get("estimate_type") or {}
            variant_snapshot = taxonomy_snapshot.get("variant") or {}
            batch = EstimateBatch(
                id=batch_id,
                project_id=session.project_id,
                name="DB preview import",
                estimate_kind=int(estimate_type_snapshot.get("estimate_kind") or 1),
                source_filename=None,
                estimate_type_id=estimate_type_snapshot.get("id"),
                estimate_type_title=estimate_type_snapshot.get("title"),
                estimate_type_number=estimate_type_snapshot.get("number"),
                project_variant_id=session.project_variant_id,
                project_variant_title=variant_snapshot.get("title"),
                project_variant_number=variant_snapshot.get("number"),
                taxonomy_dictionary_version=session.taxonomy_dictionary_version,
                building_params=session.building_params,
                project_structure_options=session.project_structure_options,
                taxonomy_snapshot=taxonomy_snapshot,
                work_rate_catalog_version=snapshot_payload.get("work_rate_catalog_version"),
                work_rate_catalog_hash=snapshot_payload.get("work_rate_catalog_hash"),
                applicability_hash_version=2,
                applicability_schema_version="applicability@2.0.0",
                source_row_scope_version=2,
                source_row_scope_migration_status="not_required",
                calculation_status="pending",
                import_status="pending",
                is_active=False,
                taxonomy_resolution_mode="persisted_snapshot",
                taxonomy_locked=True,
            )
            self.db.add(batch)
            outbox = TransactionalOutbox(
                id=str(uuid4()),
                aggregate_type="estimate_batch",
                aggregate_id=batch_id,
                event_type="estimate_import_requested",
                idempotency_key=idempotency_key,
                payload={
                    "preview_session_id": session.id,
                    "estimate_batch_id": batch_id,
                    "idempotency_key": idempotency_key,
                    "snapshot_payload_version": SNAPSHOT_PAYLOAD_VERSION,
                    "snapshot_hash_algorithm": HASH_ALGORITHM,
                    "snapshot_hash": snapshot_hash,
                },
                status="pending",
                attempt_count=0,
                created_at=now,
                updated_at=now,
            )
            self.db.add(outbox)
            session.status = STATUS_CONFIRMED
            session.confirmed_at = now
            session.confirming_started_at = None
            session.estimate_batch_id = batch_id
            session.snapshot_payload_version = SNAPSHOT_PAYLOAD_VERSION
            session.snapshot_hash_algorithm = HASH_ALGORITHM
            session.snapshot_hash = snapshot_hash
            session.snapshot_payload = snapshot_payload
            await self.db.commit()
            return ConfirmResult(session.id, batch_id, outbox.id, idempotency_key, snapshot_hash)
        except Exception:
            await self.db.rollback()
            await self._reset_abandoned_confirming(preview_session_id, owner_user_id)
            raise

    async def _claim_confirming(self, *, owner_user_id: str, preview_session_id: str, now: datetime) -> None:
        session = await self.db.scalar(
            select(EstimatePreviewSession)
            .where(EstimatePreviewSession.id == str(preview_session_id))
            .with_for_update()
        )
        if session is None or session.owner_user_id != str(owner_user_id):
            raise PreviewDomainError("preview_session_not_found", 404)
        await self._recover_or_reject_confirming(session, now)
        await self._lazy_expire(session, commit=False)
        if session.status != STATUS_ACTIVE:
            raise PreviewDomainError("preview_session_not_active", 409)
        if not session.project_id:
            raise PreviewDomainError("project_not_found", 404)
        await self._ensure_project_member(session.project_id, owner_user_id)
        self.feature_gate.ensure_allowed(project_variant_id=session.project_variant_id, user_id=owner_user_id)
        session.status = STATUS_CONFIRMING
        session.confirming_started_at = now
        session.confirming_attempt_count = int(session.confirming_attempt_count or 0) + 1
        await self.db.commit()

    async def _reset_abandoned_confirming(self, preview_session_id: str, owner_user_id: str) -> None:
        session = await self.db.scalar(
            select(EstimatePreviewSession)
            .where(EstimatePreviewSession.id == str(preview_session_id))
            .with_for_update()
        )
        if session is None or session.owner_user_id != str(owner_user_id) or session.status != STATUS_CONFIRMING:
            return
        has_outbox = await self.db.scalar(
            select(TransactionalOutbox.id)
            .where(TransactionalOutbox.aggregate_type == "estimate_batch")
            .where(TransactionalOutbox.payload["preview_session_id"].astext == session.id)
            .limit(1)
        )
        if not session.estimate_batch_id and not session.snapshot_hash and not has_outbox:
            session.status = STATUS_ACTIVE
            session.confirming_started_at = None
            await self.db.commit()

    async def _rows(self, preview_session_id: str, *, for_update: bool = False) -> list[EstimatePreviewRow]:
        stmt = (
            select(EstimatePreviewRow)
            .where(EstimatePreviewRow.preview_session_id == str(preview_session_id))
            .order_by(EstimatePreviewRow.source_row_index, EstimatePreviewRow.source_row_key)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return list(await self.db.scalars(stmt))

    async def _lazy_expire(self, session: EstimatePreviewSession, *, commit: bool = True) -> None:
        if session.status == STATUS_ACTIVE and session.expires_at and session.expires_at <= utcnow():
            session.status = STATUS_EXPIRED
            session.expired_at = utcnow()
            if commit:
                await self.db.commit()

    async def _recover_or_reject_confirming(self, session: EstimatePreviewSession, now: datetime) -> None:
        if session.status != STATUS_CONFIRMING:
            return
        retry_window = timedelta(
            seconds=settings.PREVIEW_CONFIRMING_RETRY_DELAY_SECONDS
            * (settings.PREVIEW_CONFIRMING_MAX_RETRIES + 1)
        )
        stale = session.confirming_started_at and session.confirming_started_at + retry_window <= now
        if not stale:
            raise PreviewDomainError("preview_confirmation_in_progress", 409)
        has_outbox = await self.db.scalar(
            select(TransactionalOutbox.id)
            .where(TransactionalOutbox.aggregate_type == "estimate_batch")
            .where(TransactionalOutbox.payload["preview_session_id"].astext == session.id)
            .limit(1)
        )
        if session.estimate_batch_id or session.snapshot_hash or has_outbox:
            raise PreviewDomainError("preview_confirmation_incomplete", 409)
        session.status = STATUS_ACTIVE
        session.confirming_started_at = None

    def _snapshot_payload(self, session: EstimatePreviewSession, rows: list[EstimatePreviewRow]) -> dict[str, Any]:
        taxonomy_snapshot = _batch_taxonomy_snapshot(session.project_variant_id)
        catalog_hash = work_rate_catalog_hash()
        return {
            "snapshot_payload_version": SNAPSHOT_PAYLOAD_VERSION,
            "preview_session_id": session.id,
            "owner_user_id": session.owner_user_id,
            "project_id": session.project_id,
            "project_variant_id": session.project_variant_id,
            "taxonomy_dictionary_version": session.taxonomy_dictionary_version,
            "taxonomy_snapshot": taxonomy_snapshot,
            "work_rate_catalog_version": "1.2",
            "work_rate_catalog_hash": catalog_hash,
            "building_params": session.building_params,
            "project_structure_options": session.project_structure_options,
            "source_file_fingerprint_algorithm": session.source_file_fingerprint_algorithm,
            "source_file_fingerprint": session.source_file_fingerprint,
            "source_file_size_bytes": session.source_file_size_bytes,
            "rows": [
                {
                    "source_row_key": row.source_row_key,
                    "source_scope_id": row.source_scope_id,
                    "source_row_index": row.source_row_index,
                    "source_text": row.source_text,
                    "parsed_data": row.parsed_data,
                    "classification_result": row.classification_result,
                    "confirmation_approved": row.confirmation_approved,
                    "confirmation_manual_override": row.confirmation_manual_override,
                }
                for row in rows
            ],
        }
