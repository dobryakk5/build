from __future__ import annotations

import asyncio
import gc
import logging
from datetime import datetime, timezone

from celery.exceptions import MaxRetriesExceededError, Retry
from sqlalchemy import or_, select, text

from app.core.database import get_db_context
from app.models.stage10 import EstimateImportJob
from app.services.estimate_import_worker import EstimateImportWorker, TransactionalOutboxPublisher
from app.tasks.celery_app import celery_app


logger = logging.getLogger(__name__)

STAGE10_IMPORT_ADVISORY_LOCK_ID = 2700010


def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            from app.core.database import engine

            loop.run_until_complete(engine.dispose())
        finally:
            asyncio.set_event_loop(None)
        loop.close()


@celery_app.task(
    name="app.tasks.estimate_import_tasks.process_stage10_estimate_import_queue",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def process_stage10_estimate_import_queue(self):
    """Drain Stage 10 outbox/import jobs immediately after preview confirm.

    A PostgreSQL advisory lock keeps the whole contour single-threaded even if
    Celery is started with concurrency greater than one or duplicate drain tasks
    are enqueued.
    """
    coro = _process_stage10_estimate_import_queue_async()
    try:
        return run_async(coro)
    except Exception as exc:
        if asyncio.iscoroutine(coro):
            coro.close()
        logger.exception(
            "stage10 estimate import drain failed (attempt %d): %s",
            self.request.retries + 1,
            exc,
        )
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            logger.error("stage10 estimate import drain: all attempts exhausted")
            raise


@celery_app.task(
    name="app.tasks.estimate_import_tasks.process_legacy_estimate_upload_job",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def process_legacy_estimate_upload_job(self, job_id: str):
    """Run the legacy post-preview upload job through Celery, one at a time."""
    coro = _process_legacy_estimate_upload_job_async(job_id)
    try:
        result = run_async(coro)
        if result.get("status") == "busy":
            raise self.retry(countdown=5)
        return result
    except Retry:
        raise
    except Exception as exc:
        if asyncio.iscoroutine(coro):
            coro.close()
        logger.exception(
            "legacy estimate upload job %s failed in celery (attempt %d): %s",
            job_id,
            self.request.retries + 1,
            exc,
        )
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            logger.error("legacy estimate upload job %s: all attempts exhausted", job_id)
            raise


@celery_app.task(
    name="app.tasks.estimate_import_tasks.process_ktp_estimate_stage1_job",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def process_ktp_estimate_stage1_job(self, job_id: str):
    """Run KTP estimate stage1 through Celery in the same single-threaded lane."""
    coro = _process_ktp_estimate_stage1_job_async(job_id)
    try:
        result = run_async(coro)
        if result.get("status") == "busy":
            raise self.retry(countdown=5)
        return result
    except Retry:
        raise
    except Exception as exc:
        if asyncio.iscoroutine(coro):
            coro.close()
        logger.exception(
            "KTP estimate stage1 job %s failed in celery (attempt %d): %s",
            job_id,
            self.request.retries + 1,
            exc,
        )
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            logger.error("KTP estimate stage1 job %s: all attempts exhausted", job_id)
            raise


async def _process_stage10_estimate_import_queue_async() -> dict[str, int | str]:
    async with get_db_context() as db:
        locked = bool(
            await db.scalar(
                text("SELECT pg_try_advisory_lock(:lock_id)").bindparams(
                    lock_id=STAGE10_IMPORT_ADVISORY_LOCK_ID
                )
            )
        )
        if not locked:
            return {"status": "busy", "published": 0, "completed": 0, "blocked": 0}

        published = 0
        completed = 0
        blocked = 0
        try:
            published = await TransactionalOutboxPublisher(db).publish_due(limit=1)
            now = datetime.now(timezone.utc)
            job_ids = list(
                await db.scalars(
                    select(EstimateImportJob.id)
                    .where(EstimateImportJob.status.in_(("queued", "retrying")))
                    .where(or_(EstimateImportJob.next_attempt_at.is_(None), EstimateImportJob.next_attempt_at <= now))
                    .order_by(EstimateImportJob.queued_at, EstimateImportJob.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            )
            worker = EstimateImportWorker(db)
            for job_id in job_ids:
                try:
                    result = await worker.run_job(str(job_id))
                finally:
                    db.sync_session.expunge_all()
                    gc.collect()
                if result.status == "completed":
                    completed += 1
                elif result.status in {"blocked", "failed"}:
                    blocked += 1
            return {
                "status": "drained",
                "published": published,
                "completed": completed,
                "blocked": blocked,
            }
        finally:
            await db.execute(
                text("SELECT pg_advisory_unlock(:lock_id)").bindparams(
                    lock_id=STAGE10_IMPORT_ADVISORY_LOCK_ID
                )
            )


async def _process_legacy_estimate_upload_job_async(job_id: str) -> dict[str, str]:
    async with get_db_context() as db:
        locked = bool(
            await db.scalar(
                text("SELECT pg_try_advisory_lock(:lock_id)").bindparams(
                    lock_id=STAGE10_IMPORT_ADVISORY_LOCK_ID
                )
            )
        )
        if not locked:
            return {"status": "busy", "job_id": job_id}
        try:
            from app.services.upload_service import _process_upload

            await _process_upload(job_id)
            return {"status": "done", "job_id": job_id}
        finally:
            await db.execute(
                text("SELECT pg_advisory_unlock(:lock_id)").bindparams(
                    lock_id=STAGE10_IMPORT_ADVISORY_LOCK_ID
                )
            )


async def _process_ktp_estimate_stage1_job_async(job_id: str) -> dict[str, str]:
    async with get_db_context() as db:
        locked = bool(
            await db.scalar(
                text("SELECT pg_try_advisory_lock(:lock_id)").bindparams(
                    lock_id=STAGE10_IMPORT_ADVISORY_LOCK_ID
                )
            )
        )
        if not locked:
            return {"status": "busy", "job_id": job_id}
        try:
            from app.services.ktp_estimate_service import _process_stage1

            await _process_stage1(job_id)
            return {"status": "done", "job_id": job_id}
        finally:
            await db.execute(
                text("SELECT pg_advisory_unlock(:lock_id)").bindparams(
                    lock_id=STAGE10_IMPORT_ADVISORY_LOCK_ID
                )
            )
