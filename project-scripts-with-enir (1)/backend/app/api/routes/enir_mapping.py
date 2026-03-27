"""
Роуты маппинга сметы → ЕНИР.

POST /projects/{pid}/enir-mapping/group/{task_id}   — маппинг одной группы
POST /projects/{pid}/enir-mapping/all               — маппинг всех групп

GET  /projects/{pid}/enir-mapping                   — текущее состояние маппинга

PATCH /projects/{pid}/enir-mapping/group/{id}/confirm    — подтвердить/изменить группу
PATCH /projects/{pid}/enir-mapping/estimate/{id}/confirm — подтвердить/изменить строку
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps          import require_action, get_db
from app.core.permissions  import Action
from app.models            import ProjectMember
from app.models.enir_mapping import EnirGroupMapping, EnirEstimateMapping
from app.models.gantt      import GanttTask
from app.models.estimate   import Estimate
from app.models.enir       import EnirCollection, EnirParagraph
from app.services.enir_mapping_service import (
    run_mapping_for_group,
    run_mapping_for_project,
    confirm_group_mapping,
    confirm_estimate_mapping,
)

import json

router = APIRouter(prefix="/projects/{project_id}/enir-mapping", tags=["enir-mapping"])


# ─── serializers ─────────────────────────────────────────────────────────────

def _ser_group(gmap: EnirGroupMapping, task: GanttTask | None, coll: EnirCollection | None) -> dict:
    return {
        "id":            gmap.id,
        "task_id":       gmap.task_id,
        "task_name":     task.name if task else None,
        "collection_id": gmap.collection_id,
        "collection_code":  coll.code  if coll else None,
        "collection_title": coll.title if coll else None,
        "status":        gmap.status,
        "confidence":    float(gmap.confidence) if gmap.confidence is not None else None,
        "ai_reasoning":  gmap.ai_reasoning,
        "alternatives":  json.loads(gmap.alternatives) if gmap.alternatives else [],
        "updated_at":    gmap.updated_at.isoformat(),
    }


def _ser_estimate(
    emap: EnirEstimateMapping,
    est: Estimate | None,
    para: EnirParagraph | None,
) -> dict:
    return {
        "id":              emap.id,
        "estimate_id":     emap.estimate_id,
        "work_name":       est.work_name if est else None,
        "unit":            est.unit      if est else None,
        "paragraph_id":    emap.paragraph_id,
        "paragraph_code":  para.code  if para else None,
        "paragraph_title": para.title if para else None,
        "norm_row_id":     emap.norm_row_id,
        "norm_row_hint":   emap.norm_row_hint,
        "status":          emap.status,
        "confidence":      float(emap.confidence) if emap.confidence is not None else None,
        "ai_reasoning":    emap.ai_reasoning,
        "alternatives":    json.loads(emap.alternatives) if emap.alternatives else [],
        "updated_at":      emap.updated_at.isoformat(),
    }


# ─── GET /enir-mapping ────────────────────────────────────────────────────────

@router.get("")
async def get_mapping_state(
    project_id: str,
    member: ProjectMember = Depends(require_action(Action.VIEW)),
    db: AsyncSession = Depends(get_db),
):
    """
    Текущее состояние всего маппинга проекта.
    Возвращает группы с вложенными estimate-маппингами.
    """
    gmaps = await db.execute(
        select(EnirGroupMapping)
        .where(EnirGroupMapping.project_id == project_id)
        .order_by(EnirGroupMapping.id)
    )
    gmaps = list(gmaps.scalars())

    result = []
    for gmap in gmaps:
        task = await db.get(GanttTask, gmap.task_id)
        coll = await db.get(EnirCollection, gmap.collection_id) if gmap.collection_id else None

        # estimate-маппинги этой группы
        emaps = await db.execute(
            select(EnirEstimateMapping)
            .where(EnirEstimateMapping.group_mapping_id == gmap.id)
            .order_by(EnirEstimateMapping.id)
        )
        emaps = list(emaps.scalars())

        est_list = []
        for emap in emaps:
            est  = await db.get(Estimate, emap.estimate_id)
            para = await db.get(EnirParagraph, emap.paragraph_id) if emap.paragraph_id else None
            est_list.append(_ser_estimate(emap, est, para))

        group_data = _ser_group(gmap, task, coll)
        group_data["estimates"] = est_list
        result.append(group_data)

    # статистика
    all_emaps = [e for g in result for e in g["estimates"]]
    return {
        "groups": result,
        "stats": {
            "groups_total":    len(result),
            "groups_confirmed": sum(1 for g in result if g["status"] == "confirmed"),
            "estimates_total":     len(all_emaps),
            "estimates_confirmed": sum(1 for e in all_emaps if e["status"] == "confirmed"),
            "estimates_suggested": sum(1 for e in all_emaps if e["status"] == "ai_suggested"),
            "estimates_missing":   sum(1 for e in all_emaps if e["paragraph_id"] is None),
        },
    }


# ─── POST /enir-mapping/group/{task_id} ──────────────────────────────────────

@router.post("/group/{task_id}")
async def map_group(
    project_id: str,
    task_id: str,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    """Запустить маппинг для одной группы задач (кнопка «Маппинг группы»)."""
    try:
        result = await run_mapping_for_group(project_id, task_id, db)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


# ─── POST /enir-mapping/all ───────────────────────────────────────────────────

@router.post("/all")
async def map_all_groups(
    project_id: str,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    """Запустить маппинг для всех верхних групп проекта (кнопка «Маппинг всей сметы»)."""
    try:
        result = await run_mapping_for_project(project_id, db)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


# ─── PATCH /enir-mapping/group/{id}/confirm ───────────────────────────────────

class GroupConfirmBody(BaseModel):
    collection_id: Optional[int] = None   # None = подтвердить текущий выбор ИИ


@router.patch("/group/{mapping_id}/confirm")
async def confirm_group(
    project_id: str,
    mapping_id: int,
    body: GroupConfirmBody,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    """Подтвердить или вручную исправить сборник для группы."""
    try:
        gmap = await confirm_group_mapping(mapping_id, body.collection_id, db)
    except ValueError as e:
        raise HTTPException(404, str(e))

    coll = await db.get(EnirCollection, gmap.collection_id) if gmap.collection_id else None
    task = await db.get(GanttTask, gmap.task_id)
    return _ser_group(gmap, task, coll)


# ─── PATCH /enir-mapping/estimate/{id}/confirm ────────────────────────────────

class EstimateConfirmBody(BaseModel):
    paragraph_id:  Optional[int] = None
    norm_row_id:   Optional[str] = None
    norm_row_hint: Optional[str] = None


@router.patch("/estimate/{mapping_id}/confirm")
async def confirm_estimate(
    project_id: str,
    mapping_id: int,
    body: EstimateConfirmBody,
    member: ProjectMember = Depends(require_action(Action.EDIT)),
    db: AsyncSession = Depends(get_db),
):
    """Подтвердить или вручную исправить параграф / строку нормы для строки сметы."""
    try:
        emap = await confirm_estimate_mapping(
            mapping_id,
            body.paragraph_id,
            body.norm_row_id,
            body.norm_row_hint,
            db,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

    est  = await db.get(Estimate, emap.estimate_id)
    para = await db.get(EnirParagraph, emap.paragraph_id) if emap.paragraph_id else None
    return _ser_estimate(emap, est, para)
