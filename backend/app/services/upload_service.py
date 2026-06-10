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
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from fastapi import UploadFile, HTTPException
from sqlalchemy import bindparam, select, delete, func, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

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
        db          = db,
        col_mapping = col_mapping,
        sheet       = sheet,
    )


# ─────────────────────────────────────────────────────────────────────────────
# PREVIEW (parse to tmp, no DB writes) + CONFIRM
# ─────────────────────────────────────────────────────────────────────────────

_ITEM_TYPE_ORDER = ("work", "material", "mechanism", "overhead", "unknown")
_LOW_CONFIDENCE = 0.7


MAX_PREVIEW_GROUP_ROWS = 2000
_NO_SECTION = "Без раздела"


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
    return {
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
        "row_hash":    _row_hash(row.section, row.work_name, row.unit, row.quantity, row.total_price),
    }


async def _enrich_work_subtypes(rows: list, db: AsyncSession) -> None:
    """Финальный проход классификации работ по JSON v3.

    Только work-строки получают canonical ``work_subtype_code``. У остальных
    поля типизации очищаются. Запускать ПОСЛЕ правок оператора.
    """
    from app.services.work_taxonomy_service import classify_work

    for row in rows:
        raw = row.raw_data if isinstance(getattr(row, "raw_data", None), dict) else {}
        if isinstance(raw.get("classification_confidence"), (int, float)):
            raw.setdefault("item_type_confidence", raw.get("classification_confidence"))
        row.raw_data = raw
        if resolve_item_type(row) == "work":
            result = classify_work(row.work_name or "", row.section)
            raw.update(result.as_raw_data())
            raw["operator_review_required"] = bool(result.needs_review)
            raw["operator_review_status"] = None
            raw["operator_review_reason"] = result.reason if result.needs_review else None
            continue
        for key in (
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
            "operator_review_required",
            "operator_review_status",
            "operator_review_reason",
            "dictionary_version",
        ):
            raw.pop(key, None)


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


def _material_dict(material: dict) -> dict:
    """A nested ParsedRow.materials entry (Excel «работа+материалы» formats)."""
    return {
        "row_order":   None,
        "section":     None,
        "item_type":   "material",
        "name":        material.get("name") or material.get("work_name") or "",
        "spec":        material.get("spec"),
        "unit":        material.get("unit"),
        "quantity":    material.get("quantity") or material.get("qty"),
        "total_price": material.get("total_price") or material.get("total"),
        "confidence":  None,
        "reason":      "nested_material",
    }


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

        g = groups[section]
        item_type = resolve_item_type(row)
        bucket_totals = g["totals"].setdefault(item_type, {"count": 0, "total": 0.0})
        bucket_totals["count"] += 1
        bucket_totals["total"] = round(bucket_totals["total"] + float(row.total_price or 0), 2)

        if rows_emitted >= MAX_PREVIEW_GROUP_ROWS:
            truncated = True
            continue

        entry = _row_preview_dict(row)
        if item_type == "work":
            entry["materials"] = [_material_dict(m) for m in (getattr(row, "materials", None) or [])]
        g[_GROUP_BUCKETS.get(item_type, "unknown")].append(entry)
        rows_emitted += 1

    return {
        "groups": [groups[s] for s in order],
        "truncated": truncated,
        "no_section_count": no_section_count,
    }


def _compute_preview(rows: list, subtotal_rows: list[dict], meta: dict) -> dict:
    breakdown = {t: {"count": 0, "total": 0.0} for t in _ITEM_TYPE_ORDER}
    unknown_rows: list[dict] = []
    low_confidence_rows: list[dict] = []

    for row in rows:
        item_type = resolve_item_type(row)
        bucket = breakdown.setdefault(item_type, {"count": 0, "total": 0.0})
        bucket["count"] += 1
        bucket["total"] += float(row.total_price or 0)

        raw = getattr(row, "raw_data", None) or {}
        if item_type == "unknown" and len(unknown_rows) < 20:
            unknown_rows.append(_row_preview_dict(row))
        conf = raw.get("item_type_confidence")
        if conf is None and isinstance(raw.get("classification_confidence"), (int, float)):
            conf = raw.get("classification_confidence")
        if conf is not None and conf < _LOW_CONFIDENCE and len(low_confidence_rows) < 20:
            low_confidence_rows.append(_row_preview_dict(row))

    computed_total = round(sum(float(r.total_price or 0) for r in rows), 2)

    declared_total = _declared_total_from_meta(meta) or _declared_total_price(subtotal_rows)
    difference = (
        round(declared_total - computed_total, 2) if declared_total is not None else None
    )
    difference_reason = None
    if difference is not None and abs(difference) > 1:
        difference_reason = (
            "Сумма строк отличается от итоговой суммы сметы. Возможны строки в сводной "
            "без детального листа или расхождение в исходном файле — проверьте перед импортом."
        )

    return {
        "type_breakdown": breakdown,
        "computed_total_all_rows": computed_total,
        "declared_total": declared_total,
        "difference": difference,
        "difference_reason": difference_reason,
        "unknown_count": breakdown.get("unknown", {}).get("count", 0),
        "unknown_rows": unknown_rows,
        "low_confidence_rows": low_confidence_rows,
        "sample_rows": [_row_preview_dict(r) for r in rows[:20]],
        "ignored_subtotal_rows_count": len(subtotal_rows),
        "declared_totals": meta.get("declared_totals"),
    }


