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
    → сохраняем estimates, gantt_tasks, task_dependencies
    → пересчитываем даты
    → Job.status = "done" | "failed"
    → temp-файл удаляется в любом случае (finally)
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import date, datetime
from uuid import uuid4

from fastapi import UploadFile, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models                      import Job, GanttTask, Estimate, TaskDependency
from app.services.excel_parser       import ExcelEstimateParser, NeedsMappingError
from app.services.gantt_builder      import GanttBuilder


_parser = ExcelEstimateParser()

# Сколько времени (сек) храним tmp-файл в ожидании подтверждения маппинга
# (после этого времени файл не будет найден и вернётся 404)
TMP_TTL_SECONDS = 3600


# ─────────────────────────────────────────────────────────────────────────────
# ЗАПУСК JOB (авто-парсинг)
# ─────────────────────────────────────────────────────────────────────────────

async def start_upload_job(
    file:             UploadFile,
    project_id:       str,
    user_id:          str,
    start_date:       date,
    workers:          int,
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
        db          = db,
        col_mapping = col_mapping,
        sheet       = sheet,
    )


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
    db:          AsyncSession,
    col_mapping: dict[int, str] | None = None,
    sheet:       str | None = None,
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
            "col_mapping": col_mapping,   # None = авто
            "sheet":       sheet,
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
            col_mapping = job.input.get("col_mapping")   # None → авто
            sheet       = job.input.get("sheet")

            # ── 1. Удаляем дубли ─────────────────────────────────────────────
            existing_estimates = await db.scalars(
                select(Estimate)
                .where(Estimate.project_id == job.project_id)
                .where(Estimate.deleted_at == None)
            )
            existing_ids = [e.id for e in existing_estimates]

            if existing_ids:
                gantt_ids_result = await db.scalars(
                    select(GanttTask.id)
                    .where(GanttTask.project_id == job.project_id)
                    .where(GanttTask.deleted_at == None)
                )
                gantt_ids = list(gantt_ids_result)
                if gantt_ids:
                    await db.execute(
                        delete(TaskDependency)
                        .where(TaskDependency.task_id.in_(gantt_ids))
                    )

                now = datetime.utcnow()
                await db.execute(
                    GanttTask.__table__.update()
                    .where(GanttTask.project_id == job.project_id)
                    .where(GanttTask.deleted_at == None)
                    .values(deleted_at=now)
                )
                await db.execute(
                    Estimate.__table__.update()
                    .where(Estimate.project_id == job.project_id)
                    .where(Estimate.deleted_at == None)
                    .values(deleted_at=now)
                )
                await db.flush()

            # ── 2. Парсим файл ────────────────────────────────────────────────
            if col_mapping is not None:
                # Ручной маппинг: ключи из JSON пришли как строки → конвертим
                int_mapping = {int(k): v for k, v in col_mapping.items()}
                rows, meta = _parser.parse_mapped(tmp_path, int_mapping, sheet=sheet)
            else:
                from app.services.parser_factory import parse_estimate, FORMAT_SCAN, FORMAT_UNKNOWN
                rows, meta = parse_estimate(tmp_path)
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

            # ── 3. Сохраняем estimates ────────────────────────────────────────
            estimates = []
            for i, row in enumerate(rows):
                est = Estimate(
                    id          = str(uuid4()),
                    project_id  = job.project_id,
                    section     = row.section,
                    work_name   = row.work_name,
                    unit        = row.unit,
                    quantity    = row.quantity,
                    unit_price  = row.unit_price,
                    total_price = row.total_price,
                    row_order   = i,
                    raw_data    = row.raw_data,
                )
                db.add(est)
                estimates.append(est)

            await db.flush()

            # ── 4. Строим Ганта ───────────────────────────────────────────────
            builder   = GanttBuilder()
            task_dtos = builder.build(
                project_id = job.project_id,
                estimates  = estimates,
                start_date = start_date,
                workers    = workers,
            )

            for dto in task_dtos:
                db.add(GanttTask(
                    id           = dto.id,
                    project_id   = dto.project_id,
                    estimate_id  = dto.estimate_id,
                    parent_id    = dto.parent_id,
                    name         = dto.name,
                    start_date   = dto.start_date,
                    working_days = dto.working_days,
                    progress     = 0,
                    is_group     = dto.is_group,
                    type         = dto.type,
                    color        = dto.color,
                    row_order    = dto.row_order,
                ))

            await db.flush()

            # ── 5. Зависимости между разделами ───────────────────────────────
            for pred_id, succ_id in builder.get_dependencies(task_dtos):
                db.add(TaskDependency(
                    task_id    = succ_id,
                    depends_on = pred_id,
                ))

            # ── 6. Пересчёт дат ──────────────────────────────────────────────
            from app.services.gantt_service import resolve_project_dates
            await resolve_project_dates(job.project_id, db)

            job.status = "done"
            job.result = {
                "estimates_count":   len(estimates),
                "gantt_tasks_count": len(task_dtos),
                "strategy":          meta.get("strategy"),
                "confidence":        meta.get("confidence"),
                "total_price":       sum(
                    float(e.total_price) for e in estimates if e.total_price
                ),
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