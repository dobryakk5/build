# backend/app/api/routes/estimates.py
"""
Fix 4: Асинхронный upload → 202 + job_id
"""
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile, File, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps         import require_action, get_db, get_current_user
from app.core.permissions import Action
from app.models           import Estimate, EstimateBatch, FerWordsEntry, GanttTask, ProjectMember
from app.schemas          import EstimateBatchResponse, EstimateRow, EstimateSummary, JobStartResponse, UploadStartResponse, JobResponse
from app.services.estimate_fer_matcher import (
    _apply_group_match_result,
    confirm_group_candidate,
    get_manual_group_options,
    match_estimate_group_with_vector,
    match_estimate_with_vector,
    resolve_manual_group_match,
    start_fer_match_job,
)
from app.services.fer_words_service import (
    apply_fer_words_choice,
    build_estimate_fer_words_text,
    build_fer_words_candidate_for_entry,
    get_fer_words_candidates_for_estimate,
    start_fer_words_match_job,
)
from app.services.upload_service import start_upload_job, start_upload_job_with_mapping

router = APIRouter(prefix="/projects/{project_id}", tags=["estimates"])


async def _load_group_estimates(db: AsyncSession, estimate: Estimate) -> list[Estimate]:
    if not estimate.estimate_batch_id or not estimate.section or not str(estimate.section).strip():
        return [estimate]

    return list(
        await db.scalars(
            select(Estimate)
            .where(Estimate.project_id == estimate.project_id)
            .where(Estimate.estimate_batch_id == estimate.estimate_batch_id)
            .where(Estimate.section == estimate.section)
            .where(Estimate.deleted_at.is_(None))
            .order_by(Estimate.row_order, Estimate.id)
        )
    )


@router.post("/estimates/upload", response_model=UploadStartResponse, status_code=202)
async def upload_estimate(
    project_id:       UUID,
    file:             UploadFile = File(...),
    start_date:       date       = Query(default_factory=date.today),
    workers:          int        = Query(default=3, ge=1, le=20),
    estimate_kind:    int        = Query(ge=1, le=9),
    complex_mode:     bool       = Query(default=False),
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
        estimate_kind    = estimate_kind,
        complex_mode     = complex_mode,
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
    estimate_kind: int
    complex_mode: bool = False


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
        estimate_kind = body.estimate_kind,
        complex_mode  = body.complex_mode,
        db          = db,
    )
    return UploadStartResponse(job_id=job.id)


@router.get("/estimates", response_model=list[EstimateRow])
async def list_estimates(
    project_id: UUID,
    section:    str | None = Query(default=None),
    estimate_batch_id: UUID | None = Query(default=None),
    member: ProjectMember = Depends(require_action(Action.VIEW)),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(Estimate)
        .where(Estimate.project_id == str(project_id))
        .where(Estimate.deleted_at.is_(None))
        .order_by(Estimate.row_order)
    )
    if estimate_batch_id:
        q = q.where(Estimate.estimate_batch_id == str(estimate_batch_id))
    if section:
        q = q.where(Estimate.section == section)

    estimates = await db.scalars(q)
    return list(estimates)


@router.get("/estimates/summary", response_model=EstimateSummary)
async def estimate_summary(
    project_id: UUID,
    estimate_batch_id: UUID | None = Query(default=None),
    member: ProjectMember = Depends(require_action(Action.VIEW)),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(
            Estimate.section,
            func.sum(Estimate.total_price).label("subtotal"),
            func.count().label("items"),
        )
        .where(Estimate.project_id == str(project_id))
        .where(Estimate.deleted_at.is_(None))
    )
    if estimate_batch_id:
        q = q.where(Estimate.estimate_batch_id == str(estimate_batch_id))
    q = q.group_by(Estimate.section).order_by(func.sum(Estimate.total_price).desc())

    rows = await db.execute(q)
    sections = [
        {"name": r.section or "Без раздела", "subtotal": float(r.subtotal or 0), "items": r.items}
        for r in rows
    ]
    total = sum(s["subtotal"] for s in sections)
    return EstimateSummary(total=total, sections=sections)


