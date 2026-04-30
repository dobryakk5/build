# backend/app/api/routes/ktp.py
"""
HTTP-роутер для КТП.

Все эндпоинты:
- принадлежность batch/group к project_id проверяется в сервисе
- права проверяются через require_action (как в estimates.py)
- path-параметр называется project_id (как требует get_project_member в deps.py)
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
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


# ─── Pydantic schemas ────────────────────────────────────────────────────────

class KtpGroupOut(BaseModel):
    id: str
    project_id: str
    estimate_batch_id: str
    group_key: str
    title: str
    row_count: int
    total_price: float | None
    sort_order: int
    status: str  # new | questions_required | generated | failed
    ktp_card_id: str | None = None

    class Config:
        from_attributes = True


class BuildGroupsRequest(BaseModel):
    estimate_batch_id: str
    force: bool = False


class KtpStepOut(BaseModel):
    no: int
    stage: str
    work_details: str
    control_points: str


class KtpCardOut(BaseModel):
    id: str
    title: str | None
    goal: str | None
    steps: list[KtpStepOut]
    recommendations: list[str]
    status: str


class KtpQuestionOut(BaseModel):
    key: str
    label: str
    type: str
    hint: str | None = None
    options: list[str] | None = None


class GenerateRequest(BaseModel):
    answers: dict[str, str] = {}


class GenerateResponse(BaseModel):
    sufficient: bool
    questions: list[KtpQuestionOut] = []
    ktp_card_id: str | None = None
    ktp: KtpCardOut | None = None


class KtpGroupDetailOut(BaseModel):
    group: KtpGroupOut
    card: KtpCardOut | None


# ─── Converters ──────────────────────────────────────────────────────────────

def _group_to_out(g: KtpGroup) -> KtpGroupOut:
    card_id = g.ktp_card.id if g.ktp_card else None
    return KtpGroupOut(
        id=g.id,
        project_id=g.project_id,
        estimate_batch_id=g.estimate_batch_id,
        group_key=g.group_key,
        title=g.title,
        row_count=g.row_count,
        total_price=float(g.total_price) if g.total_price is not None else None,
        sort_order=g.sort_order,
        status=g.status,
        ktp_card_id=card_id,
    )


def _card_to_out(card) -> KtpCardOut | None:
    if not card:
        return None
    return KtpCardOut(
        id=card.id,
        title=card.title,
        goal=card.goal,
        steps=[KtpStepOut(**s) for s in (card.steps_json or [])],
        recommendations=card.recommendations_json or [],
        status=card.status,
    )


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/groups", response_model=list[KtpGroupOut])
async def list_ktp_groups(
    project_id: UUID,
    estimate_batch_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.VIEW)),
):
    """Список групп КТП для батча (без построения). Идемпотентный GET."""
    groups = await get_ktp_groups(db, str(project_id), estimate_batch_id)
    return [_group_to_out(g) for g in groups]


@router.post("/groups/build", response_model=list[KtpGroupOut])
async def build_groups(
    project_id: UUID,
    body: BuildGroupsRequest,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.EDIT)),
):
    """
    Построить или обновить группы работ по батчу.

    Идемпотентно при force=False: если группы уже есть — возвращает их.
    force=True пересобирает с нуля (существующие КТП удаляются каскадно).
    """
    try:
        groups = await build_ktp_groups_for_batch(
            db,
            project_id=str(project_id),
            estimate_batch_id=body.estimate_batch_id,
            force=body.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return [_group_to_out(g) for g in groups]


@router.get("/groups/{group_id}", response_model=KtpGroupDetailOut)
async def get_group_detail(
    project_id: UUID,
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.VIEW)),
):
    """Получить группу и её КТП (если уже создана)."""
    group = await db.scalar(
        select(KtpGroup)
        .where(KtpGroup.id == str(group_id))
        .where(KtpGroup.project_id == str(project_id))
    )
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")

    # ktp_card уже загружен через selectin на модели
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
    """
    Сгенерировать КТП для группы.

    Если LLM считает данных недостаточно — возвращает список вопросов.
    Повторный вызов с answers завершает генерацию.
    """
    try:
        result = await generate_ktp_for_group(
            db,
            project_id=str(project_id),
            group_id=str(group_id),
            answers=body.answers or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ошибка генерации: {exc}")

    if not result["sufficient"]:
        return GenerateResponse(
            sufficient=False,
            questions=[KtpQuestionOut(**q) for q in result["questions"]],
        )

    ktp = result["ktp"]
    return GenerateResponse(
        sufficient=True,
        ktp_card_id=result["ktp_card_id"],
        ktp=KtpCardOut(
            id=result["ktp_card_id"],
            title=ktp["title"],
            goal=ktp["goal"],
            steps=[KtpStepOut(**s) for s in ktp["steps"]],
            recommendations=ktp["recommendations"],
            status="generated",
        ),
    )


@router.get("/groups/{group_id}/card", response_model=KtpCardOut)
async def get_card(
    project_id: UUID,
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    _member=Depends(require_action(Action.VIEW)),
):
    """Получить сохранённую КТП для группы."""
    try:
        card = await get_ktp_card(db, str(project_id), str(group_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if not card:
        raise HTTPException(status_code=404, detail="КТП ещё не создана")
    return _card_to_out(card)
