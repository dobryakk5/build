from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_action
from app.core.permissions import Action
from app.models import KtpEstimateSession, KtpWbsGroup, KtpWbsItem
from app.models.project import ProjectMember
from app.services import ktp_estimate_service as svc

router = APIRouter(prefix="/projects/{project_id}/ktp-estimate", tags=["ktp-estimate"])


# ─────────────────────────────────────────────────────────────────────────────
# СХЕМЫ
# ─────────────────────────────────────────────────────────────────────────────

class SessionOut(BaseModel):
    id: str
    project_id: str
    estimate_batch_id: str
    status: str
    error_message: str | None = None
    stage1_job_id: str | None = None
    gpr_job_id: str | None = None

    @classmethod
    def of(cls, s: KtpEstimateSession) -> "SessionOut":
        return cls(
            id=s.id,
            project_id=s.project_id,
            estimate_batch_id=s.estimate_batch_id,
            status=s.status,
            error_message=s.error_message,
            stage1_job_id=s.stage1_job_id,
            gpr_job_id=s.gpr_job_id,
        )


class ItemOut(BaseModel):
    id: str
    group_id: str
    name: str
    sort_order: float
    origin: str
    estimate_id: str | None = None
    unit: str | None = None
    quantity: float | None = None
    quantity_source: str | None = None
    review_status: str
    ai_reason: str | None = None
    norm_source: str | None = None
    norm_kind: str | None = None
    norm_value: float | None = None
    norm_unit: str | None = None
    brigade_size: int | None = None
    labor_hours: float | None = None
    duration_days: int | None = None
    fer_table_id: int | None = None
    fer_row_id: int | None = None
    fer_match_source: str | None = None
    fer_match_score: float | None = None
    fer_h_hour: float | None = None
    fer_unit: str | None = None
    fer_unit_multiplier: float | None = None
    fer_match_label: str | None = None

    @classmethod
    def of(cls, it: KtpWbsItem) -> "ItemOut":
        fer_match_label = None
        if it.fer_match_candidates:
            for candidate in it.fer_match_candidates:
                if isinstance(candidate, dict) and candidate.get("table_id") == it.fer_table_id:
                    fer_match_label = candidate.get("work_type")
                    break
            if fer_match_label is None and isinstance(it.fer_match_candidates[0], dict):
                fer_match_label = it.fer_match_candidates[0].get("work_type")
        return cls(
            id=it.id,
            group_id=it.group_id,
            name=it.name,
            sort_order=float(it.sort_order),
            origin=it.origin,
            estimate_id=it.estimate_id,
            unit=it.unit,
            quantity=float(it.quantity) if it.quantity is not None else None,
            quantity_source=it.quantity_source,
            review_status=it.review_status,
            ai_reason=it.ai_reason,
            norm_source=it.norm_source,
            norm_kind=it.norm_kind,
            norm_value=float(it.norm_value) if it.norm_value is not None else None,
            norm_unit=it.norm_unit,
            brigade_size=it.brigade_size,
            labor_hours=float(it.labor_hours) if it.labor_hours is not None else None,
            duration_days=it.duration_days,
            fer_table_id=int(it.fer_table_id) if it.fer_table_id is not None else None,
            fer_row_id=int(it.fer_row_id) if it.fer_row_id is not None else None,
            fer_match_source=it.fer_match_source,
            fer_match_score=float(it.fer_match_score) if it.fer_match_score is not None else None,
            fer_h_hour=float(it.fer_h_hour) if it.fer_h_hour is not None else None,
            fer_unit=it.fer_unit,
            fer_unit_multiplier=float(it.fer_unit_multiplier) if it.fer_unit_multiplier is not None else None,
            fer_match_label=fer_match_label,
        )


class GroupOut(BaseModel):
    id: str
    title: str
    sort_order: float
    wt_code: str | None = None
    wt_name: str | None = None
    status: str
    start_date: str | None = None
    duration_days: int | None = None
    items: list[ItemOut] = Field(default_factory=list)

    @classmethod
    def of(cls, g: KtpWbsGroup) -> "GroupOut":
        return cls(
            id=g.id,
            title=g.title,
            sort_order=float(g.sort_order),
            wt_code=g.wt_code,
            wt_name=g.wt_name,
            status=g.status,
            start_date=str(g.start_date) if g.start_date else None,
            duration_days=g.duration_days,
            items=[ItemOut.of(it) for it in sorted(g.items, key=lambda x: float(x.sort_order))],
        )


