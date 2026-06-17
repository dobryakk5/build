"""Read-only public API for the canonical JSON work taxonomy."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.work_taxonomy_service import (
    get_project_hierarchy,
    get_work_taxonomy_sections,
    get_work_taxonomy_subtypes,
)


router = APIRouter(prefix="/work-taxonomy", tags=["work-taxonomy"])


@router.get("/sections")
async def work_taxonomy_sections(db: AsyncSession = Depends(get_db)):
    return await get_work_taxonomy_sections(db)


@router.get("/project-hierarchy")
async def work_taxonomy_project_hierarchy(
    dictionary_version: str | None = Query(None),
    include_stages: bool = Query(False),
):
    try:
        return get_project_hierarchy(
            dictionary_version_filter=dictionary_version,
            include_stages=include_stages,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/subtypes")
async def work_taxonomy_subtypes(
    section_code: str | None = Query(None),
    q: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await get_work_taxonomy_subtypes(db, section_code=section_code, q=q)
