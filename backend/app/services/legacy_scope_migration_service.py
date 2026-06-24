"""Batch-atomic legacy source-row/applicability migration.

This module is the stage-8 reference implementation.  It deliberately uses a
closed, versioned JSON-path registry and never scans arbitrary string leaves.
Production repositories must preserve the same one-transaction-per-batch
boundary and failure semantics.
"""
from __future__ import annotations

import copy
import json
import re
import sqlite3
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping, MutableMapping, Sequence
from uuid import UUID, uuid4

try:
    from app.services.applicability_hash_service import ApplicabilityHashService
    from app.services.canonical_json_service import LegacyApplicabilityCanonicalJsonV1
    from app.services.estimate_preview_service import (
        SqliteEstimatePreviewStore,
        _json_dump,
        _json_load,
        _uuid_text,
        utcnow,
        _iso,
    )
    from app.services.source_identity_service import legacy_source_row_key
except ModuleNotFoundError:  # standalone delivery scripts
    from services.applicability_hash_service import ApplicabilityHashService
    from services.canonical_json_service import LegacyApplicabilityCanonicalJsonV1
    from services.estimate_preview_service import (
        SqliteEstimatePreviewStore,
        _json_dump,
        _json_load,
        _uuid_text,
        utcnow,
        _iso,
    )
    from services.source_identity_service import legacy_source_row_key

LEGACY_SCOPE_JSON_REGISTRY_VERSION = "legacy_scope_json_paths@1.0.0"
LEGACY_SCOPE_RE = re.compile(r"^estimate_row:(?P<estimate_id>[0-9A-Fa-f-]{36})$")

# Exact, frozen paths only.  ``*`` means every element of an array at that
# registered location; it is not a recursive wildcard.
LEGACY_SCOPE_JSON_PATHS_V1 = MappingProxyType({
    "estimates": MappingProxyType({
        "raw_data": (
            ("source_row_key",),
            ("work_scope_key",),
            ("legacy_work_scope_key",),
            ("applicability_hash",),
            ("applicability_hash_version",),
            ("applicability_schema_version",),
            ("applicability",),
        ),
        "calculation_trace": (
            ("*", "source_row_key"),
            ("*", "work_scope_key"),
            ("*", "applicability_hash"),
            ("*", "applicability_hash_version"),
            ("events", "*", "source_row_key"),
            ("events", "*", "work_scope_key"),
            ("events", "*", "applicability_hash"),
            ("events", "*", "applicability_hash_version"),
        ),
        "projection_json": (
            ("source_row_key",),
            ("work_scope_key",),
            ("applicability_hash",),
            ("applicability_hash_version",),
            ("projections", "*", "source_row_key"),
            ("projections", "*", "work_scope_key"),
            ("projections", "*", "applicability_hash"),
            ("projections", "*", "applicability_hash_version"),
        ),
    }),
    "estimate_quantity_projections": MappingProxyType({
        "metadata_json": (
            ("source_row_key",),
            ("work_scope_key",),
            ("applicability_hash",),
            ("applicability_hash_version",),
        ),
    }),
    "estimate_package_resolutions": MappingProxyType({
        "resolution_payload": (
            ("source_row_key",),
            ("work_scope_key",),
            ("applicability_hash",),
            ("applicability_hash_version",),
        ),
    }),
    "ktp_groups": MappingProxyType({
        "metadata_json": (
            ("source_rows", "*", "source_row_key"),
            ("source_rows", "*", "work_scope_key"),
            ("source_rows", "*", "applicability_hash"),
            ("source_rows", "*", "applicability_hash_version"),
        ),
    }),
    "ktp_items": MappingProxyType({
        "metadata_json": (
            ("source_row_key",),
            ("work_scope_key",),
            ("applicability_hash",),
            ("applicability_hash_version",),
        ),
    }),
    "gantt_tasks": MappingProxyType({
        "projection_metadata": (
            ("source_row_key",),
            ("work_scope_key",),
            ("applicability_hash",),
            ("applicability_hash_version",),
        ),
    }),
    "taxonomy_snapshots": MappingProxyType({
        "snapshot_payload": (
            ("rows", "*", "source_row_key"),
            ("rows", "*", "work_scope_key"),
            ("rows", "*", "applicability_hash"),
            ("rows", "*", "applicability_hash_version"),
            ("projection_json", "*", "source_row_key"),
            ("projection_json", "*", "work_scope_key"),
        ),
    }),
})

