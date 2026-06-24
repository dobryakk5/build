"""Versioned canonical JSON serializers used by immutable estimate contracts.

V1 is intentionally limited to the legacy applicability algorithm.  V2 is a
schema-independent canonical JSON implementation for snapshot hashes and
schema-aware applicability hashes.  Changing either implementation requires a
new version rather than editing the released algorithm in place.
"""
from __future__ import annotations

import json
import math
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence

CANONICAL_JSON_V2_VERSION = "canonical_json_v2@1"
LEGACY_APPLICABILITY_CANONICAL_JSON_V1_VERSION = "legacy_applicability_canonical_json_v1@1"

# This set is part of the V2 data contract.  It must stay empty and immutable
# for V2; adding a path requires a new canonicalizer/payload version.
CANONICAL_UNORDERED_ARRAY_PATHS_V2: frozenset[str] = frozenset()

_IDENTIFIER_SUFFIXES = ("_id", "_code", "_key", "_version", "_algorithm")
_IDENTIFIER_FIELDS = frozenset(
    {
        "project_variant_id",
        "canonical_stage_id",
        "semantic_stage_option_id",
        "operation_code",
        "operation_package_code",
        "unit_code",
        "source_row_key",
        "preview_session_id",
        "taxonomy_dictionary_version",
        "source_file_fingerprint_algorithm",
        "source_file_fingerprint",
        "owner_user_id",
        "template_stage_number",
        "stage_number",
        "floor_kind",
    }
)
_FREE_TEXT_FIELDS = frozenset(
    {
        "source_text",
        "work_name",
        "item_text",
        "spec",
        "description",
        "comment",
        "title",
        "label",
        "raw_text",
    }
)


class CanonicalJsonError(ValueError):
    """Base error with a stable domain code."""

    code = "canonical_json_error"


class InvalidSnapshotNumericValue(CanonicalJsonError):
    code = "invalid_snapshot_numeric_value"


class DuplicateKeyAfterNormalization(CanonicalJsonError):
    code = "canonical_json_duplicate_key_after_normalization"


def _normalize_key(value: str) -> str:
    return unicodedata.normalize("NFC", value.strip())