class GroupDependencyOut(BaseModel):
    group_id: str
    depends_on_group_id: str


class SessionSubtypeOut(BaseModel):
    id: str
    subtype_code: str
    subtype_name: str
    macro_name: str | None = None
    unit: str | None = None
    volume: float | None = None
    output_per_day: float | None = None
    crew_size: int | None = None
    lag_after_days: int = 0
    output_source: str = "default"
    crew_source: str = "default"
    lag_source: str = "default"

    @classmethod
    def of(cls, s) -> "SessionSubtypeOut":
        return cls(
            id=s.id,
            subtype_code=s.subtype_code,
            subtype_name=s.subtype_name,
            macro_name=s.macro_name,
            unit=s.unit,
            volume=float(s.volume) if s.volume is not None else None,
            output_per_day=float(s.output_per_day) if s.output_per_day is not None else None,
            crew_size=s.crew_size,
            lag_after_days=int(s.lag_after_days or 0),
            output_source=s.output_source,
            crew_source=s.crew_source,
            lag_source=s.lag_source,
        )


class WbsOut(BaseModel):
    session: SessionOut
    groups: list[GroupOut]
    group_dependencies: list[GroupDependencyOut]
    session_subtypes: list[SessionSubtypeOut] = Field(default_factory=list)

    @classmethod
    def of(cls, payload: dict) -> "WbsOut":
        return cls(
            session=SessionOut.of(payload["session"]),
            groups=[GroupOut.of(g) for g in payload["groups"]],
            group_dependencies=[
                GroupDependencyOut(
                    group_id=d.group_id, depends_on_group_id=d.depends_on_group_id
                )
                for d in payload["group_dependencies"]
            ],
            session_subtypes=[
                SessionSubtypeOut.of(s) for s in payload.get("session_subtypes", [])
            ],
        )


class CardOut(BaseModel):
    id: str
    title: str | None = None
    goal: str | None = None
    steps: list[dict] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    status: str
    questions_json: list[dict] | None = None


class StartSessionRequest(BaseModel):
    estimate_batch_id: str
    force: bool = False


class StartSessionResponse(BaseModel):
    job_id: str | None = None
    session_id: str
    status: str


class ItemPatch(BaseModel):
    name: str | None = None
    group_id: str | None = None
    review_status: str | None = None
    unit: str | None = None
    quantity: float | None = None
    sort_order: float | None = None


class CreateItemRequest(BaseModel):
    name: str
    unit: str | None = None
    quantity: float | None = None


class GroupPatch(BaseModel):
    title: str | None = None
    sort_order: float | None = None
    wt_code: str | None = None


class CreateGroupRequest(BaseModel):
    title: str


class GenerateCardRequest(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


class GenerateCardResponse(BaseModel):
    sufficient: bool
    questions: list[dict] = Field(default_factory=list)
    group_id: str | None = None
    card: CardOut | None = None


class CardPatch(BaseModel):
    title: str | None = None
    goal: str | None = None
    steps: list[dict] | None = None
    recommendations: list[str] | None = None


class BuildGprResponse(BaseModel):
    job_id: str


class FerJobResponse(BaseModel):
    job_id: str


class ItemFerPatch(BaseModel):
    fer_table_id: int | None = None


class SessionSubtypePatch(BaseModel):
    volume: float | None = None
    output_per_day: float | None = None
    crew_size: int | None = None
    lag_after_days: int | None = None


def _value_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    code = 404 if "не найден" in detail or "не найдена" in detail else 422
    return HTTPException(status_code=code, detail=detail)


# ─────────────────────────────────────────────────────────────────────────────
# ЭТАП 1 — СЕАНС И WBS
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/sessions", response_model=StartSessionResponse)
async def start_session(
    project_id: UUID,
    body: StartSessionRequest,
    db: AsyncSession = Depends(get_db),
    member: ProjectMember = Depends(require_action(Action.EDIT)),
):
    try:
        job, session = await svc.start_stage1_job(
            db,
            project_id=str(project_id),
            estimate_batch_id=body.estimate_batch_id,
            user_id=member.user_id,
            force=body.force,
        )
    except ValueError as exc:
        raise _value_error(exc)
    # если новый job не создан, но сеанс ещё обрабатывается — отдаём
    # его сохранённый job_id, чтобы фронт сразу подхватил поллинг
    job_id = job.id if job else None
    if job_id is None and session.status in {"stage1_pending", "stage1_processing"}:
        job_id = session.stage1_job_id
    return StartSessionResponse(
        job_id=job_id,
        session_id=session.id,
        status=session.status,
    )


@router.get("/sessions", response_model=SessionOut | None)
async def get_session(
    project_id: UUID,
    estimate_batch_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.VIEW)),
):
    session = await svc.get_session(db, str(project_id), estimate_batch_id)
    return SessionOut.of(session) if session else None


