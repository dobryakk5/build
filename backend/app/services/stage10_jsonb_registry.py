from __future__ import annotations

from dataclasses import dataclass


JSONB_PATH_REGISTRY_VERSION = "stage10_legacy_scope_jsonb_paths@1.0.0"


@dataclass(frozen=True)
class JsonbPathSpec:
    table_name: str
    column_name: str
    paths: tuple[tuple[str, ...], ...]


# Closed registry for DB-B legacy remapping. Backfill code may only read/write
# these paths; heuristic traversal of arbitrary JSON payloads is intentionally
# forbidden by the production contract.
LEGACY_SCOPE_JSONB_PATHS: tuple[JsonbPathSpec, ...] = (
    JsonbPathSpec(
        "estimates",
        "raw_data",
        (
            ("source_row_key",),
            ("source_scope_id",),
            ("work_scope_key",),
            ("legacy_work_scope_key",),
            ("applicability",),
            ("applicability_hash",),
            ("applicability_hash_version",),
            ("applicability_schema_version",),
            ("operation_code",),
            ("operation_package_code",),
            ("stage_instance_id",),
            ("ktp_quantity_projections",),
        ),
    ),
    JsonbPathSpec("estimates", "stage_match_score_json", (("source_row_key",), ("work_scope_key",))),
    JsonbPathSpec("estimates", "work_type_match_score_json", (("source_row_key",), ("work_scope_key",))),
    JsonbPathSpec(
        "estimate_quantity_projections",
        "metadata_json",
        (
            ("source_row_key",),
            ("work_scope_key",),
            ("applicability_hash",),
            ("applicability_hash_version",),
            ("projection_id",),
        ),
    ),
    JsonbPathSpec(
        "estimate_package_resolutions",
        "resolution_payload",
        (
            ("source_row_key",),
            ("work_scope_key",),
            ("applicability_hash",),
            ("applicability_hash_version",),
            ("package_resolution_id",),
        ),
    ),
    JsonbPathSpec("ktp_wbs_items", "work_type_candidates", (("source_row_key",), ("work_scope_key",))),
)


def registered_jsonb_paths() -> tuple[JsonbPathSpec, ...]:
    return LEGACY_SCOPE_JSONB_PATHS
