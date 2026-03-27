"""
Справочник ЕНИР — FastAPI роут.
Все запросы идут в PostgreSQL через async SQLAlchemy.

Endpoints:
  GET /enir                              — список сборников
  GET /enir/search?q=...                 — поиск параграфов по всем сборникам
  GET /enir/{collection_id}/paragraphs   — параграфы сборника (левая панель UI)
  GET /enir/paragraph/{id}               — полный параграф, включая E1-таблицы
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.enir import (
    EnirCollection,
    EnirTechnicalCoefficient,
    EnirTechnicalCoefficientParagraph,
    EnirParagraph,
    EnirWorkComposition,
    EnirWorkOperation,
    EnirSourceWorkItem,
    EnirNormTable,
    EnirNormRow,
)

router = APIRouter(prefix="/enir", tags=["enir"])


# ─── serializers ─────────────────────────────────────────────────────────────

def _structure_ref(node, source_key: str) -> dict | None:
    if node is None:
        return None
    return {
        "id": node.id,
        "source_id": getattr(node, source_key),
        "title": node.title,
    }


def _structure_title(p: EnirParagraph) -> str | None:
    if p.chapter is not None:
        return p.chapter.title
    if p.section is not None:
        return p.section.title
    return None


def _is_technical(p: EnirParagraph) -> bool:
    return (p.code or "").upper().startswith("TECH_")


def _paragraph_search_clause(pattern: str):
    return or_(
        EnirParagraph.code.ilike(pattern),
        EnirParagraph.title.ilike(pattern),
        EnirParagraph.work_compositions.any(EnirWorkComposition.condition.ilike(pattern)),
        EnirParagraph.work_compositions.any(
            EnirWorkComposition.operations.any(EnirWorkOperation.text.ilike(pattern))
        ),
        EnirParagraph.source_work_items.any(EnirSourceWorkItem.raw_text.ilike(pattern)),
    )


def _para_short(p: EnirParagraph) -> dict:
    return {
        "id":            p.id,
        "collection_id": p.collection_id,
        "source_paragraph_id": p.source_paragraph_id,
        "code":          p.code,
        "title":         p.title,
        "unit":          p.unit,
        "html_anchor":   p.html_anchor,
        "section":       _structure_ref(p.section, "source_section_id"),
        "chapter":       _structure_ref(p.chapter, "source_chapter_id"),
        "structure_title": _structure_title(p),
        "is_technical":  _is_technical(p),
    }


def _paragraph_ref(p: EnirParagraph | None) -> dict | None:
    if p is None:
        return None
    return {
        "id": p.id,
        "code": p.code,
        "title": p.title,
    }


def _serialize_note(note, *, code_field: str) -> dict:
    return {
        "text": note.text,
        "coefficient": float(note.coefficient) if note.coefficient is not None else None,
        "conditions": note.conditions,
        "formula": note.formula,
        code_field: getattr(note, code_field),
    }


def _serialize_norm_table(table: EnirNormTable) -> dict:
    columns = sorted(table.columns, key=lambda c: c.sort_order)
    rows = sorted(table.rows, key=lambda r: r.sort_order)

    serialized_rows = []
    for row in rows:
        values_by_column_id: dict[int, list] = {}
        for value in row.values:
            values_by_column_id.setdefault(value.norm_column_id, []).append(
                {
                    "value_type": value.value_type,
                    "value_text": value.value_text,
                    "value_numeric": float(value.value_numeric) if value.value_numeric is not None else None,
                }
            )

        serialized_rows.append(
            {
                "id": row.id,
                "source_row_id": row.source_row_id,
                "source_row_num": row.source_row_num,
                "sort_order": row.sort_order,
                "params": row.params,
                "cells": [
                    {
                        "column_id": column.id,
                        "column_key": column.source_column_key,
                        "sort_order": column.sort_order,
                        "header": column.header,
                        "label": column.label,
                        "values": values_by_column_id.get(column.id, []),
                    }
                    for column in columns
                ],
            }
        )

    return {
        "id": table.id,
        "source_table_id": table.source_table_id,
        "sort_order": table.sort_order,
        "title": table.title,
        "row_count": table.row_count,
        "columns": [
            {
                "id": column.id,
                "column_key": column.source_column_key,
                "sort_order": column.sort_order,
                "header": column.header,
                "label": column.label,
            }
            for column in columns
        ],
        "rows": serialized_rows,
    }


def _technical_coefficient_scope(tc: EnirTechnicalCoefficient) -> str:
    if tc.paragraph_id is not None:
        return "paragraph"
    if tc.paragraph_links:
        return "paragraph_list"
    if tc.chapter_id is not None:
        return "chapter"
    if tc.section_id is not None:
        return "section"
    return "collection"


def _serialize_technical_coefficient(tc: EnirTechnicalCoefficient) -> dict:
    return {
        "id": tc.id,
        "code": tc.code,
        "description": tc.description,
        "multiplier": float(tc.multiplier) if tc.multiplier is not None else None,
        "conditions": tc.conditions,
        "formula": tc.formula,
        "sort_order": tc.sort_order,
        "scope": _technical_coefficient_scope(tc),
        "section": _structure_ref(tc.section, "source_section_id"),
        "chapter": _structure_ref(tc.chapter, "source_chapter_id"),
        "paragraph": _paragraph_ref(tc.paragraph),
        "applicable_paragraphs": [
            _paragraph_ref(link.paragraph)
            for link in tc.paragraph_links
            if link.paragraph is not None
        ],
    }


def _para_full(
    p: EnirParagraph,
    *,
    technical_coefficients: list[EnirTechnicalCoefficient],
) -> dict:
    work_compositions = []
    for comp in p.work_compositions:
        work_compositions.append({
            "condition":  comp.condition,
            "operations": [op.text for op in comp.operations],
        })

    return {
        "id":            p.id,
        "collection_id": p.collection_id,
        "collection": {
            "id": p.collection.id,
            "code": p.collection.code,
            "title": p.collection.title,
            "description": p.collection.description,
            "issue": p.collection.issue,
            "issue_title": p.collection.issue_title,
            "source_file": p.collection.source_file,
            "source_format": p.collection.source_format,
        },
        "source_paragraph_id": p.source_paragraph_id,
        "code":          p.code,
        "title":         p.title,
        "unit":          p.unit,
        "html_anchor":   p.html_anchor,
        "section":       _structure_ref(p.section, "source_section_id"),
        "chapter":       _structure_ref(p.chapter, "source_chapter_id"),
        "structure_title": _structure_title(p),
        "is_technical":  _is_technical(p),
        "work_compositions": work_compositions,
        "crew": [
            {
                "profession": c.profession,
                "grade":      float(c.grade) if c.grade is not None else None,
                "count":      c.count,
            }
            for c in p.crew
        ],
        "norms": [
            {
                "row_num":      n.row_num,
                "work_type":    n.work_type,
                "condition":    n.condition,
                "thickness_mm": n.thickness_mm,
                "column_label": n.column_label,
                "norm_time":    float(n.norm_time)  if n.norm_time  is not None else None,
                "price_rub":    float(n.price_rub)  if n.price_rub  is not None else None,
            }
            for n in p.norms
        ],
        "notes": [
            {"num": note.num, **_serialize_note(note, code_field="pr_code")}
            for note in p.notes
        ],
        "technical_characteristics": [
            {
                "sort_order": item.sort_order,
                "raw_text": item.raw_text,
            }
            for item in p.technical_characteristics
        ],
        "application_notes": [
            {
                "sort_order": item.sort_order,
                "text": item.text,
            }
            for item in p.application_notes
        ],
        "refs": [
            {
                "sort_order": item.sort_order,
                "ref_type": item.ref_type,
                "link_text": item.link_text,
                "href": item.href,
                "abs_url": item.abs_url,
                "context_text": item.context_text,
                "is_meganorm": item.is_meganorm,
            }
            for item in p.paragraph_refs
        ],
        "source_work_items": [
            {
                "sort_order": item.sort_order,
                "raw_text": item.raw_text,
            }
            for item in p.source_work_items
        ],
        "source_crew_items": [
            {
                "sort_order": item.sort_order,
                "profession": item.profession,
                "grade": float(item.grade) if item.grade is not None else None,
                "count": item.count,
                "raw_text": item.raw_text,
            }
            for item in p.source_crew_items
        ],
        "source_notes": [
            {"sort_order": item.sort_order, **_serialize_note(item, code_field="code")}
            for item in p.source_notes
        ],
        "norm_tables": [_serialize_norm_table(table) for table in p.norm_tables],
        "technical_coefficients": [
            _serialize_technical_coefficient(tc)
            for tc in technical_coefficients
        ],
        "has_legacy_norms": len(p.norms) > 0,
        "has_tabular_norms": len(p.norm_tables) > 0,
    }


# ─── endpoints ───────────────────────────────────────────────────────────────

@router.get("")
async def list_collections(db: AsyncSession = Depends(get_db)):
    """Список всех сборников с количеством параграфов."""
    result = await db.execute(
        select(
            EnirCollection.id,
            EnirCollection.code,
            EnirCollection.title,
            EnirCollection.description,
            EnirCollection.issue,
            EnirCollection.issue_title,
            EnirCollection.source_file,
            EnirCollection.source_format,
            EnirCollection.sort_order,
            func.count(EnirParagraph.id).label("paragraph_count"),
        )
        .outerjoin(EnirParagraph, EnirParagraph.collection_id == EnirCollection.id)
        .group_by(EnirCollection.id)
        .order_by(EnirCollection.sort_order, EnirCollection.code)
    )
    return [
        {
            "id":              r.id,
            "code":            r.code,
            "title":           r.title,
            "description":     r.description,
            "issue":           r.issue,
            "issue_title":     r.issue_title,
            "source_file":     r.source_file,
            "source_format":   r.source_format,
            "sort_order":      r.sort_order,
            "paragraph_count": r.paragraph_count,
        }
        for r in result.all()
    ]


@router.get("/search")
async def search_paragraphs(
    q: str = Query(..., min_length=1),
    collection_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Поиск параграфов по коду или названию (ilike), до 100 результатов."""
    pattern = f"%{q}%"
    stmt = (
        select(EnirParagraph)
        .where(_paragraph_search_clause(pattern))
        .options(
            selectinload(EnirParagraph.section),
            selectinload(EnirParagraph.chapter),
        )
        .order_by(EnirParagraph.collection_id, EnirParagraph.sort_order)
        .limit(100)
    )
    if collection_id is not None:
        stmt = stmt.where(EnirParagraph.collection_id == collection_id)

    result = await db.execute(stmt)
    return [_para_short(p) for p in result.scalars().all()]


