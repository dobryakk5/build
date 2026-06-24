from __future__ import annotations

from uuid import UUID

import pytest

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
