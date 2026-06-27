"""Immutable batch-level taxonomy snapshots for post-release imports."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    from app.services.canonical_json_service import CanonicalJsonServiceV2
except ModuleNotFoundError:  # standalone delivery scripts
    from services.canonical_json_service import CanonicalJsonServiceV2

BATCH_TAXONOMY_SNAPSHOT_SCHEMA_VERSION = "estimate_batch_taxonomy_snapshot@1.0.0"
SNAPSHOT_PAYLOAD_VERSION = 1
TARGET_DICTIONARY_FILENAME = "construction_work_dictionary_v6_5_0.json"
SNAPSHOT_EXTERNAL_METADATA_KEYS = frozenset(
    {
        "building_params",
        "work_rate_catalog_version",
        "work_rate_catalog_hash",
    }
)


def resolve_config_path(path_text: str) -> Path:
    path = Path(path_text)
    if path.exists():
        return path
    project_root = Path(__file__).resolve().parents[3]
    candidate = project_root / path_text
    if candidate.exists():
        return candidate
    backend_root = Path(__file__).resolve().parents[2]
    candidate = backend_root / path_text
    if candidate.exists():
        return candidate
    return path


class TaxonomySnapshotError(ValueError):
    code = "taxonomy_snapshot_error"


class TaxonomyVariantNotFound(TaxonomySnapshotError):
    code = "taxonomy_variant_not_found"


class TaxonomySnapshotIntegrityError(TaxonomySnapshotError):
    code = "taxonomy_snapshot_integrity_mismatch"


@dataclass(frozen=True)
class ImmutableTaxonomySnapshot:
    """Canonical payload plus integrity hash with no mutable internal object."""

    canonical_json: str
    content_hash: str

    def to_json(self) -> dict[str, Any]:
        # Parsing the canonical string returns a new object for every caller, so
        # nested mutations cannot modify the stored snapshot.
        result = json.loads(self.canonical_json)
        result["snapshot_content_hash_algorithm"] = "sha256"
        result["snapshot_content_hash"] = self.content_hash
        return result

    def assert_integrity(self, candidate: Mapping[str, Any] | None = None) -> None:
        payload = copy.deepcopy(dict(candidate) if candidate is not None else self.to_json())
        expected = str(payload.pop("snapshot_content_hash", "") or "")
        algorithm = str(payload.pop("snapshot_content_hash_algorithm", "") or "")
        for key in SNAPSHOT_EXTERNAL_METADATA_KEYS:
            payload.pop(key, None)
        if algorithm != "sha256" or expected != self.content_hash:
            raise TaxonomySnapshotIntegrityError("snapshot integrity metadata does not match")
        actual_json = CanonicalJsonServiceV2.dumps(payload)
        actual = hashlib.sha256(actual_json.encode("utf-8")).hexdigest()
        if actual != expected:
            raise TaxonomySnapshotIntegrityError("taxonomy snapshot payload was modified")


def _dictionary_sha256(dictionary: Mapping[str, Any]) -> str:
    # Source dictionaries are released JSON artifacts.  For in-memory builders,
    # use deterministic compact JSON rather than filesystem formatting.
    raw = json.dumps(dictionary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_target_dictionary(root: str | Path | None = None) -> tuple[dict[str, Any], str]:
    if root is not None:
        path = Path(root) / "data" / TARGET_DICTIONARY_FILENAME
    else:
        try:
            from app.core.config import settings
        except ModuleNotFoundError:  # standalone delivery scripts
            path = Path(__file__).resolve().parents[1] / "data" / TARGET_DICTIONARY_FILENAME
        else:
            path = resolve_config_path(settings.WORK_TAXONOMY_PATH)
    raw_bytes = path.read_bytes()
    return json.loads(raw_bytes.decode("utf-8")), hashlib.sha256(raw_bytes).hexdigest()


def work_rate_catalog_hash(path: str | Path | None = None) -> str | None:
    if path is None:
        try:
            from app.core.config import settings
        except ModuleNotFoundError:
            return None
        path = settings.WORK_RATE_CATALOG_PATH
    resolved = resolve_config_path(str(path))
    return hashlib.sha256(resolved.read_bytes()).hexdigest() if resolved.exists() else None


def _find_variant(dictionary: Mapping[str, Any], project_variant_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    hierarchy = dictionary.get("project_hierarchy")
    estimate_types = hierarchy.get("estimate_types") if isinstance(hierarchy, Mapping) else None
    for estimate_type in estimate_types or []:
        if not isinstance(estimate_type, Mapping):
            continue
        for variant in estimate_type.get("project_variants") or []:
            if isinstance(variant, Mapping) and variant.get("id") == project_variant_id:
                return copy.deepcopy(dict(estimate_type)), copy.deepcopy(dict(variant))
    raise TaxonomyVariantNotFound(project_variant_id)


def build_immutable_taxonomy_snapshot(
    *,
    project_variant_id: str,
    dictionary: Mapping[str, Any] | None = None,
    source_dictionary_sha256: str | None = None,
) -> ImmutableTaxonomySnapshot:
    if dictionary is None:
        loaded, file_hash = load_target_dictionary()
        dictionary = loaded
        source_dictionary_sha256 = file_hash
    estimate_type, variant = _find_variant(dictionary, project_variant_id)
    source_hash = source_dictionary_sha256 or _dictionary_sha256(dictionary)
    applicability_schema = copy.deepcopy(dictionary.get("applicability_schema") or {})
    operation_policy = copy.deepcopy(dictionary.get("operation_object_resolution_policy") or {})
    payload: dict[str, Any] = {
        "snapshot_schema_version": BATCH_TAXONOMY_SNAPSHOT_SCHEMA_VERSION,
        "snapshot_payload_version": SNAPSHOT_PAYLOAD_VERSION,
        "source_dictionary_version": dictionary.get("dictionary_version"),
        "source_dictionary_schema_version": (dictionary.get("meta") or {}).get("schema_version"),
        "source_dictionary_sha256": source_hash,
        "project_variant_id": project_variant_id,
        "estimate_type": {
            key: copy.deepcopy(estimate_type.get(key))
            for key in ("id", "number", "title", "estimate_kind")
            if estimate_type.get(key) is not None
        },
        "variant": variant,
        "applicability_schema": applicability_schema,
        "applicability_schema_version": applicability_schema.get("schema_version"),
        "canonicalizer_versions": {
            "snapshot": CanonicalJsonServiceV2.version,
            "applicability_hash_v1": "legacy_applicability_canonical_json_v1@1",
            "applicability_hash_v2": CanonicalJsonServiceV2.version,
        },
        "hash_payload_versions": {
            "taxonomy_snapshot": SNAPSHOT_PAYLOAD_VERSION,
            "preview_content_hash": 1,
            "snapshot_hash": 1,
        },
        # These explicit copies make the downstream dependency contract clear,
        # even though the exact variant subtree is also preserved above.
        "operation_registry": copy.deepcopy(variant.get("operation_registry") or {}),
        "package_definitions": copy.deepcopy(operation_policy.get("operation_packages") or {}),
        "operation_object_resolution_policy": operation_policy,
    }
    canonical = CanonicalJsonServiceV2.dumps(payload)
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return ImmutableTaxonomySnapshot(canonical, content_hash)


def load_immutable_taxonomy_snapshot(payload: Mapping[str, Any]) -> ImmutableTaxonomySnapshot:
    copy_payload = copy.deepcopy(dict(payload))
    expected = str(copy_payload.pop("snapshot_content_hash", "") or "")
    algorithm = str(copy_payload.pop("snapshot_content_hash_algorithm", "") or "")
    for key in SNAPSHOT_EXTERNAL_METADATA_KEYS:
        copy_payload.pop(key, None)
    if algorithm != "sha256" or len(expected) != 64:
        raise TaxonomySnapshotIntegrityError("invalid taxonomy snapshot integrity metadata")
    canonical = CanonicalJsonServiceV2.dumps(copy_payload)
    actual = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if actual != expected:
        raise TaxonomySnapshotIntegrityError("taxonomy snapshot payload was modified")
    return ImmutableTaxonomySnapshot(canonical, actual)
