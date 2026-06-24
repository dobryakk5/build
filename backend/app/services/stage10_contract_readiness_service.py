from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.stage10_jsonb_registry import JSONB_PATH_REGISTRY_VERSION, registered_jsonb_paths


@dataclass(frozen=True)
class Stage10ReadinessReport:
    ready: bool
    failures: dict[str, int] = field(default_factory=dict)
    registry_version: str = JSONB_PATH_REGISTRY_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "failures": self.failures,
            "registry_version": self.registry_version,
        }


class Stage10ContractReadinessService:
    """Pre-flight checks for the separate DB-C contract deployment phase."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def check(self) -> Stage10ReadinessReport:
        failures: dict[str, int] = {}
        checks = {
            "legacy_scope_migration_unresolved": """
                SELECT count(*)
                FROM estimate_batches
                WHERE source_row_scope_migration_status IN ('pending','running','failed')
            """,
            "required_batch_metadata_null": """
                SELECT count(*)
                FROM estimate_batches
                WHERE project_variant_id = 'residential_construction_kirpichnye_doma'
                  AND (
                    taxonomy_snapshot IS NULL
                    OR taxonomy_dictionary_version IS NULL
                    OR work_rate_catalog_version IS NULL
                    OR work_rate_catalog_hash IS NULL
                    OR applicability_hash_version IS NULL
                    OR applicability_schema_version IS NULL
                    OR source_row_scope_version IS NULL
                  )
            """,
            "duplicate_estimate_source_row_key": """
                SELECT count(*)
                FROM (
                    SELECT estimate_batch_id, source_row_key
                    FROM estimates
                    WHERE source_row_key IS NOT NULL
                    GROUP BY estimate_batch_id, source_row_key
                    HAVING count(*) > 1
                ) duplicates
            """,
            "invalid_estimate_uuid_or_hash_lengths": """
                SELECT count(*)
                FROM estimates
                WHERE (source_row_key IS NULL AND estimate_batch_id IN (
                    SELECT id FROM estimate_batches
                    WHERE project_variant_id = 'residential_construction_kirpichnye_doma'
                ))
                OR (applicability_hash IS NOT NULL AND length(applicability_hash) <> 64)
            """,
            "missing_projection_downstream_metadata": """
                SELECT count(*)
                FROM estimate_batches b
                WHERE b.project_variant_id = 'residential_construction_kirpichnye_doma'
                  AND b.import_status = 'completed'
                  AND NOT EXISTS (
                    SELECT 1
                    FROM stage_instance_projection_summaries s
                    WHERE s.estimate_batch_id = b.id
                  )
            """,
        }
        for code, sql in checks.items():
            count = int((await self.db.scalar(text(sql))) or 0)
            if count:
                failures[code] = count
        if not registered_jsonb_paths():
            failures["jsonb_path_registry_empty"] = 1
        return Stage10ReadinessReport(ready=not failures, failures=failures)
