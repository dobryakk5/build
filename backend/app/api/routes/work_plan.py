"""
План работ (КТП проекта) — CRUD и автогенерация.
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from datetime import date as _date
from app.services import project_work_plan_service as pwp_service
from app.services import nw_palette_service
from app.services import narrow_fer_matcher
from app.services import gantt_from_plan_service

router = APIRouter(
    prefix="/projects/{project_id}/batches/{batch_id}/work-plan",
    tags=["work-plan"],
)


# ─── Схемы запроса ───
class CardUpdate(BaseModel):
    object_type_code:         str | None = None
    building_technology_code: str | None = None
    location_scope_code:      str | None = None
    stage_code:               str | None = None
    is_capital_repair:        bool | None = None
    unit:                     str | None = None
    quantity:                 float | None = None
    workers_count:            int | None = None
    status:                   str | None = None
    notes:                    str | None = None


class CardCreate(BaseModel):
    nw_item_code: str
    unit:         str | None = None
    quantity:     float | None = None
    notes:        str | None = None
    estimate_ids: list[str] | None = None  # сразу привязать строки сметы
    source_label: str | None = None        # для ручной карточки опциональный заголовок


class LinkEstimates(BaseModel):
    estimate_ids: list[str]


class BuildGantt(BaseModel):
    start_date: _date
    hours_per_day: float | None = None
    replace: bool = False


class SetFerRow(BaseModel):
    fer_row_id: int | None = None  # None — сбросить выбор


class SetFerTable(BaseModel):
    fer_table_id: int | None = None  # None — сбросить назначение ФЕР


# ─── GET — текущий план ───
@router.get("")
async def get_work_plan(
    project_id: str,
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Получить план работ для batch'а."""
    plan = await pwp_service.get_plan(db, batch_id)
    return {"items": plan, "total": len(plan)}


