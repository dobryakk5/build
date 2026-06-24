"""Quantity-policy resolution and non-financial floor projection for KTP.

The service deliberately does not clone Estimate/financial rows.  It attaches
``ktp_quantity_projections`` to each source work row.  A downstream KTP builder
may materialize one or more KTP items from that list while keeping one Estimate
row and unchanged financial totals.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Iterable

PROJECTION_VERSION = "brick-house-quantity-projection-v1"


@dataclass(frozen=True)
class QuantityProjectionReport:
    source_rows: int = 0
    projected_items: int = 0
    explicit_items: int = 0
    inherited_items: int = 0
    derived_items: int = 0
    review_rows: int = 0
    skipped_rows: int = 0

    def as_dict(self) -> dict[str, int | str]:
        return {
            "projection_version": PROJECTION_VERSION,
            "source_rows": self.source_rows,
            "projected_items": self.projected_items,
            "explicit_items": self.explicit_items,
            "inherited_items": self.inherited_items,
            "derived_items": self.derived_items,
            "review_rows": self.review_rows,
            "skipped_rows": self.skipped_rows,
        }


@dataclass
class _RowBinding:
    index: int
    row: Any
    raw: dict[str, Any]
    template_stage_number: str
    stage_instance_id: str
    floor_number: int | None
    floor_kind: str | None
    floor_label: str | None
    operation_code: str
    operation_package_code: str | None
    calculation_code: str
    quantity: float | None
    unit_code: str | None
    semantic_stage_option_id: str | None
    stage_option_source: str | None
    applicability_hash: str
    applicability_hash_version: int
    applicability_schema_version: str | None
    work_scope_key: str
    source_row_key: str | None
    resolution_status: str
    calculation_blocked: bool
    reason_code: str | None
    policy: dict[str, Any]
    binding_key: str


_FLOOR_WORDS = {
    "первый", "первого", "первом", "первая", "первой",
    "второй", "второго", "втором", "вторая", "второй",
    "третий", "третьего", "третьем", "третья", "третьей",
    "четвертый", "четвертого", "четвертом", "четвёртый", "четвёртого", "четвёртом",
    "пятый", "пятого", "пятом", "шестой", "шестого", "шестом",
    "седьмой", "седьмого", "седьмом", "восьмой", "восьмого", "восьмом",
    "девятый", "девятого", "девятом", "десятый", "десятого", "десятом",
}


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().replace("ё", "е")
    text = re.sub(r"[^0-9a-zа-я]+", " ", text)
    return " ".join(text.split())


def _floor_neutral_name(value: Any) -> str:
    tokens = _normalize_text(value).split()
    result: list[str] = []
    skip_next_floor_word = False
    for token in tokens:
        if token in _FLOOR_WORDS:
            skip_next_floor_word = True
            continue
        if re.fullmatch(r"\d{1,3}", token):
            skip_next_floor_word = True
            continue
        if token.startswith("этаж") or token in {"мансарда", "мансардный", "цоколь", "цокольный"}:
            skip_next_floor_word = False
            continue
        if skip_next_floor_word and token.startswith("этаж"):
            skip_next_floor_word = False
            continue
        result.append(token)
        skip_next_floor_word = False
    return " ".join(result)


def _stable_hash(payload: Any, length: int = 20) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _default_normalize_unit(value: Any) -> str | None:
    text = _normalize_text(value)
    return text or None


def _resolve_unit_code(value: Any, normalize_unit: Callable[[Any], Any] | None) -> str | None:
    if normalize_unit is None:
        return _default_normalize_unit(value)
    try:
        normalized = normalize_unit(value)
    except Exception:  # noqa: BLE001 - validation diagnostics, not import blocker
        return _default_normalize_unit(value)
    if isinstance(normalized, tuple):
        return str(normalized[0] or "").strip() or None
    return str(normalized or "").strip() or None


def _operation_policy_index(variant: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for stage in variant.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        number = str(stage.get("number") or "")
        for operation in stage.get("operations") or []:
            if not isinstance(operation, dict):
                continue
            code = str(operation.get("operation_code") or "")
            if number and code:
                result[(number, code)] = dict(operation.get("quantity_policy") or {})
        # Packages are explicit by default. A package cannot be decomposed from
        # one length/area/volume unless a later verified model says so.
        for package_code in stage.get("operation_packages") or []:
            code = str(package_code or "")
            if number and code:
                result.setdefault((number, code), {"mode": "explicit_only"})
    return result


def _stage_instances_by_template(stage_instances: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for stage in stage_instances:
        if not isinstance(stage, dict):
            continue
        template = str(stage.get("template_stage_number") or stage.get("number") or "")
        if template:
            result.setdefault(template, []).append(stage)
    for values in result.values():
        values.sort(key=lambda item: (int(item.get("sort_order") or 0), str(item.get("stage_instance_id") or "")))
    return result


def _applicability_payload(raw: dict[str, Any]) -> dict[str, Any]:
    explicit = raw.get("quantity_applicability")
    if isinstance(explicit, dict):
        return explicit
    explicit = raw.get("rate_applicability")
    if isinstance(explicit, dict):
        return explicit
    explicit = raw.get("applicability")
    if isinstance(explicit, dict):
        return explicit
    result: dict[str, Any] = {}
    for key in (
        "selected_object_scope_code",
        "object_scope_code",
        "wall_location",
        "material_type",
        "construction_type",
        "finish_type",
    ):
        value = raw.get(key)
        if value not in (None, "", [], {}):
            result[key] = value
    return result


def _work_scope_key(row: Any, raw: dict[str, Any], calculation_code: str) -> str:
    value = str(raw.get("work_scope_key") or "").strip()
    if value:
        return value
    namespace_fields = (
        ("source_scope_id", "source_scope"),
        ("parent_work_id", "parent_work"),
        ("section_block_id", "section_block"),
        ("recognized_constructive_scope", "recognized_scope"),
    )
    for key, prefix in namespace_fields:
        value = str(raw.get(key) or "").strip()
        if value:
            return f"{prefix}:{value}"
    source_row_key = str(raw.get("source_row_key") or "").strip()
    if source_row_key:
        return f"estimate_row:{source_row_key}"

    # Backward-compatible fallback for release-candidate rows created before
    # source_row_key. New v2 batches must always reach one of the canonical
    # branches above.
    object_scope = str(
        raw.get("selected_object_scope_code")
        or raw.get("object_scope_code")
        or ""
    ).strip()
    name = _floor_neutral_name(getattr(row, "work_name", None) or raw.get("item_text") or "")
    spec = _floor_neutral_name(raw.get("spec") or "")
    payload = [calculation_code, object_scope, name, spec]
    return "auto:" + _stable_hash(payload, 24)


def _binding_key(
    *,
    template_stage_number: str,
    calculation_code: str,
    unit_code: str | None,
    semantic_stage_option_id: str | None,
    applicability_hash: str,
    applicability_hash_version: int,
    work_scope_key: str,
) -> str:
    return "|".join(
        [
            template_stage_number,
            calculation_code,
            unit_code or "",
            semantic_stage_option_id or "",
            applicability_hash,
            str(applicability_hash_version),
            work_scope_key,
        ]
    )


def _projection_payload(
    binding: _RowBinding,
    target_stage: dict[str, Any],
    *,
    quantity: float | None,
    quantity_source: str | None,
    inherited_from_row_order: int | None = None,
    derived_from_operation_code: str | None = None,
    needs_review: bool = False,
    review_reason: str | None = None,
) -> dict[str, Any]:
    target_instance_id = str(target_stage.get("stage_instance_id") or binding.stage_instance_id)
    effective_needs_review = bool(
        needs_review
        or binding.resolution_status != "resolved"
        or binding.calculation_blocked
    )
    effective_reason = review_reason or binding.reason_code
    payload = {
        "projection_version": PROJECTION_VERSION,
        "projection_id": "qp:" + _stable_hash(
            [
                binding.index,
                binding.binding_key,
                target_instance_id,
                quantity_source,
                inherited_from_row_order,
                derived_from_operation_code,
            ],
            28,
        ),
        "source_row_order": binding.index,
        "source_stage_instance_id": binding.stage_instance_id,
        "target_stage_instance_id": target_instance_id,
        "target_template_stage_number": str(
            target_stage.get("template_stage_number") or binding.template_stage_number
        ),
        "target_stage_number": target_stage.get("number"),
        "target_stage_title": target_stage.get("title"),
        "target_stage_sort_order": target_stage.get("sort_order"),
        "canonical_stage_id": target_stage.get("canonical_stage_id"),
        "floor_number": target_stage.get("floor_number"),
        "floor_kind": target_stage.get("floor_kind"),
        "floor_label": target_stage.get("floor_label"),
        "floor_component": target_stage.get("floor_component"),
        "component_role": target_stage.get("component_role"),
        "operation_code": binding.operation_code or None,
        "operation_package_code": binding.operation_package_code,
        "calculation_code": binding.calculation_code,
        "semantic_stage_option_id": binding.semantic_stage_option_id,
        "stage_option_source": binding.stage_option_source,
        "source_row_key": binding.source_row_key,
        "work_scope_key": binding.work_scope_key,
        "applicability_hash": binding.applicability_hash,
        "applicability_hash_version": binding.applicability_hash_version,
        "applicability_schema_version": binding.applicability_schema_version,
        "quantity": quantity,
        "unit_code": binding.unit_code,
        "quantity_source": quantity_source,
        "inherited_from_row_order": inherited_from_row_order,
        "derived_from_operation_code": derived_from_operation_code,
        "needs_review": effective_needs_review,
        "review_reason": effective_reason,
        "resolution_status": (
            "needs_review" if effective_needs_review else "resolved"
        ),
        "calculation_blocked": bool(effective_needs_review),
        "reason_code": effective_reason,
    }
    return payload


def _mark_review(binding: _RowBinding, reason: str) -> None:
    raw = binding.raw
    raw["quantity_projection_needs_review"] = True
    reasons = list(raw.get("quantity_projection_review_reasons") or [])
    if reason not in reasons:
        reasons.append(reason)
    raw["quantity_projection_review_reasons"] = reasons
    raw.setdefault("quantity_projection_review_reason", reason)
    raw["operator_review_required"] = True
    if not raw.get("operator_review_reason"):
        raw["operator_review_reason"] = reason


def _append_projection(binding: _RowBinding, payload: dict[str, Any]) -> None:
    projections = list(binding.raw.get("ktp_quantity_projections") or [])
    if not any(item.get("projection_id") == payload.get("projection_id") for item in projections if isinstance(item, dict)):
        projections.append(payload)
    projections.sort(
        key=lambda item: (
            item.get("floor_number") is None,
            int(item.get("floor_number") or 0),
            str(item.get("target_stage_instance_id") or ""),
        )
    )
    binding.raw["ktp_quantity_projections"] = projections
    binding.raw["quantity_projection_count"] = len(projections)


def _current_stage_payload(binding: _RowBinding, stage_lookup: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return stage_lookup.get(binding.stage_instance_id) or {
        "stage_instance_id": binding.stage_instance_id,
        "template_stage_number": binding.template_stage_number,
        "number": binding.raw.get("work_stage_number"),
        "title": binding.raw.get("work_stage_title"),
        "floor_number": binding.floor_number,
        "floor_kind": binding.floor_kind,
        "floor_label": binding.floor_label,
        "floor_component": binding.raw.get("floor_component"),
        "component_role": binding.raw.get("component_role"),
    }


def _prepare_bindings(
    rows: list[Any],
    *,
    variant: dict[str, Any],
    normalize_unit: Callable[[Any], Any] | None,
) -> tuple[list[_RowBinding], int]:
    policy_index = _operation_policy_index(variant)
    bindings: list[_RowBinding] = []
    skipped = 0
    for index, row in enumerate(rows):
        raw = row.raw_data if isinstance(getattr(row, "raw_data", None), dict) else {}
        row.raw_data = raw
        raw.pop("ktp_quantity_projections", None)
        raw["ktp_quantity_projections"] = []
        raw.pop("quantity_projection_review_reasons", None)
        raw.pop("quantity_projection_review_reason", None)
        raw["quantity_projection_needs_review"] = False
        raw["quantity_projection_count"] = 0
        raw["quantity_projection_version"] = PROJECTION_VERSION

        if raw.get("row_role") != "work" or not raw.get("work_type_applicable", True):
            skipped += 1
            continue
        operation_code = str(raw.get("operation_code") or "").strip()
        package_code = str(raw.get("operation_package_code") or "").strip() or None
        calculation_code = operation_code or package_code or ""
        template = str(raw.get("template_stage_number") or "").strip()
        stage_instance_id = str(raw.get("stage_instance_id") or "").strip()
        if not calculation_code or not template or not stage_instance_id:
            skipped += 1
            raw["quantity_projection_needs_review"] = True
            raw["quantity_projection_review_reason"] = "quantity_projection_context_missing"
            raw["quantity_projection_review_reasons"] = ["quantity_projection_context_missing"]
            continue

        unit_code = _resolve_unit_code(getattr(row, "unit", None), normalize_unit)
        applicability_hash = str(
            raw.get("applicability_hash")
            or raw.get("rate_applicability_hash")
            or _stable_hash(_applicability_payload(raw), 24)
        )
        try:
            applicability_hash_version = int(raw.get("applicability_hash_version") or 1)
        except (TypeError, ValueError):
            applicability_hash_version = 1
        applicability_schema_version = (
            str(raw.get("applicability_schema_version")).strip()
            if raw.get("applicability_schema_version") not in (None, "")
            else None
        )
        scope = _work_scope_key(row, raw, calculation_code)
        source_row_key = str(raw.get("source_row_key") or "").strip() or None
        resolution_status = str(raw.get("resolution_status") or "resolved")
        calculation_blocked = bool(raw.get("calculation_blocked", False))
        reason_code = str(raw.get("reason_code") or "").strip() or None
        option_id = str(
            raw.get("semantic_stage_option_id")
            or raw.get("stage_option_id")
            or ""
        ).strip() or None
        stage_option_source = str(raw.get("stage_option_source") or "").strip() or None
        policy = dict(policy_index.get((template, calculation_code)) or {})
        if not policy:
            # Packages are explicit by design; unknown atomic operations must
            # not inherit merely because they share a broad stage.
            policy = {"mode": "explicit_only", "implicit_default": True}
        mode = str(policy.get("mode") or "explicit_only")
        raw["quantity_policy"] = policy
        raw["quantity_policy_mode"] = mode
        raw["work_scope_key"] = scope
        raw["quantity_applicability_hash"] = applicability_hash
        key = _binding_key(
            template_stage_number=template,
            calculation_code=calculation_code,
            unit_code=unit_code,
            semantic_stage_option_id=option_id,
            applicability_hash=applicability_hash,
            applicability_hash_version=applicability_hash_version,
            work_scope_key=scope,
        )
        raw["quantity_binding_key"] = key
        bindings.append(
            _RowBinding(
                index=index,
                row=row,
                raw=raw,
                template_stage_number=template,
                stage_instance_id=stage_instance_id,
                floor_number=raw.get("floor_number"),
                floor_kind=raw.get("floor_kind"),
                floor_label=raw.get("floor_label"),
                operation_code=operation_code,
                operation_package_code=package_code,
                calculation_code=calculation_code,
                quantity=_as_float(getattr(row, "quantity", None)),
                unit_code=unit_code,
                semantic_stage_option_id=option_id,
                stage_option_source=stage_option_source,
                applicability_hash=applicability_hash,
                applicability_hash_version=applicability_hash_version,
                applicability_schema_version=applicability_schema_version,
                work_scope_key=scope,
                source_row_key=source_row_key,
                resolution_status=resolution_status,
                calculation_blocked=calculation_blocked,
                reason_code=reason_code,
                policy=policy,
                binding_key=key,
            )
        )
    return bindings, skipped


def enrich_quantity_projections(
    rows: list[Any],
    *,
    variant: dict[str, Any],
    stage_instances: list[dict[str, Any]],
    normalize_unit: Callable[[Any], Any] | None = None,
) -> QuantityProjectionReport:
    """Attach KTP quantity projections to already-classified estimate rows.

    ``rows`` is mutated in place only through ``row.raw_data``.  ``row.quantity``,
    financial values and row count remain unchanged.
    """
    bindings, skipped = _prepare_bindings(rows, variant=variant, normalize_unit=normalize_unit)
    by_template = _stage_instances_by_template(stage_instances)
    stage_lookup = {
        str(stage.get("stage_instance_id") or ""): stage
        for stage in stage_instances
        if isinstance(stage, dict) and stage.get("stage_instance_id")
    }
    by_key: dict[str, list[_RowBinding]] = {}
    for binding in bindings:
        by_key.setdefault(binding.binding_key, []).append(binding)

    # First pass: explicit/no-quantity rows and inheritance.
    for group in by_key.values():
        group.sort(key=lambda item: item.index)
        mode = str(group[0].policy.get("mode") or "explicit_only")
        targets = by_template.get(group[0].template_stage_number) or []
        target_by_instance = {
            str(stage.get("stage_instance_id") or ""): stage for stage in targets
        }
        explicit_by_instance: dict[str, list[_RowBinding]] = {}
        missing_by_instance: dict[str, list[_RowBinding]] = {}
        for binding in group:
            bucket = explicit_by_instance if binding.quantity is not None else missing_by_instance
            bucket.setdefault(binding.stage_instance_id, []).append(binding)

        if mode == "no_quantity":
            for binding in group:
                target = _current_stage_payload(binding, stage_lookup)
                _append_projection(
                    binding,
                    _projection_payload(
                        binding,
                        target,
                        quantity=None,
                        quantity_source="no_quantity",
                    ),
                )
            continue

        # Every explicit source row remains an explicit projection of itself.
        for instance_id, explicit_rows in explicit_by_instance.items():
            target = target_by_instance.get(instance_id) or _current_stage_payload(explicit_rows[0], stage_lookup)
            for binding in explicit_rows:
                _append_projection(
                    binding,
                    _projection_payload(
                        binding,
                        target,
                        quantity=binding.quantity,
                        quantity_source="explicit",
                    ),
                )

        if mode == "explicit_only":
            for missing_rows in missing_by_instance.values():
                for binding in missing_rows:
                    _mark_review(binding, "explicit_quantity_required")
            continue

        if mode == "explicit_or_inherit":
            inherit_source = str(group[0].policy.get("inherit_source") or "")
            if inherit_source != "floor_1_same_operation":
                for binding in group:
                    if binding.quantity is None:
                        _mark_review(binding, "unsupported_quantity_inherit_source")
                continue

            # Structural slabs inherit only among ordinary 2.7.10 instances.
            # The basement top slab (2.7.7) is a separate template and source.
            if group[0].raw.get("floor_component") == "slab" and group[0].template_stage_number != "2.7.10":
                for binding in group:
                    if binding.quantity is None:
                        _mark_review(binding, "quantity_inheritance_source_unresolved")
                continue

            floor1_targets = [stage for stage in targets if stage.get("floor_number") == 1]
            floor1_instance_ids = {str(stage.get("stage_instance_id") or "") for stage in floor1_targets}
            floor1_candidates = [
                binding
                for binding in group
                if binding.stage_instance_id in floor1_instance_ids
            ]
            if len(floor1_candidates) > 1:
                for binding in group:
                    _mark_review(binding, "multiple_floor_1_quantity_sources")
                continue
            floor1_source = floor1_candidates[0] if floor1_candidates else None
            source_is_resolved = bool(
                floor1_source is not None
                and floor1_source.resolution_status == "resolved"
                and not floor1_source.calculation_blocked
                and floor1_source.quantity is not None
                and floor1_source.quantity > 0
            )

            def block_inheritance(recipient: _RowBinding, target: dict[str, Any]) -> None:
                _mark_review(recipient, "quantity_inheritance_source_unresolved")
                legacy_reasons = list(recipient.raw.get("quantity_projection_review_reasons") or [])
                if "floor_1_quantity_source_missing" not in legacy_reasons:
                    legacy_reasons.append("floor_1_quantity_source_missing")
                recipient.raw["quantity_projection_review_reasons"] = legacy_reasons
                # New v2 batches persist an explicit blocked projection so all
                # downstream services see the unresolved target. Legacy v1 rows
                # retain release-candidate behaviour (review marker, no payload).
                if recipient.applicability_hash_version < 2 and not recipient.source_row_key:
                    return
                _append_projection(
                    recipient,
                    _projection_payload(
                        recipient,
                        target,
                        quantity=None,
                        quantity_source=None,
                        inherited_from_row_order=(floor1_source.index if floor1_source else None),
                        needs_review=True,
                        review_reason="quantity_inheritance_source_unresolved",
                    ),
                )

            for target in targets:
                instance_id = str(target.get("stage_instance_id") or "")
                # An explicit target value always wins and remains usable even
                # when floor 1 is unresolved.
                if explicit_by_instance.get(instance_id):
                    continue
                missing_rows = missing_by_instance.get(instance_id) or []
                if target.get("floor_number") == 1:
                    for binding in missing_rows:
                        _mark_review(binding, "floor_1_quantity_required")
                    continue
                if len(missing_rows) > 1:
                    for binding in missing_rows:
                        _mark_review(binding, "multiple_target_rows_for_inherited_quantity")
                    continue
                recipient = (
                    missing_rows[0]
                    if missing_rows
                    else (floor1_source if floor1_source is not None else group[0])
                )
                if not source_is_resolved:
                    block_inheritance(recipient, target)
                    continue
                _append_projection(
                    recipient,
                    _projection_payload(
                        recipient,
                        target,
                        quantity=floor1_source.quantity,
                        quantity_source="inherited_from_floor_1",
                        inherited_from_row_order=floor1_source.index,
                    ),
                )
                recipient.raw["quantity_inherited_projection_count"] = int(
                    recipient.raw.get("quantity_inherited_projection_count") or 0
                ) + 1
                if recipient.index != floor1_source.index:
                    recipient.raw["quantity_inherited"] = True
                    recipient.raw["quantity_inherited_from_row_order"] = floor1_source.index
            continue

        # derive_from_operation and verified_model are resolved in the second pass.
        if mode not in {"derive_from_operation", "verified_model"}:
            for binding in group:
                if binding.quantity is None:
                    _mark_review(binding, "unsupported_quantity_policy_mode")

    # Lookup all projections by stage / operation / scope for derivation.
    projection_lookup: dict[tuple[str, str, str, str | None], list[dict[str, Any]]] = {}
    for binding in bindings:
        for projection in binding.raw.get("ktp_quantity_projections") or []:
            key = (
                str(projection.get("target_stage_instance_id") or ""),
                str(projection.get("calculation_code") or ""),
                str(projection.get("work_scope_key") or ""),
                projection.get("unit_code"),
            )
            projection_lookup.setdefault(key, []).append(projection)

    for binding in bindings:
        mode = str(binding.policy.get("mode") or "explicit_only")
        if mode == "derive_from_operation" and binding.quantity is None:
            source_operation = str(binding.policy.get("source_operation_code") or "").strip()
            conversion = binding.policy.get("conversion") if isinstance(binding.policy.get("conversion"), dict) else {}
            conversion_type = str(conversion.get("type") or "same_quantity")
            source_unit = str(conversion.get("source_unit_code") or binding.unit_code or "") or None
            candidates = projection_lookup.get(
                (binding.stage_instance_id, source_operation, binding.work_scope_key, source_unit),
                [],
            )
            if len(candidates) != 1:
                _mark_review(binding, "derive_quantity_source_missing_or_ambiguous")
                continue
            source = candidates[0]
            if conversion_type == "same_quantity":
                if source.get("unit_code") != binding.unit_code:
                    _mark_review(binding, "quantity_conversion_model_required")
                    continue
                factor = _as_float(conversion.get("factor"))
                factor = 1.0 if factor is None else factor
                quantity = _as_float(source.get("quantity"))
                quantity = quantity * factor if quantity is not None else None
            elif conversion_type == "verified_model":
                model_result = binding.raw.get("verified_quantity_model_result")
                quantity = _as_float(
                    model_result.get("quantity") if isinstance(model_result, dict) else None
                )
                if quantity is None:
                    _mark_review(binding, "quantity_conversion_model_required")
                    continue
            else:
                _mark_review(binding, "quantity_conversion_model_required")
                continue
            target = _current_stage_payload(binding, stage_lookup)
            _append_projection(
                binding,
                _projection_payload(
                    binding,
                    target,
                    quantity=quantity,
                    quantity_source="derived_from_operation",
                    derived_from_operation_code=source_operation,
                ),
            )
        elif mode == "verified_model" and binding.quantity is None:
            model_result = binding.raw.get("verified_quantity_model_result")
            quantity = _as_float(model_result.get("quantity") if isinstance(model_result, dict) else None)
            if quantity is None:
                _mark_review(binding, "verified_quantity_model_required")
                continue
            target = _current_stage_payload(binding, stage_lookup)
            _append_projection(
                binding,
                _projection_payload(
                    binding,
                    target,
                    quantity=quantity,
                    quantity_source="verified_model",
                ),
            )

    projected = explicit = inherited = derived = reviews = 0
    for binding in bindings:
        projections = binding.raw.get("ktp_quantity_projections") or []
        projected += len(projections)
        for projection in projections:
            source = projection.get("quantity_source")
            explicit += source == "explicit"
            inherited += source == "inherited_from_floor_1"
            derived += source in {"derived_from_operation", "verified_model"}
        if binding.raw.get("quantity_projection_needs_review"):
            reviews += 1

    report = QuantityProjectionReport(
        source_rows=len(bindings),
        projected_items=projected,
        explicit_items=explicit,
        inherited_items=inherited,
        derived_items=derived,
        review_rows=reviews,
        skipped_rows=skipped,
    )
    for binding in bindings:
        binding.raw["quantity_projection_report"] = report.as_dict()
    return report


def ktp_projection_payloads_for_estimate(estimate: Any) -> list[dict[str, Any]]:
    """Return KTP item payloads for one Estimate-like object.

    The helper is framework-neutral and is used by ``ktp_estimate_service``.
    When no stage-6 projection exists it returns one backward-compatible item.
    """
    raw = estimate.raw_data if isinstance(getattr(estimate, "raw_data", None), dict) else {}
    source_projections = [
        dict(item)
        for item in (raw.get("ktp_quantity_projections") or [])
        if isinstance(item, dict)
    ]
    projections = [
        item for item in source_projections
        if not item.get("calculation_suppressed")
    ]
    # Stage 7 may suppress every projection of a duplicate package/atomic row.
    # An explicitly empty result means "do not materialize a KTP calculation",
    # not "fall back to the original Estimate row".
    if source_projections and not projections:
        return []
    if not projections:
        return [
            {
                "projection_id": None,
                "name": getattr(estimate, "work_name", None),
                "quantity": _as_float(getattr(estimate, "quantity", None)),
                "unit": getattr(estimate, "unit", None),
                "quantity_source": "estimate",
                "needs_review": bool(raw.get("quantity_projection_needs_review")),
                "review_reason": raw.get("quantity_projection_review_reason"),
                "floor_number": raw.get("floor_number"),
                "floor_kind": raw.get("floor_kind"),
                "floor_label": raw.get("floor_label"),
                "floor_component": raw.get("floor_component"),
                "component_role": raw.get("component_role"),
                "target_stage_instance_id": raw.get("stage_instance_id"),
                "target_template_stage_number": raw.get("template_stage_number") or raw.get("work_stage_number"),
                "target_stage_number": raw.get("work_stage_number"),
                "target_stage_title": raw.get("work_stage_title"),
                "target_stage_sort_order": raw.get("stage_sort_order"),
                "canonical_stage_id": raw.get("canonical_stage_id"),
                "operation_code": raw.get("operation_code"),
                "operation_package_code": raw.get("operation_package_code"),
                "semantic_stage_option_id": raw.get("semantic_stage_option_id") or raw.get("stage_option_id"),
                "stage_option_source": raw.get("stage_option_source"),
                "source_row_key": raw.get("source_row_key"),
                "work_scope_key": raw.get("work_scope_key"),
                "applicability_hash": raw.get("applicability_hash") or raw.get("rate_applicability_hash"),
                "applicability_hash_version": raw.get("applicability_hash_version"),
                "applicability_schema_version": raw.get("applicability_schema_version"),
                "quantity_policy_mode": raw.get("quantity_policy_mode"),
            }
        ]

    result: list[dict[str, Any]] = []
    base_name = str(getattr(estimate, "work_name", None) or "").strip()
    for projection in projections:
        floor_label = str(projection.get("floor_label") or "").strip()
        name = base_name
        if floor_label and floor_label.casefold() not in base_name.casefold():
            name = f"{base_name} — {floor_label}" if base_name else floor_label
        needs_review = bool(
            projection.get("needs_review")
            or projection.get("package_resolution_needs_review")
        )
        result.append(
            {
                **projection,
                "name": name,
                "unit": getattr(estimate, "unit", None),
                "needs_review": needs_review,
                "review_reason": (
                    projection.get("review_reason")
                    or projection.get("package_resolution_reason")
                ),
                # Unresolved representation conflicts remain visible to the
                # operator but are not calculable until a mode is selected.
                "quantity": (
                    None
                    if projection.get("package_resolution_needs_review")
                    else projection.get("quantity")
                ),
            }
        )
    return result
