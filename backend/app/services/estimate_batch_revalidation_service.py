from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import REVALIDATE_BLOCKED_BATCH_PERMISSION, has_project_permission
from app.models import Estimate, EstimateBatch, ProjectMember
from app.models.stage10 import EstimateBatchRevalidationRun, EstimateImportJob, TransactionalOutbox


REVALIDATE_PERMISSION = REVALIDATE_BLOCKED_BATCH_PERMISSION

BLOCKING_REASON_CODES = frozenset(
    {
        "mixed_applicability_hash_versions",
        "applicability_hash_version_mismatch",
        "preview_snapshot_integrity_mismatch",
        "legacy_projection_scope_unresolved",
        "legacy_applicability_unrecoverable",
        "missing_applicability_hash_version",
        "dynamic_floor_structure_2_7_disabled",
        "dynamic_floor_structure_2_7_not_allowed",
        "dynamic_floor_structure_2_7_allowlist_invalid",
    }
)

REVIEW_REASON_CODES = frozenset(
    {
        "stage_option_required",
        "basement_top_slab_option_required",
        "user_rate_input_required",
        "quantity_inheritance_scope_required",
        "quantity_inheritance_source_unresolved",
    }
)

GUARDED_OPERATIONS = frozenset({"recalculate", "confirm", "generate_ktp", "generate_gpr"})


class RevalidationDomainError(RuntimeError):
    def __init__(self, code: str, http_status: int, *, details: dict[str, Any] | None = None):
        super().__init__(code)
        self.code = code
        self.http_status = http_status
        self.details = details or {}


@dataclass(frozen=True)
class BatchValidationReport:
    blocking_reason_codes: tuple[str, ...] = ()
    review_reason_codes: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        return bool(self.blocking_reason_codes)


@dataclass(frozen=True)
class RevalidationResult:
    batch_id: str
    calculation_status: str
    calculation_block_reason: str | None
    blocking_reason_codes: tuple[str, ...]
    review_reason_codes: tuple[str, ...]
    import_command_requeued: bool
    import_job_id: str | None
    idempotency_key: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "calculation_status": self.calculation_status,
            "calculation_block_reason": self.calculation_block_reason,
            "blocking_reason_codes": list(self.blocking_reason_codes),
            "review_reason_codes": list(self.review_reason_codes),
            "import_command_requeued": self.import_command_requeued,
            "import_job_id": self.import_job_id,
            "idempotency_key": self.idempotency_key,
        }


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EstimateBatchIntegrityValidator:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def validate(self, batch: EstimateBatch) -> BatchValidationReport:
        blocking: set[str] = set()
        review: set[str] = set()
        current = batch.calculation_block_reason
        if current in REVIEW_REASON_CODES:
            review.add(current)
        elif current in BLOCKING_REASON_CODES:
            await self._validate_known_block(batch, current, blocking)
        elif current:
            blocking.add(current)
        if batch.applicability_hash_version is None:
            blocking.add("missing_applicability_hash_version")
        return BatchValidationReport(tuple(sorted(blocking)), tuple(sorted(review)))

    async def _validate_known_block(self, batch: EstimateBatch, reason: str, blocking: set[str]) -> None:
        if reason == "missing_applicability_hash_version":
            if batch.applicability_hash_version is None:
                blocking.add(reason)
            return
        if reason == "legacy_projection_scope_unresolved":
            if batch.source_row_scope_migration_status == "failed":
                blocking.add(reason)
            return
        if reason == "legacy_applicability_unrecoverable":
            if batch.source_row_scope_migration_status == "failed":
                blocking.add(reason)
            return
        # Fail closed for technical reasons whose production validator has not
        # proven recovery yet. This preserves the post-release contract.
        blocking.add(reason)


class BlockedBatchGuard:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def ensure_operation_allowed(self, batch_id: str, operation: str) -> EstimateBatch:
        batch = await self.db.get(EstimateBatch, str(batch_id))
        if batch is None:
            raise RevalidationDomainError("estimate_batch_not_found", 404)
        if operation in GUARDED_OPERATIONS and batch.calculation_status == "blocked":
            raise RevalidationDomainError(
                "batch_revalidation_required",
                409,
                details={"batch_id": batch.id, "calculation_block_reason": batch.calculation_block_reason},
            )
        return batch


class EstimateBatchRevalidationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.validator = EstimateBatchIntegrityValidator(db)

    async def scoped_batch_for_user(self, *, batch_id: str, user_id: str) -> tuple[EstimateBatch, ProjectMember]:
        row = (
            await self.db.execute(
                select(EstimateBatch, ProjectMember)
                .join(ProjectMember, ProjectMember.project_id == EstimateBatch.project_id)
                .where(EstimateBatch.id == str(batch_id))
                .where(ProjectMember.user_id == str(user_id))
                .with_for_update()
            )
        ).first()
        if row is None:
            raise RevalidationDomainError("estimate_batch_not_found", 404)
        return row[0], row[1]

    async def revalidate(self, *, batch_id: str, requested_by_user_id: str) -> RevalidationResult:
        batch, member = await self.scoped_batch_for_user(batch_id=batch_id, user_id=requested_by_user_id)
        if not has_project_permission(member.role, REVALIDATE_PERMISSION):
            raise RevalidationDomainError("revalidation_permission_required", 403)
        if batch.calculation_status != "blocked":
            raise RevalidationDomainError("batch_is_not_blocked", 409)

        previous_status = str(batch.calculation_status)
        report = await self.validator.validate(batch)
        if report.blocked:
            primary = report.blocking_reason_codes[0]
            batch.calculation_block_reason = primary
            await self._audit(batch, requested_by_user_id, previous_status, "blocked", report, False, None)
            await self.db.commit()
            raise RevalidationDomainError(
                "revalidation_still_blocked",
                409,
                details={
                    "calculation_status": "blocked",
                    "calculation_block_reason": primary,
                    "blocking_reason_codes": list(report.blocking_reason_codes),
                },
            )

        estimate_count = int(
            await self.db.scalar(
                select(func.count()).select_from(Estimate).where(Estimate.estimate_batch_id == batch.id)
            )
            or 0
        )
        target_status = "needs_review" if report.review_reason_codes else "pending"
        import_requeued = False
        job_id: str | None = None
        idempotency_key: str | None = None

        if estimate_count == 0 and batch.import_status in {"blocked", "failed", "pending"}:
            job = await self.db.scalar(
                select(EstimateImportJob)
                .where(EstimateImportJob.estimate_batch_id == batch.id)
                .order_by(EstimateImportJob.created_at.desc())
                .limit(1)
                .with_for_update()
            )
            if job is not None:
                job_id = job.id
                idempotency_key = job.idempotency_key
                job.status = "queued"
                job.reason_code = None
                job.reason_details = None
                job.next_attempt_at = None
                job.worker_id = None
                job.started_at = None
                job.finished_at = None
                job.updated_at = utcnow()
                import_requeued = True
            else:
                outbox = await self.db.scalar(
                    select(TransactionalOutbox)
                    .where(TransactionalOutbox.aggregate_id == batch.id)
                    .order_by(TransactionalOutbox.created_at.desc())
                    .limit(1)
                    .with_for_update()
                )
                if outbox is not None:
                    idempotency_key = outbox.idempotency_key
                    outbox.status = "pending"
                    outbox.next_attempt_at = None
                    outbox.last_error_code = None
                    outbox.last_error_details = None
                    outbox.dead_lettered_at = None
                    outbox.updated_at = utcnow()
                    import_requeued = True
            batch.import_status = "pending"

        batch.calculation_status = target_status
        batch.calculation_block_reason = None
        batch.revalidated_at = utcnow()
        batch.revalidated_by_user_id = str(requested_by_user_id)
        await self._audit(batch, requested_by_user_id, previous_status, target_status, report, import_requeued, job_id)
        await self.db.commit()
        return RevalidationResult(
            batch_id=batch.id,
            calculation_status=target_status,
            calculation_block_reason=None,
            blocking_reason_codes=(),
            review_reason_codes=report.review_reason_codes,
            import_command_requeued=import_requeued,
            import_job_id=job_id,
            idempotency_key=idempotency_key,
        )

    async def _audit(
        self,
        batch: EstimateBatch,
        user_id: str,
        previous_status: str,
        result_status: str,
        report: BatchValidationReport,
        import_requeued: bool,
        import_job_id: str | None,
    ) -> None:
        self.db.add(
            EstimateBatchRevalidationRun(
                id=str(uuid4()),
                estimate_batch_id=batch.id,
                requested_by_user_id=str(user_id),
                permission_code=REVALIDATE_PERMISSION,
                previous_calculation_status=previous_status,
                result_calculation_status=result_status,
                blocking_reason_codes=list(report.blocking_reason_codes),
                review_reason_codes=list(report.review_reason_codes),
                import_command_requeued=import_requeued,
                import_job_id=import_job_id,
                created_at=utcnow(),
            )
        )
