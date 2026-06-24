from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.stage10 import EstimateImportJob, EstimatePreviewRow, EstimatePreviewSession, TransactionalOutbox


BLOCKING_OUTBOX_STATUSES = ("pending", "publishing", "dead_letter")
BLOCKING_JOB_STATUSES = ("queued", "running", "retrying")
TERMINAL_JOB_STATUSES = ("completed", "failed", "blocked")


@dataclass(frozen=True)
class PreviewRetentionResult:
    purged_session_count: int
    purged_row_count: int


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EstimatePreviewRetentionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def purge_due(self, *, limit: int = 100) -> PreviewRetentionResult:
        cutoff = utcnow() - timedelta(days=settings.ESTIMATE_CONFIRMED_SNAPSHOT_RETENTION_DAYS)
        blocking_outbox = (
            select(TransactionalOutbox.id)
            .where(TransactionalOutbox.payload["preview_session_id"].astext == EstimatePreviewSession.id)
            .where(TransactionalOutbox.status.in_(BLOCKING_OUTBOX_STATUSES))
        )
        blocking_job = (
            select(EstimateImportJob.id)
            .where(EstimateImportJob.preview_session_id == EstimatePreviewSession.id)
            .where(EstimateImportJob.status.in_(BLOCKING_JOB_STATUSES))
        )
        terminal_job = (
            select(EstimateImportJob.id)
            .where(EstimateImportJob.preview_session_id == EstimatePreviewSession.id)
            .where(EstimateImportJob.status.in_(TERMINAL_JOB_STATUSES))
        )
        sessions = list(
            await self.db.scalars(
                select(EstimatePreviewSession)
                .where(EstimatePreviewSession.status == "confirmed")
                .where(EstimatePreviewSession.snapshot_payload.is_not(None))
                .where(EstimatePreviewSession.snapshot_purged_at.is_(None))
                .where(EstimatePreviewSession.confirmed_at <= cutoff)
                .where(~blocking_outbox.exists())
                .where(~blocking_job.exists())
                .where(terminal_job.exists())
                .order_by(EstimatePreviewSession.confirmed_at, EstimatePreviewSession.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        row_count = 0
        now = utcnow()
        for session in sessions:
            result = await self.db.execute(
                delete(EstimatePreviewRow).where(EstimatePreviewRow.preview_session_id == session.id)
            )
            row_count += int(result.rowcount or 0)
            session.snapshot_payload = None
            session.snapshot_purged_at = now
        await self.db.commit()
        return PreviewRetentionResult(len(sessions), row_count)
