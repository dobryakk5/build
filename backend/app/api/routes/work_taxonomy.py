"""Public API for the canonical JSON work taxonomy."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.work_taxonomy_service import (
    get_canonical_stages,
    get_estimate_types,
    get_project_hierarchy,
    get_project_variant_stages,
    get_project_variants,
    get_work_taxonomy_sections,
    get_work_taxonomy_subtypes,
    update_project_stage_title,
)


router = APIRouter(prefix="/work-taxonomy", tags=["work-taxonomy"])


class WorkStageTitlePatch(BaseModel):
    title: str = Field(min_length=1, max_length=240)


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


@router.get("/estimate-types")
async def work_taxonomy_estimate_types():
    return get_estimate_types()


@router.get("/estimate-types/{estimate_type_id}/variants")
async def work_taxonomy_project_variants(estimate_type_id: str):
    try:
        return get_project_variants(estimate_type_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/estimate-types/{estimate_type_id}/variants/{project_variant_id}/stages")
async def work_taxonomy_project_variant_stages(
    estimate_type_id: str,
    project_variant_id: str,
):
    try:
        return get_project_variant_stages(estimate_type_id, project_variant_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.patch("/project-hierarchy/stages/{stage_id}")
async def work_taxonomy_update_project_stage(stage_id: str, patch: WorkStageTitlePatch):
    try:
        return update_project_stage_title(stage_id, patch.title)
    except KeyError as exc:
        raise HTTPException(404, f"Unknown stage_id: {stage_id}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/canonical-stages")
async def work_taxonomy_canonical_stages():
    return get_canonical_stages()


@router.get("/subtypes")
async def work_taxonomy_subtypes(
    section_code: str | None = Query(None),
    q: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await get_work_taxonomy_subtypes(db, section_code=section_code, q=q)
