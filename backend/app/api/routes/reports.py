from datetime import date, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps         import get_current_user, require_action, get_project_member, get_db
from app.core.permissions import Action
from app.models           import DailyReport, DailyReportItem, GanttTask, ProjectMember, User
from app.services.gantt_service import update_leaf_progress

router = APIRouter(prefix="/projects/{project_id}", tags=["reports"])


# ── Схемы ─────────────────────────────────────────────────────────────────────

class ReportItemIn(BaseModel):
    task_id:        str
    work_done:      str   = Field(min_length=1)
    volume_done:    float | None = None
    volume_unit:    str | None   = None
    progress_after: int   = Field(ge=0, le=100)
    workers_count:  int | None   = None
    workers_note:   str | None   = None
    materials_used: list[dict]   = []


class ReportIn(BaseModel):
    report_date: date
    summary:     str | None = None
    issues:      str | None = None
    weather:     str | None = None
    items:       list[ReportItemIn] = []


# ── Список отчётов ────────────────────────────────────────────────────────────

@router.get("/reports")
async def list_reports(
    project_id: str,
    from_date:  date | None = Query(default=None),
    to_date:    date | None = Query(default=None),
    member:     ProjectMember = Depends(require_action(Action.VIEW_REPORTS)),
    db:         AsyncSession  = Depends(get_db),
):
    q = select(DailyReport).where(DailyReport.project_id == project_id)
    if from_date:
        q = q.where(DailyReport.report_date >= from_date)
    if to_date:
        q = q.where(DailyReport.report_date <= to_date)
    q = q.order_by(DailyReport.report_date.desc())

    reports = await db.scalars(q)
    result  = []
    for r in reports:
        author = await db.get(User, r.author_id)
        result.append({
            "id":           r.id,
            "report_date":  str(r.report_date),
            "status":       r.status,
            "author":       {"id": author.id, "name": author.name} if author else None,
            "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
            "issues":       r.issues,
        })
    return result


# ── Статус отчётов за сегодня ─────────────────────────────────────────────────

@router.get("/reports/today")
async def reports_today(
    project_id: str,
    member:     ProjectMember = Depends(require_action(Action.VIEW_REPORTS)),
    db:         AsyncSession  = Depends(get_db),
):
    today = date.today()
    foremen = await db.scalars(
        select(ProjectMember)
        .where(ProjectMember.project_id == project_id)
        .where(ProjectMember.role       == "foreman")
    )

    result = []
    for f in foremen:
        user   = await db.get(User, f.user_id)
        report = await db.scalar(
            select(DailyReport)
            .where(DailyReport.project_id  == project_id)
            .where(DailyReport.author_id   == f.user_id)
            .where(DailyReport.report_date == today)
        )
        result.append({
            "foreman":   {"id": user.id, "name": user.name} if user else None,
            "submitted": report is not None and report.status == "submitted",
            "status":    report.status if report else "missing",
            "report_id": report.id     if report else None,
        })

    return {"date": str(today), "foremen": result}


# ── Создать / обновить черновик ───────────────────────────────────────────────

@router.post("/reports", status_code=201)
async def create_or_update_report(
    project_id:   str,
    body:         ReportIn,
    current_user: User          = Depends(get_current_user),
    member:       ProjectMember = Depends(require_action(Action.SUBMIT_REPORT)),
    db:           AsyncSession  = Depends(get_db),
):
    # Один отчёт на прораба в день — upsert
    existing = await db.scalar(
        select(DailyReport)
        .where(DailyReport.project_id  == project_id)
        .where(DailyReport.author_id   == current_user.id)
        .where(DailyReport.report_date == body.report_date)
    )

    if existing and existing.status == "submitted":
        raise HTTPException(409, "Отчёт за этот день уже отправлен")

    if existing:
        report = existing
        # Обновляем общие поля
        report.summary = body.summary
        report.issues  = body.issues
        report.weather = body.weather
        # Удаляем старые строки
        old_items = await db.scalars(
            select(DailyReportItem).where(DailyReportItem.report_id == report.id)
        )
        for item in old_items:
            await db.delete(item)
    else:
        report = DailyReport(
            id          = str(uuid4()),
            project_id  = project_id,
            author_id   = current_user.id,
            report_date = body.report_date,
            summary     = body.summary,
            issues      = body.issues,
            weather     = body.weather,
            status      = "draft",
        )
        db.add(report)
        await db.flush()

    # Добавляем строки отчёта
    for item_in in body.items:
        task = await db.get(GanttTask, item_in.task_id)
        if not task or task.project_id != project_id:
            raise HTTPException(404, f"Задача {item_in.task_id} не найдена в проекте")

        db.add(DailyReportItem(
            id             = str(uuid4()),
            report_id      = report.id,
            task_id        = item_in.task_id,
            work_done      = item_in.work_done,
            volume_done    = item_in.volume_done,
            volume_unit    = item_in.volume_unit,
            progress_after = item_in.progress_after,
            workers_count  = item_in.workers_count,
            workers_note   = item_in.workers_note,
            materials_used = item_in.materials_used,
        ))

    await db.commit()
    return {"id": report.id, "status": report.status}


