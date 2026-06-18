# backend/app/api/routes/estimates.py
"""
Fix 4: Асинхронный upload → 202 + job_id
"""
from datetime import date, datetime, timezone
import json
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile, File, Form, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps         import require_action, get_db, get_current_user
from app.core.clarifications import UNKNOWN_CLARIFICATION_MARKERS
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
from app.services.gantt_calculations import DEFAULT_HOURS_PER_DAY, calculate_working_days
from app.services.gantt_service import resolve_project_dates
from app.services.upload_service import (
    build_gantt_for_estimate_batch,
    confirm_upload_job,
    preview_upload_job,
    start_upload_job,
    start_upload_job_with_mapping,
)
from app.services.parser_factory import VALID_PARSER_PROFILES, UI_PROFILES, PROFILE_AUTO
from app.services.work_taxonomy_service import (
    get_estimate_types,
    suggest_project_hierarchy_variants,
    validate_project_hierarchy_selection,
)
from app.services.preview_session import (
    PreviewStorageUnavailable,
    get_preview_session,
    set_preview_status,
    try_consume_preview_session,
    update_preview_session,
)

router = APIRouter(prefix="/projects/{project_id}", tags=["estimates"])

from app.core.estimate_types import (
    ESTIMATE_ITEM_TYPE_WORK,
    ESTIMATE_ITEM_TYPE_MECHANISM,
    resolve_item_type,
)

CLARIFICATION_PAYLOAD_VERSION = "v1"
MAX_CLARIFICATION_BYTES = 50_000
MAX_CLARIFICATION_QUESTIONS = 250
MAX_CLARIFICATION_TEXT_LENGTH = 500


def _ensure_no_reserved_keys(value, path: str = "clarification_answers") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if key_text.startswith("__"):
                raise HTTPException(400, f"Служебный ключ {path}.{key_text} запрещён")
            _ensure_no_reserved_keys(child, f"{path}.{key_text}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _ensure_no_reserved_keys(child, f"{path}[{index}]")


def _clean_clarification_text(value, max_length: int = MAX_CLARIFICATION_TEXT_LENGTH) -> str:
    return " ".join(str(value or "").split()).strip()[:max_length]


def _clean_clarification_answers(value) -> list[str]:
    if not isinstance(value, list):
        return []
    answers: list[str] = []
    for item in value:
        answer = _clean_clarification_text(item, 200)
        if not answer or answer in UNKNOWN_CLARIFICATION_MARKERS or answer in answers:
            continue
        answers.append(answer)
    return answers


def _normalize_clarification_payload(payload: dict | None) -> dict | None:
    if not payload:
        return None
    _ensure_no_reserved_keys(payload)
    if payload.get("version") != CLARIFICATION_PAYLOAD_VERSION:
        raise HTTPException(400, "Неподдерживаемая версия уточнений")
    if not isinstance(payload.get("form"), dict):
        raise HTTPException(400, "Уточнения должны содержать объект form")

    source_form = payload["form"]
    form: dict[str, dict] = {}
    for raw_key, raw_value in source_form.items():
        key = _clean_clarification_text(raw_key, 64)
        if not key or key.startswith("_"):
            continue

        if isinstance(raw_value, dict):
            answers = _clean_clarification_answers(raw_value.get("answers"))
            question = _clean_clarification_text(
                raw_value.get("question") or raw_value.get("question_text") or key,
                200,
            )
            section = _clean_clarification_text(raw_value.get("section"), 120)
        else:
            answers = _clean_clarification_answers(raw_value)
            question = key
            section = ""

        if answers:
            form[key] = {
                "question": question,
                "answers": answers,
            }
            if section:
                form[key]["section"] = section
        if len(form) > MAX_CLARIFICATION_QUESTIONS:
            raise HTTPException(400, "Слишком много уточнений")

    if not form:
        return None

    normalized = {
        "version": CLARIFICATION_PAYLOAD_VERSION,
        "form": form,
    }
    estimate_kind = payload.get("estimate_kind")
    if isinstance(estimate_kind, int):
        normalized["estimate_kind"] = estimate_kind
    kind_title = _clean_clarification_text(payload.get("kind_title"), 160)
    if kind_title:
        normalized["kind_title"] = kind_title
    return normalized


def _parse_clarification_answers(raw: str | None) -> dict | None:
    if not raw:
        return None
    if len(raw.encode("utf-8")) > MAX_CLARIFICATION_BYTES:
        raise HTTPException(400, "Слишком большой JSON уточнений")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "Некорректный JSON уточнений")
    if not isinstance(parsed, dict):
        raise HTTPException(400, "Уточнения должны быть JSON-объектом")
    return _normalize_clarification_payload(parsed)