MIGRATION_PENDING = "pending"
MIGRATION_COMPLETED = "completed"
MIGRATION_FAILED = "failed"
MIGRATION_NOT_REQUIRED = "not_required"


class LegacyMigrationError(RuntimeError):
    reason_code = "legacy_projection_scope_unresolved"

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.details = copy.deepcopy(dict(details or {}))


class LegacyProjectionScopeUnresolved(LegacyMigrationError):
    reason_code = "legacy_projection_scope_unresolved"


class LegacyApplicabilityUnrecoverable(LegacyMigrationError):
    reason_code = "legacy_applicability_unrecoverable"


@dataclass(frozen=True)
class EstimateRemap:
    estimate_id: str
    source_row_key: str
    legacy_work_scope_key: str
    work_scope_key: str
    applicability: dict[str, Any]
    applicability_hash: str
    applicability_hash_version: int = 1
    applicability_schema_version: None = None


@dataclass(frozen=True)
class LegacyMigrationResult:
    batch_id: str
    status: str
    migrated_estimate_count: int
    updated_record_counts: Mapping[str, int]
    reason_code: str | None = None


class _JsonPathTools:
    @classmethod
    def values(cls, payload: Any, path: Sequence[str]) -> list[Any]:
        if not path:
            return [payload]
        head, *tail = path
        if head == "*":
            if not isinstance(payload, list):
                return []
            out: list[Any] = []
            for item in payload:
                out.extend(cls.values(item, tail))
            return out
        if not isinstance(payload, Mapping) or head not in payload:
            return []
        return cls.values(payload[head], tail)

    @classmethod
    def replace(cls, payload: Any, path: Sequence[str], replacer) -> int:
        if not path:
            return 0
        head, *tail = path
        if head == "*":
            if not isinstance(payload, list):
                return 0
            return sum(cls.replace(item, tail, replacer) for item in payload)
        if not isinstance(payload, MutableMapping) or head not in payload:
            return 0
        if not tail:
            old = payload[head]
            new, changed = replacer(old, head)
            if changed:
                payload[head] = new
                return 1
            return 0
        return cls.replace(payload[head], tail, replacer)