@router.get("/sessions/{session_id}/wbs", response_model=WbsOut)
async def get_wbs(
    project_id: UUID,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.VIEW)),
):
    try:
        payload = await svc.get_wbs(db, str(project_id), str(session_id))
    except ValueError as exc:
        raise _value_error(exc)
    return WbsOut.of(payload)


@router.delete("/sessions/{session_id}", status_code=204)
async def reset_session(
    project_id: UUID,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        await svc.reset_session(db, str(project_id), str(session_id))
    except ValueError as exc:
        raise _value_error(exc)
    return None


@router.patch("/items/{item_id}", response_model=WbsOut)
async def patch_item(
    project_id: UUID,
    item_id: UUID,
    body: ItemPatch,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        payload = await svc.update_item(
            db, str(project_id), str(item_id), body.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise _value_error(exc)
    return WbsOut.of(payload)


@router.post("/groups/{group_id}/items", response_model=WbsOut)
async def add_item(
    project_id: UUID,
    group_id: UUID,
    body: CreateItemRequest,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        payload = await svc.create_item(
            db, str(project_id), str(group_id), body.model_dump()
        )
    except ValueError as exc:
        raise _value_error(exc)
    return WbsOut.of(payload)


@router.delete("/items/{item_id}", response_model=WbsOut)
async def remove_item(
    project_id: UUID,
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        payload = await svc.delete_item(db, str(project_id), str(item_id))
    except ValueError as exc:
        raise _value_error(exc)
    return WbsOut.of(payload)


@router.post("/sessions/{session_id}/groups", response_model=WbsOut)
async def add_group(
    project_id: UUID,
    session_id: UUID,
    body: CreateGroupRequest,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        payload = await svc.create_group(
            db, str(project_id), str(session_id), body.model_dump()
        )
    except ValueError as exc:
        raise _value_error(exc)
    return WbsOut.of(payload)


@router.patch("/groups/{group_id}", response_model=WbsOut)
async def patch_group(
    project_id: UUID,
    group_id: UUID,
    body: GroupPatch,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        payload = await svc.update_group(
            db, str(project_id), str(group_id), body.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise _value_error(exc)
    return WbsOut.of(payload)


@router.delete("/groups/{group_id}", response_model=WbsOut)
async def remove_group(
    project_id: UUID,
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        payload = await svc.delete_group(db, str(project_id), str(group_id))
    except ValueError as exc:
        raise _value_error(exc)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return WbsOut.of(payload)


@router.post("/sessions/{session_id}/approve-stage1", response_model=SessionOut)
async def approve_stage1(
    project_id: UUID,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        session = await svc.approve_stage1(db, str(project_id), str(session_id))
    except ValueError as exc:
        raise _value_error(exc)
    return SessionOut.of(session)


# ─────────────────────────────────────────────────────────────────────────────
# ЭТАП 2 — КАРТОЧКИ
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/groups/{group_id}/generate-card", response_model=GenerateCardResponse)
async def generate_card(
    project_id: UUID,
    group_id: UUID,
    body: GenerateCardRequest,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        result = await svc.generate_card_for_wbs_group(
            db, str(project_id), str(group_id), body.answers or None
        )
    except ValueError as exc:
        raise _value_error(exc)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Ошибка генерации: {exc}")

    if not result["sufficient"]:
        return GenerateCardResponse(sufficient=False, questions=result["questions"])
    return GenerateCardResponse(
        sufficient=True,
        group_id=result["group_id"],
        card=CardOut(**result["card"]),
    )


@router.get("/groups/{group_id}/card", response_model=CardOut)
async def get_card(
    project_id: UUID,
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.VIEW)),
):
    try:
        card = await svc.get_card(db, str(project_id), str(group_id))
    except ValueError as exc:
        raise _value_error(exc)
    return CardOut(**card)


@router.patch("/groups/{group_id}/card", response_model=CardOut)
async def patch_card(
    project_id: UUID,
    group_id: UUID,
    body: CardPatch,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        card = await svc.update_card(
            db, str(project_id), str(group_id), body.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise _value_error(exc)
    return CardOut(**card)


@router.post("/sessions/{session_id}/approve-stage2", response_model=SessionOut)
async def approve_stage2(
    project_id: UUID,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        session = await svc.approve_stage2(db, str(project_id), str(session_id))
    except ValueError as exc:
        raise _value_error(exc)
    return SessionOut.of(session)


# ─────────────────────────────────────────────────────────────────────────────
# ЭТАП 4 — ПРОИЗВОДИТЕЛЬНОСТЬ ПО ПОДТИПАМ РАБОТ
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/build-subtypes", response_model=WbsOut)
async def build_subtypes(
    project_id: UUID,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        payload = await svc.rebuild_session_subtypes(
            db, str(project_id), str(session_id)
        )
    except ValueError as exc:
        raise _value_error(exc)
    return WbsOut.of(payload)


@router.patch("/session-subtypes/{subtype_id}", response_model=WbsOut)
async def patch_session_subtype(
    project_id: UUID,
    subtype_id: UUID,
    body: SessionSubtypePatch,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        payload = await svc.update_session_subtype(
            db, str(project_id), str(subtype_id), body.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise _value_error(exc)
    return WbsOut.of(payload)


@router.post("/sessions/{session_id}/approve-prod", response_model=SessionOut)
async def approve_prod(
    project_id: UUID,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        session = await svc.approve_prod(db, str(project_id), str(session_id))
    except ValueError as exc:
        raise _value_error(exc)
    return SessionOut.of(session)


# ─────────────────────────────────────────────────────────────────────────────
# ЭТАП 2.5 — НАЗНАЧЕНИЕ ФЕР (legacy, выведено из потока)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/match-fer", response_model=FerJobResponse)
async def match_fer(
    project_id: UUID,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    member: ProjectMember = Depends(require_action(Action.EDIT)),
):
    try:
        job = await svc.start_fer_match_job(
            db,
            str(project_id),
            str(session_id),
            member.user_id,
        )
    except ValueError as exc:
        raise _value_error(exc)
    return FerJobResponse(job_id=job.id)


@router.post("/sessions/{session_id}/approve-fer", response_model=SessionOut)
async def approve_fer(
    project_id: UUID,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        session = await svc.approve_fer_matches(db, str(project_id), str(session_id))
    except ValueError as exc:
        raise _value_error(exc)
    return SessionOut.of(session)


@router.patch("/items/{item_id}/fer", response_model=WbsOut)
async def patch_item_fer(
    project_id: UUID,
    item_id: UUID,
    body: ItemFerPatch,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        payload = await svc.update_item_fer(
            db,
            str(project_id),
            str(item_id),
            body.fer_table_id,
        )
    except ValueError as exc:
        raise _value_error(exc)
    return WbsOut.of(payload)


@router.post("/items/{item_id}/match-fer", response_model=WbsOut)
async def match_item_fer(
    project_id: UUID,
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        payload = await svc.auto_match_item_fer(db, str(project_id), str(item_id))
    except ValueError as exc:
        raise _value_error(exc)
    return WbsOut.of(payload)


# ─────────────────────────────────────────────────────────────────────────────
# ЭТАП 3 — ПОСЛЕДОВАТЕЛЬНОСТЬ ГРУПП (2-й уровень) + ГПР
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/propose-sequence", response_model=WbsOut)
async def propose_sequence(
    project_id: UUID,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        payload = await svc.propose_group_sequence(
            db, str(project_id), str(session_id)
        )
    except ValueError as exc:
        raise _value_error(exc)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Ошибка построения последовательности: {exc}")
    return WbsOut.of(payload)


@router.post("/sessions/{session_id}/approve-sequence", response_model=SessionOut)
async def approve_sequence(
    project_id: UUID,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        session = await svc.approve_group_sequence(
            db, str(project_id), str(session_id)
        )
    except ValueError as exc:
        raise _value_error(exc)
    return SessionOut.of(session)


@router.post("/sessions/{session_id}/build-gpr", response_model=BuildGprResponse)
async def build_gpr(
    project_id: UUID,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    member: ProjectMember = Depends(require_action(Action.EDIT)),
):
    from app.services import ktp_gpr_service

    try:
        job = await ktp_gpr_service.start_gpr_job(
            db,
            project_id=str(project_id),
            session_id=str(session_id),
            user_id=member.user_id,
        )
    except ValueError as exc:
        raise _value_error(exc)
    return BuildGprResponse(job_id=job.id)