@router.get("/{collection_id}/paragraphs")
async def list_paragraphs(
    collection_id: int,
    q: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Параграфы одного сборника (короткие, для левой панели)."""
    coll = await db.get(EnirCollection, collection_id)
    if not coll:
        raise HTTPException(status_code=404, detail="Сборник не найден")

    stmt = (
        select(EnirParagraph)
        .where(EnirParagraph.collection_id == collection_id)
        .options(
            selectinload(EnirParagraph.section),
            selectinload(EnirParagraph.chapter),
        )
        .order_by(EnirParagraph.sort_order)
    )
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(_paragraph_search_clause(pattern))

    result = await db.execute(stmt)
    return [_para_short(p) for p in result.scalars().all()]


@router.get("/paragraph/{paragraph_id}")
async def get_paragraph(
    paragraph_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Полный параграф со всеми связанными данными."""
    result = await db.execute(
        select(EnirParagraph)
        .where(EnirParagraph.id == paragraph_id)
        .options(
            selectinload(EnirParagraph.collection),
            selectinload(EnirParagraph.section),
            selectinload(EnirParagraph.chapter),
            selectinload(EnirParagraph.work_compositions).selectinload(
                EnirWorkComposition.operations
            ),
            selectinload(EnirParagraph.crew),
            selectinload(EnirParagraph.norms),
            selectinload(EnirParagraph.notes),
            selectinload(EnirParagraph.technical_characteristics),
            selectinload(EnirParagraph.application_notes),
            selectinload(EnirParagraph.paragraph_refs),
            selectinload(EnirParagraph.source_work_items),
            selectinload(EnirParagraph.source_crew_items),
            selectinload(EnirParagraph.source_notes),
            selectinload(EnirParagraph.norm_tables).selectinload(EnirNormTable.columns),
            selectinload(EnirParagraph.norm_tables)
                .selectinload(EnirNormTable.rows)
                .selectinload(EnirNormRow.values),
        )
    )
    para = result.scalar_one_or_none()
    if not para:
        raise HTTPException(status_code=404, detail="Параграф не найден")

    scope_filters = [
        and_(
            EnirTechnicalCoefficient.section_id.is_(None),
            EnirTechnicalCoefficient.chapter_id.is_(None),
            EnirTechnicalCoefficient.paragraph_id.is_(None),
            ~EnirTechnicalCoefficient.paragraph_links.any(),
        ),
        EnirTechnicalCoefficient.paragraph_id == para.id,
        EnirTechnicalCoefficient.paragraph_links.any(
            EnirTechnicalCoefficientParagraph.paragraph_id == para.id
        ),
    ]
    if para.section_id is not None:
        scope_filters.append(EnirTechnicalCoefficient.section_id == para.section_id)
    if para.chapter_id is not None:
        scope_filters.append(EnirTechnicalCoefficient.chapter_id == para.chapter_id)

    tc_result = await db.execute(
        select(EnirTechnicalCoefficient)
        .where(
            EnirTechnicalCoefficient.collection_id == para.collection_id,
            or_(*scope_filters),
        )
        .options(
            selectinload(EnirTechnicalCoefficient.section),
            selectinload(EnirTechnicalCoefficient.chapter),
            selectinload(EnirTechnicalCoefficient.paragraph),
            selectinload(EnirTechnicalCoefficient.paragraph_links).selectinload(
                EnirTechnicalCoefficientParagraph.paragraph
            ),
        )
        .order_by(EnirTechnicalCoefficient.sort_order, EnirTechnicalCoefficient.id)
    )
    technical_coefficients = tc_result.scalars().all()
    return _para_full(para, technical_coefficients=technical_coefficients)