def _public_clarification_answers(value: dict | None) -> dict | None:
    if not isinstance(value, dict):
        return None
    public = {
        key: val
        for key, val in value.items()
        if key in {"version", "estimate_kind", "kind_title", "form"}
    }
    return public or None


def _resolve_upload_hierarchy_selection(
    estimate_type_id: str | None,
    project_variant_id: str | None,
    estimate_kind: int | None,
) -> tuple[int, dict | None]:
    if estimate_type_id or project_variant_id:
        try:
            selection = validate_project_hierarchy_selection(
                estimate_type_id,
                project_variant_id,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return int(selection["estimate_kind"]), selection
    if estimate_kind is None:
        raise HTTPException(400, "Выберите тип сметы и вариант объекта")
    return estimate_kind, None


def _resolve_preview_hierarchy_selection(
    estimate_type_id: str | None,
    project_variant_id: str | None,
    estimate_kind: int | None,
) -> tuple[int, dict | None]:
    if estimate_type_id and project_variant_id:
        return _resolve_upload_hierarchy_selection(estimate_type_id, project_variant_id, estimate_kind)
    if estimate_kind is not None:
        return estimate_kind, None
    if estimate_type_id:
        for item in get_estimate_types():
            if item.get("id") == estimate_type_id or item.get("number") == estimate_type_id:
                return int(item["estimate_kind"]), None
    raise HTTPException(400, "Выберите тип сметы")


def _estimate_item_type(estimate: Estimate) -> str:
    return resolve_item_type(estimate)


def _is_mechanism_estimate(estimate: Estimate) -> bool:
    return _estimate_item_type(estimate) == ESTIMATE_ITEM_TYPE_MECHANISM


def _ensure_work_estimate(estimate: Estimate) -> None:
    if _is_mechanism_estimate(estimate):
        raise HTTPException(400, "Для механизма операция недоступна")


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
    clarification_answers: str | None = Form(default=None),
    start_date:       date       = Query(default_factory=date.today),
    workers:          int        = Query(default=3, ge=1, le=20),
    estimate_kind:    int | None = Query(default=None, ge=1, le=9),
    estimate_type_id: str | None = Query(default=None),
    project_variant_id: str | None = Query(default=None),
    complex_mode:     bool       = Query(default=False),
    current_user      = Depends(get_current_user),
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession  = Depends(get_db),
):
    """
    Принимает Excel-смету, немедленно отвечает 202 + job_id.
    Парсинг сметы происходит в фоне. Гант строится отдельным действием со страницы сметы.
    Клиент опрашивает GET /jobs/{job_id} каждые 1-2 секунды.
    """
    parsed_clarification_answers = _parse_clarification_answers(clarification_answers)
    resolved_estimate_kind, hierarchy_selection = _resolve_upload_hierarchy_selection(
        estimate_type_id,
        project_variant_id,
        estimate_kind,
    )

    job = await start_upload_job(
        file             = file,
        project_id       = str(project_id),
        user_id          = current_user.id,
        start_date       = start_date,
        workers          = workers,
        estimate_kind    = resolved_estimate_kind,
        complex_mode     = complex_mode,
        clarification_answers = parsed_clarification_answers,
        hierarchy_selection = hierarchy_selection,
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
    estimate_kind: int | None = None
    estimate_type_id: str | None = None
    project_variant_id: str | None = None
    complex_mode: bool = False
    clarification_answers: dict | None = None
    parser_profile: str = "manual_mapping"


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
    resolved_estimate_kind, hierarchy_selection = _resolve_upload_hierarchy_selection(
        body.estimate_type_id,
        body.project_variant_id,
        body.estimate_kind,
    )
    job = await start_upload_job_with_mapping(
        tmp_path    = body.tmp_path,
        sheet       = body.sheet,
        col_mapping = body.col_mapping,
        project_id  = str(project_id),
        user_id     = current_user.id,
        start_date  = body.start_date,
        workers     = body.workers,
        estimate_kind = resolved_estimate_kind,
        complex_mode  = body.complex_mode,
        clarification_answers = _normalize_clarification_payload(body.clarification_answers),
        hierarchy_selection = hierarchy_selection,
        db          = db,
    )
    return UploadStartResponse(job_id=job.id)


# ─────────────────────────────────────────────────────────────────────────────
# Двухшаговый импорт по профилю: preview → confirm
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/estimates/parser-profiles")
async def list_parser_profiles(
    member: ProjectMember = Depends(require_action(Action.VIEW)),
):
    """Профили импорта для выпадашки на фронте (только готовые)."""
    return {"profiles": UI_PROFILES}


@router.post("/estimates/upload/preview")
async def preview_estimate(
    project_id:       UUID,
    file:             UploadFile = File(...),
    clarification_answers: str | None = Form(default=None),
    start_date:       date       = Query(default_factory=date.today),
    workers:          int        = Query(default=3, ge=1, le=20),
    estimate_kind:    int | None = Query(default=None, ge=1, le=9),
    estimate_type_id: str | None = Query(default=None),
    project_variant_id: str | None = Query(default=None),
    complex_mode:     bool       = Query(default=False),
    parser_profile:   str        = Query(default=PROFILE_AUTO),
    build_gantt:      bool       = Query(default=True),
    current_user      = Depends(get_current_user),
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession  = Depends(get_db),
):
    """
    Шаг 1: парсит файл во временное хранилище и возвращает разбивку по типам
    (работы/материалы/механизмы/накладные/сомнительные) БЕЗ записи в БД.
    Возвращает preview_id для подтверждения импорта.
    """
    if parser_profile not in VALID_PARSER_PROFILES:
        raise HTTPException(400, f"Неизвестный профиль импорта: {parser_profile}")

    resolved_estimate_kind, hierarchy_selection = _resolve_preview_hierarchy_selection(
        estimate_type_id,
        project_variant_id,
        estimate_kind,
    )

    try:
        return await preview_upload_job(
            file             = file,
            project_id       = str(project_id),
            user_id          = current_user.id,
            parser_profile   = parser_profile,
            start_date       = start_date,
            workers          = workers,
            estimate_kind    = resolved_estimate_kind,
            complex_mode     = complex_mode,
            build_gantt      = build_gantt,
            clarification_answers = _parse_clarification_answers(clarification_answers),
            hierarchy_selection = hierarchy_selection,
            hierarchy_suggestions = suggest_project_hierarchy_variants,
            suggestion_estimate_type_id = estimate_type_id,
            db               = db,
        )
    except PreviewStorageUnavailable:
        raise HTTPException(503, "Временное хранилище импорта недоступно. Повторите позже.")


class PreviewTypeOverride(BaseModel):
    index:     int
    row_hash:  str
    item_type: str


class PreviewAddedRow(BaseModel):
    section:     str | None = None
    name:        str
    item_type:   str = "work"
    unit:        str | None = None
    quantity:    float | None = None
    total_price: float | None = None


class PreviewStageOverride(BaseModel):
    index: int
    row_hash: str
    work_stage_number: str | None = None
    work_stage_title: str | None = None
    canonical_stage_id: str | None = None
    stage_occurrence_index: int | None = None
    stage_occurrence_label: str | None = None
    stage_options_mode: str | None = None
    stage_option_id: str | None = None
    stage_option_title: str | None = None
    section_id: str | None = None
    subtype_id: str | None = None
    row_role: str | None = None


class PreviewEdits(BaseModel):
    type_overrides: list[PreviewTypeOverride] = Field(default_factory=list)
    added_rows:     list[PreviewAddedRow] = Field(default_factory=list)
    stage_overrides: list[PreviewStageOverride] = Field(default_factory=list)


class ConfirmImportRequest(BaseModel):
    preview_id:  str
    build_gantt: bool | None = None
    edits:       PreviewEdits | None = None


@router.post("/estimates/upload/confirm", response_model=UploadStartResponse, status_code=202)
async def confirm_import(
    project_id:   UUID,
    body:         ConfirmImportRequest,
    current_user  = Depends(get_current_user),
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    """
    Шаг 2: подтверждает импорт по preview_id. Профиль берётся из preview-сессии.
    Только здесь происходит замена старой сметы (после успешного парсинга).
    """
    try:
        preview = await get_preview_session(body.preview_id)
    except PreviewStorageUnavailable:
        raise HTTPException(503, "Временное хранилище импорта недоступно. Повторите позже.")

    if not preview:
        raise HTTPException(410, "Превью истекло. Загрузите файл заново.")
    if preview.get("project_id") != str(project_id) or preview.get("user_id") != current_user.id:
        raise HTTPException(403, "Превью принадлежит другому проекту или пользователю.")

    outcome = await try_consume_preview_session(body.preview_id)
    if outcome == "missing":
        raise HTTPException(410, "Превью истекло. Загрузите файл заново.")
    if outcome == "already_consumed":
        raise HTTPException(409, "Этот импорт уже подтверждён.")

    try:
        edits = body.edits.model_dump() if body.edits else None
        job = await confirm_upload_job(preview, body.build_gantt, db, edits=edits)
    except Exception:
        # Откатываем сессию в ready, чтобы пользователь мог повторить попытку.
        await set_preview_status(body.preview_id, "ready")
        raise

    await update_preview_session(body.preview_id, job_id=job.id)
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
        select(Estimate)
        .where(Estimate.project_id == str(project_id))
        .where(Estimate.deleted_at.is_(None))
        .order_by(Estimate.row_order, Estimate.id)
    )
    if estimate_batch_id:
        q = q.where(Estimate.estimate_batch_id == str(estimate_batch_id))

    rows = list(await db.scalars(q))
    section_totals: dict[str, dict[str, float | int | str]] = {}
    total = 0.0
    for row in rows:
        if _is_mechanism_estimate(row):
            continue
        section_name = row.section or "Без раздела"
        row_total = float(row.total_price or 0)
        total += row_total
        section = section_totals.setdefault(section_name, {"name": section_name, "subtotal": 0.0, "items": 0})
        section["subtotal"] = float(section["subtotal"]) + row_total
        section["items"] = int(section["items"]) + 1

    sections = sorted(
        (
            {"name": str(section["name"]), "subtotal": float(section["subtotal"]), "items": int(section["items"])}
            for section in section_totals.values()
        ),
        key=lambda item: item["subtotal"],
        reverse=True,
    )
    return EstimateSummary(total=total, sections=sections)


class MechanismCreateRequest(BaseModel):
    estimate_batch_id: UUID
    section: str | None = Field(default=None, max_length=255)
    name: str = Field(min_length=1, max_length=5000)
    unit: str | None = Field(default=None, max_length=50)
    quantity: float | None = Field(default=None, ge=0)
    unit_price: float | None = Field(default=None, ge=0)
    total_price: float | None = Field(default=None, ge=0)


@router.post("/estimates/mechanisms", response_model=EstimateRow, status_code=201)
async def create_estimate_mechanism(
    project_id: UUID,
    body: MechanismCreateRequest,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    batch = await db.get(EstimateBatch, str(body.estimate_batch_id))
    if not batch or batch.project_id != str(project_id) or batch.deleted_at:
        raise HTTPException(404, "Блок сметы не найден")

    next_row_order = await db.scalar(
        select(func.max(Estimate.row_order))
        .where(Estimate.project_id == str(project_id))
        .where(Estimate.estimate_batch_id == str(body.estimate_batch_id))
        .where(Estimate.deleted_at.is_(None))
    )

    total_price = body.total_price
    if total_price is None and body.quantity is not None and body.unit_price is not None:
        total_price = round(body.quantity * body.unit_price, 2)

    mechanism = Estimate(
        project_id=str(project_id),
        estimate_batch_id=str(body.estimate_batch_id),
        section=(body.section or "").strip() or None,
        work_name=body.name.strip(),
        unit=(body.unit or "").strip() or None,
        quantity=body.quantity,
        unit_price=body.unit_price,
        total_price=total_price,
        materials=None,
        row_order=int(next_row_order or -1) + 1,
        raw_data={"item_type": ESTIMATE_ITEM_TYPE_MECHANISM},
    )
    db.add(mechanism)
    await db.commit()
    await db.refresh(mechanism)
    return mechanism


@router.delete("/estimates/{estimate_id}", status_code=204)
async def delete_estimate_mechanism(
    project_id: UUID,
    estimate_id: UUID,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    est = await db.get(Estimate, str(estimate_id))
    if not est or est.project_id != str(project_id) or est.deleted_at:
        raise HTTPException(404, "Строка сметы не найдена")
    if not _is_mechanism_estimate(est):
        raise HTTPException(400, "Удалять можно только строки механизмов")

    est.deleted_at = datetime.now(timezone.utc)
    await db.commit()


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
                start_date=batch.start_date,
                workers_count=batch.workers_count,
                hours_per_day=float(batch.hours_per_day or DEFAULT_HOURS_PER_DAY),
                source_filename=batch.source_filename,
                estimate_type_id=batch.estimate_type_id,
                estimate_type_title=batch.estimate_type_title,
                estimate_type_number=batch.estimate_type_number,
                project_variant_id=batch.project_variant_id,
                project_variant_title=batch.project_variant_title,
                project_variant_number=batch.project_variant_number,
                taxonomy_dictionary_version=batch.taxonomy_dictionary_version,
                clarification_answers=_public_clarification_answers(batch.clarification_answers),
                estimates_count=estimates_count or 0,
                gantt_tasks_count=gantt_tasks_count or 0,
                fer_matched_count=fer_matched_count or 0,
                fer_words_matched_count=fer_words_matched_count or 0,
                total_price=float(total_price or 0),
                created_at=batch.created_at,
            )
        )
    return result


class EstimateBatchWorkersUpdate(BaseModel):
    workers_count: int


class EstimateBatchScheduleUpdate(BaseModel):
    workers_count: int | None = None
    hours_per_day: float | None = None


class EstimateBatchGanttBuildRequest(BaseModel):
    start_date: date | None = None


async def _update_estimate_batch_schedule(
    project_id: str,
    estimate_batch_id: str,
    workers_count: int | None,
    hours_per_day: float | None,
    db: AsyncSession,
) -> dict:
    if workers_count is None and hours_per_day is None:
        raise HTTPException(422, "At least one of workers_count or hours_per_day is required")
    if workers_count is not None and (workers_count < 1 or workers_count > 500):
        raise HTTPException(422, "workers_count must be between 1 and 500")
    if hours_per_day is not None and (hours_per_day <= 0 or hours_per_day > 24):
        raise HTTPException(422, "hours_per_day must be between 0 and 24")

    batch = await db.get(EstimateBatch, str(estimate_batch_id))
    if not batch or batch.project_id != str(project_id) or batch.deleted_at:
        raise HTTPException(404, "Блок сметы не найден")

    current_hours_per_day = getattr(batch, "hours_per_day", None)
    next_workers_count = workers_count if workers_count is not None else int(batch.workers_count or 1)
    next_hours_per_day = float(hours_per_day if hours_per_day is not None else current_hours_per_day or DEFAULT_HOURS_PER_DAY)

    batch.workers_count = next_workers_count
    batch.hours_per_day = next_hours_per_day
    gantt_tasks = list(
        await db.scalars(
            select(GanttTask)
            .where(GanttTask.project_id == str(project_id))
            .where(GanttTask.estimate_batch_id == str(estimate_batch_id))
            .where(GanttTask.deleted_at.is_(None))
            .where(GanttTask.is_group.is_(False))
        )
    )
    for task in gantt_tasks:
        task.workers_count = next_workers_count
        task.hours_per_day = next_hours_per_day
        if task.labor_hours is not None:
            task.working_days = calculate_working_days(
                task.labor_hours,
                next_workers_count,
                next_hours_per_day,
            ) or 1

    await db.flush()
    await resolve_project_dates(project_id, db)
    await db.commit()
    return {
        "id": batch.id,
        "workers_count": batch.workers_count,
        "hours_per_day": float(batch.hours_per_day or DEFAULT_HOURS_PER_DAY),
        "updated_gantt_tasks_count": len(gantt_tasks),
    }


@router.patch("/estimate-batches/{estimate_batch_id}/workers")
async def update_estimate_batch_workers(
    project_id: UUID,
    estimate_batch_id: UUID,
    body: EstimateBatchWorkersUpdate,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    result = await _update_estimate_batch_schedule(
        project_id=str(project_id),
        estimate_batch_id=str(estimate_batch_id),
        workers_count=body.workers_count,
        hours_per_day=None,
        db=db,
    )
    return {
        "id": result["id"],
        "workers_count": result["workers_count"],
        "updated_gantt_tasks_count": result["updated_gantt_tasks_count"],
    }


@router.patch("/estimate-batches/{estimate_batch_id}/schedule")
async def update_estimate_batch_schedule(
    project_id: UUID,
    estimate_batch_id: UUID,
    body: EstimateBatchScheduleUpdate,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    return await _update_estimate_batch_schedule(
        project_id=str(project_id),
        estimate_batch_id=str(estimate_batch_id),
        workers_count=body.workers_count,
        hours_per_day=body.hours_per_day,
        db=db,
    )


@router.post("/estimate-batches/{estimate_batch_id}/build-gantt")
async def build_estimate_batch_gantt(
    project_id: UUID,
    estimate_batch_id: UUID,
    body: EstimateBatchGanttBuildRequest | None = None,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    result = await build_gantt_for_estimate_batch(
        project_id=str(project_id),
        estimate_batch_id=str(estimate_batch_id),
        start_date=body.start_date if body else None,
        db=db,
    )
    await resolve_project_dates(str(project_id), db)
    await db.commit()
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


class FerMultiplierUpdate(BaseModel):
    fer_multiplier: float


class LaborHoursUpdate(BaseModel):
    labor_hours: float | None = None


@router.patch("/estimates/{estimate_id}/labor-hours")
async def update_estimate_labor_hours(
    project_id: UUID,
    estimate_id: UUID,
    body: LaborHoursUpdate,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    est = await db.get(Estimate, str(estimate_id))
    if not est or est.project_id != str(project_id) or est.deleted_at:
        raise HTTPException(404, "Строка сметы не найдена")
    _ensure_work_estimate(est)

    if body.labor_hours is not None and (body.labor_hours < 0 or body.labor_hours > 1_000_000):
        raise HTTPException(400, "Трудоёмкость должна быть от 0 до 1 000 000 ч-ч")

    est.labor_hours = round(float(body.labor_hours), 2) if body.labor_hours is not None else None

    await db.commit()
    return {
        "id": est.id,
        "labor_hours": float(est.labor_hours) if est.labor_hours is not None else None,
    }


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
    _ensure_work_estimate(est)

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


@router.patch("/estimates/{estimate_id}/fer-multiplier")
async def update_estimate_fer_multiplier(
    project_id: UUID,
    estimate_id: UUID,
    body: FerMultiplierUpdate,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    est = await db.get(Estimate, str(estimate_id))
    if not est or est.project_id != str(project_id) or est.deleted_at:
        raise HTTPException(404, "Строка сметы не найдена")
    _ensure_work_estimate(est)

    if body.fer_multiplier < 0 or body.fer_multiplier > 1000:
        raise HTTPException(400, "Множитель должен быть от 0 до 1000")

    est.fer_multiplier = round(float(body.fer_multiplier), 1)

    await db.commit()
    return {
        "id": est.id,
        "fer_multiplier": float(est.fer_multiplier),
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
    _ensure_work_estimate(est)

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
        "strategy": "manual" if est.fer_table_id is not None else None,
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
    _ensure_work_estimate(est)

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
    _ensure_work_estimate(est)

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
    _ensure_work_estimate(est)

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
    _ensure_work_estimate(est)

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
    _ensure_work_estimate(est)

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
    _ensure_work_estimate(est)

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
    _ensure_work_estimate(est)

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
