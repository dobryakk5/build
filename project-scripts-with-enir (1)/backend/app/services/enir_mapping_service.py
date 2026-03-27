"""
app/services/enir_mapping_service.py

Оркестрация двухэтапного маппинга.
Вызывается из роута, пишет результаты в БД.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enir        import EnirCollection, EnirParagraph
from app.models.enir_mapping import EnirGroupMapping, EnirEstimateMapping
from app.models.gantt       import GanttTask
from app.models.estimate    import Estimate
from app.services.enir_mapping_ai import map_group_to_collection, map_estimate_to_paragraph

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────────────────────────────────

async def _get_top_groups(project_id: str, db: AsyncSession) -> list[GanttTask]:
    """Верхние группы проекта (is_group=True, parent_id=NULL)."""
    result = await db.execute(
        select(GanttTask)
        .where(GanttTask.project_id == project_id)
        .where(GanttTask.is_group   == True)
        .where(GanttTask.parent_id  == None)
        .where(GanttTask.deleted_at == None)
        .order_by(GanttTask.row_order)
    )
    return list(result.scalars())


async def _get_group_estimates(task_id: str, db: AsyncSession) -> list[Estimate]:
    """
    Строки сметы, привязанные к задачам внутри группы.
    Сначала собираем все task_id дерева (рекурсивно через parent_id),
    потом берём estimates через estimate_id задач.
    """
    # рекурсивный CTE для всего поддерева
    tree_cte = (
        select(GanttTask.id)
        .where(GanttTask.id == task_id)
        .cte(name="subtree", recursive=True)
    )
    child = select(GanttTask.id).join(tree_cte, GanttTask.parent_id == tree_cte.c.id)
    tree_cte = tree_cte.union_all(child)

    # все задачи поддерева с estimate_id
    tasks = await db.execute(
        select(GanttTask)
        .where(GanttTask.id.in_(select(tree_cte.c.id)))
        .where(GanttTask.estimate_id != None)
        .where(GanttTask.deleted_at  == None)
    )
    task_list = list(tasks.scalars())

    if not task_list:
        return []

    estimate_ids = [t.estimate_id for t in task_list]
    estimates = await db.execute(
        select(Estimate)
        .where(Estimate.id.in_(estimate_ids))
        .where(Estimate.deleted_at == None)
        .order_by(Estimate.row_order)
    )
    return list(estimates.scalars())


async def _all_collections(db: AsyncSession) -> list[dict]:
    rows = await db.execute(
        select(EnirCollection).order_by(EnirCollection.sort_order, EnirCollection.code)
    )
    return [
        {"id": c.id, "code": c.code, "title": c.title, "description": c.description}
        for c in rows.scalars()
    ]


async def _paragraphs_for_collection(collection_id: int, db: AsyncSession) -> list[dict]:
    rows = await db.execute(
        select(EnirParagraph)
        .where(EnirParagraph.collection_id == collection_id)
        .order_by(EnirParagraph.sort_order)
    )
    return [
        {"id": p.id, "code": p.code, "title": p.title, "unit": p.unit}
        for p in rows.scalars()
    ]


def _upsert_group_mapping(
    db: AsyncSession,
    existing: EnirGroupMapping | None,
    project_id: str,
    task_id: str,
    ai_result: dict,
) -> EnirGroupMapping:
    """Создаёт или обновляет запись group_mapping."""
    if existing is None:
        existing = EnirGroupMapping(project_id=project_id, task_id=task_id)
        db.add(existing)

    existing.collection_id = ai_result.get("collection_id")
    existing.status        = "ai_suggested"
    existing.confidence    = ai_result.get("confidence")
    existing.ai_reasoning  = ai_result.get("reasoning")
    existing.alternatives  = json.dumps(ai_result.get("alternatives", []), ensure_ascii=False)
    return existing


def _upsert_estimate_mapping(
    db: AsyncSession,
    existing: EnirEstimateMapping | None,
    project_id: str,
    group_mapping_id: int,
    estimate_id: str,
    ai_result: dict,
) -> EnirEstimateMapping:
    """Создаёт или обновляет запись estimate_mapping."""
    if existing is None:
        existing = EnirEstimateMapping(
            project_id=project_id,
            group_mapping_id=group_mapping_id,
            estimate_id=estimate_id,
        )
        db.add(existing)

    existing.paragraph_id  = ai_result.get("paragraph_id")
    existing.norm_row_id   = ai_result.get("norm_row_id")
    existing.norm_row_hint = ai_result.get("norm_row_hint", "")
    existing.status        = "ai_suggested"
    existing.confidence    = ai_result.get("confidence")
    existing.ai_reasoning  = ai_result.get("reasoning")
    existing.alternatives  = json.dumps(ai_result.get("alternatives", []), ensure_ascii=False)
    return existing


# ─────────────────────────────────────────────────────────────────────────────
# Публичное API сервиса
# ─────────────────────────────────────────────────────────────────────────────

async def run_mapping_for_group(
    project_id: str,
    task_id: str,
    db: AsyncSession,
) -> dict:
    """
    Маппинг одной группы:
      1. group → collection  (ИИ)
      2. каждый estimate → paragraph (ИИ)

    Возвращает сводку: {group_mapping_id, collection_id, estimates_mapped, estimates_failed}
    """
    collections = await _all_collections(db)
    if not collections:
        raise RuntimeError("ЕНИР не загружен — нет сборников в БД")

    task = await db.get(GanttTask, task_id)
    if not task:
        raise ValueError(f"Задача {task_id} не найдена")

    estimates = await _get_group_estimates(task_id, db)
    sample    = [e.work_name for e in estimates[:10]]

    # ── Этап 1: группа → сборник ──────────────────────────────────────────
    log.info("Stage 1: mapping group '%s' → collection", task.name)
    ai1 = await map_group_to_collection(task.name, sample, collections)

    existing_gmap = await db.scalar(
        select(EnirGroupMapping).where(EnirGroupMapping.task_id == task_id)
    )
    gmap = _upsert_group_mapping(db, existing_gmap, project_id, task_id, ai1)
    await db.flush()  # нужен gmap.id для этапа 2

    if not ai1.get("collection_id"):
        await db.commit()
        return {
            "group_mapping_id": gmap.id,
            "collection_id": None,
            "estimates_mapped": 0,
            "estimates_failed": len(estimates),
            "warning": "Сборник ЕНИР не определён — маппинг строк пропущен",
        }

    # ── Этап 2: каждая строка сметы → параграф ───────────────────────────
    collection_id = ai1["collection_id"]
    coll = next(c for c in collections if c["id"] == collection_id)
    paragraphs = await _paragraphs_for_collection(collection_id, db)

    mapped = 0
    failed = 0

    for est in estimates:
        log.info("Stage 2: mapping estimate '%s'", est.work_name[:60])
        try:
            ai2 = await map_estimate_to_paragraph(
                work_name        = est.work_name,
                unit             = est.unit,
                collection_code  = coll["code"],
                collection_title = coll["title"],
                paragraphs       = paragraphs,
            )
        except Exception as e:
            log.error("AI failed for estimate %s: %s", est.id, e)
            ai2 = {
                "paragraph_id":   None,
                "paragraph_code": None,
                "confidence":     0.0,
                "reasoning":      f"Ошибка ИИ: {e}",
                "norm_row_id":    None,
                "norm_row_hint":  "",
                "alternatives":   [],
            }
            failed += 1
        else:
            mapped += 1

        existing_emap = await db.scalar(
            select(EnirEstimateMapping)
            .where(EnirEstimateMapping.estimate_id == est.id)
        )
        _upsert_estimate_mapping(db, existing_emap, project_id, gmap.id, est.id, ai2)

    await db.commit()

    return {
        "group_mapping_id": gmap.id,
        "collection_id": collection_id,
        "collection_code": coll["code"],
        "estimates_mapped": mapped,
        "estimates_failed": failed,
    }


async def run_mapping_for_project(
    project_id: str,
    db: AsyncSession,
) -> dict:
    """
    Маппинг всех верхних групп проекта последовательно.
    Возвращает сводку по каждой группе.
    """
    groups = await _get_top_groups(project_id, db)
    if not groups:
        raise ValueError("В проекте нет верхних групп задач")

    results = []
    for group in groups:
        try:
            res = await run_mapping_for_group(project_id, group.id, db)
            results.append({"task_id": group.id, "task_name": group.name, **res})
        except Exception as e:
            log.error("Mapping failed for group %s: %s", group.id, e)
            results.append({
                "task_id":   group.id,
                "task_name": group.name,
                "error":     str(e),
            })

    return {
        "groups_total":  len(groups),
        "groups_ok":     sum(1 for r in results if "error" not in r),
        "groups_failed": sum(1 for r in results if "error" in r),
        "results":       results,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Подтверждение / отклонение / ручной выбор
# ─────────────────────────────────────────────────────────────────────────────

async def confirm_group_mapping(
    mapping_id: int,
    collection_id: int | None,
    db: AsyncSession,
) -> EnirGroupMapping:
    """Пользователь подтверждает или меняет сборник вручную."""
    gmap = await db.get(EnirGroupMapping, mapping_id)
    if not gmap:
        raise ValueError(f"GroupMapping {mapping_id} не найден")

    if collection_id is not None and collection_id != gmap.collection_id:
        gmap.collection_id = collection_id
        gmap.status        = "manual"
    else:
        gmap.status = "confirmed"

    await db.commit()
    return gmap


async def confirm_estimate_mapping(
    mapping_id: int,
    paragraph_id: int | None,
    norm_row_id: str | None,
    norm_row_hint: str | None,
    db: AsyncSession,
) -> EnirEstimateMapping:
    """Пользователь подтверждает или меняет параграф/строку нормы вручную."""
    emap = await db.get(EnirEstimateMapping, mapping_id)
    if not emap:
        raise ValueError(f"EstimateMapping {mapping_id} не найден")

    changed = False
    if paragraph_id is not None and paragraph_id != emap.paragraph_id:
        emap.paragraph_id = paragraph_id
        changed = True
    if norm_row_id is not None:
        emap.norm_row_id = norm_row_id
        changed = True
    if norm_row_hint is not None:
        emap.norm_row_hint = norm_row_hint

    emap.status = "manual" if changed else "confirmed"
    await db.commit()
    return emap