class LegacyScopeMigrationService:
    """Migrate one legacy batch in one transaction and mark failures separately."""

    DOWNSTREAM_TABLES = (
        "estimate_quantity_projections",
        "estimate_package_resolutions",
        "ktp_items",
        "gantt_tasks",
    )
    MULTI_SCOPE_TABLES = ("ktp_groups", "taxonomy_snapshots")

    def __init__(self, *, store: SqliteEstimatePreviewStore, fault_hook=None):
        self.store = store
        self.fault_hook = fault_hook or (lambda _point: None)

    def migrate_batch(self, batch_id: Any) -> LegacyMigrationResult:
        batch_uuid = _uuid_text(batch_id, field="estimate_batch_id")
        run_id = self._start_audit_run(batch_uuid)
        try:
            result = self._migrate_batch_atomic(batch_uuid)
        except LegacyMigrationError as exc:
            self._mark_failed(batch_uuid, exc)
            self._finish_audit_run(run_id, status="failed", failure_code=exc.reason_code, failure_details=exc.details)
            return LegacyMigrationResult(
                batch_id=batch_uuid,
                status=MIGRATION_FAILED,
                migrated_estimate_count=0,
                updated_record_counts={},
                reason_code=exc.reason_code,
            )
        except Exception as exc:
            self._finish_audit_run(
                run_id,
                status="failed",
                failure_code="legacy_scope_migration_failed",
                failure_details={"exception_type": type(exc).__name__, "message": str(exc)},
            )
            raise
        self._finish_audit_run(
            run_id,
            status="completed",
            migrated_estimate_count=result.migrated_estimate_count,
            updated_record_counts=result.updated_record_counts,
        )
        return result

    def _migrate_batch_atomic(self, batch_id: str) -> LegacyMigrationResult:
        counts: dict[str, int] = {}
        with self.store.transaction() as db:
            batch = db.execute("SELECT * FROM estimate_batches WHERE id=?", (batch_id,)).fetchone()
            if batch is None:
                raise KeyError("estimate batch not found")
            if batch["source_row_scope_migration_status"] == MIGRATION_COMPLETED:
                return LegacyMigrationResult(batch_id, MIGRATION_COMPLETED, 0, {})
            if int(batch["source_row_scope_version"] or 0) != 1:
                raise LegacyProjectionScopeUnresolved(
                    "only source_row_scope_version=1 can be backfilled",
                    details={"source_row_scope_version": batch["source_row_scope_version"]},
                )

            estimate_rows = db.execute(
                "SELECT * FROM estimates WHERE estimate_batch_id=? ORDER BY id", (batch_id,)
            ).fetchall()
            remaps = self._build_remaps(batch_id, estimate_rows)
            if not remaps:
                raise LegacyProjectionScopeUnresolved("legacy batch has no estimates")

            for estimate in estimate_rows:
                remap = remaps[estimate["id"]]
                json_updates = self._rewrite_estimate_json(estimate, remap)
                db.execute(
                    """UPDATE estimates SET source_row_key=?, work_scope_key=?, legacy_work_scope_key=?,
                       applicability=?, applicability_hash=?, applicability_hash_version=1,
                       applicability_schema_version=NULL, raw_data=?, calculation_trace=?, projection_json=?,
                       updated_at=? WHERE id=? AND estimate_batch_id=?""",
                    (
                        remap.source_row_key,
                        remap.work_scope_key,
                        remap.legacy_work_scope_key,
                        _json_dump(remap.applicability),
                        remap.applicability_hash,
                        json_updates["raw_data"],
                        json_updates["calculation_trace"],
                        json_updates["projection_json"],
                        _iso(utcnow()),
                        estimate["id"],
                        batch_id,
                    ),
                )
            counts["estimates"] = len(estimate_rows)
            self.fault_hook("after_estimates")

            for table in self.DOWNSTREAM_TABLES:
                counts[table] = self._rewrite_single_scope_table(db, table, batch_id, remaps)
                self.fault_hook(f"after_{table}")
            for table in self.MULTI_SCOPE_TABLES:
                counts[table] = self._rewrite_multi_scope_table(db, table, batch_id, remaps)
                self.fault_hook(f"after_{table}")

            # Stage summaries are stage-level, but any registered JSON metadata
            # must still be remapped if the table is later extended.
            counts["stage_instance_projection_summaries"] = 0

            db.execute(
                """UPDATE estimate_batches
                   SET source_row_scope_version=2,
                       source_row_scope_migration_status='completed',
                       source_row_scope_migration_failure_code=NULL,
                       source_row_scope_migration_failure_details=NULL,
                       applicability_hash_version=1,
                       applicability_schema_version=NULL,
                       calculation_status=CASE WHEN calculation_status='blocked' THEN 'pending' ELSE calculation_status END,
                       calculation_block_reason=NULL
                   WHERE id=?""",
                (batch_id,),
            )
            self.fault_hook("before_commit")
            return LegacyMigrationResult(batch_id, MIGRATION_COMPLETED, len(remaps), MappingProxyType(dict(counts)))

    def _build_remaps(self, batch_id: str, estimates: Iterable[sqlite3.Row]) -> dict[str, EstimateRemap]:
        remaps: dict[str, EstimateRemap] = {}
        for row in estimates:
            estimate_id = str(UUID(str(row["id"])))
            old_scope = str(row["work_scope_key"] or f"estimate_row:{estimate_id}")
            matched = LEGACY_SCOPE_RE.fullmatch(old_scope)
            if not matched or str(UUID(matched.group("estimate_id"))) != estimate_id:
                raise LegacyProjectionScopeUnresolved(
                    "estimate scope does not identify its own row",
                    details={"estimate_id": estimate_id, "work_scope_key": old_scope},
                )
            applicability = self._recover_applicability(row)
            hash_result = ApplicabilityHashService.calculate(applicability, hash_version=1)
            source_key = str(legacy_source_row_key(batch_id, estimate_id))
            remaps[estimate_id] = EstimateRemap(
                estimate_id=estimate_id,
                source_row_key=source_key,
                legacy_work_scope_key=old_scope,
                work_scope_key=f"estimate_row:{source_key}",
                applicability=applicability,
                applicability_hash=hash_result.hash_value,
            )
        return remaps

    def _recover_applicability(self, row: sqlite3.Row) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        direct = _json_load(row["applicability"], None)
        if isinstance(direct, Mapping):
            candidates.append(dict(direct))
        for column in ("raw_data", "parsed_data", "classification_result"):
            payload = _json_load(row[column], {})
            if isinstance(payload, Mapping) and isinstance(payload.get("applicability"), Mapping):
                candidates.append(dict(payload["applicability"]))
        unique: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            unique[LegacyApplicabilityCanonicalJsonV1.dumps(candidate)] = candidate
        non_empty = {key: value for key, value in unique.items() if value}
        if non_empty:
            unique = non_empty
        if len(unique) != 1:
            raise LegacyApplicabilityUnrecoverable(
                "applicability cannot be restored unambiguously",
                details={"estimate_id": row["id"], "candidate_count": len(unique)},
            )
        return next(iter(unique.values()))

    def _rewrite_estimate_json(self, row: sqlite3.Row, remap: EstimateRemap) -> dict[str, str | None]:
        result: dict[str, str | None] = {}
        table_registry = LEGACY_SCOPE_JSON_PATHS_V1["estimates"]
        for column, paths in table_registry.items():
            raw = row[column]
            if raw is None:
                result[column] = None
                continue
            payload = _json_load(raw, None)
            if payload is None:
                result[column] = raw
                continue
            for path in paths:
                _JsonPathTools.replace(payload, path, lambda value, field: self._replace_value(value, field, remap, {remap.estimate_id: remap}))
            result[column] = _json_dump(payload)
        return result

    def _rewrite_single_scope_table(
        self, db: sqlite3.Connection, table: str, batch_id: str, remaps: Mapping[str, EstimateRemap]
    ) -> int:
        rows = db.execute(f"SELECT * FROM {table} WHERE estimate_batch_id=? ORDER BY id", (batch_id,)).fetchall()
        registry = LEGACY_SCOPE_JSON_PATHS_V1.get(table, {})
        updated = 0
        for row in rows:
            remap = self._resolve_row_remap(row, table, remaps, registry)
            assignments: dict[str, Any] = {}
            for column in ("source_row_key", "work_scope_key", "applicability", "applicability_hash", "applicability_hash_version", "applicability_schema_version"):
                if column in row.keys():
                    assignments[column] = {
                        "source_row_key": remap.source_row_key,
                        "work_scope_key": remap.work_scope_key,
                        "applicability": _json_dump(remap.applicability),
                        "applicability_hash": remap.applicability_hash,
                        "applicability_hash_version": 1,
                        "applicability_schema_version": None,
                    }[column]
            for column, paths in registry.items():
                raw = row[column]
                if raw is None:
                    continue
                payload = _json_load(raw, None)
                if payload is None:
                    continue
                for path in paths:
                    _JsonPathTools.replace(payload, path, lambda value, field: self._replace_value(value, field, remap, remaps))
                assignments[column] = _json_dump(payload)
            if assignments:
                sql = ", ".join(f"{key}=?" for key in assignments)
                db.execute(f"UPDATE {table} SET {sql} WHERE id=?", (*assignments.values(), row["id"]))
                updated += 1
        return updated

    def _rewrite_multi_scope_table(
        self, db: sqlite3.Connection, table: str, batch_id: str, remaps: Mapping[str, EstimateRemap]
    ) -> int:
        rows = db.execute(f"SELECT * FROM {table} WHERE estimate_batch_id=? ORDER BY id", (batch_id,)).fetchall()
        registry = LEGACY_SCOPE_JSON_PATHS_V1.get(table, {})
        updated = 0
        for row in rows:
            assignments: dict[str, Any] = {}
            for column, paths in registry.items():
                payload = _json_load(row[column], None)
                if payload is None:
                    continue
                before = _json_dump(payload)
                self._rewrite_registered_row_collections(table, payload, remaps)
                for path in paths:
                    _JsonPathTools.replace(payload, path, lambda value, field: self._replace_global_value(value, field, remaps))
                after = _json_dump(payload)
                if after != before:
                    assignments[column] = after
            if assignments:
                sql = ", ".join(f"{key}=?" for key in assignments)
                db.execute(f"UPDATE {table} SET {sql} WHERE id=?", (*assignments.values(), row["id"]))
                updated += 1
        return updated

    def _rewrite_registered_row_collections(
        self, table: str, payload: Any, remaps: Mapping[str, EstimateRemap]
    ) -> None:
        if not isinstance(payload, MutableMapping):
            return
        collection_names = {
            "ktp_groups": ("source_rows",),
            "taxonomy_snapshots": ("rows", "projection_json"),
        }.get(table, ())
        for name in collection_names:
            collection = payload.get(name)
            if not isinstance(collection, list):
                continue
            for item in collection:
                if not isinstance(item, MutableMapping):
                    continue
                candidate_ids = self._estimate_ids_from_value(item.get("work_scope_key"))
                if not candidate_ids:
                    try:
                        candidate_id = str(UUID(str(item.get("source_row_key"))))
                    except (ValueError, TypeError):
                        continue
                    candidate_ids = {candidate_id}
                if len(candidate_ids) != 1:
                    raise LegacyProjectionScopeUnresolved("embedded row has ambiguous legacy identity")
                estimate_id = next(iter(candidate_ids))
                if estimate_id not in remaps:
                    raise LegacyProjectionScopeUnresolved("embedded row points outside batch")
                remap = remaps[estimate_id]
                item["source_row_key"] = remap.source_row_key
                item["work_scope_key"] = remap.work_scope_key
                if "applicability_hash" in item:
                    item["applicability_hash"] = remap.applicability_hash
                if "applicability_hash_version" in item:
                    item["applicability_hash_version"] = 1
                if "applicability_schema_version" in item:
                    item["applicability_schema_version"] = None

    def _resolve_row_remap(
        self,
        row: sqlite3.Row,
        table: str,
        remaps: Mapping[str, EstimateRemap],
        registry: Mapping[str, Sequence[Sequence[str]]],
    ) -> EstimateRemap:
        candidates: set[str] = set()
        direct_id = row["estimate_id"] if "estimate_id" in row.keys() else None
        if direct_id:
            try:
                candidates.add(str(UUID(str(direct_id))))
            except ValueError as exc:
                raise LegacyProjectionScopeUnresolved(f"{table} has invalid estimate_id") from exc
        if "work_scope_key" in row.keys() and row["work_scope_key"]:
            candidates.update(self._estimate_ids_from_value(row["work_scope_key"]))
        for column, paths in registry.items():
            payload = _json_load(row[column], None)
            if payload is None:
                continue
            for path in paths:
                for value in _JsonPathTools.values(payload, path):
                    if path[-1] == "work_scope_key":
                        candidates.update(self._estimate_ids_from_value(value))
        if len(candidates) != 1:
            raise LegacyProjectionScopeUnresolved(
                f"{table} row cannot be linked to exactly one estimate",
                details={"table": table, "record_id": row["id"], "candidate_estimate_ids": sorted(candidates)},
            )
        estimate_id = next(iter(candidates))
        if estimate_id not in remaps:
            raise LegacyProjectionScopeUnresolved(
                f"{table} points to an estimate outside the batch",
                details={"table": table, "record_id": row["id"], "estimate_id": estimate_id},
            )
        return remaps[estimate_id]

    @staticmethod
    def _estimate_ids_from_value(value: Any) -> set[str]:
        if not isinstance(value, str):
            return set()
        matched = LEGACY_SCOPE_RE.fullmatch(value.strip())
        if not matched:
            return set()
        try:
            return {str(UUID(matched.group("estimate_id")))}
        except ValueError:
            return set()

    def _replace_value(
        self, value: Any, field: str, remap: EstimateRemap, remaps: Mapping[str, EstimateRemap]
    ) -> tuple[Any, bool]:
        if field == "source_row_key":
            return remap.source_row_key, value != remap.source_row_key
        if field == "work_scope_key":
            legacy_ids = self._estimate_ids_from_value(value)
            if legacy_ids and legacy_ids != {remap.estimate_id}:
                raise LegacyProjectionScopeUnresolved("conflicting scope in registered JSON path")
            return remap.work_scope_key, value != remap.work_scope_key
        if field == "legacy_work_scope_key":
            return remap.legacy_work_scope_key, value != remap.legacy_work_scope_key
        if field == "applicability_hash":
            return remap.applicability_hash, value != remap.applicability_hash
        if field == "applicability_hash_version":
            return 1, value != 1
        if field == "applicability_schema_version":
            return None, value is not None
        if field == "applicability":
            return copy.deepcopy(remap.applicability), value != remap.applicability
        return value, False

    def _replace_global_value(
        self, value: Any, field: str, remaps: Mapping[str, EstimateRemap]
    ) -> tuple[Any, bool]:
        if field == "work_scope_key":
            if value in {remap.work_scope_key for remap in remaps.values()}:
                return value, False
            ids = self._estimate_ids_from_value(value)
            if not ids:
                return value, False
            estimate_id = next(iter(ids))
            if estimate_id not in remaps:
                raise LegacyProjectionScopeUnresolved("registered JSON path points outside batch")
            return remaps[estimate_id].work_scope_key, True
        if field == "source_row_key":
            if value in {remap.source_row_key for remap in remaps.values()}:
                return value, False
            # Legacy payloads used Estimate.id as row identity.
            try:
                estimate_id = str(UUID(str(value)))
            except (ValueError, TypeError):
                return value, False
            if estimate_id not in remaps:
                raise LegacyProjectionScopeUnresolved("registered JSON source_row_key points outside batch")
            return remaps[estimate_id].source_row_key, True
        # Hash fields in multi-row payloads are replaced only when adjacent row
        # metadata has already established a row; generic cross-field guessing is
        # prohibited.  Existing values therefore remain auditable.
        return value, False

    def _start_audit_run(self, batch_id: str) -> str:
        run_id = str(uuid4())
        with self.store.transaction() as db:
            db.execute(
                """INSERT INTO estimate_batch_scope_migration_runs (
                    id, estimate_batch_id, source_contract_version, target_contract_version,
                    json_path_registry_version, status, migrated_estimate_count,
                    updated_record_counts, started_at
                ) VALUES (?,?,?,?,?,'running',0,'{}',?)""",
                (run_id, batch_id, 1, 2, LEGACY_SCOPE_JSON_REGISTRY_VERSION, _iso(utcnow())),
            )
        return run_id

    def _finish_audit_run(
        self,
        run_id: str,
        *,
        status: str,
        migrated_estimate_count: int = 0,
        updated_record_counts: Mapping[str, int] | None = None,
        failure_code: str | None = None,
        failure_details: Mapping[str, Any] | None = None,
    ) -> None:
        with self.store.transaction() as db:
            db.execute(
                """UPDATE estimate_batch_scope_migration_runs
                   SET status=?, migrated_estimate_count=?, updated_record_counts=?,
                       failure_code=?, failure_details=?, finished_at=? WHERE id=?""",
                (
                    status,
                    migrated_estimate_count,
                    _json_dump(dict(updated_record_counts or {})),
                    failure_code,
                    _json_dump(dict(failure_details or {})) if failure_details is not None else None,
                    _iso(utcnow()),
                    run_id,
                ),
            )

    def _mark_failed(self, batch_id: str, exc: LegacyMigrationError) -> None:
        with self.store.transaction() as db:
            db.execute(
                """UPDATE estimate_batches SET source_row_scope_migration_status='failed',
                   source_row_scope_migration_failure_code=?,
                   source_row_scope_migration_failure_details=?,
                   calculation_status='blocked', calculation_block_reason=?
                   WHERE id=?""",
                (exc.reason_code, _json_dump(exc.details), exc.reason_code, batch_id),
            )


class LegacyMigrationRevalidationValidator:
    """Expose stage-8 blocking reasons to the later revalidation endpoint."""

    @staticmethod
    def blocking_reasons(batch: Mapping[str, Any] | sqlite3.Row) -> tuple[str, ...]:
        status = batch["source_row_scope_migration_status"]
        reason = batch["calculation_block_reason"]
        allowed = {"legacy_projection_scope_unresolved", "legacy_applicability_unrecoverable"}
        if status == MIGRATION_FAILED and reason in allowed:
            return (str(reason),)
        return ()