# ── Отправить финальный отчёт ─────────────────────────────────────────────────

@router.post("/reports/{report_id}/submit")
async def submit_report(
    project_id:   str,
    report_id:    str,
    current_user: User          = Depends(get_current_user),
    member:       ProjectMember = Depends(require_action(Action.SUBMIT_REPORT)),
    db:           AsyncSession  = Depends(get_db),
):
    report = await db.get(DailyReport, report_id)
    if not report or report.project_id != project_id:
        raise HTTPException(404, "Отчёт не найден")
    if report.author_id != current_user.id and member.role not in ("owner", "pm"):
        raise HTTPException(403)
    if report.status == "submitted":
        raise HTTPException(409, "Отчёт уже отправлен")

    items = await db.scalars(
        select(DailyReportItem).where(DailyReportItem.report_id == report_id)
    )

    # Обновляем прогресс задач
    for item in items:
        task = await db.get(GanttTask, item.task_id)
        if task and not task.is_group:
            await update_leaf_progress(task, item.progress_after, current_user.id, db)

    report.status       = "submitted"
    report.submitted_at = datetime.utcnow()
    await db.commit()

    return {"id": report.id, "status": "submitted"}


# ── Принять отчёт (PM) ────────────────────────────────────────────────────────

@router.post("/reports/{report_id}/review")
async def review_report(
    project_id:   str,
    report_id:    str,
    current_user: User          = Depends(get_current_user),
    member:       ProjectMember = Depends(require_action(Action.VIEW_REPORTS)),
    db:           AsyncSession  = Depends(get_db),
):
    if member.role not in ("owner", "pm"):
        raise HTTPException(403, "Только PM или owner может принять отчёт")

    report = await db.get(DailyReport, report_id)
    if not report or report.project_id != project_id:
        raise HTTPException(404)
    if report.status != "submitted":
        raise HTTPException(409, "Можно принять только отправленный отчёт")

    report.status      = "reviewed"
    report.reviewed_by = current_user.id
    report.reviewed_at = datetime.utcnow()
    await db.commit()

    return {"id": report.id, "status": "reviewed"}


# ── Получить один отчёт ───────────────────────────────────────────────────────

@router.get("/reports/{report_id}")
async def get_report(
    project_id: str,
    report_id:  str,
    member:     ProjectMember = Depends(require_action(Action.VIEW)),
    db:         AsyncSession  = Depends(get_db),
):
    report = await db.get(DailyReport, report_id)
    if not report or report.project_id != project_id:
        raise HTTPException(404)

    author = await db.get(User, report.author_id)
    items  = await db.scalars(
        select(DailyReportItem).where(DailyReportItem.report_id == report_id)
    )

    items_out = []
    for item in items:
        task = await db.get(GanttTask, item.task_id)
        items_out.append({
            "id":             item.id,
            "task_id":        item.task_id,
            "task_name":      task.name if task else "—",
            "work_done":      item.work_done,
            "volume_done":    float(item.volume_done) if item.volume_done else None,
            "volume_unit":    item.volume_unit,
            "progress_after": item.progress_after,
            "workers_count":  item.workers_count,
        })

    return {
        "id":           report.id,
        "report_date":  str(report.report_date),
        "status":       report.status,
        "author":       {"id": author.id, "name": author.name} if author else None,
        "summary":      report.summary,
        "issues":       report.issues,
        "weather":      report.weather,
        "items":        items_out,
        "submitted_at": report.submitted_at.isoformat() if report.submitted_at else None,
    }