def _declared_total_from_meta(meta: dict) -> float | None:
    """Pick the grand total from a parser's declared_totals (PDF), if present."""
    totals = meta.get("declared_totals")
    if not isinstance(totals, list):
        return None
    for kind in ("grand_total", "section_total"):
        values = [t.get("total") for t in totals if t.get("kind") == kind and t.get("total") is not None]
        if values:
            return float(sum(values)) if kind == "section_total" else float(values[-1])
    return None


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
    db:               AsyncSession,
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
    await _enrich_work_subtypes(rows, db)
    preview = _compute_preview(rows, subtotal_rows, meta)
    grouped = _build_preview_groups(rows)
    flat_rows = [_row_preview_dict(r, index=i) for i, r in enumerate(rows[:MAX_PREVIEW_GROUP_ROWS])]

    warnings: list[str] = []
    if preview["difference_reason"]:
        warnings.append(preview["difference_reason"])
    if grouped["no_section_count"]:
        warnings.append(f"Есть строки без раздела: {grouped['no_section_count']}.")

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

async def _process_upload(job_id: str) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if not job:
            return

        tmp_path = job.input.get("tmp_path")
        job.status     = "processing"
        job.started_at = datetime.utcnow()
        await db.commit()

        try:
            start_date  = date.fromisoformat(job.input["start_date"])
            workers     = int(job.input["workers"])
            estimate_kind = int(job.input["estimate_kind"])
            complex_mode = bool(job.input.get("complex_mode"))
            clarification_answers = job.input.get("clarification_answers")
            col_mapping = job.input.get("col_mapping")   # None → авто
            sheet       = job.input.get("sheet")
            parser_profile = job.input.get("parser_profile", "auto")
            build_gantt = bool(job.input.get("build_gantt", True))

            # ── 1. Парсим файл (ДО любого удаления старой сметы) ──────────────
            if col_mapping is not None:
                # Ручной маппинг: ключи из JSON пришли как строки → конвертим
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

            # ── 1b. Правки оператора (шаг 2): смена типа + добавленные строки ──
            #        порядок: split → overrides/added → enrich подтипом.
            rows = _apply_operator_edits(rows, job.input.get("edits"))
            await _enrich_work_subtypes(rows, db)

            # ── 2. Парсинг успешен — теперь безопасно заменить старую смету ───
            #     (перенос soft-replace ПОСЛЕ парсинга: ошибка парсера больше не
            #      уничтожает прежнюю смету проекта).
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
                clarification_answers=clarification_answers,
                parser_profile=parser_profile,
                import_meta={
                    "parser_profile":   parser_profile,
                    "detected_format":  meta.get("format"),
                    "strategy":         meta.get("strategy"),
                    "confidence":       meta.get("confidence"),
                    "declared_totals":  meta.get("declared_totals"),
                    "type_breakdown":   preview_stats["type_breakdown"],
                    "computed_total_all_rows": preview_stats["computed_total_all_rows"],
                    "declared_total":   preview_stats["declared_total"],
                    "difference":       preview_stats["difference"],
                    "difference_reason": preview_stats["difference_reason"],
                    "unknown_count":    preview_stats["unknown_count"],
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
                    manual_override = bool(raw.get("manual_override")),
                )
                db.add(est)
                estimates.append(est)

            await db.flush()

            # Гант строится отдельным действием со страницы сметы.

            total_price = sum(
                float(e.total_price) for e in estimates if e.total_price
            )
            declared_total_price = _declared_total_from_meta(meta) or _declared_total_price(subtotal_rows)
            subtotal_difference = (
                round(total_price - declared_total_price, 2)
                if declared_total_price is not None
                else None
            )

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
            subtotal_rows.append(describe_subtotal_row(row))
            continue
        work_rows.append(row)
    return work_rows, subtotal_rows


def _declared_total_price(subtotal_rows: list[dict]) -> float | None:
    for subtotal in reversed(subtotal_rows):
        value = subtotal.get("total_price")
        if value is not None:
            return float(value)
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