# ─── GET — палитра NW для типа сметы ───
@router.get("/palette")
async def get_palette(
    project_id: str,
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Палитра NW которые ожидаются для типа сметы (для UI «возможно надо добавить»)."""
    from sqlalchemy import text as sa_text
    kind_row = (await db.execute(
        sa_text("SELECT estimate_kind FROM estimate_batches WHERE id = :id"),
        {"id": batch_id},
    )).mappings().first()
    if not kind_row:
        raise HTTPException(status_code=404, detail="batch not found")
    palette = await nw_palette_service.get_palette(db, int(kind_row["estimate_kind"]))
    wt_palette = await nw_palette_service.get_wt_palette(db, int(kind_row["estimate_kind"]))
    return {
        "estimate_kind": int(kind_row["estimate_kind"]),
        "wt_codes": wt_palette,
        "nw_items": palette,
    }


@router.get("/fer-scopes")
async def get_fer_scopes(
    project_id: str,
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Все ФЕР-разделы, доступные для типа загруженной сметы."""
    from sqlalchemy import text as sa_text

    rows = (await db.execute(
        sa_text(
            """
            SELECT
                eb.estimate_kind,
                wts.work_name,
                c.id AS collection_id,
                c.num AS collection_num,
                c.name AS collection_name,
                s.id AS section_id,
                s.title AS section_title
            FROM estimate_batches eb
            JOIN fer.work_type_sections wts ON wts.id = eb.estimate_kind
            JOIN fer.sections s ON s.id = ANY(wts.section_ids)
            JOIN fer.collections c ON c.id = s.collection_id
            WHERE eb.id = :batch_id
              AND eb.project_id = :project_id
              AND eb.deleted_at IS NULL
            ORDER BY c.num, s.title
            """
        ),
        {"batch_id": batch_id, "project_id": project_id},
    )).mappings().all()

    if not rows:
        raise HTTPException(status_code=404, detail="batch not found")

    first = rows[0]
    return {
        "estimate_kind": int(first["estimate_kind"]),
        "work_name": first["work_name"],
        "scopes": [
            {
                "collection_id": row["collection_id"],
                "collection_num": row["collection_num"],
                "collection_name": row["collection_name"],
                "section_id": row["section_id"],
                "section_title": row["section_title"],
            }
            for row in rows
        ],
    }


# ─── POST — автогенерация плана из сметы ───
@router.post("/auto")
async def auto_create_plan(
    project_id: str,
    batch_id: str,
    force: bool = Query(False, description="Пересоздать с нуля (удалить существующие карточки)"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Автогенерация плана работ из загруженной сметы (шаг 2 пайплайна)."""
    if force:
        from sqlalchemy import text as sa_text
        await db.execute(
            sa_text("DELETE FROM fer.project_work_plan WHERE estimate_batch_id = :id"),
            {"id": batch_id},
        )
        await db.commit()
    else:
        # Не пересоздавать если уже есть план
        existing = await pwp_service.get_plan(db, batch_id)
        if existing:
            raise HTTPException(
                status_code=409,
                detail="План уже существует. Используйте force=true для пересоздания.",
            )

    summary = await pwp_service.auto_create_from_estimate(
        db, batch_id, user_id=user.id,
    )
    return summary


# ─── GET /unmatched — строки сметы без привязки к плану ───
@router.get("/unmatched")
async def get_unmatched(
    project_id: str,
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = await pwp_service.get_unmatched_estimate_rows(db, batch_id)
    return {"items": rows, "total": len(rows)}


# ─── POST /{plan_id}/link-estimates — привязать строки сметы к карточке ───
@router.post("/{plan_id}/link-estimates")
async def link_estimates(
    project_id: str,
    batch_id: str,
    plan_id: int,
    body: LinkEstimates,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    n = await pwp_service.link_estimates_to_card(db, plan_id, body.estimate_ids)
    return {"plan_id": plan_id, "linked": n}


# ─── POST /llm-resolve — LLM-проход для unmatched ───
@router.post("/llm-resolve")
async def llm_resolve(
    project_id: str,
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    LLM-разбор строк сметы которые не привязаны к карточкам плана.
    Возвращает summary с counters.
    """
    summary = await pwp_service.llm_resolve_unmatched(db, batch_id, user_id=user.id)
    return summary


# ─── POST /{plan_id}/match-fer — узкий FER matcher для одной карточки ───
@router.post("/{plan_id}/match-fer")
async def match_card_fer(
    project_id: str,
    batch_id: str,
    plan_id: int,
    use_llm: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    res = await narrow_fer_matcher.match_card_to_fer(db, plan_id, use_llm=use_llm)
    if res.get("fer_table_id"):
        res["duration"] = await gantt_from_plan_service.compute_card_duration(db, plan_id)
        await db.commit()
    return res


# ─── POST /match-fer-all — узкий FER matcher для всех карточек батча ───
@router.post("/match-fer-all")
async def match_all_fer(
    project_id: str,
    batch_id: str,
    use_llm: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    summary = await narrow_fer_matcher.match_all_confirmed_cards(db, batch_id, use_llm=use_llm)
    summary["duration"] = await gantt_from_plan_service.compute_all_durations(db, batch_id)
    return summary


# ─── POST /{plan_id}/set-fer-table — ручное назначение / переназначение ФЕР ───
@router.post("/{plan_id}/set-fer-table")
async def set_fer_table(
    project_id: str,
    batch_id: str,
    plan_id: int,
    body: SetFerTable,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from sqlalchemy import text as sa_text

    card = (await db.execute(
        sa_text(
            """
            SELECT id
            FROM fer.project_work_plan
            WHERE id = :id AND estimate_batch_id = :batch_id
            """
        ),
        {"id": plan_id, "batch_id": batch_id},
    )).mappings().first()
    if not card:
        raise HTTPException(status_code=404, detail="plan card not found")

    table_row = None
    if body.fer_table_id is not None:
        table_row = (await db.execute(
            sa_text(
                """
                SELECT
                    t.id,
                    t.table_title,
                    (
                        COALESCE(c.ignored, FALSE)
                        OR COALESCE(s.ignored, FALSE)
                        OR COALESCE(ss.ignored, FALSE)
                        OR COALESCE(t.ignored, FALSE)
                    ) AS effective_ignored
                FROM fer.fer_tables t
                JOIN fer.collections c ON c.id = t.collection_id
                LEFT JOIN fer.sections s ON s.id = t.section_id
                LEFT JOIN fer.subsections ss ON ss.id = t.subsection_id
                WHERE t.id = :table_id
                """
            ),
            {"table_id": body.fer_table_id},
        )).mappings().first()
        if not table_row:
            raise HTTPException(status_code=404, detail="FER table not found")
        if table_row.get("effective_ignored"):
            raise HTTPException(status_code=400, detail="FER table is ignored")

    if table_row is None:
        await db.execute(
            sa_text(
                """
                UPDATE fer.project_work_plan
                SET fer_table_id = NULL,
                    fer_row_id = NULL,
                    fer_match_score = NULL,
                    fer_match_source = NULL,
                    fer_candidates = NULL,
                    fer_matched_at = NULL,
                    human_hours_per_unit = NULL,
                    duration_days = NULL,
                    status = 'needs_review',
                    updated_at = NOW()
                WHERE id = :id
                """
            ),
            {"id": plan_id},
        )
        await db.commit()
        return {"plan_id": plan_id, "fer_table_id": None, "fer_match_score": None, "fer_match_source": None}

    await db.execute(
        sa_text(
            """
            UPDATE fer.project_work_plan
            SET fer_table_id = :table_id,
                fer_row_id = NULL,
                fer_match_score = 1.0,
                fer_match_source = 'manual',
                fer_candidates = NULL,
                fer_matched_at = NOW(),
                human_hours_per_unit = NULL,
                duration_days = NULL,
                status = 'fer_mapped',
                updated_at = NOW()
            WHERE id = :id
            """
        ),
        {"id": plan_id, "table_id": int(table_row["id"])},
    )
    await db.commit()
    duration = await gantt_from_plan_service.compute_card_duration(db, plan_id)
    await db.commit()
    return {
        "plan_id": plan_id,
        "fer_table_id": int(table_row["id"]),
        "fer_table_title": table_row["table_title"],
        "fer_match_score": 1.0,
        "fer_match_source": "manual",
        "duration": duration,
    }


# ─── GET /{plan_id}/fer-rows — список строк FER таблицы карточки ───
@router.get("/{plan_id}/fer-rows")
async def get_card_fer_rows(
    project_id: str,
    batch_id: str,
    plan_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = await narrow_fer_matcher.get_fer_rows_for_card(db, plan_id)
    return {"items": rows, "total": len(rows)}


# ─── GET /{plan_id}/details — карточка + связанные строки сметы ───
@router.get("/{plan_id}/details")
async def get_card_detail(
    project_id: str,
    batch_id: str,
    plan_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await pwp_service.get_card_detail(db, batch_id, plan_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─── POST /{plan_id}/set-fer-row — установить fer_row_id и пересчитать длительность ───
@router.post("/{plan_id}/set-fer-row")
async def set_fer_row(
    project_id: str,
    batch_id: str,
    plan_id: int,
    body: SetFerRow,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from sqlalchemy import text as sa_text
    await db.execute(
        sa_text("UPDATE fer.project_work_plan SET fer_row_id = :rid, updated_at = NOW() WHERE id = :id"),
        {"rid": body.fer_row_id, "id": plan_id},
    )
    await db.commit()
    # Пересчитываем и при сбросе строки: тогда берётся AVG по таблице.
    summary = await gantt_from_plan_service.compute_card_duration(db, plan_id)
    await db.commit()
    return {"plan_id": plan_id, "fer_row_id": body.fer_row_id, "duration_recomputed": summary}


# ─── POST /{plan_id}/auto-pick-fer-row — LLM подбирает строку ФЕР ───
@router.post("/{plan_id}/auto-pick-fer-row")
async def auto_pick_fer_row(
    project_id: str,
    batch_id: str,
    plan_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    res = await narrow_fer_matcher.llm_pick_fer_row(db, plan_id)
    # Пересчитаем длительность если строка выбрана
    if res.get("fer_row_id"):
        summary = await gantt_from_plan_service.compute_card_duration(db, plan_id)
        await db.commit()
        res["duration"] = summary
    return res


# ─── POST /compute-durations — рассчитать длительность всех карточек ───
@router.post("/compute-durations")
async def compute_durations(
    project_id: str,
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Из ФЕР human_hours считаем human_hours_per_unit и duration_days для каждой карточки."""
    res = await gantt_from_plan_service.compute_all_durations(db, batch_id)
    return res


# ─── POST /build-gantt — собрать задачи Ганта ───
@router.post("/build-gantt")
async def build_gantt(
    project_id: str,
    batch_id: str,
    body: BuildGantt,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Из карточек плана создаёт задачи Ганта (группировка по WT × stage + зависимости)."""
    res = await gantt_from_plan_service.build_gantt(
        db, batch_id,
        start_date=body.start_date,
        hours_per_day=body.hours_per_day,
        replace=body.replace,
    )
    return res


# ─── PATCH — правки прорабом ───
@router.patch("/{plan_id}")
async def update_card(
    project_id: str,
    batch_id: str,
    plan_id: int,
    body: CardUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    fields = body.model_dump(exclude_unset=True)
    await pwp_service.update_card(db, plan_id, fields)
    duration = None
    if {"quantity", "workers_count"} & set(fields.keys()):
        duration = await gantt_from_plan_service.compute_card_duration(db, plan_id)
        await db.commit()
    return {"id": plan_id, "updated": list(fields.keys()), "duration": duration}


# ─── POST /confirm — подтвердить одну ───
@router.post("/{plan_id}/confirm")
async def confirm_card(
    project_id: str,
    batch_id: str,
    plan_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await pwp_service.confirm_card(db, plan_id)
    return {"id": plan_id, "status": "confirmed"}


# ─── POST /confirm-all — подтвердить все ───
@router.post("/confirm-all")
async def confirm_all(
    project_id: str,
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    n = await pwp_service.confirm_all(db, batch_id)
    return {"confirmed": n}


# ─── POST — прораб добавил вручную ───
@router.post("")
async def add_card(
    project_id: str,
    batch_id: str,
    body: CardCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pid = await pwp_service.add_custom_card(
        db, batch_id,
        nw_item_code=body.nw_item_code,
        unit=body.unit,
        quantity=body.quantity,
        user_id=user.id,
        notes=body.notes,
        estimate_ids=body.estimate_ids,
        source_label=body.source_label,
    )
    return {"id": pid, "status": "custom_added", "linked_estimates": len(body.estimate_ids or [])}


# ─── DELETE — soft remove ───
@router.delete("/{plan_id}")
async def delete_card(
    project_id: str,
    batch_id: str,
    plan_id: int,
    hard: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await pwp_service.delete_card(db, plan_id, soft=not hard)
    return {"id": plan_id, "deleted": True, "hard": hard}
