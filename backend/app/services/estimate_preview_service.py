"""DB-backed preview/confirm domain for the post-release import contour.

PostgreSQL storage is defined by migrations 063/064/067.  The SQLite store in
this module is a deterministic reference implementation used by delivery tests
and local API integration.  It preserves the same transaction boundaries:
confirm decisions, immutable snapshot, inactive batch and outbox record commit
atomically.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from uuid import uuid4

try:
    from app.services.canonical_json_service import CanonicalJsonServiceV2
    from app.services.dynamic_floor_feature_flag import (
        DynamicFloorFeatureGate,
        normalize_user_id,
    )
    from app.services.source_file_fingerprint_service import fingerprint_raw_bytes
    from app.services.source_identity_service import new_source_row_key, normalize_uuid
    from app.services.taxonomy_snapshot_service import build_immutable_taxonomy_snapshot, load_target_dictionary
except ModuleNotFoundError:  # standalone delivery scripts
    from services.canonical_json_service import CanonicalJsonServiceV2
    from services.dynamic_floor_feature_flag import DynamicFloorFeatureGate, normalize_user_id
    from services.source_file_fingerprint_service import fingerprint_raw_bytes
    from services.source_identity_service import new_source_row_key, normalize_uuid
    from services.taxonomy_snapshot_service import build_immutable_taxonomy_snapshot, load_target_dictionary

PREVIEW_CONTENT_HASH_PAYLOAD_VERSION = 1
SNAPSHOT_PAYLOAD_VERSION = 1
HASH_ALGORITHM = "sha256"
DEFAULT_PROCESSING_TIMEOUT_MINUTES = 60
DEFAULT_ACTIVE_TTL_MINUTES = 1440

STATUS_PROCESSING = "processing"
STATUS_ACTIVE = "active"
STATUS_CONFIRMING = "confirming"
STATUS_CONFIRMED = "confirmed"
STATUS_EXPIRED = "expired"
STATUS_CANCELLED = "cancelled"
STATUS_FAILED = "failed"
PREVIEW_STATUSES = frozenset({
    STATUS_PROCESSING, STATUS_ACTIVE, STATUS_CONFIRMING, STATUS_CONFIRMED,
    STATUS_EXPIRED, STATUS_CANCELLED, STATUS_FAILED,
})


class PreviewDomainError(ValueError):
    def __init__(self, code: str, http_status: int, message: str | None = None, *, details: Any = None):
        super().__init__(message or code)
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
        return {
            "preview_session_id": self.preview_session_id,
            "estimate_batch_id": self.estimate_batch_id,
            "outbox_record_id": self.outbox_record_id,
            "idempotency_key": self.idempotency_key,
            "snapshot_hash": self.snapshot_hash,
        }


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_load(value: str | None, default: Any) -> Any:
    return copy.deepcopy(default) if value is None else json.loads(value)


def _uuid_text(value: Any, *, field: str) -> str:
    parsed = normalize_uuid(value)
    if parsed is None:
        raise PreviewDomainError("invalid_uuid", 422, f"{field} must be UUID")
    return str(parsed)


class SqliteEstimatePreviewStore:
    """Transactional reference store mirroring the PostgreSQL stage-2 schema."""

    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self):
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield self.connection
            except Exception:
                self.connection.execute("ROLLBACK")
                raise
            else:
                self.connection.execute("COMMIT")

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS estimate_batches (
                id TEXT PRIMARY KEY,
                project_variant_id TEXT NOT NULL,
                project_structure_options TEXT NOT NULL,
                applicability_hash_version INTEGER,
                applicability_schema_version TEXT,
                source_row_scope_version INTEGER NOT NULL,
                source_row_scope_migration_status TEXT NOT NULL,
                source_row_scope_migration_failure_code TEXT,
                source_row_scope_migration_failure_details TEXT,
                calculation_status TEXT NOT NULL,
                calculation_block_reason TEXT,
                import_status TEXT NOT NULL,
                supersedes_batch_id TEXT,
                is_active INTEGER NOT NULL,
                taxonomy_dictionary_version TEXT NOT NULL,
                taxonomy_snapshot TEXT NOT NULL,
                revalidated_at TEXT,
                revalidated_by_user_id TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS estimate_preview_sessions (
                id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                project_variant_id TEXT NOT NULL,
                taxonomy_dictionary_version TEXT NOT NULL,
                building_params TEXT NOT NULL,
                project_structure_options TEXT NOT NULL,
                source_file_fingerprint_algorithm TEXT NOT NULL CHECK(source_file_fingerprint_algorithm='sha256'),
                source_file_fingerprint TEXT NOT NULL CHECK(length(source_file_fingerprint)=64),
                source_file_size_bytes INTEGER NOT NULL CHECK(source_file_size_bytes>0),
                status TEXT NOT NULL CHECK(status IN ('processing','active','confirming','confirmed','expired','cancelled','failed')),
                created_at TEXT NOT NULL,
                processing_deadline_at TEXT NOT NULL,
                activated_at TEXT,
                expires_at TEXT,
                confirmed_at TEXT,
                cancelled_at TEXT,
                expired_at TEXT,
                failed_at TEXT,
                failure_code TEXT,
                failure_details TEXT,
                estimate_batch_id TEXT UNIQUE REFERENCES estimate_batches(id),
                snapshot_payload_version INTEGER,
                snapshot_hash_algorithm TEXT CHECK(snapshot_hash_algorithm IS NULL OR snapshot_hash_algorithm='sha256'),
                snapshot_hash TEXT,
                snapshot_purged_at TEXT,
                preview_content_hash_payload_version INTEGER NOT NULL DEFAULT 1,
                preview_content_hash_algorithm TEXT NOT NULL DEFAULT 'sha256' CHECK(preview_content_hash_algorithm='sha256'),
                preview_content_hash TEXT,
                CHECK(status != 'active' OR (activated_at IS NOT NULL AND expires_at IS NOT NULL AND preview_content_hash IS NOT NULL AND expired_at IS NULL)),
                CHECK(status != 'expired' OR (activated_at IS NOT NULL AND expires_at IS NOT NULL AND expired_at IS NOT NULL AND confirmed_at IS NULL)),
                CHECK(status != 'confirmed' OR (activated_at IS NOT NULL AND confirmed_at IS NOT NULL AND estimate_batch_id IS NOT NULL AND snapshot_payload_version IS NOT NULL AND snapshot_hash_algorithm='sha256' AND snapshot_hash IS NOT NULL)),
                CHECK(status != 'cancelled' OR cancelled_at IS NOT NULL),
                CHECK(status != 'failed' OR (failed_at IS NOT NULL AND failure_code IS NOT NULL))
            );
            CREATE TABLE IF NOT EXISTS estimate_preview_rows (
                id TEXT PRIMARY KEY,
                preview_session_id TEXT NOT NULL REFERENCES estimate_preview_sessions(id) ON DELETE CASCADE,
                source_row_key TEXT NOT NULL,
                source_scope_id TEXT,
                source_row_index INTEGER NOT NULL CHECK(source_row_index>=0),
                source_text TEXT NOT NULL,
                parsed_data TEXT NOT NULL,
                classification_result TEXT NOT NULL,
                confirmation_approved INTEGER,
                confirmation_manual_override TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(preview_session_id, source_row_key),
                CHECK(confirmation_approved IS NOT 0 OR confirmation_manual_override IS NULL)
            );
            CREATE INDEX IF NOT EXISTS ix_preview_rows_order
                ON estimate_preview_rows(preview_session_id, source_row_index, source_row_key);
            CREATE TABLE IF NOT EXISTS transactional_outbox (
                id TEXT PRIMARY KEY,
                aggregate_type TEXT NOT NULL,
                aggregate_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','publishing','published','dead_letter')),
                attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
                next_attempt_at TEXT,
                last_error_code TEXT,
                last_error_details TEXT,
                published_at TEXT,
                dead_lettered_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS estimate_import_jobs (
                id TEXT PRIMARY KEY,
                preview_session_id TEXT NOT NULL REFERENCES estimate_preview_sessions(id),
                estimate_batch_id TEXT NOT NULL REFERENCES estimate_batches(id),
                outbox_record_id TEXT REFERENCES transactional_outbox(id),
                idempotency_key TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL CHECK(status IN ('queued','running','retrying','completed','failed','blocked')),
                reason_code TEXT,
                reason_details TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT,
                snapshot_payload_version INTEGER,
                snapshot_hash_algorithm TEXT,
                snapshot_hash TEXT,
                worker_id TEXT,
                queued_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS estimates (
                id TEXT PRIMARY KEY,
                estimate_batch_id TEXT NOT NULL REFERENCES estimate_batches(id) ON DELETE CASCADE,
                source_row_key TEXT,
                source_scope_id TEXT,
                work_scope_key TEXT,
                legacy_work_scope_key TEXT,
                source_row_index INTEGER NOT NULL,
                source_text TEXT NOT NULL,
                parsed_data TEXT NOT NULL,
                classification_result TEXT NOT NULL,
                confirmation_approved INTEGER,
                confirmation_manual_override TEXT,
                applicability TEXT,
                applicability_hash TEXT CHECK(applicability_hash IS NULL OR length(applicability_hash)=64),
                applicability_hash_version INTEGER,
                applicability_schema_version TEXT,
                raw_data TEXT,
                calculation_trace TEXT,
                projection_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(estimate_batch_id, source_row_key)
            );
            CREATE INDEX IF NOT EXISTS ix_estimates_batch_order
                ON estimates(estimate_batch_id, source_row_index, source_row_key);
            CREATE TABLE IF NOT EXISTS stage_instance_projection_summaries (
                id TEXT PRIMARY KEY,
                estimate_batch_id TEXT NOT NULL REFERENCES estimate_batches(id) ON DELETE CASCADE,
                stage_instance_id TEXT NOT NULL,
                projection_generation_status TEXT NOT NULL DEFAULT 'pending',
                metadata_json TEXT,
                UNIQUE(estimate_batch_id, stage_instance_id)
            );
            CREATE TABLE IF NOT EXISTS estimate_quantity_projections (
                id TEXT PRIMARY KEY,
                estimate_batch_id TEXT NOT NULL REFERENCES estimate_batches(id) ON DELETE CASCADE,
                estimate_id TEXT REFERENCES estimates(id) ON DELETE CASCADE,
                source_row_key TEXT,
                work_scope_key TEXT,
                applicability TEXT,
                applicability_hash TEXT,
                applicability_hash_version INTEGER,
                applicability_schema_version TEXT,
                metadata_json TEXT
            );
            CREATE TABLE IF NOT EXISTS estimate_package_resolutions (
                id TEXT PRIMARY KEY,
                estimate_batch_id TEXT NOT NULL REFERENCES estimate_batches(id) ON DELETE CASCADE,
                estimate_id TEXT REFERENCES estimates(id) ON DELETE CASCADE,
                source_row_key TEXT,
                work_scope_key TEXT,
                applicability_hash TEXT,
                applicability_hash_version INTEGER,
                applicability_schema_version TEXT,
                resolution_payload TEXT
            );
            CREATE TABLE IF NOT EXISTS ktp_groups (
                id TEXT PRIMARY KEY,
                estimate_batch_id TEXT NOT NULL REFERENCES estimate_batches(id) ON DELETE CASCADE,
                metadata_json TEXT
            );
            CREATE TABLE IF NOT EXISTS ktp_items (
                id TEXT PRIMARY KEY,
                estimate_batch_id TEXT NOT NULL REFERENCES estimate_batches(id) ON DELETE CASCADE,
                estimate_id TEXT REFERENCES estimates(id) ON DELETE CASCADE,
                source_row_key TEXT,
                work_scope_key TEXT,
                applicability_hash TEXT,
                applicability_hash_version INTEGER,
                applicability_schema_version TEXT,
                metadata_json TEXT
            );
            CREATE TABLE IF NOT EXISTS gantt_tasks (
                id TEXT PRIMARY KEY,
                estimate_batch_id TEXT NOT NULL REFERENCES estimate_batches(id) ON DELETE CASCADE,
                estimate_id TEXT REFERENCES estimates(id) ON DELETE CASCADE,
                source_row_key TEXT,
                work_scope_key TEXT,
                applicability_hash TEXT,
                applicability_hash_version INTEGER,
                applicability_schema_version TEXT,
                projection_metadata TEXT
            );
            CREATE TABLE IF NOT EXISTS taxonomy_snapshots (
                id TEXT PRIMARY KEY,
                estimate_batch_id TEXT NOT NULL REFERENCES estimate_batches(id) ON DELETE CASCADE,
                snapshot_payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS estimate_batch_scope_migration_runs (
                id TEXT PRIMARY KEY,
                estimate_batch_id TEXT NOT NULL REFERENCES estimate_batches(id) ON DELETE CASCADE,
                source_contract_version INTEGER NOT NULL,
                target_contract_version INTEGER NOT NULL,
                json_path_registry_version TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('running','completed','failed')),
                migrated_estimate_count INTEGER NOT NULL DEFAULT 0,
                updated_record_counts TEXT NOT NULL DEFAULT '{}',
                failure_code TEXT,
                failure_details TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS estimate_batch_revalidation_runs (
                id TEXT PRIMARY KEY,
                estimate_batch_id TEXT NOT NULL REFERENCES estimate_batches(id) ON DELETE CASCADE,
                requested_by_user_id TEXT NOT NULL,
                permission_code TEXT NOT NULL,
                previous_calculation_status TEXT NOT NULL,
                result_calculation_status TEXT NOT NULL,
                blocking_reason_codes TEXT NOT NULL DEFAULT '[]',
                review_reason_codes TEXT NOT NULL DEFAULT '[]',
                import_command_requeued INTEGER NOT NULL DEFAULT 0,
                import_job_id TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_batch_revalidation_runs_batch
                ON estimate_batch_revalidation_runs(estimate_batch_id, created_at);
            """
        )


