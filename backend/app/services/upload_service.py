# backend/app/services/upload_service.py
"""
Асинхронный upload сметы.

Поток:
  POST /estimates/upload
    → файл сохраняется во временный файл на диске
    → создаётся Job(status=pending)
    → asyncio.create_task запускает обработку в фоне
    → клиент получает 202 + job_id немедленно

  Обработка (_process_upload):
    → Job.status = "processing"
    → проверка дублей: удаляем старые estimates + gantt_tasks проекта
    → парсим Excel из temp-файла
    → сохраняем estimates, gantt_tasks, task_dependencies
    → пересчитываем даты
    → Job.status = "done" | "failed"
    → temp-файл удаляется в любом случае (finally)
"""
from __future__ import annotations

import asyncio
import io
import os
import tempfile
from datetime import date, datetime
from uuid import uuid4

from fastapi import BackgroundTasks, UploadFile, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models            import Job, GanttTask, Estimate, TaskDependency
from app.services.excel_parser  import ExcelEstimateParser
from app.services.gantt_builder import GanttBuilder


# ── Запуск job ────────────────────────────────────────────────────────────────

async def start_upload_job(
    file:             UploadFile,
    project_id:       str,
    user_id:          str,
    start_date:       date,
    workers:          int,
    background_tasks: BackgroundTasks,
    db:               AsyncSession,
) -> Job:
    """
    Сохраняет файл на диск, создаёт Job, запускает обработку в фоне.
    Возвращает Job немедленно — клиент получает 202 + job_id.
    """
    allowed = (".xlsx", ".xls", ".pdf")
    if not file.filename.lower().endswith(allowed):
        raise HTTPException(400, f"Поддерживаются: {', '.join(allowed)}")

    # Сохраняем во временный файл (delete=False — сами удалим в finally)
    fname = file.filename.lower()
    if fname.endswith(".pdf"):
        suffix = ".pdf"
    elif fname.endswith(".xls"):
        suffix = ".xls"
    else:
        suffix = ".xlsx"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="estimate_")
    try:
        contents = await file.read()
        tmp.write(contents)
        tmp_path = tmp.name
    finally:
        tmp.close()

    job = Job(
        id         = str(uuid4()),
        type       = "estimate_upload",
        status     = "pending",
        project_id = project_id,
        created_by = user_id,
        input      = {
            "filename":   file.filename,
            "tmp_path":   tmp_path,       # путь к temp-файлу
            "start_date": str(start_date),
            "workers":    workers,
        },
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # asyncio.create_task надёжнее BackgroundTasks для async функций:
    # задача продолжает работать даже после отправки ответа клиенту.
    # В продакшне — заменить на Celery task.
    asyncio.create_task(_process_upload(job.id))

    return job


# ── Фоновая обработка ─────────────────────────────────────────────────────────

async def _process_upload(job_id: str) -> None:
    """
    Выполняется асинхронно после ответа 202.
    Temp-файл удаляется в finally — в любом случае (done или failed).
    """
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
            start_date = date.fromisoformat(job.input["start_date"])
            workers    = int(job.input["workers"])

            # ── 1. Удаляем дубли ─────────────────────────────────────────────
            # Если смета уже загружалась — чистим старые данные проекта.
            # Порядок важен: сначала gantt (FK на estimates), потом estimates.
            existing_estimates = await db.scalars(
                select(Estimate)
                .where(Estimate.project_id == job.project_id)
                .where(Estimate.deleted_at == None)
            )
            existing_ids = [e.id for e in existing_estimates]

            if existing_ids:
                # Удаляем зависимости задач проекта
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

                # Мягкое удаление старых задач и смет
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

            # ── 2. Парсим файл (Excel или PDF) ──────────────────────────────
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
                raise ValueError("Не удалось распознать строки сметы. "
                                 "Убедитесь что файл содержит колонки: "
                                 "наименование, количество, единица, сумма.")

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

            # Удаляем temp-файл в любом случае
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass  # не критично если не удалился


# ── Статус job ────────────────────────────────────────────────────────────────

async def get_job(job_id: str, db: AsyncSession) -> Job:
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job не найден")
    return job
