from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_action
from app.core.permissions import Action
from app.models.ktp import KtpGroup
from app.services.ktp_service import (
    build_ktp_groups_for_batch,
    generate_ktp_for_group,
    get_ktp_card,
    get_ktp_groups,
)

router = APIRouter(prefix="/projects/{project_id}/ktp", tags=["ktp"])


class KtpQuestionOut(BaseModel):
    key: str
    label: str
    type: str
    hint: str | None = None
    options: list[str] | None = None


class KtpStepOut(BaseModel):
    no: int
    stage: str
    work_details: str
    control_points: str


class KtpCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str | None
    goal: str | None
    steps: list[KtpStepOut]
    recommendations: list[str]
    status: str
    questions_json: list[KtpQuestionOut] | None = None


class KtpGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    estimate_batch_id: str
    group_key: str
    title: str
    row_count: int
    total_price: float | None
    sort_order: int
    status: str
    ktp_card_id: str | None = None


class KtpGroupDetailOut(BaseModel):
    group: KtpGroupOut
    card: KtpCardOut | None


class BuildGroupsRequest(BaseModel):
    estimate_batch_id: str
    force: bool = False


class GenerateRequest(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


class GenerateResponse(BaseModel):
    sufficient: bool
    questions: list[KtpQuestionOut] = Field(default_factory=list)
    ktp_card_id: str | None = None
    ktp: KtpCardOut | None = None


def _group_to_out(group: KtpGroup) -> KtpGroupOut:
    return KtpGroupOut(
        id=group.id,
        project_id=group.project_id,
        estimate_batch_id=group.estimate_batch_id,
        group_key=group.group_key,
        title=group.title,
        row_count=group.row_count,
        total_price=float(group.total_price) if group.total_price is not None else None,
        sort_order=group.sort_order,
        status=group.status,
        ktp_card_id=group.ktp_card.id if group.ktp_card else None,
    )


def _card_to_out(card) -> KtpCardOut | None:
    if not card:
        return None
    return KtpCardOut(
        id=card.id,
        title=card.title,
        goal=card.goal,
        steps=[KtpStepOut(**step) for step in (card.steps_json or [])],
        recommendations=list(card.recommendations_json or []),
        status=card.status,
        questions_json=[KtpQuestionOut(**q) for q in (card.questions_json or [])] or None,
    )


@router.get("/groups", response_model=list[KtpGroupOut])
async def list_ktp_groups(
    project_id: UUID,
    estimate_batch_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.VIEW)),
):
    groups = await get_ktp_groups(db, str(project_id), estimate_batch_id)
    return [_group_to_out(group) for group in groups]


@router.post("/groups/build", response_model=list[KtpGroupOut])
async def build_groups(
    project_id: UUID,
    body: BuildGroupsRequest,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        groups = await build_ktp_groups_for_batch(
            db,
            project_id=str(project_id),
            estimate_batch_id=body.estimate_batch_id,
            force=body.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return [_group_to_out(group) for group in groups]


@router.get("/groups/{group_id}", response_model=KtpGroupDetailOut)
async def get_group_detail(
    project_id: UUID,
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.VIEW)),
):
    group = await db.scalar(
        select(KtpGroup)
        .where(KtpGroup.id == str(group_id))
        .where(KtpGroup.project_id == str(project_id))
    )
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")

    return KtpGroupDetailOut(
        group=_group_to_out(group),
        card=_card_to_out(group.ktp_card),
    )


@router.post("/groups/{group_id}/generate", response_model=GenerateResponse)
async def generate_ktp(
    project_id: UUID,
    group_id: UUID,
    body: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    try:
        result = await generate_ktp_for_group(
            db,
            project_id=str(project_id),
            group_id=str(group_id),
            answers=body.answers or None,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "не найден" in detail or "не найдена" in detail else 502
        raise HTTPException(status_code=status_code, detail=detail)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ошибка генерации: {exc}")

    if not result["sufficient"]:
        return GenerateResponse(
            sufficient=False,
            questions=[KtpQuestionOut(**q) for q in result["questions"]],
        )

    return GenerateResponse(
        sufficient=True,
        ktp_card_id=result["ktp_card_id"],
        ktp=KtpCardOut(**result["ktp"]),
    )


@router.get("/groups/{group_id}/card", response_model=KtpCardOut)
async def get_card(
    project_id: UUID,
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.VIEW)),
):
    try:
        card = await get_ktp_card(db, str(project_id), str(group_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if not card:
        raise HTTPException(status_code=404, detail="КТП ещё не создана")
    return _card_to_out(card)