def _normalize_line_endings(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _is_identifier_field(field_name: str | None) -> bool:
    if not field_name:
        return False
    return field_name in _IDENTIFIER_FIELDS or field_name.endswith(_IDENTIFIER_SUFFIXES)


def _normalize_string(value: str, field_name: str | None) -> str:
    normalized = unicodedata.normalize("NFC", value)
    if _is_identifier_field(field_name):
        return normalized.strip()
    # Free text and all other string leaves preserve whitespace.  The explicit
    # branch documents the contract and lets future versions diverge safely.
    if field_name in _FREE_TEXT_FIELDS:
        return _normalize_line_endings(normalized)
    return _normalize_line_endings(normalized)


def _decimal_from_number(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise TypeError("bool is not a numeric token")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidSnapshotNumericValue(
                "NaN and Infinity are not valid canonical JSON numbers"
            )
        number = Decimal(str(value))
    else:
        raise TypeError(f"unsupported numeric type: {type(value)!r}")
    if not number.is_finite():
        raise InvalidSnapshotNumericValue(
            "NaN and Infinity are not valid canonical JSON numbers"
        )
    return number


def _number_token(value: Any) -> str:
    try:
        number = _decimal_from_number(value)
    except (InvalidOperation, ValueError) as exc:
        raise InvalidSnapshotNumericValue(str(exc)) from exc
    if number == 0:
        return "0"
    # Fixed-point output expands exponent notation.  Trailing fractional zeroes
    # and a trailing decimal separator are removed.
    token = format(number, "f")
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token


def _path_token(path: Sequence[str]) -> str:
    return ".".join(path)


class CanonicalJsonServiceV2:
    """Canonicalize JSON-compatible values using the frozen V2 contract."""

    version = CANONICAL_JSON_V2_VERSION

    @classmethod
    def dumps(
        cls,
        payload: Any,
        *,
        schema_set_paths: Iterable[Sequence[str] | str] = (),
    ) -> str:
        extra_paths = frozenset(
            item if isinstance(item, str) else _path_token(tuple(str(part) for part in item))
            for item in schema_set_paths
        )
        return cls._serialize(
            payload,
            path=(),
            field_name=None,
            schema_set_paths=extra_paths,
        )

    @classmethod
    def dump_bytes(
        cls,
        payload: Any,
        *,
        schema_set_paths: Iterable[Sequence[str] | str] = (),
    ) -> bytes:
        return cls.dumps(payload, schema_set_paths=schema_set_paths).encode("utf-8")

    @classmethod
    def _is_set_like_array(
        cls,
        *,
        path: Sequence[str],
        field_name: str | None,
        schema_set_paths: frozenset[str],
    ) -> bool:
        path_name = _path_token(path)
        if field_name == "semantic_stage_option_ids":
            return True
        if len(path) >= 2 and path[-2] == "project_structure_options":
            return True
        if path_name in CANONICAL_UNORDERED_ARRAY_PATHS_V2:
            return True
        return path_name in schema_set_paths

    @classmethod
    def _serialize(
        cls,
        value: Any,
        *,
        path: tuple[str, ...],
        field_name: str | None,
        schema_set_paths: frozenset[str],
    ) -> str:
        if value is None:
            return "null"
        if value is True:
            return "true"
        if value is False:
            return "false"
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            return _number_token(value)
        if isinstance(value, str):
            return json.dumps(
                _normalize_string(value, field_name),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        if isinstance(value, Mapping):
            normalized: dict[str, Any] = {}
            original_by_key: dict[str, str] = {}
            for raw_key, item in value.items():
                if not isinstance(raw_key, str):
                    raise TypeError("canonical JSON object keys must be strings")
                key = _normalize_key(raw_key)
                if key in normalized:
                    prior = original_by_key[key]
                    raise DuplicateKeyAfterNormalization(
                        f"object keys {prior!r} and {raw_key!r} normalize to {key!r}"
                    )
                normalized[key] = item
                original_by_key[key] = raw_key
            parts: list[str] = []
            for key in sorted(normalized):
                key_token = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
                value_token = cls._serialize(
                    normalized[key],
                    path=(*path, key),
                    field_name=key,
                    schema_set_paths=schema_set_paths,
                )
                parts.append(f"{key_token}:{value_token}")
            return "{" + ",".join(parts) + "}"
        if isinstance(value, (list, tuple)):
            tokens = [
                cls._serialize(
                    item,
                    path=(*path, str(index)),
                    field_name=None,
                    schema_set_paths=schema_set_paths,
                )
                for index, item in enumerate(value)
            ]
            if cls._is_set_like_array(
                path=path,
                field_name=field_name,
                schema_set_paths=schema_set_paths,
            ):
                tokens = sorted(set(tokens))
            return "[" + ",".join(tokens) + "]"
        raise TypeError(f"value is not JSON-compatible: {type(value)!r}")


class LegacyApplicabilityCanonicalJsonV1:
    """Frozen byte-compatible serializer used by release-candidate V1 hashes."""

    version = LEGACY_APPLICABILITY_CANONICAL_JSON_V1_VERSION

    @staticmethod
    def normalize(payload: Mapping[str, Any] | None) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in (payload or {}).items():
            if value is None or value == "" or value == [] or value == {}:
                continue
            if isinstance(value, list):
                result[str(key)] = sorted(value, key=lambda item: str(item))
            else:
                result[str(key)] = value
        return result

    @classmethod
    def dumps(cls, payload: Mapping[str, Any] | None) -> str:
        return json.dumps(
            cls.normalize(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def dump_bytes(cls, payload: Mapping[str, Any] | None) -> bytes:
        return cls.dumps(payload).encode("utf-8")
