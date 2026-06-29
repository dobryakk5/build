"""Typed domain errors for the KTP estimate workflow."""
from __future__ import annotations

from typing import Any


class KtpDomainError(RuntimeError):
    code = "ktp_domain_error"
    http_status = 422

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class KtpNotFoundError(KtpDomainError):
    code = "ktp_entity_not_found"
    http_status = 404


class KtpPermissionError(KtpDomainError):
    code = "ktp_permission_denied"
    http_status = 403


class KtpConflictError(KtpDomainError):
    code = "ktp_conflict"
    http_status = 409


class SequenceLockedByTaxonomy(KtpConflictError):
    code = "sequence_is_locked_by_taxonomy"


class KtpValidationError(KtpDomainError):
    code = "ktp_validation_error"
    http_status = 422


class Stage1ReviewRequired(KtpConflictError):
    code = "stage1_review_required"


class Stage1JobAlreadyRunning(KtpConflictError):
    code = "stage1_job_already_running"


class TaxonomySnapshotRequired(KtpConflictError):
    code = "taxonomy_snapshot_required"


class TaxonomySnapshotIntegrity(KtpConflictError):
    code = "taxonomy_snapshot_integrity_mismatch"


class InvalidStageAwareRowReference(KtpConflictError):
    code = "invalid_stage_aware_row_reference"


class Stage1RunSuperseded(KtpConflictError):
    code = "stage1_run_superseded"