@router.get("/estimate-batches", response_model=list[EstimateBatchResponse])
async def list_estimate_batches(
    project_id: UUID,
    member: ProjectMember = Depends(require_action(Action.VIEW)),
    db: AsyncSession = Depends(get_db),
):
    batches = list(
        await db.scalars(
            select(EstimateBatch)
            .where(EstimateBatch.project_id == str(project_id))
            .where(EstimateBatch.deleted_at.is_(None))
            .order_by(EstimateBatch.created_at)
        )
    )

    result: list[EstimateBatchResponse] = []
    for batch in batches:
        estimates_count = await db.scalar(
            select(func.count())
            .select_from(Estimate)
            .where(Estimate.estimate_batch_id == batch.id)
            .where(Estimate.deleted_at.is_(None))
        )
        gantt_tasks_count = await db.scalar(
            select(func.count())
            .select_from(GanttTask)
            .where(GanttTask.estimate_batch_id == batch.id)
            .where(GanttTask.deleted_at.is_(None))
        )
        total_price = await db.scalar(
            select(func.sum(Estimate.total_price))
            .where(Estimate.estimate_batch_id == batch.id)
            .where(Estimate.deleted_at.is_(None))
        )
        fer_matched_count = await db.scalar(
            select(func.count())
            .select_from(Estimate)
            .where(Estimate.estimate_batch_id == batch.id)
            .where(Estimate.deleted_at.is_(None))
            .where(Estimate.fer_table_id.is_not(None))
        )
        fer_words_matched_count = await db.scalar(
            select(func.count())
            .select_from(Estimate)
            .where(Estimate.estimate_batch_id == batch.id)
            .where(Estimate.deleted_at.is_(None))
            .where(Estimate.fer_words_entry_id.is_not(None))
        )
        result.append(
            EstimateBatchResponse(
                id=batch.id,
                project_id=batch.project_id,
                name=batch.name,
                estimate_kind=batch.estimate_kind,
                source_filename=batch.source_filename,
                estimates_count=estimates_count or 0,
                gantt_tasks_count=gantt_tasks_count or 0,
                fer_matched_count=fer_matched_count or 0,
                fer_words_matched_count=fer_words_matched_count or 0,
                total_price=float(total_price or 0),
                created_at=batch.created_at,
            )
        )
    return result


