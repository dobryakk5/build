"""
Справочник нормализованных видов работ (NW).
GET-only — справочник редактируется через миграции.
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

router = APIRouter(prefix="/nw", tags=["nw"])


async def _fetch_all(db: AsyncSession, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    result = await db.execute(text(sql), params or {})
    return [dict(row) for row in result.mappings().all()]


async def _fetch_one(db: AsyncSession, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    result = await db.execute(text(sql), params)
    row = result.mappings().first()
    return dict(row) if row is not None else None


@router.get("/work-types")
async def nw_work_types(db: AsyncSession = Depends(get_db)):
    """Верхний уровень иерархии — 11 типов работ + счётчик NW в каждом."""
    return await _fetch_all(
        db,
        """
        SELECT
            wt.code,
            wt.name,
            wt.description,
            wt.sort_order,
            COUNT(i.code) AS items_count
        FROM fer.nw_work_type wt
        LEFT JOIN fer.nw_item i ON i.work_type_code = wt.code
        GROUP BY wt.code, wt.name, wt.description, wt.sort_order
        ORDER BY wt.sort_order
        """,
    )


@router.get("/dictionaries")
async def nw_dictionaries(db: AsyncSession = Depends(get_db)):
    """Все справочники атрибутов одним ответом — для UI dropdowns/чипов."""
    object_types = await _fetch_all(
        db, "SELECT code, name, sort_order FROM fer.nw_object_type ORDER BY sort_order"
    )
    building_tech = await _fetch_all(
        db, "SELECT code, name, sort_order FROM fer.nw_building_technology ORDER BY sort_order"
    )
    location_scopes = await _fetch_all(
        db, "SELECT code, name, sort_order FROM fer.nw_location_scope ORDER BY sort_order"
    )
    stages = await _fetch_all(
        db, "SELECT code, name, sort_order FROM fer.nw_stage ORDER BY sort_order"
    )
    repair_classes = await _fetch_all(
        db, "SELECT code, description, sort_order FROM fer.nw_repair_class ORDER BY sort_order"
    )
    return {
        "object_types":           object_types,
        "building_technologies":  building_tech,
        "location_scopes":        location_scopes,
        "stages":                 stages,
        "repair_classes":         repair_classes,
    }


@router.get("/items")
async def nw_items(
    work_type: str | None = Query(None, description="WT-01..WT-11"),
    q: str | None = Query(None, description="Подстрока в unique_label/subtype/notes"),
    object_type: str | None = Query(None, description="OT-01..OT-12"),
    location_scope: str | None = Query(None, description="LS-01..LS-11"),
    stage: str | None = Query(None, description="ST-01..ST-12"),
    repair_class: str | None = Query(None, description="none/current/capital/reconstruction"),
    db: AsyncSession = Depends(get_db),
):
    """Список NW с фильтрами и поиском по тексту."""
    where = ["TRUE"]
    params: dict[str, Any] = {}
    if work_type:
        where.append("i.work_type_code = :work_type")
        params["work_type"] = work_type
    if q:
        where.append("(i.unique_label ILIKE :q OR i.subtype ILIKE :q OR COALESCE(i.notes,'') ILIKE :q)")
        params["q"] = f"%{q}%"
    if object_type:
        where.append(":object_type = ANY(i.object_type_codes)")
        params["object_type"] = object_type
    if location_scope:
        where.append(":location_scope = ANY(i.location_scope_codes)")
        params["location_scope"] = location_scope
    if stage:
        where.append(":stage = ANY(i.stage_codes)")
        params["stage"] = stage
    if repair_class:
        where.append(":repair_class = ANY(i.repair_class_codes)")
        params["repair_class"] = repair_class

    sql = f"""
        SELECT
            i.code,
            i.unique_label,
            i.work_type_code,
            wt.name AS work_type_name,
            i.subtype,
            i.object_type_codes,
            i.building_technology_codes,
            i.location_scope_codes,
            i.stage_codes,
            i.repair_class_codes,
            i.is_capital_repair,
            i.requires_permit_review,
            i.notes,
            i.sort_order,
            (
                SELECT array_agg(
                    LPAD(m.fer_collection_num::text, 2, '0')
                    || '-' ||
                    LPAD(m.fer_section_num::text, 2, '0')
                    ORDER BY m.fer_collection_num, m.fer_section_num
                )
                FROM fer.nw_fer_mapping m
                WHERE m.nw_item_code = i.code
                  AND m.is_primary = TRUE
                  AND m.mapping_type IN ('direct','partial','composite_part')
            ) AS primary_fer_refs
        FROM fer.nw_item i
        JOIN fer.nw_work_type wt ON wt.code = i.work_type_code
        WHERE {' AND '.join(where)}
        ORDER BY i.sort_order
    """
    return await _fetch_all(db, sql, params)


@router.get("/mapping")
async def nw_mapping(
    nw_code: str | None = Query(None, description="Фильтр по NW коду"),
    fer_collection_num: int | None = Query(None, description="Фильтр по сборнику ФЕР"),
    fer_section_num: int | None = Query(None, description="Фильтр по разделу ФЕР"),
    mapping_type: str | None = Query(None, description="direct/partial/composite_part/out_of_scope_subscope"),
    confidence: str | None = Query(None, description="high/medium/low"),
    primary_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """
    Long-table NW ↔ ФЕР маппинг. Использовать для:
    - подбора ФЕР расценок по выбранному NW (фильтр по nw_code)
    - подсветки замапленных NW при просмотре раздела ФЕР (фильтр по collection+section)
    """
    where = ["TRUE"]
    params: dict[str, Any] = {}
    if nw_code:
        where.append("m.nw_item_code = :nw_code")
        params["nw_code"] = nw_code
    if fer_collection_num is not None:
        where.append("m.fer_collection_num = :col")
        params["col"] = fer_collection_num
    if fer_section_num is not None:
        where.append("m.fer_section_num = :sec")
        params["sec"] = fer_section_num
    if mapping_type:
        where.append("m.mapping_type = :mtype")
        params["mtype"] = mapping_type
    if confidence:
        where.append("m.confidence = :conf")
        params["conf"] = confidence
    if primary_only:
        where.append("m.is_primary = TRUE")

    sql = f"""
        SELECT
            m.id,
            m.fer_collection_num,
            m.fer_section_num,
            m.nw_item_code,
            i.unique_label   AS nw_label,
            i.work_type_code AS nw_work_type,
            m.mapping_type,
            m.confidence,
            m.is_primary,
            m.notes
        FROM fer.nw_fer_mapping m
        JOIN fer.nw_item i ON i.code = m.nw_item_code
        WHERE {' AND '.join(where)}
        ORDER BY m.fer_collection_num, m.fer_section_num,
                 m.is_primary DESC,
                 CASE m.confidence WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END
    """
    return await _fetch_all(db, sql, params)


@router.get("/items/{code}")
async def nw_item(code: str, db: AsyncSession = Depends(get_db)):
    item = await _fetch_one(
        db,
        """
        SELECT
            i.code,
            i.unique_label,
            i.work_type_code,
            wt.name AS work_type_name,
            wt.description AS work_type_description,
            i.subtype,
            i.object_type_codes,
            i.building_technology_codes,
            i.location_scope_codes,
            i.stage_codes,
            i.repair_class_codes,
            i.is_capital_repair,
            i.requires_permit_review,
            i.notes,
            i.sort_order
        FROM fer.nw_item i
        JOIN fer.nw_work_type wt ON wt.code = i.work_type_code
        WHERE i.code = :code
        """,
        {"code": code},
    )
    if item is None:
        raise HTTPException(status_code=404, detail="NW item not found")
    # Полное название сборника/раздела JOIN-им к существующим fer.collections/fer.sections.
    # LEFT JOIN с защитным regex: если данные не стыкуются — поля будут NULL,
    # фронт покажет fallback (только номер).
    item["fer_mappings"] = await _fetch_all(
        db,
        r"""
        SELECT
            m.fer_collection_num,
            m.fer_section_num,
            m.mapping_type,
            m.confidence,
            m.is_primary,
            m.notes,
            c.id    AS collection_id,
            c.name  AS collection_name,
            s.id    AS section_id,
            s.title AS section_title
        FROM fer.nw_fer_mapping m
        LEFT JOIN fer.collections c
               ON c.num ~ '^[0-9]+$'
              AND c.num::int = m.fer_collection_num
        LEFT JOIN fer.sections s
               ON s.collection_id = c.id
              AND substring(s.title from '^Раздел\s+(\d+)') ~ '^[0-9]+$'
              AND substring(s.title from '^Раздел\s+(\d+)')::int = m.fer_section_num
        WHERE m.nw_item_code = :code
          AND m.mapping_type <> 'out_of_scope_subscope'
        ORDER BY m.is_primary DESC,
                 CASE m.confidence WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                 m.fer_collection_num, m.fer_section_num
        """,
        {"code": code},
    )
    item["work_type_fer_mappings"] = await _fetch_all(
        db,
        r"""
        SELECT DISTINCT
            m.fer_collection_num,
            m.fer_section_num,
            c.id    AS collection_id,
            c.name  AS collection_name,
            s.id    AS section_id,
            s.title AS section_title,
            'direct'::text AS mapping_type,
            'medium'::text AS confidence,
            FALSE AS is_primary,
            'Унаследовано от родительского WT'::text AS notes
        FROM fer.nw_fer_mapping m
        JOIN fer.nw_item parent_i ON parent_i.code = m.nw_item_code
        LEFT JOIN fer.collections c
               ON c.num ~ '^[0-9]+$'
              AND c.num::int = m.fer_collection_num
        LEFT JOIN fer.sections s
               ON s.collection_id = c.id
              AND substring(s.title from '^Раздел\s+(\d+)') ~ '^[0-9]+$'
              AND substring(s.title from '^Раздел\s+(\d+)')::int = m.fer_section_num
        WHERE parent_i.work_type_code = :work_type_code
          AND m.mapping_type <> 'out_of_scope_subscope'
        ORDER BY m.fer_collection_num, m.fer_section_num
        """,
        {"work_type_code": item["work_type_code"]},
    )
    return item
