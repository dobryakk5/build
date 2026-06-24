"""Versioned applicability hashing and cross-entity version validation."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

try:
    from app.services.canonical_json_service import (
        CanonicalJsonServiceV2,
        LegacyApplicabilityCanonicalJsonV1,
    )
except ModuleNotFoundError:  # standalone delivery scripts
    from services.canonical_json_service import (
        CanonicalJsonServiceV2,
        LegacyApplicabilityCanonicalJsonV1,
    )

APPLICABILITY_HASH_V1 = 1
APPLICABILITY_HASH_V2 = 2
SUPPORTED_APPLICABILITY_HASH_VERSIONS = frozenset({APPLICABILITY_HASH_V1, APPLICABILITY_HASH_V2})


class ApplicabilityHashError(ValueError):
    code = "applicability_hash_error"


class UnsupportedApplicabilityHashVersion(ApplicabilityHashError):
    code = "unsupported_applicability_hash_version"


class InvalidApplicabilitySchema(ApplicabilityHashError):
    code = "invalid_applicability_schema"


@dataclass(frozen=True)
class ApplicabilityHashResult:
    hash_value: str
    hash_version: int
    schema_version: str | None
    canonical_json: str


@dataclass(frozen=True)
class HashComparisonResult:
    comparable: bool
    matched: bool
    blocking: bool
    reason_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "comparable": self.comparable,
            "matched": self.matched,
            "blocking": self.blocking,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class HashVersionValidationResult:
    valid: bool
    blocking: bool
    reason_code: str | None
    versions: tuple[int, ...]
    missing_paths: tuple[str, ...] = ()
    invalid_paths: tuple[str, ...] = ()


class ApplicabilityHashService:
    """Route hashing only by persisted ``applicability_hash_version``."""

    @classmethod
    def calculate(
        cls,
        applicability: Mapping[str, Any] | None,
        *,
        hash_version: int,
        applicability_schema: Mapping[str, Any] | None = None,
    ) -> ApplicabilityHashResult:
        if hash_version == APPLICABILITY_HASH_V1:
            canonical = LegacyApplicabilityCanonicalJsonV1.dumps(applicability)
            return ApplicabilityHashResult(
                hash_value=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                hash_version=APPLICABILITY_HASH_V1,
                schema_version=None,
                canonical_json=canonical,
            )
        if hash_version != APPLICABILITY_HASH_V2:
            raise UnsupportedApplicabilityHashVersion(str(hash_version))
        schema = cls._validate_schema(applicability_schema)
        schema_version = str(schema["schema_version"])
        normalized, set_paths = cls._normalize_v2_values(applicability or {}, schema)
        payload = {
            "applicability_schema_version": schema_version,
            "values": normalized,
        }
        canonical = CanonicalJsonServiceV2.dumps(payload, schema_set_paths=set_paths)
        return ApplicabilityHashResult(
            hash_value=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            hash_version=APPLICABILITY_HASH_V2,
            schema_version=schema_version,
            canonical_json=canonical,
        )

    @staticmethod
    def compare(
        left_hash: str,
        left_version: int | None,
        right_hash: str,
        right_version: int | None,
    ) -> HashComparisonResult:
        if left_version is None or right_version is None:
            return HashComparisonResult(
                comparable=False,
                matched=False,
                blocking=True,
                reason_code="missing_applicability_hash_version",
            )
        if left_version != right_version:
            return HashComparisonResult(
                comparable=False,
                matched=False,
                blocking=True,
                reason_code="applicability_hash_version_mismatch",
            )
        return HashComparisonResult(
            comparable=True,
            matched=str(left_hash) == str(right_hash),
            blocking=False,
            reason_code=None,
        )

    @staticmethod
    def _validate_schema(schema: Mapping[str, Any] | None) -> Mapping[str, Any]:
        if not isinstance(schema, Mapping):
            raise InvalidApplicabilitySchema("applicability_schema is required for V2")
        if not str(schema.get("schema_version") or "").strip():
            raise InvalidApplicabilitySchema("schema_version is required")
        if not isinstance(schema.get("fields"), Mapping):
            raise InvalidApplicabilitySchema("fields must be an object")
        return schema

    @classmethod
    def _normalize_v2_values(
        cls,
        applicability: Mapping[str, Any],
        schema: Mapping[str, Any],
    ) -> tuple[dict[str, Any], set[tuple[str, ...]]]:
        fields = schema["fields"]
        normalized: dict[str, Any] = {}
        set_paths: set[tuple[str, ...]] = set()
        # Only schema-declared fields participate in V2.  The taxonomy snapshot
        # is therefore the complete source of hash semantics for the batch.
        for field_name, field_schema_raw in fields.items():
            name = str(field_name)
            field_schema = field_schema_raw if isinstance(field_schema_raw, Mapping) else {}
            if name not in applicability:
                continue
            value = applicability[name]
            preserve_null = bool(field_schema.get("preserve_null"))
            if value is None and not preserve_null:
                continue
            normalized[name] = value
            if field_schema.get("array_semantics") == "set" and isinstance(value, (list, tuple)):
                set_paths.add(("values", name))
        return normalized, set_paths


class ApplicabilityHashVersionValidator:
    """Validate one batch-wide hash version across persisted entity metadata."""

    @classmethod
    def validate(
        cls,
        *,
        batch_hash_version: int | None,
        entities: Iterable[tuple[str, Any]],
    ) -> HashVersionValidationResult:
        versions: set[int] = set()
        missing: list[str] = []
        invalid: list[str] = []
        if batch_hash_version is None:
            missing.append("EstimateBatch.applicability_hash_version")
        elif batch_hash_version not in SUPPORTED_APPLICABILITY_HASH_VERSIONS:
            invalid.append("EstimateBatch.applicability_hash_version")
        else:
            versions.add(int(batch_hash_version))

        for path, entity in entities:
            value = cls._read_version(entity)
            if value is None:
                missing.append(path)
            elif value not in SUPPORTED_APPLICABILITY_HASH_VERSIONS:
                invalid.append(path)
            else:
                versions.add(int(value))

        if missing:
            return HashVersionValidationResult(
                valid=False,
                blocking=True,
                reason_code="missing_applicability_hash_version",
                versions=tuple(sorted(versions)),
                missing_paths=tuple(missing),
                invalid_paths=tuple(invalid),
            )
        if invalid or len(versions) > 1:
            return HashVersionValidationResult(
                valid=False,
                blocking=True,
                reason_code="mixed_applicability_hash_versions",
                versions=tuple(sorted(versions)),
                missing_paths=tuple(missing),
                invalid_paths=tuple(invalid),
            )
        return HashVersionValidationResult(
            valid=True,
            blocking=False,
            reason_code=None,
            versions=tuple(sorted(versions)),
        )

    @staticmethod
    def _read_version(entity: Any) -> int | None:
        if isinstance(entity, Mapping):
            value = entity.get("applicability_hash_version")
        else:
            value = getattr(entity, "applicability_hash_version", None)
        if isinstance(value, bool):
            return None
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return -1