@router.post("/estimate-batches/{estimate_batch_id}/match-fer", response_model=JobStartResponse, status_code=202)
async def match_estimate_batch_with_fer(
    project_id: UUID,
    estimate_batch_id: UUID,
    current_user = Depends(get_current_user),
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    job = await start_fer_match_job(
        project_id=str(project_id),
        estimate_batch_id=str(estimate_batch_id),
        user_id=current_user.id,
        db=db,
    )
    return JobStartResponse(
        job_id=job.id,
        message="Сопоставление сметы с ФЕР запущено.",
    )


@router.post("/estimate-batches/{estimate_batch_id}/match-fer-words", response_model=JobStartResponse, status_code=202)
async def match_estimate_batch_with_fer_words(
    project_id: UUID,
    estimate_batch_id: UUID,
    current_user = Depends(get_current_user),
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    job = await start_fer_words_match_job(
        project_id=str(project_id),
        estimate_batch_id=str(estimate_batch_id),
        user_id=current_user.id,
        db=db,
    )
    return JobStartResponse(
        job_id=job.id,
        message="Сопоставление сметы с ФЕР слова запущено.",
    )


class ActFlagsUpdate(BaseModel):
    req_hidden_work_act: bool | None = None
    req_intermediate_act: bool | None = None
    req_ks2_ks3: bool | None = None


@router.patch("/estimates/{estimate_id}/acts")
async def update_estimate_acts(
    project_id: UUID,
    estimate_id: UUID,
    body: ActFlagsUpdate,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    est = await db.get(Estimate, str(estimate_id))
    if not est or est.project_id != str(project_id) or est.deleted_at:
        raise HTTPException(404, "Строка сметы не найдена")

    if body.req_hidden_work_act is not None:
        est.req_hidden_work_act = body.req_hidden_work_act
    if body.req_intermediate_act is not None:
        est.req_intermediate_act = body.req_intermediate_act
    if body.req_ks2_ks3 is not None:
        est.req_ks2_ks3 = body.req_ks2_ks3

    await db.commit()
    return {
        "id": est.id,
        "req_hidden_work_act": est.req_hidden_work_act,
        "req_intermediate_act": est.req_intermediate_act,
        "req_ks2_ks3": est.req_ks2_ks3,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Ручной маппинг ФЕР
# ─────────────────────────────────────────────────────────────────────────────

class FerMappingUpdate(BaseModel):
    fer_table_id: int | None = None


class FerGroupConfirmUpdate(BaseModel):
    kind: str
    ref_id: int


@router.patch("/estimates/{estimate_id}/fer")
async def update_estimate_fer(
    project_id: UUID,
    estimate_id: UUID,
    body: FerMappingUpdate,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    est = await db.get(Estimate, str(estimate_id))
    if not est or est.project_id != str(project_id) or est.deleted_at:
        raise HTTPException(404, "Строка сметы не найдена")

    if body.fer_table_id is None:
        est.fer_table_id = None
        est.fer_work_type = None
        est.fer_match_score = None
        est.fer_matched_at = None
    else:
        table_row = (
            await db.execute(
                text(
                    """
                    SELECT
                        t.id,
                        t.table_title,
                        t.common_work_name,
                        (
                            COALESCE(c.ignored, FALSE)
                            OR COALESCE(s.ignored, FALSE)
                            OR COALESCE(ss.ignored, FALSE)
                            OR COALESCE(t.ignored, FALSE)
                        ) AS effective_ignored
                    FROM fer.fer_tables
                    t
                    JOIN fer.collections c ON c.id = t.collection_id
                    LEFT JOIN fer.sections s ON s.id = t.section_id
                    LEFT JOIN fer.subsections ss ON ss.id = t.subsection_id
                    WHERE t.id = :table_id
                    """
                ),
                {"table_id": body.fer_table_id},
            )
        ).mappings().first()
        if table_row is None:
            raise HTTPException(404, "FER table not found")
        if table_row.get("effective_ignored"):
            raise HTTPException(400, "FER table is ignored")

        work_type = (table_row["common_work_name"] or "").strip() or str(table_row["table_title"]).strip()

        est.fer_table_id = int(table_row["id"])
        est.fer_work_type = work_type
        est.fer_match_score = 1.0
        est.fer_matched_at = datetime.now(timezone.utc)

    await db.commit()
    return {
        "id": est.id,
        "fer_table_id": est.fer_table_id,
        "fer_work_type": est.fer_work_type,
        "fer_match_score": float(est.fer_match_score) if est.fer_match_score is not None else None,
        "fer_matched_at": est.fer_matched_at.isoformat() if est.fer_matched_at else None,
    }


@router.post("/estimates/{estimate_id}/match-fer-vector")
async def match_estimate_fer_vector(
    project_id: UUID,
    estimate_id: UUID,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    est = await db.get(Estimate, str(estimate_id))
    if not est or est.project_id != str(project_id) or est.deleted_at:
        raise HTTPException(404, "Строка сметы не найдена")

    match = await match_estimate_with_vector(db, est)
    if match is None:
        est.fer_table_id = None
        est.fer_work_type = None
        est.fer_match_score = None
        est.fer_matched_at = None
    else:
        est.fer_table_id = match.table_id
        est.fer_work_type = match.work_type
        est.fer_match_score = round(match.score, 4)
        est.fer_matched_at = datetime.now(timezone.utc)

    await db.commit()
    return {
        "id": est.id,
        "fer_table_id": est.fer_table_id,
        "fer_work_type": est.fer_work_type,
        "fer_match_score": float(est.fer_match_score) if est.fer_match_score is not None else None,
        "fer_matched_at": est.fer_matched_at.isoformat() if est.fer_matched_at else None,
    }


@router.post("/estimates/{estimate_id}/match-fer-group-vector")
async def match_estimate_fer_group_vector(
    project_id: UUID,
    estimate_id: UUID,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    est = await db.get(Estimate, str(estimate_id))
    if not est or est.project_id != str(project_id) or est.deleted_at:
        raise HTTPException(404, "Строка сметы не найдена")

    target_estimates = await _load_group_estimates(db, est)
    matched_at = datetime.now(timezone.utc)
    match = await match_estimate_group_with_vector(db, est)
    for target in target_estimates:
        _apply_group_match_result(target, match, None if match.no_match else matched_at)
    await db.commit()
    payload = match.to_payload(est.id, None if match.no_match else matched_at)
    payload["updated_rows_count"] = len(target_estimates)
    return payload


@router.patch("/estimates/{estimate_id}/fer-group")
async def confirm_estimate_fer_group(
    project_id: UUID,
    estimate_id: UUID,
    body: FerGroupConfirmUpdate,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    est = await db.get(Estimate, str(estimate_id))
    if not est or est.project_id != str(project_id) or est.deleted_at:
        raise HTTPException(404, "Строка сметы не найдена")

    target_estimates = await _load_group_estimates(db, est)
    match = confirm_group_candidate(est, kind=body.kind, ref_id=body.ref_id)
    matched_at = datetime.now(timezone.utc)
    for target in target_estimates:
        _apply_group_match_result(target, match, matched_at)
    await db.commit()
    payload = match.to_payload(est.id, matched_at)
    payload["updated_rows_count"] = len(target_estimates)
    return payload


@router.get("/estimates/{estimate_id}/fer-group-options")
async def get_estimate_fer_group_options(
    project_id: UUID,
    estimate_id: UUID,
    member: ProjectMember = Depends(require_action(Action.VIEW)),
    db: AsyncSession = Depends(get_db),
):
    est = await db.get(Estimate, str(estimate_id))
    if not est or est.project_id != str(project_id) or est.deleted_at:
        raise HTTPException(404, "Строка сметы не найдена")

    return {
        "collections": await get_manual_group_options(db, est),
    }


@router.patch("/estimates/{estimate_id}/fer-group-manual")
async def update_estimate_fer_group_manual(
    project_id: UUID,
    estimate_id: UUID,
    body: FerGroupConfirmUpdate,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    est = await db.get(Estimate, str(estimate_id))
    if not est or est.project_id != str(project_id) or est.deleted_at:
        raise HTTPException(404, "Строка сметы не найдена")

    target_estimates = await _load_group_estimates(db, est)
    match = await resolve_manual_group_match(db, est, kind=body.kind, ref_id=body.ref_id)
    matched_at = datetime.now(timezone.utc)
    for target in target_estimates:
        _apply_group_match_result(target, match, matched_at)
    await db.commit()
    payload = match.to_payload(est.id, matched_at)
    payload["updated_rows_count"] = len(target_estimates)
    return payload


class FerWordsMappingUpdate(BaseModel):
    entry_id: int | None = None


@router.get("/estimates/{estimate_id}/fer-words-candidates")
async def get_estimate_fer_words_candidates(
    project_id: UUID,
    estimate_id: UUID,
    limit: int = Query(default=5, ge=1, le=10),
    member: ProjectMember = Depends(require_action(Action.VIEW)),
    db: AsyncSession = Depends(get_db),
):
    est = await db.get(Estimate, str(estimate_id))
    if not est or est.project_id != str(project_id) or est.deleted_at:
        raise HTTPException(404, "Строка сметы не найдена")

    candidates = await get_fer_words_candidates_for_estimate(db, est, limit=limit)
    return [candidate.to_payload() for candidate in candidates]


@router.patch("/estimates/{estimate_id}/fer-words")
async def update_estimate_fer_words(
    project_id: UUID,
    estimate_id: UUID,
    body: FerWordsMappingUpdate,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    est = await db.get(Estimate, str(estimate_id))
    if not est or est.project_id != str(project_id) or est.deleted_at:
        raise HTTPException(404, "Строка сметы не найдена")

    if body.entry_id is None:
        apply_fer_words_choice(est, None, None)
    else:
        entry = await db.get(FerWordsEntry, body.entry_id)
        if entry is None:
            raise HTTPException(404, "Строка 'ФЕР слова' не найдена")

        candidate = build_fer_words_candidate_for_entry(build_estimate_fer_words_text(est), entry)
        if candidate is None:
            raise HTTPException(400, "Не удалось сопоставить строку сметы с выбранной строкой 'ФЕР слова'")
        apply_fer_words_choice(est, entry, candidate)

    await db.commit()
    return {
        "id": est.id,
        "fer_words_entry_id": est.fer_words_entry_id,
        "fer_words_code": est.fer_words_code,
        "fer_words_name": est.fer_words_name,
        "fer_words_human_hours": float(est.fer_words_human_hours) if est.fer_words_human_hours is not None else None,
        "fer_words_machine_hours": float(est.fer_words_machine_hours) if est.fer_words_machine_hours is not None else None,
        "fer_words_match_score": float(est.fer_words_match_score) if est.fer_words_match_score is not None else None,
        "fer_words_match_count": est.fer_words_match_count,
        "fer_words_matched_at": est.fer_words_matched_at.isoformat() if est.fer_words_matched_at else None,
    }


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