class EstimatePreviewService:
    def __init__(
        self,
        *,
        store: SqliteEstimatePreviewStore,
        feature_gate: DynamicFloorFeatureGate,
        processing_timeout_minutes: int = DEFAULT_PROCESSING_TIMEOUT_MINUTES,
        active_ttl_minutes: int = DEFAULT_ACTIVE_TTL_MINUTES,
        clock: Callable[[], datetime] = utcnow,
        fault_hook: Callable[[str], None] | None = None,
    ):
        if processing_timeout_minutes <= 0 or active_ttl_minutes <= 0:
            raise ValueError("preview timeouts must be positive")
        self.store = store
        self.feature_gate = feature_gate
        self.processing_timeout = timedelta(minutes=processing_timeout_minutes)
        self.active_ttl = timedelta(minutes=active_ttl_minutes)
        self.clock = clock
        self.fault_hook = fault_hook or (lambda _point: None)
        target_dictionary, _target_hash = load_target_dictionary()
        self.taxonomy_dictionary_version = str(target_dictionary["dictionary_version"])

    def create_processing_preview(
        self,
        *,
        owner_user_id: Any,
        project_variant_id: str,
        taxonomy_dictionary_version: str | None = None,
        building_params: Mapping[str, Any],
        project_structure_options: Mapping[str, Any] | None,
        raw_uploaded_bytes: bytes,
    ) -> str:
        owner = self.feature_gate.ensure_allowed(
            project_variant_id=project_variant_id,
            user_id=owner_user_id,
        )
        supplied_taxonomy_version = str(taxonomy_dictionary_version or self.taxonomy_dictionary_version).strip()
        if supplied_taxonomy_version != self.taxonomy_dictionary_version:
            raise PreviewDomainError("taxonomy_dictionary_version_mismatch", 409)
        fingerprint = fingerprint_raw_bytes(raw_uploaded_bytes)
        now = self.clock()
        session_id = str(uuid4())
        with self.store.transaction() as db:
            db.execute(
                """INSERT INTO estimate_preview_sessions (
                    id, owner_user_id, project_variant_id, taxonomy_dictionary_version,
                    building_params, project_structure_options,
                    source_file_fingerprint_algorithm, source_file_fingerprint,
                    source_file_size_bytes, status, created_at, processing_deadline_at,
                    preview_content_hash_payload_version, preview_content_hash_algorithm
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    session_id, owner, project_variant_id, self.taxonomy_dictionary_version,
                    _json_dump(dict(building_params)), _json_dump(dict(project_structure_options or {})),
                    fingerprint.algorithm, fingerprint.fingerprint, fingerprint.size_bytes,
                    STATUS_PROCESSING, _iso(now), _iso(now + self.processing_timeout),
                    PREVIEW_CONTENT_HASH_PAYLOAD_VERSION, HASH_ALGORITHM,
                ),
            )
        return session_id

    def activate_preview(self, preview_session_id: Any, *, rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        session_id = _uuid_text(preview_session_id, field="preview_session_id")
        now = self.clock()
        normalized_rows = self._normalize_rows(rows, now=now)
        timed_out = False
        owner_user_id: str | None = None
        with self.store.transaction() as db:
            session = self._require_session(db, session_id)
            owner_user_id = session["owner_user_id"]
            if session["status"] != STATUS_PROCESSING:
                raise PreviewDomainError("preview_session_not_ready", 409)
            deadline = _parse_dt(session["processing_deadline_at"])
            if deadline is not None and deadline <= now:
                db.execute(
                    """UPDATE estimate_preview_sessions
                       SET status=?, failed_at=?, failure_code=?
                       WHERE id=? AND status=?""",
                    (STATUS_FAILED, _iso(now), "preview_processing_timeout", session_id, STATUS_PROCESSING),
                )
                timed_out = True
            else:
                for row in normalized_rows:
                    db.execute(
                        """INSERT INTO estimate_preview_rows (
                            id, preview_session_id, source_row_key, source_scope_id,
                            source_row_index, source_text, parsed_data, classification_result,
                            confirmation_approved, confirmation_manual_override, created_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            row["id"], session_id, row["source_row_key"], row["source_scope_id"],
                            row["source_row_index"], row["source_text"], _json_dump(row["parsed_data"]),
                            _json_dump(row["classification_result"]),
                            None if row["confirmation_approved"] is None else int(row["confirmation_approved"]),
                            None if row["confirmation_manual_override"] is None else _json_dump(row["confirmation_manual_override"]),
                            row["created_at"],
                        ),
                    )
                session = self._require_session(db, session_id)
                stored_rows = self._rows(db, session_id)
                preview_hash = self._preview_content_hash(session, stored_rows)
                updated = db.execute(
                    """UPDATE estimate_preview_sessions
                       SET status=?, activated_at=?, expires_at=?, preview_content_hash=?
                       WHERE id=? AND status=?""",
                    (STATUS_ACTIVE, _iso(now), _iso(now + self.active_ttl), preview_hash, session_id, STATUS_PROCESSING),
                ).rowcount
                if updated != 1:
                    raise PreviewDomainError("preview_session_not_ready", 409)
        if timed_out:
            raise PreviewDomainError("preview_session_failed", 409)
        return self.get_preview(owner_user_id=owner_user_id, preview_session_id=session_id)

    def create_active_preview(self, *, rows: Iterable[Mapping[str, Any]], **kwargs: Any) -> dict[str, Any]:
        session_id = self.create_processing_preview(**kwargs)
        try:
            return self.activate_preview(session_id, rows=rows)
        except Exception as exc:
            if not isinstance(exc, PreviewDomainError) or exc.code != "preview_session_failed":
                self.fail_processing(session_id, failure_code="preview_processing_failed", failure_details={"error": type(exc).__name__})
            raise

    def fail_processing(self, preview_session_id: Any, *, failure_code: str, failure_details: Any = None) -> None:
        session_id = _uuid_text(preview_session_id, field="preview_session_id")
        now = self.clock()
        with self.store.transaction() as db:
            updated = db.execute(
                """UPDATE estimate_preview_sessions
                   SET status=?, failed_at=?, failure_code=?, failure_details=?
                   WHERE id=? AND status=?""",
                (STATUS_FAILED, _iso(now), str(failure_code), _json_dump(failure_details) if failure_details is not None else None, session_id, STATUS_PROCESSING),
            ).rowcount
            if updated == 0:
                session = self._require_session(db, session_id)
                if session["status"] != STATUS_FAILED:
                    raise PreviewDomainError("preview_session_not_ready", 409)

    def process_timeouts(self) -> int:
        now = self.clock()
        with self.store.transaction() as db:
            result = db.execute(
                """UPDATE estimate_preview_sessions
                   SET status=?, failed_at=?, failure_code=?
                   WHERE status=? AND processing_deadline_at<=?""",
                (STATUS_FAILED, _iso(now), "preview_processing_timeout", STATUS_PROCESSING, _iso(now)),
            )
            return result.rowcount

    def expire_active_previews(self) -> int:
        now = self.clock()
        with self.store.transaction() as db:
            result = db.execute(
                """UPDATE estimate_preview_sessions
                   SET status=?, expired_at=?
                   WHERE status=? AND expires_at<=?""",
                (STATUS_EXPIRED, _iso(now), STATUS_ACTIVE, _iso(now)),
            )
            return result.rowcount

    def get_preview(self, *, owner_user_id: Any, preview_session_id: Any) -> dict[str, Any]:
        owner = normalize_user_id(owner_user_id)
        if owner is None:
            raise PreviewDomainError("authentication_required", 401)
        session_id = _uuid_text(preview_session_id, field="preview_session_id")
        with self.store.transaction() as db:
            session = self._owned_session(db, session_id, owner)
            session = self._refresh_time_status(db, session)
            rows = self._rows(db, session_id)
            return self._public_payload(session, rows)

    def cancel_preview(self, *, owner_user_id: Any, preview_session_id: Any) -> None:
        owner = normalize_user_id(owner_user_id)
        if owner is None:
            raise PreviewDomainError("authentication_required", 401)
        session_id = _uuid_text(preview_session_id, field="preview_session_id")
        now = self.clock()
        with self.store.transaction() as db:
            session = self._refresh_time_status(db, self._owned_session(db, session_id, owner))
            status = session["status"]
            if status == STATUS_CANCELLED:
                return
            if status == STATUS_EXPIRED:
                raise PreviewDomainError("preview_session_expired", 410)
            if status != STATUS_ACTIVE:
                if status in PREVIEW_STATUSES:
                    raise PreviewDomainError("preview_session_cannot_be_cancelled", 409)
                raise PreviewDomainError("invalid_preview_session_status", 409)
            db.execute(
                "UPDATE estimate_preview_sessions SET status=?, cancelled_at=? WHERE id=? AND status=?",
                (STATUS_CANCELLED, _iso(now), session_id, STATUS_ACTIVE),
            )

    def confirm_preview(
        self,
        *,
        owner_user_id: Any,
        preview_session_id: Any,
        expected_preview_content_hash: str,
        row_decisions: Sequence[Mapping[str, Any]] = (),
    ) -> ConfirmResult:
        owner = normalize_user_id(owner_user_id)
        if owner is None:
            raise PreviewDomainError("authentication_required", 401)
        session_id = _uuid_text(preview_session_id, field="preview_session_id")
        now = self.clock()
        with self.store.transaction() as db:
            session = self._refresh_time_status(db, self._owned_session(db, session_id, owner))
            self.feature_gate.ensure_allowed(project_variant_id=session["project_variant_id"], user_id=owner)
            self._assert_confirmable(session)
            rows = self._rows(db, session_id)
            actual_content_hash = self._preview_content_hash(session, rows)
            saved_content_hash = str(session["preview_content_hash"] or "")
            if actual_content_hash != saved_content_hash or str(expected_preview_content_hash) != saved_content_hash:
                raise PreviewDomainError("preview_snapshot_integrity_mismatch", 409)

            decisions = self._normalize_decisions(row_decisions)
            known_keys = {row["source_row_key"] for row in rows}
            unknown = sorted(set(decisions) - known_keys)
            if unknown:
                raise PreviewDomainError("invalid_source_row_key", 409, details={"source_row_keys": unknown})
            for source_row_key, decision in decisions.items():
                db.execute(
                    """UPDATE estimate_preview_rows
                       SET confirmation_approved=?, confirmation_manual_override=?
                       WHERE preview_session_id=? AND source_row_key=?""",
                    (
                        None if decision["approved"] is None else int(decision["approved"]),
                        None if decision["manual_override"] is None else _json_dump(decision["manual_override"]),
                        session_id, source_row_key,
                    ),
                )
            self.fault_hook("after_decisions")
            rows = self._rows(db, session_id)
            missing_required = [
                row["source_row_key"] for row in rows
                if bool(row["classification_result"].get("requires_confirmation"))
                and row["confirmation_approved"] is None
            ]
            if missing_required:
                raise PreviewDomainError("preview_row_decision_required", 409, details={"source_row_keys": missing_required})

            db.execute("UPDATE estimate_preview_sessions SET status=? WHERE id=?", (STATUS_CONFIRMING, session_id))
            session = self._require_session(db, session_id)
            snapshot_payload = self._snapshot_payload(session, rows)
            snapshot_hash = hashlib.sha256(CanonicalJsonServiceV2.dump_bytes(snapshot_payload)).hexdigest()
            taxonomy_snapshot = build_immutable_taxonomy_snapshot(project_variant_id=session["project_variant_id"]).to_json()
            previous_active = db.execute(
                """SELECT b.id FROM estimate_batches b
                   JOIN estimate_preview_sessions ps ON ps.estimate_batch_id=b.id
                   WHERE ps.owner_user_id=? AND b.project_variant_id=? AND b.is_active=1
                   ORDER BY b.created_at DESC LIMIT 1""",
                (session["owner_user_id"], session["project_variant_id"]),
            ).fetchone()
            supersedes_batch_id = previous_active["id"] if previous_active else None
            batch_id = str(uuid4())
            db.execute(
                """INSERT INTO estimate_batches (
                    id, project_variant_id, project_structure_options,
                    applicability_hash_version, applicability_schema_version,
                    source_row_scope_version, source_row_scope_migration_status,
                    calculation_status, calculation_block_reason, import_status,
                    supersedes_batch_id, is_active, taxonomy_dictionary_version,
                    taxonomy_snapshot, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    batch_id, session["project_variant_id"], session["project_structure_options"],
                    2, taxonomy_snapshot.get("applicability_schema_version"), 2, "not_required",
                    "pending", None, "pending", supersedes_batch_id, 0, session["taxonomy_dictionary_version"],
                    _json_dump(taxonomy_snapshot), _iso(now),
                ),
            )
            self.fault_hook("after_batch")
            outbox_id = str(uuid4())
            idempotency_key = f"estimate-import:{session_id}:{batch_id}"
            outbox_payload = {
                "preview_session_id": session_id,
                "estimate_batch_id": batch_id,
                "snapshot_payload_version": SNAPSHOT_PAYLOAD_VERSION,
                "snapshot_hash_algorithm": HASH_ALGORITHM,
                "snapshot_hash": snapshot_hash,
                "idempotency_key": idempotency_key,
            }
            db.execute(
                """INSERT INTO transactional_outbox (
                    id, aggregate_type, aggregate_id, event_type, idempotency_key,
                    payload, status, attempt_count, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    outbox_id, "estimate_batch", batch_id, "estimate.import.requested",
                    idempotency_key, _json_dump(outbox_payload), "pending", 0, _iso(now), _iso(now),
                ),
            )
            self.fault_hook("after_outbox")
            db.execute(
                """UPDATE estimate_preview_sessions
                   SET status=?, confirmed_at=?, estimate_batch_id=?, snapshot_payload_version=?,
                       snapshot_hash_algorithm=?, snapshot_hash=?
                   WHERE id=? AND status=?""",
                (
                    STATUS_CONFIRMED, _iso(now), batch_id, SNAPSHOT_PAYLOAD_VERSION,
                    HASH_ALGORITHM, snapshot_hash, session_id, STATUS_CONFIRMING,
                ),
            )
        return ConfirmResult(session_id, batch_id, outbox_id, idempotency_key, snapshot_hash)

    def consume_confirmed_snapshot_for_test(self, preview_session_id: Any) -> dict[str, Any]:
        """Minimal idempotent consumer used until the stage-7 worker exists."""
        session_id = _uuid_text(preview_session_id, field="preview_session_id")
        now = self.clock()
        with self.store.transaction() as db:
            session = self._require_session(db, session_id)
            if session["status"] != STATUS_CONFIRMED:
                raise PreviewDomainError("preview_session_not_confirmed", 409)
            rows = self._rows(db, session_id)
            actual = hashlib.sha256(CanonicalJsonServiceV2.dump_bytes(self._snapshot_payload(session, rows))).hexdigest()
            if actual != session["snapshot_hash"]:
                raise PreviewDomainError("preview_snapshot_integrity_mismatch", 409)
            batch_id = session["estimate_batch_id"]
            idempotency_key = f"estimate-import:{session_id}:{batch_id}"
            existing = db.execute(
                "SELECT * FROM estimate_import_jobs WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if existing is None:
                outbox = db.execute(
                    "SELECT * FROM transactional_outbox WHERE idempotency_key=?", (idempotency_key,)
                ).fetchone()
                job_id = str(uuid4())
                db.execute(
                    """INSERT INTO estimate_import_jobs (
                        id, preview_session_id, estimate_batch_id, outbox_record_id,
                        idempotency_key, status, attempt_count, snapshot_payload_version,
                        snapshot_hash_algorithm, snapshot_hash, queued_at, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        job_id, session_id, batch_id, outbox["id"] if outbox else None,
                        idempotency_key, "queued", 0, session["snapshot_payload_version"],
                        session["snapshot_hash_algorithm"], session["snapshot_hash"],
                        _iso(now), _iso(now), _iso(now),
                    ),
                )
                db.execute(
                    "UPDATE transactional_outbox SET status='published', published_at=?, updated_at=? WHERE idempotency_key=?",
                    (_iso(now), _iso(now), idempotency_key),
                )
                existing = db.execute("SELECT * FROM estimate_import_jobs WHERE id=?", (job_id,)).fetchone()
            return dict(existing)

    def _normalize_rows(self, rows: Iterable[Mapping[str, Any]], *, now: datetime) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for position, source in enumerate(rows):
            raw_key = source.get("source_row_key")
            key = str(new_source_row_key()) if raw_key in (None, "") else _uuid_text(raw_key, field="source_row_key")
            if key in seen:
                raise PreviewDomainError("duplicate_source_row_key", 409)
            seen.add(key)
            scope = source.get("source_scope_id")
            scope_text = None if scope in (None, "") else _uuid_text(scope, field="source_scope_id")
            index = int(source.get("source_row_index", position))
            if index < 0:
                raise PreviewDomainError("invalid_source_row_index", 422)
            approved = source.get("confirmation_approved")
            manual = copy.deepcopy(source.get("confirmation_manual_override"))
            if approved is False and manual is not None:
                raise PreviewDomainError("invalid_confirmation_manual_override", 422)
            result.append({
                "id": str(uuid4()),
                "source_row_key": key,
                "source_scope_id": scope_text,
                "source_row_index": index,
                "source_text": str(source.get("source_text") or ""),
                "parsed_data": copy.deepcopy(dict(source.get("parsed_data") or {})),
                "classification_result": copy.deepcopy(dict(source.get("classification_result") or {})),
                "confirmation_approved": approved if approved in (None, True, False) else bool(approved),
                "confirmation_manual_override": manual,
                "created_at": _iso(now),
            })
        return result

    def _normalize_decisions(self, decisions: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in decisions:
            key = _uuid_text(item.get("source_row_key"), field="source_row_key")
            if key in result:
                raise PreviewDomainError("duplicate_source_row_key", 409)
            approved = item.get("approved")
            if approved not in (None, True, False):
                raise PreviewDomainError("invalid_row_decision", 422)
            manual = copy.deepcopy(item.get("manual_override"))
            if approved is False and manual is not None:
                raise PreviewDomainError("invalid_confirmation_manual_override", 422)
            result[key] = {"approved": approved, "manual_override": manual}
        return result

    def _require_session(self, db: sqlite3.Connection, session_id: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM estimate_preview_sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise PreviewDomainError("preview_session_not_found", 404)
        return row

    def _owned_session(self, db: sqlite3.Connection, session_id: str, owner: str) -> sqlite3.Row:
        row = db.execute(
            "SELECT * FROM estimate_preview_sessions WHERE id=? AND owner_user_id=?", (session_id, owner)
        ).fetchone()
        if row is None:
            raise PreviewDomainError("preview_session_not_found", 404)
        return row

    def _rows(self, db: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
        result = []
        for row in db.execute(
            "SELECT * FROM estimate_preview_rows WHERE preview_session_id=? ORDER BY source_row_index ASC, source_row_key ASC",
            (session_id,),
        ).fetchall():
            result.append({
                "id": row["id"],
                "preview_session_id": row["preview_session_id"],
                "source_row_key": row["source_row_key"],
                "source_scope_id": row["source_scope_id"],
                "source_row_index": row["source_row_index"],
                "source_text": row["source_text"],
                "parsed_data": _json_load(row["parsed_data"], {}),
                "classification_result": _json_load(row["classification_result"], {}),
                "confirmation_approved": None if row["confirmation_approved"] is None else bool(row["confirmation_approved"]),
                "confirmation_manual_override": _json_load(row["confirmation_manual_override"], None),
                "created_at": row["created_at"],
            })
        return result

    def _refresh_time_status(self, db: sqlite3.Connection, session: sqlite3.Row) -> sqlite3.Row:
        now = self.clock()
        if session["status"] == STATUS_PROCESSING:
            deadline = _parse_dt(session["processing_deadline_at"])
            if deadline is not None and deadline <= now:
                db.execute(
                    """UPDATE estimate_preview_sessions
                       SET status=?, failed_at=?, failure_code=?
                       WHERE id=? AND status=? AND processing_deadline_at<=?""",
                    (STATUS_FAILED, _iso(now), "preview_processing_timeout", session["id"], STATUS_PROCESSING, _iso(now)),
                )
                session = self._require_session(db, session["id"])
        if session["status"] == STATUS_ACTIVE:
            expires = _parse_dt(session["expires_at"])
            if expires is not None and expires <= now:
                db.execute(
                    """UPDATE estimate_preview_sessions SET status=?, expired_at=?
                       WHERE id=? AND status=? AND expires_at<=?""",
                    (STATUS_EXPIRED, _iso(now), session["id"], STATUS_ACTIVE, _iso(now)),
                )
                session = self._require_session(db, session["id"])
        return session

    def _assert_confirmable(self, session: sqlite3.Row) -> None:
        status = session["status"]
        if status == STATUS_ACTIVE:
            return
        mapping = {
            STATUS_PROCESSING: (409, "preview_session_not_ready"),
            STATUS_FAILED: (409, "preview_session_failed"),
            STATUS_EXPIRED: (410, "preview_session_expired"),
            STATUS_CONFIRMED: (409, "preview_session_already_confirmed"),
            STATUS_CANCELLED: (409, "preview_session_cancelled"),
            STATUS_CONFIRMING: (409, "preview_session_not_ready"),
        }
        status_code, code = mapping.get(status, (409, "invalid_preview_session_status"))
        raise PreviewDomainError(code, status_code)

    def _session_values(self, session: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": session["id"],
            "owner_user_id": session["owner_user_id"],
            "project_variant_id": session["project_variant_id"],
            "taxonomy_dictionary_version": session["taxonomy_dictionary_version"],
            "building_params": _json_load(session["building_params"], {}),
            "project_structure_options": _json_load(session["project_structure_options"], {}),
            "source_file_fingerprint_algorithm": session["source_file_fingerprint_algorithm"],
            "source_file_fingerprint": session["source_file_fingerprint"],
            "source_file_size_bytes": session["source_file_size_bytes"],
        }

    def _preview_content_payload(self, session: sqlite3.Row, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        values = self._session_values(session)
        return {
            "preview_content_hash_payload_version": PREVIEW_CONTENT_HASH_PAYLOAD_VERSION,
            "preview_session_id": values["id"],
            "owner_user_id": values["owner_user_id"],
            "project_variant_id": values["project_variant_id"],
            "taxonomy_dictionary_version": values["taxonomy_dictionary_version"],
            "building_params": values["building_params"],
            "project_structure_options": values["project_structure_options"],
            "source_file_fingerprint_algorithm": values["source_file_fingerprint_algorithm"],
            "source_file_fingerprint": values["source_file_fingerprint"],
            "source_file_size_bytes": values["source_file_size_bytes"],
            "rows": [
                {
                    "source_row_key": row["source_row_key"],
                    "source_row_index": row["source_row_index"],
                    "source_text": row["source_text"],
                    "parsed_data": copy.deepcopy(row["parsed_data"]),
                    "classification_result": copy.deepcopy(row["classification_result"]),
                }
                for row in sorted(rows, key=lambda item: (item["source_row_index"], item["source_row_key"]))
            ],
        }

    def _preview_content_hash(self, session: sqlite3.Row, rows: Sequence[Mapping[str, Any]]) -> str:
        payload = self._preview_content_payload(session, rows)
        return hashlib.sha256(CanonicalJsonServiceV2.dump_bytes(payload)).hexdigest()

    def _snapshot_payload(self, session: sqlite3.Row, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        values = self._session_values(session)
        return {
            "snapshot_payload_version": SNAPSHOT_PAYLOAD_VERSION,
            "preview_session_id": values["id"],
            "owner_user_id": values["owner_user_id"],
            "project_variant_id": values["project_variant_id"],
            "taxonomy_dictionary_version": values["taxonomy_dictionary_version"],
            "building_params": values["building_params"],
            "project_structure_options": values["project_structure_options"],
            "source_file_fingerprint_algorithm": values["source_file_fingerprint_algorithm"],
            "source_file_fingerprint": values["source_file_fingerprint"],
            "source_file_size_bytes": values["source_file_size_bytes"],
            "rows": [
                {
                    "source_row_key": row["source_row_key"],
                    "source_row_index": row["source_row_index"],
                    "source_text": row["source_text"],
                    "parsed_data": copy.deepcopy(row["parsed_data"]),
                    "classification_result": copy.deepcopy(row["classification_result"]),
                    "confirmation_approved": row["confirmation_approved"],
                    "confirmation_manual_override": copy.deepcopy(row["confirmation_manual_override"]),
                }
                for row in sorted(rows, key=lambda item: (item["source_row_index"], item["source_row_key"]))
            ],
        }

    def _public_payload(self, session: sqlite3.Row, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        payload = self._session_values(session)
        for field in (
            "status", "created_at", "processing_deadline_at", "activated_at", "expires_at",
            "confirmed_at", "cancelled_at", "expired_at", "failed_at", "failure_code",
            "estimate_batch_id", "snapshot_payload_version", "snapshot_hash_algorithm",
            "snapshot_hash", "snapshot_purged_at", "preview_content_hash_payload_version",
            "preview_content_hash_algorithm", "preview_content_hash",
        ):
            payload[field] = session[field]
        payload["failure_details"] = _json_load(session["failure_details"], None)
        payload["rows"] = [copy.deepcopy(dict(row)) for row in rows]
        payload["can_confirm"] = session["status"] == STATUS_ACTIVE
        payload["can_cancel"] = session["status"] == STATUS_ACTIVE
        return payload
