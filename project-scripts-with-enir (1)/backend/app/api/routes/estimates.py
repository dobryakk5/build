# backend/app/api/routes/estimates.py
"""
Fix 4: Асинхронный upload → 202 + job_id
"""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps         import require_action, get_db, get_current_user
from app.core.permissions import Action
from app.models           import Estimate, ProjectMember
from app.schemas          import EstimateRow, EstimateSummary, UploadStartResponse, JobResponse
from app.services.upload_service import start_upload_job, start_upload_job_with_mapping

router = APIRouter(prefix="/projects/{project_id}", tags=["estimates"])


@router.post("/estimates/upload", response_model=UploadStartResponse, status_code=202)
async def upload_estimate(
    project_id:       UUID,
    file:             UploadFile = File(...),
    start_date:       date       = Query(default_factory=date.today),
    workers:          int        = Query(default=3, ge=1, le=20),
    current_user      = Depends(get_current_user),
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession  = Depends(get_db),
):
    """
    Принимает Excel-смету, немедленно отвечает 202 + job_id.
    Парсинг и построение Ганта происходят в фоне.
    Клиент опрашивает GET /jobs/{job_id} каждые 1-2 секунды.
    """
    job = await start_upload_job(
        file             = file,
        project_id       = str(project_id),
        user_id          = current_user.id,
        start_date       = start_date,
        workers          = workers,
        db               = db,
    )
    return UploadStartResponse(job_id=job.id)



# ─────────────────────────────────────────────────────────────────────────────
# Подтверждение ручного маппинга колонок
# ─────────────────────────────────────────────────────────────────────────────

class ConfirmMappingRequest(BaseModel):
    tmp_path:    str
    sheet:       str
    col_mapping: dict[int, str]   # {col_0based: "work_name"|"unit"|...|"skip"}
    start_date:  date
    workers:     int = 3


@router.post("/estimates/upload/confirm-mapping", response_model=UploadStartResponse, status_code=202)
async def confirm_mapping(
    project_id:   UUID,
    body:         ConfirmMappingRequest,
    current_user  = Depends(get_current_user),
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    """
    Принимает ручной маппинг колонок после того как авто-парсинг вернул 422.
    Запускает фоновую обработку с явным маппингом и возвращает job_id.
    """
    job = await start_upload_job_with_mapping(
        tmp_path    = body.tmp_path,
        sheet       = body.sheet,
        col_mapping = body.col_mapping,
        project_id  = str(project_id),
        user_id     = current_user.id,
        start_date  = body.start_date,
        workers     = body.workers,
        db          = db,
    )
    return UploadStartResponse(job_id=job.id)


@router.get("/estimates", response_model=list[EstimateRow])
async def list_estimates(
    project_id: UUID,
    section:    str | None = Query(default=None),
    member: ProjectMember = Depends(require_action(Action.VIEW)),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(Estimate)
        .where(Estimate.project_id == str(project_id))
        .where(Estimate.deleted_at == None)
        .order_by(Estimate.row_order)
    )
    if section:
        q = q.where(Estimate.section == section)

    estimates = await db.scalars(q)
    return list(estimates)


@router.get("/estimates/summary", response_model=EstimateSummary)
async def estimate_summary(
    project_id: UUID,
    member: ProjectMember = Depends(require_action(Action.VIEW)),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func, case
    rows = await db.execute(
        select(
            Estimate.section,
            func.sum(Estimate.total_price).label("subtotal"),
            func.count().label("items"),
        )
        .where(Estimate.project_id == str(project_id))
        .where(Estimate.deleted_at == None)
        .group_by(Estimate.section)
        .order_by(func.sum(Estimate.total_price).desc())
    )
    sections = [
        {"name": r.section or "Без раздела", "subtotal": float(r.subtotal or 0), "items": r.items}
        for r in rows
    ]
    total = sum(s["subtotal"] for s in sections)
    return EstimateSummary(total=total, sections=sections)


# ─────────────────────────────────────────────────────────────────────────────
# backend/app/api/routes/jobs.py
# ─────────────────────────────────────────────────────────────────────────────

from fastapi import APIRouter as _APIRouter
from app.schemas import JobResponse
from app.services.upload_service import get_job

jobs_router = _APIRouter(prefix="/jobs", tags=["jobs"])


@jobs_router.get("/{job_id}", response_model=JobResponse)
async def get_job_status(
    job_id: str,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Polling endpoint. Клиент вызывает каждые 1.5с пока status != done|failed.

    Статусы:
      pending    — в очереди
      processing — выполняется прямо сейчас
      done       — готово, result содержит итоги
      failed     — ошибка, result.error содержит описание
    """
    return await get_job(job_id, db)