# backend/app/services/upload_service.py
"""
Асинхронный upload сметы.

Поток (авто):
  POST /estimates/upload
    → файл сохраняется во временный файл на диске
    → если парсер не уверен (NeedsMappingError) — сразу возвращаем 422
      с {needs_mapping: true, preview_rows, col_count, tmp_path, sheet}
    → иначе создаётся Job(status=pending), запускается фоновая обработка
    → клиент получает 202 + job_id

Поток (ручной маппинг):
  POST /estimates/upload/confirm-mapping
    → принимаем {tmp_path, sheet, col_mapping: {col_index: field_key}}
    → создаём Job, запускаем обработку с явным маппингом

  Обработка (_process_upload):
    → Job.status = "processing"
    → удаляем старые estimates + gantt_tasks проекта
    → парсим Excel (авто или по маппингу)
    → сохраняем estimates и estimate_batch
    → Job.status = "done" | "failed"
    → temp-файл удаляется в любом случае (finally)
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import tempfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4

from fastapi import UploadFile, HTTPException
from sqlalchemy import bindparam, select, delete, func, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.date_utils             import working_days_between, task_end_date
from app.core.estimate_types         import resolve_item_type, VALID_ESTIMATE_ITEM_TYPES
from app.models                      import Job, GanttTask, Estimate, EstimateBatch, TaskDependency
from app.services.excel_parser       import (
    ExcelEstimateParser,
    NeedsMappingError,
    ParsedRow,
    describe_subtotal_row,
    is_subtotal_row,
)
from app.services.gantt_builder      import GanttBuilder, GanttTaskDTO
from app.services.gantt_calculations import DEFAULT_HOURS_PER_DAY


_parser = ExcelEstimateParser()

# Сколько времени (сек) храним tmp-файл в ожидании подтверждения маппинга
# (после этого времени файл не будет найден и вернётся 404)
TMP_TTL_SECONDS = 3600


def _estimate_item_type(estimate: Estimate) -> str:
    return resolve_item_type(estimate)


# ─────────────────────────────────────────────────────────────────────────────
# ЗАПУСК JOB (авто-парсинг)
# ─────────────────────────────────────────────────────────────────────────────

async def start_upload_job(
    file:             UploadFile,
    project_id:       str,
    user_id:          str,
    start_date:       date,
    workers:          int,
    estimate_kind:    int,
    complex_mode:     bool,
    clarification_answers: dict | None,
    hierarchy_selection: dict | None,
    db:               AsyncSession,
) -> Job:
    """
    Сохраняет файл, пробует авто-парсинг.
    - Если парсер уверен (confidence ≥ 0.8) → создаёт Job и запускает фон.
    - Если нет → поднимает HTTPException 422 с данными для UI маппинга.
    """
    allowed = (".xlsx", ".xls", ".pdf")
    if not file.filename.lower().endswith(allowed):
        raise HTTPException(400, f"Поддерживаются: {', '.join(allowed)}")

    suffix = _get_suffix(file.filename)
    tmp_path = _save_tmp(await file.read(), suffix)

    # ── Для Excel пробуем авто-парсинг ────────────────────────────────────
    if suffix in (".xlsx", ".xls"):
        try:
            _parser.parse(tmp_path)   # просто проверяем уверенность
        except NeedsMappingError as e:
            # Файл сохранён — отдаём превью, tmp_path нужен для confirm-mapping
            raise HTTPException(
                status_code=422,
                detail={
                    "needs_mapping": True,
                    "filename":      e.filename,
                    "sheet":         e.sheet,
                    "preview_rows":  e.preview_rows,
                    "col_count":     e.col_count,
                    "tmp_path":      tmp_path,   # фронт вернёт это поле при подтверждении
                },
            )

    return await _create_and_run_job(
        tmp_path   = tmp_path,
        filename   = file.filename,
        project_id = project_id,
        user_id    = user_id,
        start_date = start_date,
        workers    = workers,
        estimate_kind = estimate_kind,
        complex_mode  = complex_mode,
        clarification_answers = clarification_answers,
        hierarchy_selection = hierarchy_selection,
        db         = db,
    )


# ─────────────────────────────────────────────────────────────────────────────
# ЗАПУСК JOB (ручной маппинг)
# ─────────────────────────────────────────────────────────────────────────────

async def start_upload_job_with_mapping(
    tmp_path:   str,
    sheet:      str,
    col_mapping: dict[int, str],   # {col_0based: "work_name"|"unit"|...|"skip"}
    project_id: str,
    user_id:    str,
    start_date: date,
    workers:    int,
    estimate_kind: int,
    complex_mode: bool,
    clarification_answers: dict | None,
    hierarchy_selection: dict | None,
    db:         AsyncSession,
) -> Job:
    """
    Запускает обработку файла с явным маппингом колонок.
    tmp_path пришёл из ответа 422 предыдущего upload-запроса.
    """
    if not os.path.exists(tmp_path):
        raise HTTPException(404, "Временный файл не найден или устарел. Загрузите файл заново.")

    return await _create_and_run_job(
        tmp_path    = tmp_path,
        filename    = os.path.basename(tmp_path),
        project_id  = project_id,
        user_id     = user_id,
        start_date  = start_date,
        workers     = workers,
        estimate_kind = estimate_kind,
        complex_mode  = complex_mode,
        clarification_answers = clarification_answers,
        hierarchy_selection = hierarchy_selection,
        db          = db,
        col_mapping = col_mapping,
        sheet       = sheet,
    )


# ─────────────────────────────────────────────────────────────────────────────
# PREVIEW (parse to tmp, no DB writes) + CONFIRM
# ─────────────────────────────────────────────────────────────────────────────

_ITEM_TYPE_ORDER = ("work", "material", "mechanism", "overhead", "unknown")
_LOW_CONFIDENCE = 0.7
EARLY_INHERIT_ROLES = {"material", "mechanism", "labor", "logistics", "overhead"}


MAX_PREVIEW_GROUP_ROWS = 2000
_NO_SECTION = "Без раздела"
_MONEY_QUANT = Decimal("0.01")


def _row_role_from_item_type(item_type: str | None, name: str | None = None) -> str | None:
    if item_type == "work":
        return "work"
    if item_type == "material":
        return "material"
    if item_type == "mechanism":
        return "mechanism"
    if item_type == "overhead":
        text = re.sub(r"\s+", " ", str(name or "").strip().casefold())
        if any(term in text for term in ("доставка", "вывоз", "разгрузка", "погрузка")):
            return "logistics"
        return "overhead"
    return None


def _row_item_type_confidence(raw: dict) -> float | None:
    value = raw.get("item_type_confidence")
    if value is None:
        value = raw.get("classification_confidence")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _resolve_effective_row_role(
    *,
    item_type_role: str | None,
    detected_role: str,
    item_type_confidence: float | None,
) -> tuple[str, str | None]:
    if (
        item_type_role == "work"
        and item_type_confidence is not None
        and item_type_confidence < _LOW_CONFIDENCE
        and detected_role in EARLY_INHERIT_ROLES
    ):
        return detected_role, "low_confidence_parser_item_type"
    return item_type_role or detected_role or "unknown", None


def _is_confident_work_result(result, auto_accept_min_score: int, unknown_code: str) -> bool:
    return bool(
        result
        and result.subtype_code != unknown_code
        and not result.needs_review
        and int(result.score or 0) >= auto_accept_min_score
    )


class PreviewChangedError(Exception):
    """Правки оператора не легли на текущий re-parse (строка под index изменилась)."""


def _norm_hash_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _norm_hash_num(value) -> str:
    if value is None:
        return ""
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, ValueError):
        return str(value)


def _row_hash(section, name, unit, quantity, total_price) -> str:
    """Стабильный отпечаток строки для сверки preview↔confirm (после нормализации,
    чтобы 1000 и 1000.0 совпадали)."""
    parts = [
        _norm_hash_text(section),
        _norm_hash_text(name),
        _norm_hash_text(unit),
        _norm_hash_num(quantity),
        _norm_hash_num(total_price),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def _row_preview_dict(row, index: int | None = None) -> dict:
    raw = getattr(row, "raw_data", None) or {}
    item_type_confidence = raw.get("item_type_confidence")
    if item_type_confidence is None and isinstance(raw.get("classification_confidence"), (int, float)):
        item_type_confidence = raw.get("classification_confidence")
    result = {
        "index":       index,
        "row_order":   getattr(row, "row_order", 0),
        "section":     row.section,
        "item_type":   resolve_item_type(row),
        "name":        row.work_name,
        "spec":        raw.get("spec"),
        "unit":        row.unit,
        "quantity":    float(row.quantity) if row.quantity is not None else None,
        "total_price": float(row.total_price) if row.total_price is not None else None,
        "confidence":  item_type_confidence,
        "reason":      raw.get("classification_reason"),
        "macro_id":    raw.get("macro_id"),
        "subtype_code": raw.get("work_subtype_code") or raw.get("subtype_code"),
        "subtype_name": raw.get("work_subtype_name") or raw.get("subtype_name"),
        "work_section_code": raw.get("work_section_code"),
        "work_section_name": raw.get("work_section_name"),
        "work_subtype_code": raw.get("work_subtype_code") or raw.get("subtype_code"),
        "work_subtype_name": raw.get("work_subtype_name") or raw.get("subtype_name"),
        "classification_score": raw.get("classification_score"),
        "classification_confidence": raw.get("classification_confidence"),
        "classification_needs_review": raw.get("classification_needs_review"),
        "classification_source": raw.get("classification_source"),
        "classification_candidates": raw.get("classification_candidates"),
        "classification_matched_terms": raw.get("classification_matched_terms"),
        "operator_review_required": raw.get("operator_review_required"),
        "work_stage_number": raw.get("work_stage_number"),
        "work_stage_title": raw.get("work_stage_title"),
        "canonical_stage_id": raw.get("canonical_stage_id"),
        "stage_occurrence_index": raw.get("stage_occurrence_index"),
        "stage_occurrence_label": raw.get("stage_occurrence_label"),
        "stage_options_mode": raw.get("stage_options_mode"),
        "stage_option_id": raw.get("stage_option_id"),
        "stage_option_title": raw.get("stage_option_title"),
        "stage_confidence": raw.get("stage_confidence"),
        "stage_match_type": raw.get("stage_match_type"),
        "stage_match_score_json": raw.get("stage_match_score_json"),
        "work_type_match_score_json": raw.get("work_type_match_score_json"),
        "row_role": raw.get("row_role"),
        "section_id": raw.get("section_id"),
        "subtype_id": raw.get("subtype_id"),
        "needs_review": raw.get("needs_review"),
        "review_reason": raw.get("review_reason"),
        "work_type_confidence": raw.get("work_type_confidence"),
        "row_hash":    _row_hash(row.section, row.work_name, row.unit, row.quantity, row.total_price),
    }
    materials = getattr(row, "materials", None) or []
    if materials:
        result["materials"] = [_material_dict(material) for material in materials]
        result["materials_total"] = _money_float(sum(
            (_decimal_value(material.get("total_price")) for material in materials),
            Decimal("0"),
        ))
    return result


def _zero_or_empty(value) -> bool:
    if value is None or value == "":
        return True
    try:
        return Decimal(str(value)) == 0
    except (InvalidOperation, ValueError, TypeError):
        return False


def _filter_unselected_catalog_rows(rows: list, meta: dict) -> tuple[list, int]:
    """Remove unselected rows from catalog-like Excel price lists.

    The heuristic is intentionally conservative: it is enabled only for a large
    row-oriented Excel where at least half of data rows have zero quantity and
    zero total, while a meaningful set of active rows remains. This matches
    estimate templates where the contractor selects rows by entering quantity.
    """
    if meta.get("format") != "excel" or meta.get("strategy") != "row" or len(rows) < 50:
        meta["inactive_catalog_rows_count"] = 0
        return rows, 0

    zero_rows = [
        row
        for row in rows
        if _zero_or_empty(getattr(row, "quantity", None))
        and _zero_or_empty(getattr(row, "total_price", None))
    ]
    active_count = len(rows) - len(zero_rows)
    priced_zero_count = sum(
        1 for row in zero_rows if not _zero_or_empty(getattr(row, "unit_price", None))
    )
    catalog_like = (
        len(zero_rows) / max(1, len(rows)) >= 0.50
        and active_count >= 10
        and priced_zero_count >= max(10, len(zero_rows) // 2)
    )
    if not catalog_like:
        meta["inactive_catalog_rows_count"] = 0
        return rows, 0

    zero_ids = {id(row) for row in zero_rows}
    for row in zero_rows:
        raw = row.raw_data if isinstance(getattr(row, "raw_data", None), dict) else {}
        raw.update(
            {
                "source_row_kind": "catalog_item",
                "is_active_estimate_row": False,
                "row_role": "inactive_catalog_row",
                "skip_taxonomy": True,
                "skip_stage_classifier": True,
                "classification_source": "inactive_catalog_row",
                "classification_reason": "zero_quantity_and_total_in_catalog_like_excel",
            }
        )
        row.raw_data = raw

    meta["catalog_like_excel"] = True
    meta["inactive_catalog_rows_count"] = len(zero_rows)
    meta["active_estimate_rows_count"] = active_count
    return [row for row in rows if id(row) not in zero_ids], len(zero_rows)


def _enrich_work_subtypes_sync(
    rows: list,
    hierarchy_selection: dict | None = None,
) -> dict[int, object]:
    """Classify active rows once and return reusable results by row index."""
    from app.services.work_taxonomy_service import (
        UNKNOWN_SUBTYPE_CODE,
        _load_dictionary,
        classify_row_role,
        classify_work_cascade,
        get_estimate_type_scope,
        get_variant_scope,
        inherited_context_raw,
        should_inherit_parent_context,
    )

    variant_scope = None
    estimate_type_scope = None
    if hierarchy_selection:
        estimate_type_id = hierarchy_selection.get("estimate_type_id")
        project_variant_id = hierarchy_selection.get("project_variant_id")
        if estimate_type_id:
            estimate_type_scope = get_estimate_type_scope(str(estimate_type_id))
        if estimate_type_id and project_variant_id:
            variant_scope = get_variant_scope(str(estimate_type_id), str(project_variant_id))

    has_hierarchy_scope = bool(variant_scope is not None or estimate_type_scope is not None)
    thresholds = ((_load_dictionary().get("scoring") or {}).get("decision_thresholds") or {})
    auto_accept_min_score = int(thresholds.get("auto_accept_min_score", 9))

    taxonomy_keys = (
        "macro_id",
        "subtype_code",
        "subtype_name",
        "work_section_code",
        "work_section_name",
        "work_subtype_code",
        "work_subtype_name",
        "classification_score",
        "classification_confidence",
        "classification_needs_review",
        "classification_source",
        "classification_candidates",
        "classification_matched_terms",
        "classification_reason",
        "classification_related_sections",
        "classification_scope",
        "classification_scope_estimate_type",
        "classification_scope_project_variant",
        "classification_scope_candidate_sections",
        "classification_scope_candidate_pairs",
        "classification_fallback_used",
        "operator_review_required",
        "operator_review_status",
        "operator_review_reason",
        "dictionary_version",
        "parent_context_source",
        "parent_context_code",
        "context_inherited",
        "context_inheritance_reason",
        "work_type_applicable",
    )
    parent_context: dict | None = None
    preclassified_results: dict[int, object] = {}

    for index, row in enumerate(rows):
        raw = row.raw_data if isinstance(getattr(row, "raw_data", None), dict) else {}
        row.raw_data = raw
        if is_subtotal_row(row):
            raw.update(
                {
                    "row_role": "total",
                    "skip_taxonomy": True,
                    "skip_stage_classifier": True,
                    "classification_source": "subtotal_filter",
                    "classification_reason": "subtotal_or_total_row",
                    "operator_review_required": False,
                }
            )
            continue
        item_type_confidence = _row_item_type_confidence(raw)
        if item_type_confidence is not None:
            raw["item_type_confidence"] = item_type_confidence
        if raw.get("skip_taxonomy"):
            raw.setdefault("row_role", "inactive_catalog_row")
            continue

        item_type = resolve_item_type(row)
        item_type_role = _row_role_from_item_type(item_type, row.work_name)
        detected_role = classify_row_role(
            row.work_name or "",
            row.section,
            row.unit,
            row.quantity,
            allow_absent_header=True,
        )
        row_role, override_reason = _resolve_effective_row_role(
            item_type_role=item_type_role,
            detected_role=detected_role,
            item_type_confidence=item_type_confidence,
        )
        role_diagnostics = {
            "source_item_type": item_type,
            "source_item_type_confidence": item_type_confidence,
            "detected_row_role": detected_role,
            "source_row_role": item_type_role or "unknown",
            "row_role": row_role,
        }
        if override_reason:
            role_diagnostics["row_role_override_reason"] = override_reason
        raw.update(role_diagnostics)

        if row_role == "header":
            context_result = classify_work_cascade(
                row.work_name or "",
                row.section,
                row_role="work",
                variant_scope=variant_scope,
                estimate_type_scope=estimate_type_scope,
            )
            preclassified_results[index] = context_result
            if not context_result.needs_review and context_result.subtype_code != UNKNOWN_SUBTYPE_CODE:
                context_raw = context_result.as_raw_data()
                context_raw["parent_context_source"] = "header"
                context_raw["context_inherited"] = False
                parent_context = context_raw
            for key in taxonomy_keys:
                raw.pop(key, None)
            raw.update(role_diagnostics)
            raw.update(
                {
                    "classification_source": "row_role_header",
                    "classification_reason": "set_context_only",
                    "operator_review_required": False,
                    "operator_review_status": None,
                    "operator_review_reason": None,
                    "context_inherited": False,
                }
            )
            continue

        # Correctly typed flat resource rows never enter work taxonomy.
        if row_role in EARLY_INHERIT_ROLES:
            if row_role == "overhead":
                for key in taxonomy_keys:
                    raw.pop(key, None)
                raw.update(role_diagnostics)
                raw.update(
                    {
                        "classification_source": "row_role_overhead",
                        "classification_reason": "work_type_not_applicable_for_overhead",
                        "operator_review_required": False,
                        "operator_review_status": None,
                        "operator_review_reason": None,
                        "context_inherited": False,
                        "work_type_applicable": False,
                    }
                )
                continue

            if parent_context and should_inherit_parent_context(row_role, row.work_name or ""):
                raw.update(
                    inherited_context_raw(
                        parent_context,
                        row_role=row_role,
                        reason=f"{row_role}_inherits_parent_context",
                    )
                )
                raw.update(role_diagnostics)
                raw["operator_review_required"] = False
                raw["operator_review_status"] = None
                raw["operator_review_reason"] = None
                raw["work_type_applicable"] = True
                continue

            for key in taxonomy_keys:
                raw.pop(key, None)
            raw.update(role_diagnostics)
            raw["context_inherited"] = False
            raw["classification_reason"] = "resource_row_without_parent_context"
            raw["operator_review_required"] = True
            continue

        if row_role == "unknown":
            result = classify_work_cascade(
                row.work_name or "",
                row.section,
                row_role="unknown",
                variant_scope=variant_scope,
                estimate_type_scope=estimate_type_scope,
                allow_global_fallback=not has_hierarchy_scope,
            )
            preclassified_results[index] = result
            if _is_confident_work_result(result, auto_accept_min_score, UNKNOWN_SUBTYPE_CODE):
                raw.update(result.as_raw_data())
                raw.update(role_diagnostics)
                raw["source_row_role"] = "unknown"
                raw["row_role"] = "work"
                raw["row_role_promoted_from"] = "unknown"
                raw["operator_review_required"] = False
                raw["operator_review_status"] = None
                raw["operator_review_reason"] = None
                parent_context = dict(raw)
            elif parent_context:
                raw.update(
                    inherited_context_raw(
                        parent_context,
                        row_role="unknown",
                        reason="unknown_low_confidence_inherits_parent",
                    )
                )
                raw.update(role_diagnostics)
                raw["source_row_role"] = "unknown"
                raw["row_role"] = "unknown"
                raw["operator_review_required"] = False
                raw["operator_review_status"] = None
                raw["operator_review_reason"] = None
            else:
                raw.update(result.as_raw_data())
                raw.update(role_diagnostics)
                raw["source_row_role"] = "unknown"
                raw["row_role"] = "unknown"
                raw["operator_review_required"] = True
                raw["operator_review_status"] = None
                raw["operator_review_reason"] = "unknown_row_without_confident_match_or_parent"
            continue

        if row_role == "work":
            result = classify_work_cascade(
                row.work_name or "",
                row.section,
                row_role="work",
                variant_scope=variant_scope,
                estimate_type_scope=estimate_type_scope,
            )
            preclassified_results[index] = result
            inherited = False
            if (
                parent_context
                and should_inherit_parent_context(result.row_role, row.work_name or "", result)
                and (result.needs_review or result.subtype_code == UNKNOWN_SUBTYPE_CODE)
            ):
                raw.update(
                    inherited_context_raw(
                        parent_context,
                        row_role=result.row_role,
                        reason="generic_or_low_confidence_work_row",
                    )
                )
                inherited = True
            else:
                raw.update(result.as_raw_data())
            raw.update(role_diagnostics)
            raw["row_role"] = "work"
            raw["operator_review_required"] = False if inherited else bool(result.needs_review)
            raw["operator_review_status"] = None
            raw["operator_review_reason"] = None if inherited else (result.reason if result.needs_review else None)
            if raw.get("work_subtype_code") and raw.get("work_subtype_code") != UNKNOWN_SUBTYPE_CODE:
                parent_context = dict(raw)
            continue

        for key in taxonomy_keys:
            raw.pop(key, None)
        raw.update(role_diagnostics)
        raw["context_inherited"] = False

    return preclassified_results


def _enrich_work_stages_sync(
    rows: list,
    hierarchy_selection: dict | None,
    preclassified_results: dict[int, object] | None = None,
) -> None:
    if not hierarchy_selection:
        return
    estimate_type_id = hierarchy_selection.get("estimate_type_id")
    project_variant_id = hierarchy_selection.get("project_variant_id")
    if not estimate_type_id or not project_variant_id:
        return

    from app.services.stage_classifier import StageClassifier
    from app.services.work_taxonomy_service import (
        get_project_variant_stages,
        get_sequential_scoring_policy,
    )

    stages = get_project_variant_stages(str(estimate_type_id), str(project_variant_id))
    classifier = StageClassifier(get_sequential_scoring_policy())
    estimate_profile_id = hierarchy_selection.get("estimate_profile_id") or hierarchy_selection.get("estimate_type_id")
    previous_context: dict | None = None
    preclassified_results = preclassified_results or {}
    for index, row in enumerate(rows):
        raw = row.raw_data if isinstance(getattr(row, "raw_data", None), dict) else {}
        row.raw_data = raw
        raw["row_order"] = index
        if is_subtotal_row(row):
            raw.update(
                {
                    "row_role": "total",
                    "skip_taxonomy": True,
                    "skip_stage_classifier": True,
                    "classification_source": "subtotal_filter",
                    "classification_reason": "subtotal_or_total_row",
                    "operator_review_required": False,
                }
            )
            continue
        if raw.get("skip_stage_classifier"):
            continue
        row_role = raw.get("row_role") or "unknown"
        match = classifier.classify_row_to_stage(
            " ".join(str(part or "") for part in (row.section, row.work_name)),
            str(row_role),
            stages,
            previous_context,
            estimate_profile_id=str(estimate_profile_id) if estimate_profile_id else None,
            row_order=index,
            global_result=preclassified_results.get(index),
        )
        if not match.stage:
            raw.setdefault("row_role", str(row_role))
            raw.setdefault("needs_review", match.needs_review)
            raw.setdefault("review_reason", match.review_reason)
            raw.setdefault("stage_match_type", match.match_type)
            raw.setdefault("stage_match_score_json", match.score_breakdown)
            continue
        stage_raw = match.as_raw_data(
            estimate_type_id=hierarchy_selection.get("estimate_type_id"),
            estimate_type_number=hierarchy_selection.get("estimate_type_number"),
            project_variant_id=hierarchy_selection.get("project_variant_id"),
            project_variant_number=hierarchy_selection.get("project_variant_number"),
            row_role=str(row_role),
        )
        base_result = preclassified_results.get(index)
        preserve_base = bool(
            base_result
            and getattr(base_result, "subtype_code", None)
            and getattr(base_result, "subtype_code", None) != "unknown/needs_review"
            and not bool(getattr(base_result, "needs_review", True))
            and (
                match.needs_review
                or match.work_type_match is None
                or match.work_type_match.needs_review
            )
        )
        if preserve_base:
            base_section, base_subtype = str(base_result.subtype_code).split("/", 1)
            stage_raw.update(
                {
                    "section_id": base_section,
                    "subtype_id": base_subtype,
                    "work_section_code": base_section,
                    "work_subtype_code": base_result.subtype_code,
                    "work_type_confidence": base_result.confidence,
                }
            )
            stage_raw.setdefault("work_type_match_score_json", {})["preserved_preclassified_result"] = {
                "subtype_code": base_result.subtype_code,
                "source": base_result.source,
                "score": base_result.score,
                "reason": "stage_or_stage_work_type_requires_review",
            }
        raw.update(stage_raw)
        if raw.get("section_id"):
            raw["work_section_code"] = raw.get("section_id")
        if raw.get("section_id") and raw.get("subtype_id"):
            raw["work_subtype_code"] = f"{raw['section_id']}/{raw['subtype_id']}"
        if (
            not match.needs_review
            and raw.get("work_stage_number")
            and raw.get("row_role") in {"work", "header"}
        ):
            previous_context = dict(raw)


async def _enrich_work_subtypes(rows: list, db: AsyncSession, hierarchy_selection: dict | None = None) -> None:
    preclassified_results = await run_in_threadpool(
        _enrich_work_subtypes_sync,
        rows,
        hierarchy_selection,
    )
    await run_in_threadpool(
        _enrich_work_stages_sync,
        rows,
        hierarchy_selection,
        preclassified_results,
    )


def _apply_operator_edits(rows: list, edits: dict | None) -> list:
    """Применить правки шага 2: смена item_type по (index, row_hash) и добавленные
    строки. Возвращает итоговый список строк (с добавленными в конце)."""
    if not edits:
        return rows

    for override in edits.get("type_overrides") or []:
        index = override.get("index")
        if not isinstance(index, int) or index < 0 or index >= len(rows):
            raise PreviewChangedError("PREVIEW_EXPIRED_OR_CHANGED: строка вне диапазона")
        row = rows[index]
        expected = override.get("row_hash")
        actual = _row_hash(row.section, row.work_name, row.unit, row.quantity, row.total_price)
        if expected and expected != actual:
            raise PreviewChangedError("PREVIEW_EXPIRED_OR_CHANGED: строка изменилась")
        item_type = override.get("item_type")
        if item_type not in VALID_ESTIMATE_ITEM_TYPES:
            raise PreviewChangedError(f"PREVIEW_EXPIRED_OR_CHANGED: недопустимый тип «{item_type}»")
        raw = row.raw_data if isinstance(getattr(row, "raw_data", None), dict) else {}
        raw["item_type"] = item_type
        raw["classification_reason"] = "operator_override"
        row.raw_data = raw

    for added in edits.get("added_rows") or []:
        item_type = added.get("item_type")
        if item_type not in VALID_ESTIMATE_ITEM_TYPES:
            item_type = "work"
        rows.append(ParsedRow(
            section=added.get("section") or None,
            work_name=(added.get("name") or "").strip(),
            unit=added.get("unit") or None,
            quantity=added.get("quantity"),
            total_price=added.get("total_price"),
            raw_data={
                "item_type": item_type,
                "classification_reason": "operator_added",
                "classification_confidence": 1.0,
                "manual_added": True,
            },
        ))

    return rows


def _apply_stage_operator_overrides(rows: list, edits: dict | None) -> None:
    if not edits:
        return
    for override in edits.get("stage_overrides") or []:
        index = override.get("index")
        if not isinstance(index, int) or index < 0 or index >= len(rows):
            raise PreviewChangedError("PREVIEW_EXPIRED_OR_CHANGED: строка stage override вне диапазона")
        row = rows[index]
        expected = override.get("row_hash")
        actual = _row_hash(row.section, row.work_name, row.unit, row.quantity, row.total_price)
        if expected and expected != actual:
            raise PreviewChangedError("PREVIEW_EXPIRED_OR_CHANGED: строка изменилась")
        raw = row.raw_data if isinstance(getattr(row, "raw_data", None), dict) else {}
        row.raw_data = raw

        def set_clean(key: str, value):
            if value is None:
                raw.pop(key, None)
            else:
                raw[key] = value

        for key in (
            "work_stage_number",
            "work_stage_title",
            "canonical_stage_id",
            "stage_occurrence_index",
            "stage_occurrence_label",
            "stage_options_mode",
            "stage_option_id",
            "stage_option_title",
            "section_id",
            "subtype_id",
            "row_role",
        ):
            if key in override:
                set_clean(key, override.get(key))

        section_id = raw.get("section_id")
        subtype_id = raw.get("subtype_id")
        if section_id:
            raw["work_section_code"] = section_id
        if section_id and subtype_id:
            raw["work_subtype_code"] = f"{section_id}/{subtype_id}"
        else:
            raw.pop("work_subtype_code", None)
        raw["manual_override"] = True
        raw["needs_review"] = False
        raw["review_reason"] = None
        raw["stage_match_type"] = "manual_operator_override"
        raw["stage_confidence"] = "high"
        raw["work_type_confidence"] = "high" if section_id and subtype_id else "low"
        raw["stage_match_score_json"] = {
            "manual_override": True,
            "operator_fields": sorted(override.keys()),
        }
        raw["work_type_match_score_json"] = {
            "manual_override": True,
            "winner": {
                "section_id": section_id,
                "subtype_id": subtype_id,
                "source": "manual_operator_override",
            },
        }


def _parse_upload_rows_for_import(
    tmp_path: str,
    col_mapping: dict | None,
    sheet: str | None,
    parser_profile: str,
    edits: dict | None,
    hierarchy_selection: dict | None,
) -> tuple[list, list[dict], dict]:
    if col_mapping is not None:
        int_mapping = {int(k): v for k, v in col_mapping.items()}
        rows, meta = _parser.parse_mapped(tmp_path, int_mapping, sheet=sheet)
    else:
        from app.services.parser_factory import parse_estimate, FORMAT_SCAN, FORMAT_UNKNOWN

        rows, meta = parse_estimate(tmp_path, parser_profile=parser_profile)
        if meta.get("format") == FORMAT_SCAN:
            raise ValueError(
                "PDF содержит только изображения (скан). "
                "Загрузите текстовый PDF или Excel-файл."
            )
        if meta.get("format") == FORMAT_UNKNOWN:
            raise ValueError("Не удалось определить формат файла сметы.")

    if not rows:
        raise ValueError(
            "Не удалось распознать строки сметы. "
            "Убедитесь что файл содержит колонки: "
            "наименование, количество, единица, сумма."
        )

    rows, subtotal_rows = _split_work_and_subtotal_rows(rows)
    if not rows:
        raise ValueError(
            "В файле найдены только строки подытогов. "
            "Строки с «Итого» и «Всего» используются для сверки, "
            "но не считаются работами."
        )

    rows, _inactive_count = _filter_unselected_catalog_rows(rows, meta)
    if not rows:
        raise ValueError("В файле не осталось активных строк сметы после исключения нулевых позиций каталога.")
    rows = _apply_operator_edits(rows, edits)
    preclassified_results = _enrich_work_subtypes_sync(rows, hierarchy_selection)
    _enrich_work_stages_sync(rows, hierarchy_selection, preclassified_results)
    _apply_stage_operator_overrides(rows, edits)
    return rows, subtotal_rows, meta


def _material_dict(material: dict) -> dict:
    """A nested ParsedRow.materials entry (Excel «работа+материалы» formats)."""
    quantity = material.get("quantity")
    if quantity is None:
        quantity = material.get("qty")
    total_price = material.get("total_price")
    if total_price is None:
        total_price = material.get("total")
    confidence = material.get("item_type_confidence")
    return {
        "row_order":           None,
        "section":             None,
        "item_type":           "material",
        "name":                material.get("name") or material.get("work_name") or "",
        "spec":                material.get("spec"),
        "unit":                material.get("unit"),
        "quantity":            quantity,
        "unit_price":          material.get("unit_price"),
        "total_price":         total_price,
        "source_num":          material.get("source_num"),
        "parent_work_num":     material.get("parent_work_num"),
        "source_excel_row":    material.get("source_excel_row"),
        "item_type_confidence": confidence,
        "confidence":          confidence,
        "reason":              "nested_material",
    }


def _decimal_value(value, default: Decimal = Decimal("0")) -> Decimal:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _money_float(value) -> float:
    return float(_decimal_value(value).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP))


def _material_identity(material: dict) -> tuple:
    """Stable-enough identity used only to avoid preview double counting.

    Source row/number is preferred.  The content fallback keeps compatibility
    with older parsers that do not expose structural source fields.
    """
    source_row = material.get("source_excel_row")
    source_num = material.get("source_num")
    if source_row is not None or source_num:
        return ("source", source_row, source_num)
    quantity = material.get("quantity")
    if quantity is None:
        quantity = material.get("qty")
    total = material.get("total_price")
    if total is None:
        total = material.get("total")
    return (
        "content",
        material.get("name") or material.get("work_name") or "",
        material.get("unit"),
        str(quantity),
        str(total),
    )


def _top_level_material_identity(row) -> tuple:
    raw = getattr(row, "raw_data", None) or {}
    return _material_identity({
        "source_excel_row": raw.get("source_excel_row"),
        "source_num": raw.get("source_num"),
        "name": getattr(row, "work_name", None),
        "unit": getattr(row, "unit", None),
        "quantity": getattr(row, "quantity", None),
        "total_price": getattr(row, "total_price", None),
    })


def _iter_unique_nested_materials(rows: list):
    top_level_materials = {
        _top_level_material_identity(row)
        for row in rows
        if resolve_item_type(row) == "material"
    }
    for row in rows:
        for material in (getattr(row, "materials", None) or []):
            if _material_identity(material) in top_level_materials:
                continue
            yield row, material


_GROUP_BUCKETS = {
    "work": "works",
    "material": "materials",
    "mechanism": "mechanisms",
    "overhead": "overhead",
    "unknown": "unknown",
}


def _build_preview_groups(rows: list) -> dict:
    """Group rows by section → {works, materials, mechanisms, overhead, unknown}.

    Totals are computed over ALL rows; the row lists are capped at
    MAX_PREVIEW_GROUP_ROWS (transient payload, never persisted). Materials with no
    per-work link sit at the group level; works that DO carry ParsedRow.materials
    expose them nested under the work.
    """
    groups: dict[str, dict] = {}
    order: list[str] = []
    no_section_count = 0
    rows_emitted = 0
    truncated = False
    group_decimal_totals: dict[str, dict[str, Decimal]] = {}
    unique_nested_by_parent: dict[int, list[dict]] = {}
    for parent, material in _iter_unique_nested_materials(rows):
        unique_nested_by_parent.setdefault(id(parent), []).append(material)

    for row in rows:
        section = row.section or _NO_SECTION
        if not row.section:
            no_section_count += 1
        if section not in groups:
            groups[section] = {
                "section": section,
                "totals": {t: {"count": 0, "total": 0.0} for t in _ITEM_TYPE_ORDER},
                "works": [], "materials": [], "mechanisms": [], "overhead": [], "unknown": [],
            }
            order.append(section)
            group_decimal_totals[section] = {t: Decimal("0") for t in _ITEM_TYPE_ORDER}

        g = groups[section]
        item_type = resolve_item_type(row)
        bucket_totals = g["totals"].setdefault(item_type, {"count": 0, "total": 0.0})
        bucket_totals["count"] += 1
        group_decimal_totals[section].setdefault(item_type, Decimal("0"))
        group_decimal_totals[section][item_type] += _decimal_value(row.total_price)

        if item_type == "work":
            nested_materials = unique_nested_by_parent.get(id(row), [])
            material_totals = g["totals"].setdefault("material", {"count": 0, "total": 0.0})
            material_totals["count"] += len(nested_materials)
            group_decimal_totals[section]["material"] += sum(
                (_decimal_value(m.get("total_price")) for m in nested_materials),
                Decimal("0"),
            )

        if rows_emitted >= MAX_PREVIEW_GROUP_ROWS:
            truncated = True
            continue

        entry = _row_preview_dict(row)
        if item_type == "work":
            entry["materials"] = [_material_dict(m) for m in (getattr(row, "materials", None) or [])]
            entry["materials_total"] = _money_float(sum(
                (_decimal_value(m.get("total_price")) for m in (getattr(row, "materials", None) or [])),
                Decimal("0"),
            ))
        g[_GROUP_BUCKETS.get(item_type, "unknown")].append(entry)
        rows_emitted += 1

    for section in order:
        for item_type, total in group_decimal_totals[section].items():
            groups[section]["totals"].setdefault(item_type, {"count": 0, "total": 0.0})
            groups[section]["totals"][item_type]["total"] = _money_float(total)

    return {
        "groups": [groups[s] for s in order],
        "truncated": truncated,
        "no_section_count": no_section_count,
    }


def _build_stage_preview_groups(rows: list) -> list[dict]:
    groups: dict[str, dict] = {}
    order: list[str] = []
    for index, row in enumerate(rows[:MAX_PREVIEW_GROUP_ROWS]):
        raw = getattr(row, "raw_data", None) or {}
        stage_number = raw.get("work_stage_number") or "unmatched"
        if stage_number not in groups:
            title = raw.get("work_stage_title") or ("Не распределено" if stage_number == "unmatched" else "")
            groups[stage_number] = {
                "work_stage_number": None if stage_number == "unmatched" else stage_number,
                "work_stage_title": title,
                "canonical_stage_id": raw.get("canonical_stage_id"),
                "stage_options_mode": raw.get("stage_options_mode") or "none",
                "rows_count": 0,
                "needs_review_count": 0,
                "total": 0.0,
                "rows": [],
            }
            order.append(stage_number)
        group = groups[stage_number]
        entry = _row_preview_dict(row, index=index)
        group["rows_count"] += 1
        group["total"] = round(float(group["total"]) + float(row.total_price or 0), 2)
        if entry.get("needs_review") or entry.get("operator_review_required"):
            group["needs_review_count"] += 1
        group["rows"].append(entry)
    return [groups[key] for key in order]


def _compute_preview(rows: list, subtotal_rows: list[dict], meta: dict) -> dict:
    breakdown_counts = {t: 0 for t in _ITEM_TYPE_ORDER}
    breakdown_totals = {t: Decimal("0") for t in _ITEM_TYPE_ORDER}
    unknown_rows: list[dict] = []
    low_confidence_rows: list[dict] = []

    top_level_total = Decimal("0")
    for row in rows:
        item_type = resolve_item_type(row)
        breakdown_counts.setdefault(item_type, 0)
        breakdown_totals.setdefault(item_type, Decimal("0"))
        breakdown_counts[item_type] += 1
        row_total = _decimal_value(getattr(row, "total_price", None))
        breakdown_totals[item_type] += row_total
        top_level_total += row_total

        raw = getattr(row, "raw_data", None) or {}
        if item_type == "unknown" and len(unknown_rows) < 20:
            unknown_rows.append(_row_preview_dict(row))
        conf = raw.get("item_type_confidence")
        if conf is None and isinstance(raw.get("classification_confidence"), (int, float)):
            conf = raw.get("classification_confidence")
        if conf is not None and conf < _LOW_CONFIDENCE and len(low_confidence_rows) < 20:
            low_confidence_rows.append(_row_preview_dict(row))

    nested_material_total = Decimal("0")
    nested_material_count = 0
    for _parent, material in _iter_unique_nested_materials(rows):
        nested_material_count += 1
        material_total = _decimal_value(material.get("total_price"))
        nested_material_total += material_total
        breakdown_counts["material"] = breakdown_counts.get("material", 0) + 1
        breakdown_totals["material"] = breakdown_totals.get("material", Decimal("0")) + material_total

    breakdown = {
        item_type: {
            "count": breakdown_counts.get(item_type, 0),
            "total": _money_float(breakdown_totals.get(item_type, Decimal("0"))),
        }
        for item_type in dict.fromkeys((*_ITEM_TYPE_ORDER, *breakdown_counts.keys()))
    }
    computed_work_total = breakdown.get("work", {}).get("total", 0.0)
    computed_material_total = breakdown.get("material", {}).get("total", 0.0)
    computed_total_without_vat = _money_float(top_level_total + nested_material_total)

    declared = _declared_totals_from_meta(meta)
    declared_total = declared["total_without_vat"]
    if declared_total is None:
        declared_total = declared["legacy_total"]
    if declared_total is None:
        declared_total = _declared_total_price(subtotal_rows)

    vat_rate = declared["vat_rate"]
    computed_vat_total = None
    computed_total_with_vat = None
    if vat_rate is not None:
        computed_vat_total = _money_float(
            _decimal_value(computed_total_without_vat)
            * _decimal_value(vat_rate)
            / Decimal("100")
        )
        computed_total_with_vat = _money_float(
            _decimal_value(computed_total_without_vat) + _decimal_value(computed_vat_total)
        )

    difference = (
        _money_float(_decimal_value(declared_total) - _decimal_value(computed_total_without_vat))
        if declared_total is not None
        else None
    )
    difference_with_vat = (
        _money_float(
            _decimal_value(declared["total_with_vat"]) - _decimal_value(computed_total_with_vat)
        )
        if declared["total_with_vat"] is not None and computed_total_with_vat is not None
        else None
    )
    difference_reason = None
    if difference is not None and abs(difference) > 1:
        difference_reason = (
            "Сумма строк отличается от итоговой суммы сметы. Возможны строки в сводной "
            "без детального листа или расхождение в исходном файле — проверьте перед импортом."
        )

    return {
        "type_breakdown": breakdown,
        "computed_work_total": computed_work_total,
        "computed_material_total": computed_material_total,
        "computed_total_without_vat": computed_total_without_vat,
        "computed_vat_total": computed_vat_total,
        "computed_total_with_vat": computed_total_with_vat,
        # Backward-compatible field: now includes nested materials once.
        "computed_total_all_rows": computed_total_without_vat,
        "declared_total": declared_total,
        "declared_vat": declared["vat"],
        "declared_vat_rate": declared["vat_rate"],
        "declared_total_with_vat": declared["total_with_vat"],
        "difference": difference,
        "difference_with_vat": difference_with_vat,
        "difference_reason": difference_reason,
        "unknown_count": breakdown.get("unknown", {}).get("count", 0),
        "unknown_rows": unknown_rows,
        "low_confidence_rows": low_confidence_rows,
        "sample_rows": [_row_preview_dict(r) for r in rows[:20]],
        "ignored_subtotal_rows_count": len(subtotal_rows),
        "declared_totals": meta.get("declared_totals"),
        "nested_materials_count": nested_material_count,
        "stage_review_count": sum(1 for row in rows if (getattr(row, "raw_data", None) or {}).get("needs_review")),
    }


def _sample_texts_for_suggestions(rows: list, limit: int = 80) -> list[str]:
    texts: list[str] = []
    for row in rows[:limit]:
        text_value = " ".join(str(part or "") for part in (row.section, row.work_name)).strip()
        if text_value:
            texts.append(text_value)
    return texts


def _declared_totals_from_meta(meta: dict) -> dict:
    """Normalize parser-declared totals without changing the legacy list contract."""
    result = {
        "total_without_vat": None,
        "vat": None,
        "vat_rate": None,
        "total_with_vat": None,
        "legacy_total": None,
    }
    totals = meta.get("declared_totals")
    if not isinstance(totals, list):
        return result

    section_totals: list[Decimal] = []
    for item in totals:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        total = item.get("total")
        if total is None:
            continue
        value = _money_float(total)
        if kind == "total_without_vat":
            result["total_without_vat"] = value
        elif kind == "vat":
            result["vat"] = value
            if item.get("rate") is not None:
                result["vat_rate"] = float(item["rate"])
        elif kind == "grand_total":
            result["total_with_vat"] = value
        elif kind == "section_total":
            section_totals.append(_decimal_value(total))

    # Preserve the previous PDF semantics: last grand_total wins, otherwise
    # section totals are added together.  For the new matrix profile the
    # explicit total_without_vat takes precedence in _declared_total_from_meta.
    if result["total_with_vat"] is not None:
        result["legacy_total"] = result["total_with_vat"]
    elif section_totals:
        result["legacy_total"] = _money_float(sum(section_totals, Decimal("0")))
    return result


def _declared_total_from_meta(meta: dict) -> float | None:
    """Pick the reconciliation base from parser metadata.

    New work/material matrix estimates reconcile before VAT.  Existing PDF
    parsers continue to reconcile against grand_total/section_total.
    """
    totals = _declared_totals_from_meta(meta)
    if totals["total_without_vat"] is not None:
        return totals["total_without_vat"]
    return totals["legacy_total"]


async def preview_upload_job(
    file:             UploadFile,
    project_id:       str,
    user_id:          str,
    parser_profile:   str,
    start_date:       date,
    workers:          int,
    estimate_kind:    int,
    complex_mode:     bool,
    build_gantt:      bool,
    clarification_answers: dict | None,
    hierarchy_selection: dict | None,
    db:               AsyncSession,
    hierarchy_suggestions = None,
    suggestion_estimate_type_id: str | None = None,
) -> dict:
    """Parse the upload to a tmp file and return a typed breakdown WITHOUT any DB
    writes. Stores a Redis preview session and returns its preview_id."""
    from app.services.parser_factory import (
        parse_estimate, ParserProfileNotImplemented, FORMAT_SCAN, FORMAT_UNKNOWN,
    )
    from app.services.preview_session import save_preview_session

    allowed = (".xlsx", ".xls", ".pdf")
    if not file.filename.lower().endswith(allowed):
        raise HTTPException(400, f"Поддерживаются: {', '.join(allowed)}")

    suffix = _get_suffix(file.filename)
    tmp_path = _save_tmp(await file.read(), suffix)

    try:
        rows, meta = parse_estimate(tmp_path, parser_profile=parser_profile)
    except NeedsMappingError as e:
        # Legacy column-mapping flow (Excel auto, low confidence) — keep as-is.
        raise HTTPException(
            status_code=422,
            detail={
                "needs_mapping": True,
                "filename":      e.filename,
                "sheet":         e.sheet,
                "preview_rows":  e.preview_rows,
                "col_count":     e.col_count,
                "tmp_path":      tmp_path,
            },
        )
    except ParserProfileNotImplemented as e:
        _cleanup_tmp(tmp_path)
        raise HTTPException(400, {"detail": "Parser profile is not implemented yet",
                                  "parser_profile": e.parser_profile})
    except ValueError as e:
        _cleanup_tmp(tmp_path)
        raise HTTPException(400, str(e))

    if meta.get("format") in (FORMAT_SCAN, FORMAT_UNKNOWN) or not rows:
        _cleanup_tmp(tmp_path)
        raise HTTPException(422, "Не удалось распознать строки сметы в выбранном формате.")

    rows, subtotal_rows = _split_work_and_subtotal_rows(rows)
    rows, inactive_catalog_rows_count = _filter_unselected_catalog_rows(rows, meta)
    preview = _compute_preview(rows, subtotal_rows, meta)
    preview["inactive_catalog_rows_count"] = inactive_catalog_rows_count
    grouped = _build_preview_groups(rows)
    flat_rows = [_row_preview_dict(r, index=i) for i, r in enumerate(rows[:MAX_PREVIEW_GROUP_ROWS])]
    suggestions = None
    if not hierarchy_selection and hierarchy_suggestions:
        suggestions = hierarchy_suggestions(
            _sample_texts_for_suggestions(rows),
            estimate_type_id=suggestion_estimate_type_id,
            limit=3,
        )

    warnings: list[str] = []
    if preview["difference_reason"]:
        warnings.append(preview["difference_reason"])
    if grouped["no_section_count"]:
        warnings.append(f"Есть строки без раздела: {grouped['no_section_count']}.")
    if preview.get("inactive_catalog_rows_count"):
        warnings.append(
            f"Исключены невыбранные позиции каталога: {preview['inactive_catalog_rows_count']}."
        )

    preview_id = await save_preview_session({
        "project_id":     str(project_id),
        "user_id":        str(user_id),
        "tmp_path":       tmp_path,
        "filename":       file.filename,
        "parser_profile": meta.get("parser_profile", parser_profile),
        "build_gantt":    bool(build_gantt),
        "estimate_kind":  estimate_kind,
        "start_date":     str(start_date),
        "workers":        workers,
        "complex_mode":   complex_mode,
        "clarification_answers": clarification_answers,
        "hierarchy_selection": hierarchy_selection,
        "type_breakdown": preview["type_breakdown"],
        "strategy":       meta.get("strategy"),
        "detected_format": meta.get("format"),
        "confidence":     meta.get("confidence"),
    })

    return {
        "preview_id":     preview_id,
        "filename":       file.filename,
        "parser_profile": meta.get("parser_profile", parser_profile),
        "detected_format": meta.get("format"),
        "strategy":       meta.get("strategy"),
        "confidence":     meta.get("confidence"),
        "hierarchy_selection": hierarchy_selection,
        "hierarchy_suggestions": suggestions,
        "groups":         grouped["groups"],
        "rows":           flat_rows,
        "truncated":      grouped["truncated"],
        "no_section_count": grouped["no_section_count"],
        "warnings":       warnings,
        **preview,
    }


async def confirm_upload_job(
    preview: dict,
    build_gantt: bool | None,
    db: AsyncSession,
    edits: dict | None = None,
) -> Job:
    """Start the real import job from a (already consumed) preview session."""
    tmp_path = preview.get("tmp_path")
    if not tmp_path or not os.path.exists(tmp_path):
        raise HTTPException(404, "Временный файл не найден или устарел. Загрузите файл заново.")

    effective_gantt = preview.get("build_gantt", True) if build_gantt is None else bool(build_gantt)

    return await _create_and_run_job(
        tmp_path    = tmp_path,
        filename    = preview.get("filename") or os.path.basename(tmp_path),
        project_id  = preview["project_id"],
        user_id     = preview["user_id"],
        start_date  = date.fromisoformat(preview["start_date"]),
        workers     = int(preview["workers"]),
        estimate_kind = int(preview["estimate_kind"]),
        complex_mode  = bool(preview.get("complex_mode")),
        clarification_answers = preview.get("clarification_answers"),
        hierarchy_selection = preview.get("hierarchy_selection"),
        db          = db,
        parser_profile = preview.get("parser_profile", "auto"),
        build_gantt = effective_gantt,
        edits       = edits,
    )


def _cleanup_tmp(tmp_path: str | None) -> None:
    if tmp_path and os.path.exists(tmp_path):
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# ОБЩИЙ СОЗДАТЕЛЬ JOB
# ─────────────────────────────────────────────────────────────────────────────

async def _create_and_run_job(
    tmp_path:    str,
    filename:    str,
    project_id:  str,
    user_id:     str,
    start_date:  date,
    workers:     int,
    estimate_kind: int,
    complex_mode: bool,
    clarification_answers: dict | None,
    hierarchy_selection: dict | None,
    db:          AsyncSession,
    col_mapping: dict[int, str] | None = None,
    sheet:       str | None = None,
    parser_profile: str = "auto",
    build_gantt: bool = True,
    edits:       dict | None = None,
) -> Job:
    job = Job(
        id         = str(uuid4()),
        type       = "estimate_upload",
        status     = "pending",
        project_id = project_id,
        created_by = user_id,
        input      = {
            "filename":    filename,
            "tmp_path":    tmp_path,
            "start_date":  str(start_date),
            "workers":     workers,
            "estimate_kind": estimate_kind,
            "complex_mode": complex_mode,
            "clarification_answers": clarification_answers,
            "hierarchy_selection": hierarchy_selection,
            "col_mapping": col_mapping,   # None = авто
            "sheet":       sheet,
            "parser_profile": parser_profile,
            "build_gantt": build_gantt,
            "edits":       edits,
        },
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    asyncio.create_task(_process_upload(job.id))
    return job


# ─────────────────────────────────────────────────────────────────────────────
# ФОНОВАЯ ОБРАБОТКА
# ─────────────────────────────────────────────────────────────────────────────

async def _set_job_progress(job: Job, db: AsyncSession, message: str) -> None:
    job.result = {"_progress": message}
    await db.commit()


async def _process_upload(job_id: str) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if not job:
            return

        tmp_path = job.input.get("tmp_path")
        job.status     = "processing"
        job.started_at = datetime.utcnow()
        await _set_job_progress(job, db, "Создаём задачу импорта…")

        try:
            start_date  = date.fromisoformat(job.input["start_date"])
            workers     = int(job.input["workers"])
            estimate_kind = int(job.input["estimate_kind"])
            complex_mode = bool(job.input.get("complex_mode"))
            clarification_answers = job.input.get("clarification_answers")
            hierarchy_selection = (
                job.input.get("hierarchy_selection")
                if isinstance(job.input.get("hierarchy_selection"), dict)
                else {}
            )
            col_mapping = job.input.get("col_mapping")   # None → авто
            sheet       = job.input.get("sheet")
            parser_profile = job.input.get("parser_profile", "auto")
            build_gantt = bool(job.input.get("build_gantt", True))
            edits = job.input.get("edits")

            # ── 1. Парсим и классифицируем файл (ДО любого удаления старой сметы)
            # CPU-bound Excel parsing and taxonomy matching must not block the
            # FastAPI event loop; otherwise the "job created" response and polls
            # can appear stuck until this phase finishes.
            await _set_job_progress(job, db, "Парсим файл и классифицируем строки сметы…")
            rows, subtotal_rows, meta = await run_in_threadpool(
                _parse_upload_rows_for_import,
                tmp_path,
                col_mapping,
                sheet,
                parser_profile,
                edits,
                hierarchy_selection,
            )

            # ── 2. Парсинг успешен — теперь безопасно заменить старую смету ───
            #     (перенос soft-replace ПОСЛЕ парсинга: ошибка парсера больше не
            #      уничтожает прежнюю смету проекта).
            await _set_job_progress(job, db, f"Сохраняем {len(rows)} строк сметы…")
            if not complex_mode:
                await _soft_replace_project_estimates(job.project_id, db)

            preview_stats = _compute_preview(rows, subtotal_rows, meta)
            batch = EstimateBatch(
                id=str(uuid4()),
                project_id=job.project_id,
                name=_make_batch_name(job.input.get("filename")),
                estimate_kind=estimate_kind,
                start_date=start_date,
                workers_count=workers,
                hours_per_day=DEFAULT_HOURS_PER_DAY,
                source_filename=job.input.get("filename"),
                estimate_type_id=hierarchy_selection.get("estimate_type_id"),
                estimate_type_title=hierarchy_selection.get("estimate_type_title"),
                estimate_type_number=hierarchy_selection.get("estimate_type_number"),
                project_variant_id=hierarchy_selection.get("project_variant_id"),
                project_variant_title=hierarchy_selection.get("project_variant_title"),
                project_variant_number=hierarchy_selection.get("project_variant_number"),
                taxonomy_dictionary_version=hierarchy_selection.get("taxonomy_dictionary_version"),
                clarification_answers=clarification_answers,
                parser_profile=parser_profile,
                import_meta={
                    "parser_profile":   parser_profile,
                    "detected_format":  meta.get("format"),
                    "strategy":         meta.get("strategy"),
                    "confidence":       meta.get("confidence"),
                    "declared_totals":  meta.get("declared_totals"),
                    "type_breakdown":   preview_stats["type_breakdown"],
                    "computed_work_total": preview_stats["computed_work_total"],
                    "computed_material_total": preview_stats["computed_material_total"],
                    "computed_total_without_vat": preview_stats["computed_total_without_vat"],
                    "computed_vat_total": preview_stats["computed_vat_total"],
                    "computed_total_with_vat": preview_stats["computed_total_with_vat"],
                    "computed_total_all_rows": preview_stats["computed_total_all_rows"],
                    "declared_total":   preview_stats["declared_total"],
                    "declared_vat": preview_stats["declared_vat"],
                    "declared_vat_rate": preview_stats["declared_vat_rate"],
                    "declared_total_with_vat": preview_stats["declared_total_with_vat"],
                    "difference":       preview_stats["difference"],
                    "difference_with_vat": preview_stats["difference_with_vat"],
                    "difference_reason": preview_stats["difference_reason"],
                    "unknown_count":    preview_stats["unknown_count"],
                    "inactive_catalog_rows_count": meta.get("inactive_catalog_rows_count", 0),
                    "active_estimate_rows_count": meta.get("active_estimate_rows_count", len(rows)),
                    "catalog_like_excel": bool(meta.get("catalog_like_excel", False)),
                },
            )
            db.add(batch)
            await db.flush()

            # ── 3. Сохраняем estimates ────────────────────────────────────────
            estimates = []
            for i, row in enumerate(rows):
                raw = row.raw_data if isinstance(row.raw_data, dict) else {}
                est = Estimate(
                    id          = str(uuid4()),
                    project_id  = job.project_id,
                    estimate_batch_id = batch.id,
                    section     = row.section,
                    work_name   = row.work_name,
                    unit        = row.unit,
                    quantity    = row.quantity,
                    unit_price  = row.unit_price,
                    total_price = row.total_price,
                    materials   = getattr(row, "materials", None) or None,
                    row_order   = i,
                    raw_data    = raw,
                    work_section_code = raw.get("work_section_code"),
                    work_section_name = raw.get("work_section_name"),
                    work_subtype_code = raw.get("work_subtype_code") or raw.get("subtype_code"),
                    work_subtype_name = raw.get("work_subtype_name") or raw.get("subtype_name"),
                    estimate_type_id = raw.get("estimate_type_id"),
                    estimate_type_number = raw.get("estimate_type_number"),
                    project_variant_id = raw.get("project_variant_id"),
                    project_variant_number = raw.get("project_variant_number"),
                    canonical_stage_id = raw.get("canonical_stage_id"),
                    work_stage_number = raw.get("work_stage_number"),
                    work_stage_title = raw.get("work_stage_title"),
                    stage_occurrence_index = raw.get("stage_occurrence_index"),
                    stage_occurrence_label = raw.get("stage_occurrence_label"),
                    stage_options_mode = raw.get("stage_options_mode"),
                    stage_option_id = raw.get("stage_option_id"),
                    stage_option_title = raw.get("stage_option_title"),
                    section_id = raw.get("section_id"),
                    subtype_id = raw.get("subtype_id"),
                    row_role = raw.get("row_role"),
                    parent_row_id = raw.get("parent_row_id"),
                    inherited_from_row_id = raw.get("inherited_from_row_id"),
                    stage_confidence = raw.get("stage_confidence"),
                    work_type_confidence = raw.get("work_type_confidence"),
                    autofill_enabled = raw.get("autofill_enabled"),
                    needs_review = bool(raw.get("needs_review")),
                    review_reason = raw.get("review_reason"),
                    stage_match_type = raw.get("stage_match_type"),
                    stage_match_score_json = raw.get("stage_match_score_json"),
                    work_type_match_score_json = raw.get("work_type_match_score_json"),
                    classification_score = raw.get("classification_score"),
                    classification_confidence = raw.get("classification_confidence"),
                    classification_needs_review = bool(raw.get("classification_needs_review")),
                    classification_source = raw.get("classification_source"),
                    classification_candidates = raw.get("classification_candidates"),
                    classification_matched_terms = raw.get("classification_matched_terms"),
                    operator_review_required = bool(raw.get("operator_review_required")),
                    operator_review_status = raw.get("operator_review_status"),
                    operator_review_reason = raw.get("operator_review_reason"),
                    dictionary_version = raw.get("dictionary_version"),
                    prompt_version = raw.get("prompt_version"),
                    manual_override = bool(raw.get("manual_override")),
                )
                db.add(est)
                estimates.append(est)

            await db.flush()
            row_id_by_order = {int(est.row_order): est.id for est in estimates if est.row_order is not None}
            for est in estimates:
                raw = est.raw_data if isinstance(est.raw_data, dict) else {}
                parent_order = raw.get("parent_row_order")
                inherited_order = raw.get("inherited_from_row_order")
                if parent_order is not None:
                    try:
                        est.parent_row_id = row_id_by_order.get(int(parent_order))
                        raw["parent_row_id"] = est.parent_row_id
                    except (TypeError, ValueError):
                        pass
                if inherited_order is not None:
                    try:
                        est.inherited_from_row_id = row_id_by_order.get(int(inherited_order))
                        raw["inherited_from_row_id"] = est.inherited_from_row_id
                    except (TypeError, ValueError):
                        pass
                est.raw_data = raw

            # Гант строится отдельным действием со страницы сметы.

            # The parser stores materials inside Estimate.materials, therefore
            # the project total must include nested materials exactly once.
            total_price = preview_stats["computed_total_without_vat"]
            declared_total_price = preview_stats["declared_total"]
            subtotal_difference = preview_stats["difference"]

            # ── unknown-строки: импорт не блокируем, в Гант пойдут только work ─
            unknown_count = preview_stats["unknown_count"]
            no_section_count = sum(1 for r in rows if not r.section)
            warnings: list[str] = []
            if unknown_count:
                warnings.append(
                    f"Не классифицировано строк: {unknown_count}. "
                    "Они сохранены в смете, но не попадут в Гант — проверьте их тип."
                )
            if no_section_count:
                warnings.append(f"Есть строки без раздела: {no_section_count}.")
            if preview_stats["difference_reason"]:
                warnings.append(preview_stats["difference_reason"])

            job.status = "done"
            job.result = {
                "estimates_count":   len(estimates),
                "gantt_tasks_count": 0,
                "estimate_batch_id": batch.id,
                "estimate_batch_name": batch.name,
                "estimate_kind": estimate_kind,
                "estimate_type_id": hierarchy_selection.get("estimate_type_id"),
                "estimate_type_title": hierarchy_selection.get("estimate_type_title"),
                "project_variant_id": hierarchy_selection.get("project_variant_id"),
                "project_variant_title": hierarchy_selection.get("project_variant_title"),
                "taxonomy_dictionary_version": hierarchy_selection.get("taxonomy_dictionary_version"),
                "complex_mode": complex_mode,
                "parser_profile": parser_profile,
                "build_gantt": build_gantt,
                "strategy":          meta.get("strategy"),
                "confidence":        meta.get("confidence"),
                "total_price":       total_price,
                "type_breakdown":    preview_stats["type_breakdown"],
                "unknown_count":     unknown_count,
                "ignored_subtotal_rows_count": len(subtotal_rows),
                "declared_total_price": declared_total_price,
                "declared_vat": preview_stats["declared_vat"],
                "declared_vat_rate": preview_stats["declared_vat_rate"],
                "declared_total_with_vat": preview_stats["declared_total_with_vat"],
                "computed_work_total": preview_stats["computed_work_total"],
                "computed_material_total": preview_stats["computed_material_total"],
                "computed_vat_total": preview_stats["computed_vat_total"],
                "computed_total_with_vat": preview_stats["computed_total_with_vat"],
                "subtotal_difference": subtotal_difference,
                "subtotal_rows": subtotal_rows[:50],
                "warnings": warnings,
            }

        except Exception as exc:
            job.status = "failed"
            job.result = {"error": str(exc)}

        finally:
            job.finished_at = datetime.utcnow()
            await db.commit()

            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


# ─────────────────────────────────────────────────────────────────────────────
# СТАТУС JOB
# ─────────────────────────────────────────────────────────────────────────────

async def get_job(job_id: str, db: AsyncSession) -> Job:
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job не найден")
    return job


async def build_gantt_for_estimate_batch(
    project_id: str,
    estimate_batch_id: str,
    db: AsyncSession,
    start_date: date | None = None,
) -> dict:
    batch = await db.get(EstimateBatch, estimate_batch_id)
    if not batch or batch.project_id != project_id or batch.deleted_at:
        raise HTTPException(404, "Блок сметы не найден")

    effective_start_date = start_date or batch.start_date or date.today()
    workers = int(batch.workers_count or 1)
    hours_per_day = float(batch.hours_per_day or DEFAULT_HOURS_PER_DAY)

    estimates = list(
        await db.scalars(
            select(Estimate)
            .where(Estimate.project_id == project_id)
            .where(Estimate.estimate_batch_id == estimate_batch_id)
            .where(Estimate.deleted_at == None)
            .order_by(Estimate.row_order, Estimate.created_at, Estimate.id)
        )
    )
    estimates = [estimate for estimate in estimates if _estimate_item_type(estimate) == "work"]
    if not estimates:
        raise HTTPException(422, "В выбранном блоке нет строк сметы для построения Ганта")

    existing_gantt_ids = list(
        await db.scalars(
            select(GanttTask.id)
            .where(GanttTask.project_id == project_id)
            .where(GanttTask.estimate_batch_id == estimate_batch_id)
            .where(GanttTask.deleted_at == None)
        )
    )
    if existing_gantt_ids:
        await db.execute(
            delete(TaskDependency).where(
                or_(
                    TaskDependency.task_id.in_(existing_gantt_ids),
                    TaskDependency.depends_on.in_(existing_gantt_ids),
                )
            )
        )
        await db.execute(
            GanttTask.__table__.update()
            .where(GanttTask.id.in_(existing_gantt_ids))
            .values(deleted_at=datetime.utcnow())
        )
        await db.flush()

    builder = GanttBuilder()
    task_dtos = builder.build(
        project_id=project_id,
        estimates=estimates,
        start_date=effective_start_date,
        workers=workers,
        hours_per_day=hours_per_day,
        fer_hours_by_table_id=await _load_fer_human_hours_by_table_ids(estimates, db),
    )
    task_dtos = _wrap_batch_tasks(
        batch_id=batch.id,
        batch_name=batch.name,
        start_date=effective_start_date,
        task_dtos=task_dtos,
    )
    row_order_offset = await _get_row_order_offset(project_id, db)
    task_dtos = _shift_row_order(task_dtos, row_order_offset)

    for dto in task_dtos:
        db.add(
            GanttTask(
                id=dto.id,
                project_id=dto.project_id,
                estimate_batch_id=batch.id,
                estimate_id=dto.estimate_id,
                parent_id=dto.parent_id,
                name=dto.name,
                start_date=dto.start_date,
                working_days=dto.working_days,
                workers_count=dto.workers_count,
                labor_hours=dto.labor_hours,
                hours_per_day=dto.hours_per_day,
                progress=0,
                is_group=dto.is_group,
                type=dto.type,
                color=dto.color,
                row_order=dto.row_order,
            )
        )

    # ── Зависимости по графу предшествования (subtype_code) ───────────────────
    deps_count = await _build_precedence_dependencies(task_dtos, estimates, db)

    batch.start_date = effective_start_date
    await db.flush()
    return {
        "id": batch.id,
        "start_date": str(effective_start_date),
        "gantt_tasks_count": len(task_dtos),
        "dependencies_count": deps_count,
    }


async def _build_precedence_dependencies(task_dtos, estimates, db: AsyncSession) -> int:
    """Соединить задачи Ганта по графу предшествования: подтип-предшественник →
    подтип-последователь. Возвращает число созданных связей."""
    from app.services.work_taxonomy_service import (
        build_precedence_dependencies,
        load_precedence,
    )

    subtype_by_estimate_id: dict[str, str] = {}
    for est in estimates:
        raw = est.raw_data if isinstance(est.raw_data, dict) else {}
        code = est.work_subtype_code or raw.get("work_subtype_code") or raw.get("subtype_code")
        if code:
            subtype_by_estimate_id[est.id] = code

    if not subtype_by_estimate_id:
        return 0

    # subtype_code → [leaf task_id] в порядке row_order
    leaf_dtos = sorted(
        (d for d in task_dtos if d.estimate_id and d.estimate_id in subtype_by_estimate_id),
        key=lambda d: float(d.row_order),
    )
    subtype_to_task_ids: dict[str, list[str]] = {}
    for dto in leaf_dtos:
        subtype_to_task_ids.setdefault(subtype_by_estimate_id[dto.estimate_id], []).append(dto.id)

    precedence = await load_precedence(db)
    edges = build_precedence_dependencies(subtype_to_task_ids, precedence)
    for successor_task_id, predecessor_task_id, lag_days in edges:
        db.add(TaskDependency(
            task_id=successor_task_id,
            depends_on=predecessor_task_id,
            lag_days=lag_days,
        ))
    return len(edges)


async def _load_fer_human_hours_by_table_ids(
    estimates: list[Estimate],
    db: AsyncSession,
) -> dict[int, float]:
    table_ids = sorted({int(estimate.fer_table_id) for estimate in estimates if getattr(estimate, "fer_table_id", None) is not None})
    if not table_ids:
        return {}

    stmt = text(
        """
        SELECT
            table_id,
            COALESCE(SUM(h_hour), 0)::double precision AS human_hours
        FROM fer.fer_rows
        WHERE table_id IN :table_ids
        GROUP BY table_id
        """
    ).bindparams(bindparam("table_ids", expanding=True))
    result = await db.execute(stmt, {"table_ids": table_ids})
    return {
        int(row["table_id"]): float(row["human_hours"])
        for row in result.mappings().all()
    }


# ─────────────────────────────────────────────────────────────────────────────
# УТИЛИТЫ
# ─────────────────────────────────────────────────────────────────────────────

def _get_suffix(filename: str) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):  return ".pdf"
    if name.endswith(".xls"):  return ".xls"
    return ".xlsx"


def _save_tmp(contents: bytes, suffix: str) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="estimate_")
    try:
        tmp.write(contents)
    finally:
        tmp.close()
    return tmp.name


async def _soft_replace_project_estimates(project_id: str, db: AsyncSession) -> None:
    gantt_ids = list(
        await db.scalars(
            select(GanttTask.id)
            .where(GanttTask.project_id == project_id)
            .where(GanttTask.deleted_at == None)
        )
    )
    if gantt_ids:
        await db.execute(
            delete(TaskDependency)
            .where(TaskDependency.task_id.in_(gantt_ids))
        )

    now = datetime.utcnow()
    await db.execute(
        GanttTask.__table__.update()
        .where(GanttTask.project_id == project_id)
        .where(GanttTask.deleted_at == None)
        .values(deleted_at=now)
    )
    await db.execute(
        Estimate.__table__.update()
        .where(Estimate.project_id == project_id)
        .where(Estimate.deleted_at == None)
        .values(deleted_at=now)
    )
    await db.execute(
        EstimateBatch.__table__.update()
        .where(EstimateBatch.project_id == project_id)
        .where(EstimateBatch.deleted_at == None)
        .values(deleted_at=now)
    )
    await db.flush()


def _make_batch_name(filename: str | None) -> str:
    if not filename:
        return "Смета"
    stem, _ = os.path.splitext(os.path.basename(filename))
    return stem.strip() or "Смета"


def _split_work_and_subtotal_rows(rows: list) -> tuple[list, list[dict]]:
    work_rows = []
    subtotal_rows = []
    for row in rows:
        if is_subtotal_row(row):
            raw = row.raw_data if isinstance(getattr(row, "raw_data", None), dict) else {}
            raw.update(
                {
                    "row_role": "total",
                    "skip_taxonomy": True,
                    "skip_stage_classifier": True,
                    "classification_source": "subtotal_filter",
                    "classification_reason": "subtotal_or_total_row",
                    "operator_review_required": False,
                }
            )
            row.raw_data = raw
            subtotal_rows.append(describe_subtotal_row(row))
            continue
        work_rows.append(row)
    return work_rows, subtotal_rows


def _declared_total_price(subtotal_rows: list[dict]) -> float | None:
    for subtotal in reversed(subtotal_rows):
        value = subtotal.get("total_price")
        if value is not None:
            return _money_float(value)
    return None


async def _get_row_order_offset(project_id: str, db: AsyncSession) -> float:
    current_max = await db.scalar(
        select(func.max(GanttTask.row_order))
        .where(GanttTask.project_id == project_id)
        .where(GanttTask.deleted_at == None)
    )
    return float(current_max or 0) + 1000.0


def _shift_row_order(task_dtos: list[GanttTaskDTO], offset: float) -> list[GanttTaskDTO]:
    if offset <= 1000:
        return task_dtos
    return [
        GanttTaskDTO(
            id=dto.id,
            project_id=dto.project_id,
            estimate_id=dto.estimate_id,
            parent_id=dto.parent_id,
            name=dto.name,
            start_date=dto.start_date,
            working_days=dto.working_days,
            workers_count=dto.workers_count,
            labor_hours=dto.labor_hours,
            hours_per_day=dto.hours_per_day,
            is_group=dto.is_group,
            type=dto.type,
            color=dto.color,
            row_order=float(dto.row_order) + offset,
        )
        for dto in task_dtos
    ]


def _wrap_batch_tasks(
    batch_id: str,
    batch_name: str,
    start_date: date,
    task_dtos: list[GanttTaskDTO],
) -> list[GanttTaskDTO]:
    if not task_dtos:
        return task_dtos

    root_id = str(uuid4())
    min_order = min(float(dto.row_order) for dto in task_dtos)
    max_end = max(task_end_date(dto.start_date, dto.working_days) for dto in task_dtos)
    batch_days = max(1, working_days_between(start_date, max_end) + 1)

    wrapped: list[GanttTaskDTO] = [
        GanttTaskDTO(
            id=root_id,
            project_id=task_dtos[0].project_id,
            estimate_id=None,
            parent_id=None,
            name=batch_name,
            start_date=start_date,
            working_days=batch_days,
            workers_count=None,
            labor_hours=None,
            hours_per_day=8,
            is_group=True,
            type="project",
            color="#0f172a",
            row_order=min_order - 10.0,
        )
    ]

    for dto in task_dtos:
        parent_id = root_id if dto.parent_id is None else dto.parent_id
        wrapped.append(
            GanttTaskDTO(
                id=dto.id,
                project_id=dto.project_id,
                estimate_id=dto.estimate_id,
                parent_id=parent_id,
                name=dto.name,
                start_date=dto.start_date,
                working_days=dto.working_days,
                workers_count=dto.workers_count,
                labor_hours=dto.labor_hours,
                hours_per_day=dto.hours_per_day,
                is_group=dto.is_group,
                type=dto.type,
                color=dto.color,
                row_order=float(dto.row_order),
            )
        )

    return wrapped
