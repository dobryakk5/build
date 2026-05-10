"""
Палитра нормализованных видов работ (NW) для типа сметы.

Использует существующий справочник fer.work_type_sections (9 типов смет → разделы ФЕР)
и наш маппинг fer.nw_fer_mapping (раздел ФЕР → NW).

Также содержит правила декомпозиции «агрегатных» NW (дом-под-ключ, ремонт квартиры…)
на конкретные подкарточки.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ─────────────────────────────────────────────────────────────────────────────
# Декомпозиция агрегатных NW
# ─────────────────────────────────────────────────────────────────────────────
# Если строка сметы матчится на агрегатный NW («дом под ключ»), вместо одной
# карточки плана создаём родительскую + список дочерних с пустым объёмом
# (прораб заполнит вручную или будет искать сметные строки на каждую).

NW_DECOMPOSITION: dict[str, list[str]] = {
    "NW-021": [  # Жилой дом — полный цикл
        "NW-001", "NW-002", "NW-003", "NW-007", "NW-008",
        "NW-016", "NW-017", "NW-018", "NW-019", "NW-020",
        "NW-024", "NW-025", "NW-026",
        "NW-068", "NW-069", "NW-070", "NW-071",
        "NW-073", "NW-074",
        "NW-045", "NW-046", "NW-047", "NW-048", "NW-049",
        "NW-030", "NW-031", "NW-032", "NW-033",
        "NW-083",
    ],
    "NW-022": [  # Нежилое здание
        "NW-001", "NW-002", "NW-003", "NW-007", "NW-008",
        "NW-016", "NW-017", "NW-018", "NW-019",
        "NW-023", "NW-024", "NW-025", "NW-026",
        "NW-068", "NW-069", "NW-070", "NW-071",
        "NW-073", "NW-074", "NW-076",
        "NW-045", "NW-046", "NW-047", "NW-048", "NW-049", "NW-051", "NW-053",
        "NW-030", "NW-031", "NW-032", "NW-033",
    ],
    "NW-027": [  # Ремонт квартиры
        "NW-012", "NW-013", "NW-015",
        "NW-046", "NW-047", "NW-048", "NW-049",
        "NW-026",
        "NW-030", "NW-031", "NW-032", "NW-033", "NW-034",
    ],
    "NW-028": [  # Ремонт жилого дома
        "NW-012", "NW-013", "NW-015",
        "NW-019",
        "NW-072", "NW-070", "NW-071",
        "NW-077", "NW-073", "NW-074",
        "NW-045", "NW-046", "NW-047", "NW-049",
        "NW-030", "NW-031", "NW-032", "NW-033", "NW-034",
    ],
    "NW-029": [  # Ремонт нежилого помещения
        "NW-012", "NW-013", "NW-015",
        "NW-046", "NW-047", "NW-048", "NW-049", "NW-051",
        "NW-026",
        "NW-030", "NW-031", "NW-032", "NW-033", "NW-034",
    ],
    "NW-036": [  # Косметический ремонт
        "NW-031", "NW-033", "NW-034",
    ],
    "NW-039": [  # Пристройка
        "NW-001", "NW-003", "NW-016", "NW-017", "NW-018",
        "NW-024", "NW-025",
        "NW-068", "NW-069", "NW-070",
        "NW-073", "NW-074",
    ],
    "NW-040": [  # Надстройка
        "NW-001",
        "NW-023", "NW-024", "NW-025",
        "NW-068", "NW-069", "NW-070",
    ],
    "NW-041": [  # Перепрофилирование
        "NW-012", "NW-013",
        "NW-046", "NW-047", "NW-048", "NW-049",
        "NW-026",
        "NW-030", "NW-031", "NW-032", "NW-033",
    ],
    "NW-072": [  # Ремонт кровли
        "NW-014", "NW-068", "NW-069", "NW-070", "NW-071",
    ],
    "NW-077": [  # Ремонт фасада
        "NW-073", "NW-074", "NW-030",
    ],
}


def is_aggregate(nw_code: str) -> bool:
    """Является ли NW агрегатным (раскладывается на подкарточки)."""
    return nw_code in NW_DECOMPOSITION


def decompose(nw_code: str) -> list[str]:
    """Список дочерних NW для агрегатного. Пусто если NW атомарный."""
    return list(NW_DECOMPOSITION.get(nw_code, []))


# ─────────────────────────────────────────────────────────────────────────────
# Палитра NW для типа сметы
# ─────────────────────────────────────────────────────────────────────────────

async def get_palette(db: AsyncSession, estimate_kind: int) -> list[dict[str, Any]]:
    """
    Палитра NW для типа сметы — какие виды работ ОЖИДАЮТСЯ при таком типе проекта.

    Выводится из существующего fer.work_type_sections (раздел ФЕР → ожидаемый NW
    через nw_fer_mapping).

    Возвращает список:
      [{"nw_item_code": "NW-001", "unique_label": "...",
        "work_type_code": "WT-01", "work_type_name": "...",
        "stage_code": "ST-02"|None}]
    """
    rows = await db.execute(
        text(
            r"""
            SELECT DISTINCT
                i.code         AS nw_item_code,
                i.unique_label AS unique_label,
                i.subtype      AS subtype,
                i.work_type_code,
                wt.name        AS work_type_name,
                wt.sort_order  AS wt_order,
                i.sort_order   AS nw_order,
                -- первый stage из массива (приближение)
                (i.stage_codes)[1] AS stage_code
            FROM fer.work_type_sections wts
            JOIN fer.sections sec       ON sec.id = ANY(wts.section_ids)
            JOIN fer.collections c
              ON c.id = sec.collection_id AND c.num ~ '^[0-9]+$'
            JOIN fer.nw_fer_mapping m
              ON m.fer_collection_num = c.num::int
             AND m.fer_section_num   = (substring(sec.title from '^Раздел\s+(\d+)'))::int
            JOIN fer.nw_item i      ON i.code = m.nw_item_code
            JOIN fer.nw_work_type wt ON wt.code = i.work_type_code
            WHERE wts.id = :kind
              AND m.mapping_type IN ('direct','partial')
            ORDER BY wt_order, nw_order
            """
        ),
        {"kind": estimate_kind},
    )
    return [dict(r) for r in rows.mappings()]


async def get_wt_palette(db: AsyncSession, estimate_kind: int) -> list[str]:
    """Только список WT кодов (для верхнего уровня UI)."""
    palette = await get_palette(db, estimate_kind)
    seen: list[str] = []
    for p in palette:
        wt = p["work_type_code"]
        if wt not in seen:
            seen.append(wt)
    return seen
