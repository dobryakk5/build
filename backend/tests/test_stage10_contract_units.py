from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.core.permissions import (
    REVALIDATE_BLOCKED_BATCH_PERMISSION,
    has_project_permission,
)
from app.services.dynamic_floor_feature_flag import (
    DYNAMIC_FLOOR_VARIANT_ID,
    DynamicFloorFeatureConfig,
    DynamicFloorFeatureGate,
    FeatureFlagError,
)
from app.services.source_identity_service import (
    TAXONOMY_SOURCE_ROW_NAMESPACE,
    legacy_source_row_key,
)
from app.services.stage10_jsonb_registry import (
    JSONB_PATH_REGISTRY_VERSION,
    LEGACY_SCOPE_JSONB_PATHS,
)
from app.services.taxonomy_compatibility_service import batch_uses_legacy_taxonomy
from app.api.routes.estimates import _forbid_dynamic_floor_legacy_redis_path


def test_stage10_revalidation_permission_is_project_role_scoped():
    assert has_project_permission("owner", REVALIDATE_BLOCKED_BATCH_PERMISSION)
    assert has_project_permission("pm", REVALIDATE_BLOCKED_BATCH_PERMISSION)
    for role in ("foreman", "supplier", "viewer", "unknown"):
        assert not has_project_permission(role, REVALIDATE_BLOCKED_BATCH_PERMISSION)


def test_dynamic_floor_feature_flag_off_forbids_exact_variant():
    gate = DynamicFloorFeatureGate(DynamicFloorFeatureConfig.parse(mode="off", allowlist_text=""))
    with pytest.raises(FeatureFlagError) as exc:
        gate.ensure_allowed(project_variant_id=DYNAMIC_FLOOR_VARIANT_ID, user_id=UUID(int=1))
    assert exc.value.code == "dynamic_floor_structure_2_7_disabled"
    assert exc.value.http_status == 409


def test_dynamic_floor_feature_flag_allowlist_empty_allows_nobody():
    gate = DynamicFloorFeatureGate(DynamicFloorFeatureConfig.parse(mode="allowlist", allowlist_text=""))
    with pytest.raises(FeatureFlagError) as exc:
        gate.ensure_allowed(project_variant_id=DYNAMIC_FLOOR_VARIANT_ID, user_id=UUID(int=1))
    assert exc.value.code == "dynamic_floor_structure_2_7_not_allowed"
    assert exc.value.http_status == 409


def test_dynamic_floor_feature_flag_invalid_allowlist_is_server_config_error():
    with pytest.raises(FeatureFlagError) as exc:
        DynamicFloorFeatureConfig.parse(mode="allowlist", allowlist_text="not-a-uuid")
    assert exc.value.code == "dynamic_floor_structure_2_7_allowlist_invalid"
    assert exc.value.http_status == 500


def test_legacy_source_row_key_is_stable_uuid_v5():
    first = legacy_source_row_key("550e8400-e29b-41d4-a716-446655440000", "550e8400-e29b-41d4-a716-446655440001")
    second = legacy_source_row_key("550e8400-e29b-41d4-a716-446655440000", "550e8400-e29b-41d4-a716-446655440001")
    assert first == second
    assert UUID(first).version == 5
    assert TAXONOMY_SOURCE_ROW_NAMESPACE == UUID("87a63bb7-9041-59aa-bdfe-4418504ccae8")


def test_closed_jsonb_registry_is_versioned_and_nonempty():
    assert JSONB_PATH_REGISTRY_VERSION == "stage10_legacy_scope_jsonb_paths@1.0.0"
    assert LEGACY_SCOPE_JSONB_PATHS
    assert any(spec.table_name == "estimates" and spec.column_name == "raw_data" for spec in LEGACY_SCOPE_JSONB_PATHS)


def test_legacy_redis_upload_path_is_forbidden_for_dynamic_floor_variant(monkeypatch):
    monkeypatch.setattr(
        "app.services.dynamic_floor_feature_flag.settings.DYNAMIC_FLOOR_STRUCTURE_2_7_MODE",
        "off",
    )
    with pytest.raises(HTTPException) as exc:
        _forbid_dynamic_floor_legacy_redis_path(DYNAMIC_FLOOR_VARIANT_ID, str(UUID(int=1)))
    assert exc.value.status_code == 409
    assert exc.value.detail == {"code": "dynamic_floor_structure_2_7_disabled"}

    assert _forbid_dynamic_floor_legacy_redis_path("another_variant", str(UUID(int=1))) is None


def test_stage10_snapshot_batch_is_not_legacy_when_estimate_raw_data_is_audit_only():
    batch = SimpleNamespace(
        project_variant_id=DYNAMIC_FLOOR_VARIANT_ID,
        taxonomy_resolution_mode="persisted_snapshot",
        taxonomy_dictionary_version="construction_work_dictionary_v6_5_0@1.9.0",
        taxonomy_snapshot={"source_dictionary_version": "construction_work_dictionary_v6_5_0@1.9.0"},
    )
    estimates = [
        SimpleNamespace(raw_data={"row": ["1", "Работа без legacy taxonomy-полей"]}),
    ]

    assert not batch_uses_legacy_taxonomy(batch, estimates)
