"""
Справочник ЕНИР — FastAPI роут.
Все запросы идут в PostgreSQL через async SQLAlchemy.

Endpoints:
  GET /enir                              — список сборников
  GET /enir/search?q=...                 — поиск параграфов по всем сборникам
  GET /enir/{collection_id}/paragraphs   — параграфы сборника (левая панель UI)
  GET /enir/paragraph/{id}               — полный параграф (нормы, состав, звено, примечания)
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.enir import (
    EnirCollection,
    EnirParagraph,
    EnirWorkComposition,
    EnirCrewMember,
    EnirNormTable,
    EnirNote,
)

router = APIRouter(prefix="/enir", tags=["enir"])


# ─── serializers ─────────────────────────────────────────────────────────────

def _para_short(p: EnirParagraph) -> dict:
    return {
        "id":            p.id,
        "collection_id": p.collection_id,
        "code":          p.code,
        "title":         p.title,
        "unit":          p.unit,
    }


def _para_full(p: EnirParagraph) -> dict:
    work_compositions = []
    for comp in p.work_compositions:
        work_compositions.append({
            "condition":  comp.condition,
            "operations": [op.text for op in comp.operations],
        })

    return {
        "id":            p.id,
        "collection_id": p.collection_id,
        "code":          p.code,
        "title":         p.title,
        "unit":          p.unit,
        "work_compositions": work_compositions,
        "crew": [
            {
                "profession": c.profession,
                "grade":      float(c.grade) if c.grade is not None else None,
                "count":      c.count,
            }
            for c in p.crew
        ],
        "norm_tables": [
            {
                "table_id":    n.table_id,
                "table_order": n.table_order,
                "title":       n.title,
                "row_count":   n.row_count,
                "columns":     n.columns or [],
                "rows":        n.rows or [],
            }
            for n in p.norm_tables
        ],
        "notes": [
            {
                "num":         note.num,
                "text":        note.text,
                "coefficient": float(note.coefficient) if note.coefficient is not None else None,
                "pr_code":     note.pr_code,
            }
            for note in p.notes
        ],
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
            EnirCollection.schema_version,
            EnirCollection.source_file,
            EnirCollection.description,
            EnirCollection.issuing_bodies,
            EnirCollection.approval_date,
            EnirCollection.approval_number,
            EnirCollection.developer,
            EnirCollection.coordination,
            EnirCollection.amendments,
            EnirCollection.sort_order,
            func.count(EnirParagraph.id).label("paragraph_count"),
        )
        .outerjoin(EnirParagraph, EnirParagraph.collection_id == EnirCollection.id)
        .group_by(
            EnirCollection.id,
            EnirCollection.code,
            EnirCollection.title,
            EnirCollection.schema_version,
            EnirCollection.source_file,
            EnirCollection.description,
            EnirCollection.issuing_bodies,
            EnirCollection.approval_date,
            EnirCollection.approval_number,
            EnirCollection.developer,
            EnirCollection.coordination,
            EnirCollection.amendments,
            EnirCollection.sort_order,
        )
        .order_by(EnirCollection.sort_order, EnirCollection.code)
    )
    return [
        {
            "id":              r.id,
            "code":            r.code,
            "title":           r.title,
            "schema_version":  r.schema_version,
            "source_file":     r.source_file,
            "description":     r.description,
            "issuing_bodies":  r.issuing_bodies or [],
            "approval_date":   r.approval_date.isoformat() if r.approval_date else None,
            "approval_number": r.approval_number,
            "developer":       r.developer,
            "coordination":    r.coordination,
            "amendments":      r.amendments or [],
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
        .where(
            EnirParagraph.code.ilike(pattern) |
            EnirParagraph.title.ilike(pattern)
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
        .order_by(EnirParagraph.sort_order)
    )
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            EnirParagraph.code.ilike(pattern) |
            EnirParagraph.title.ilike(pattern)
        )

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
            selectinload(EnirParagraph.work_compositions).selectinload(
                EnirWorkComposition.operations
            ),
            selectinload(EnirParagraph.crew),
            selectinload(EnirParagraph.norm_tables),
            selectinload(EnirParagraph.notes),
        )
    )
    para = result.scalar_one_or_none()
    if not para:
        raise HTTPException(status_code=404, detail="Параграф не найден")
    return _para_full(para)
