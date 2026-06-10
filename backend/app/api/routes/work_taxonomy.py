"""Read-only public API for the canonical JSON v4 work taxonomy."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.work_taxonomy_service import (
    get_work_taxonomy_sections,
    get_work_taxonomy_subtypes,
)


router = APIRouter(prefix="/work-taxonomy", tags=["work-taxonomy"])


@router.get("/sections")
async def work_taxonomy_sections(db: AsyncSession = Depends(get_db)):
    return await get_work_taxonomy_sections(db)


@router.get("/subtypes")
async def work_taxonomy_subtypes(
    section_code: str | None = Query(None),
    q: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await get_work_taxonomy_subtypes(db, section_code=section_code, q=q)
