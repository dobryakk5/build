from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Estimate, EstimateBatch
from app.models.stage10 import EstimateImportJob, EstimatePreviewSession, TransactionalOutbox
from app.services.canonical_json_service import CanonicalJsonServiceV2
from app.services.dynamic_floor_feature_flag import DynamicFloorFeatureGate
from app.services.source_identity_service import resolve_work_scope_key


OUTBOX_MAX_PUBLICATION_ATTEMPTS = 6


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
            snapshot = session.snapshot_payload or {}
            actual_hash = hashlib.sha256(CanonicalJsonServiceV2.dump_bytes(snapshot)).hexdigest()
            if actual_hash != job.snapshot_hash:
                raise RuntimeError("preview_snapshot_integrity_mismatch")
            rows = snapshot.get("rows") or []
            existing_count = len(
                list(
                    await self.db.scalars(
                        select(Estimate.id).where(Estimate.estimate_batch_id == batch.id).limit(1)
                    )
                )
            )
            created = 0
            if existing_count == 0:
                for index, row in enumerate(rows):
                    if row.get("confirmation_approved") is False:
                        continue
                    parsed = row.get("parsed_data") if isinstance(row.get("parsed_data"), dict) else {}
                    raw = dict(parsed.get("raw_data") if isinstance(parsed.get("raw_data"), dict) else {})
                    raw.update(row.get("classification_result") if isinstance(row.get("classification_result"), dict) else {})
                    source_row_key = row.get("source_row_key")
                    est = Estimate(
                        id=str(uuid4()),
                        project_id=batch.project_id,
                        estimate_batch_id=batch.id,
                        section=parsed.get("section"),
                        work_name=parsed.get("work_name") or row.get("source_text") or "Imported row",
                        unit=parsed.get("unit"),
                        quantity=parsed.get("quantity"),
                        unit_price=parsed.get("unit_price"),
                        total_price=parsed.get("total_price"),
                        row_order=index,
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
                        dictionary_version=batch.taxonomy_dictionary_version,
                    )
                    self.db.add(est)
                    created += 1
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
            if batch is not None:
                batch.import_status = "blocked"
                batch.calculation_status = "blocked"
                batch.calculation_block_reason = str(exc)
                batch.is_active = False
            job.status = "blocked"
            job.reason_code = str(exc)
            job.finished_at = utcnow()
            job.updated_at = utcnow()
            await self.db.commit()
            return WorkerRunResult(job.id, "blocked", reason_code=str(exc))
