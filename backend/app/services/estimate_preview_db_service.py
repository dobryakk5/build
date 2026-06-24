from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import select
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
from app.services.taxonomy_snapshot_service import (
    build_immutable_taxonomy_snapshot,
    load_target_dictionary,
    work_rate_catalog_hash,
)


PREVIEW_CONTENT_HASH_PAYLOAD_VERSION = 1
SNAPSHOT_PAYLOAD_VERSION = 1
HASH_ALGORITHM = "sha256"

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


def _preview_hash_payload(session: EstimatePreviewSession, rows: Iterable[EstimatePreviewRow]) -> dict[str, Any]:
    return {
        "payload_version": PREVIEW_CONTENT_HASH_PAYLOAD_VERSION,
        "preview_session_id": session.id,
        "project_id": session.project_id,
        "owner_user_id": session.owner_user_id,
        "project_variant_id": session.project_variant_id,
        "taxonomy_dictionary_version": session.taxonomy_dictionary_version,
        "building_params": session.building_params,
        "project_structure_options": session.project_structure_options,
        "rows": [
            {
                "source_row_key": row.source_row_key,
                "source_scope_id": row.source_scope_id,
                "source_row_index": row.source_row_index,
                "source_text": row.source_text,
                "parsed_data": row.parsed_data,
                "classification_result": row.classification_result,
            }
            for row in rows
        ],
    }


def _preview_content_hash(session: EstimatePreviewSession, rows: Iterable[EstimatePreviewRow]) -> str:
    return _snapshot_hash(_preview_hash_payload(session, rows))


def _dynamic_taxonomy_version() -> str:
    dictionary, _hash = load_target_dictionary()
    return str(dictionary.get("dictionary_version") or "construction_work_dictionary_v6_5_0")


def _batch_taxonomy_snapshot(project_variant_id: str, building_params: dict | None = None) -> dict[str, Any]:
    snapshot = build_immutable_taxonomy_snapshot(project_variant_id=project_variant_id).to_json()
    snapshot["building_params"] = dict(building_params or {})
    snapshot["work_rate_catalog_version"] = "1.2"
    snapshot["work_rate_catalog_hash"] = work_rate_catalog_hash()
    return snapshot


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
        project_variant_id: str,
        building_params: dict[str, Any],
        project_structure_options: dict[str, Any],
        raw_uploaded_bytes: bytes,
        parsed_rows: Iterable[Any],
    ) -> dict[str, Any]:
        if project_variant_id != DYNAMIC_FLOOR_VARIANT_ID:
            raise PreviewDomainError("dynamic_floor_structure_2_7_required", 422)
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

        rows: list[EstimatePreviewRow] = []
        for index, item in enumerate(parsed_rows):
            payload = _row_from_any(item, index)
            row = EstimatePreviewRow(
                id=str(uuid4()),
                preview_session_id=session.id,
                source_row_key=payload["source_row_key"],
                source_scope_id=payload.get("source_scope_id"),
                source_row_index=payload["source_row_index"],
                source_text=payload["source_text"],
                parsed_data=payload["parsed_data"],
                classification_result=payload["classification_result"],
                created_at=now,
            )
            self.db.add(row)
            rows.append(row)
        if not rows:
            session.status = STATUS_FAILED
            session.failed_at = now
            session.failure_code = "preview_processing_failed"
            raise PreviewDomainError("preview_rows_empty", 422)

        session.status = STATUS_ACTIVE
        session.activated_at = now
        session.expires_at = now + timedelta(minutes=settings.ESTIMATE_PREVIEW_TTL_MINUTES)
        session.preview_content_hash = _preview_content_hash(session, rows)
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

            rows = await self._rows(session.id, for_update=True)
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
            batch = EstimateBatch(
                id=batch_id,
                project_id=session.project_id,
                name="DB preview import",
                estimate_kind=1,
                source_filename=None,
                project_variant_id=session.project_variant_id,
                taxonomy_dictionary_version=session.taxonomy_dictionary_version,
                building_params=session.building_params,
                project_structure_options=session.project_structure_options,
                taxonomy_snapshot=taxonomy_snapshot,
                work_rate_catalog_version=taxonomy_snapshot.get("work_rate_catalog_version"),
                work_rate_catalog_hash=taxonomy_snapshot.get("work_rate_catalog_hash"),
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
        taxonomy_snapshot = _batch_taxonomy_snapshot(session.project_variant_id, session.building_params)
        return {
            "snapshot_payload_version": SNAPSHOT_PAYLOAD_VERSION,
            "preview_session_id": session.id,
            "owner_user_id": session.owner_user_id,
            "project_id": session.project_id,
            "project_variant_id": session.project_variant_id,
            "taxonomy_dictionary_version": session.taxonomy_dictionary_version,
            "taxonomy_snapshot": taxonomy_snapshot,
            "work_rate_catalog_version": taxonomy_snapshot.get("work_rate_catalog_version"),
            "work_rate_catalog_hash": taxonomy_snapshot.get("work_rate_catalog_hash"),
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
