"""FastAPI router factory for the JSON-backed work-rate catalogue.

Production installations should replace the JSON repository with the SQL
schema from migrations/057_work_rate_catalog.sql while preserving endpoints.
"""
from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.services.work_rate_catalog_service import WorkRateCatalog
from app.services.work_rate_import_service import WorkRateImportService
from app.services.work_rate_mapping_service import WorkRateMappingService
from app.services.work_rate_selection_service import WorkRateSelectionService
from app.services.work_rate_models import MAPPING_MODES, WorkRateMapping


class CalculatePreviewRequest(BaseModel):
    rate_item_id: str
    quantity: float = Field(gt=0)
    unit_code: str
    crew_size: int | None = Field(default=None, gt=0)
    hours_per_day: float = Field(default=8.0, gt=0)


class ApproveObservationRequest(BaseModel):
    approved_by: str | None = None


class UpdateRateRequest(BaseModel):
    name: str | None = None
    notes: str | None = None
    unit_code: str | None = None
    price_min: float | None = Field(default=None, ge=0)
    price_max: float | None = Field(default=None, ge=0)
    price_avg: float | None = Field(default=None, ge=0)
    labor_min: float | None = Field(default=None, ge=0)
    labor_max: float | None = Field(default=None, ge=0)
    labor_avg: float | None = Field(default=None, ge=0)
    review_status: str | None = None
    is_active: bool | None = None


class CreateMappingRequest(BaseModel):
    operation_code: str | None = None
    taxonomy_code: str | None = None
    object_scope_code: str | None = None
    mapping_mode: str
    priority: int = 100
    confidence: float = Field(default=1.0, ge=0, le=1)
    is_primary: bool = True
    included_operations: list[str] = Field(default_factory=list)


class UpdateMappingRequest(BaseModel):
    operation_code: str | None = None
    taxonomy_code: str | None = None
    object_scope_code: str | None = None
    mapping_mode: str | None = None
    priority: int | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    is_primary: bool | None = None
    is_active: bool | None = None
    included_operations: list[str] | None = None


class ApproveMappingRequest(BaseModel):
    approved_by: str | None = None


def _body_dict(body: BaseModel) -> dict[str, Any]:
    if hasattr(body, "model_dump"):
        return body.model_dump(exclude_unset=True)
    return body.dict(exclude_unset=True)


def create_work_rate_router(
    *,
    catalog_path: str | Path,
    taxonomy_path: str | Path,
) -> APIRouter:
    router = APIRouter(prefix="/api/work-rates", tags=["work-rates"])
    catalog_file = Path(catalog_path)
    taxonomy_file = Path(taxonomy_path)
    lock = threading.RLock()

    def load() -> WorkRateCatalog:
        return WorkRateCatalog.load(catalog_file)

    def save(catalog: WorkRateCatalog) -> None:
        catalog_file.parent.mkdir(parents=True, exist_ok=True)
        catalog.save(catalog_file)

    @router.post("/import")
    async def import_rates(file: UploadFile = File(...)) -> dict[str, Any]:
        suffix = Path(file.filename or "rates.xlsx").suffix or ".xlsx"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
            fh.write(await file.read())
            tmp = Path(fh.name)
        try:
            with lock:
                catalog = load()
                run = catalog.import_file(tmp, WorkRateImportService())
                mapper = WorkRateMappingService(taxonomy_file)
                catalog.auto_map(mapper)
                save(catalog)
                return run.as_dict()
        finally:
            tmp.unlink(missing_ok=True)

    @router.get("/import-runs")
    def list_import_runs() -> list[dict[str, Any]]:
        return [run.as_dict() for run in load().import_runs]

    @router.get("/import-runs/{run_id}")
    def get_import_run(run_id: str) -> dict[str, Any]:
        run = next((row for row in load().import_runs if row.id == run_id), None)
        if run is None:
            raise HTTPException(404, "Import run not found")
        return run.as_dict()

    @router.get("")
    def list_rates(
        review_status: str | None = None,
        mapping_status: str | None = None,
        operation_code: str | None = None,
    ) -> list[dict[str, Any]]:
        catalog = load()
        operation_by_item = {
            mapping.rate_item_id: mapping.operation_code
            for mapping in catalog.mappings
            if mapping.is_active and mapping.is_primary
        }
        result = []
        for item in catalog.items:
            if not item.is_active:
                continue
            if review_status and item.review_status != review_status:
                continue
            if mapping_status and item.mapping_status != mapping_status:
                continue
            if operation_code and operation_by_item.get(item.id) != operation_code:
                continue
            row = item.as_dict()
            row["operation_code"] = operation_by_item.get(item.id)
            result.append(row)
        return result

    @router.get("/{rate_id}")
    def get_rate(rate_id: str) -> dict[str, Any]:
        catalog = load()
        item = next((row for row in catalog.items if row.id == rate_id), None)
        if item is None:
            raise HTTPException(404, "Rate not found")
        result = item.as_dict()
        result["mappings"] = [
            mapping.as_dict()
            for mapping in catalog.mappings
            if mapping.rate_item_id == rate_id and mapping.is_active
        ]
        return result

    @router.patch("/{rate_id}")
    def update_rate(rate_id: str, body: UpdateRateRequest) -> dict[str, Any]:
        with lock:
            catalog = load()
            item = next((row for row in catalog.items if row.id == rate_id), None)
            if item is None:
                raise HTTPException(404, "Rate not found")
            changes = _body_dict(body)
            for key, value in changes.items():
                setattr(item, key, value)
            if (
                item.price_min is not None and item.price_avg is not None
                and item.price_min > item.price_avg
            ) or (
                item.price_avg is not None and item.price_max is not None
                and item.price_avg > item.price_max
            ):
                raise HTTPException(422, "Invalid price range")
            if (
                item.labor_min is not None and item.labor_avg is not None
                and item.labor_min > item.labor_avg
            ) or (
                item.labor_avg is not None and item.labor_max is not None
                and item.labor_avg > item.labor_max
            ):
                raise HTTPException(422, "Invalid labor range")
            save(catalog)
            return item.as_dict()

    @router.get("/{rate_id}/mappings")
    def get_rate_mappings(rate_id: str) -> list[dict[str, Any]]:
        return [
            mapping.as_dict()
            for mapping in load().mappings
            if mapping.rate_item_id == rate_id and mapping.is_active
        ]

    @router.post("/{rate_id}/mappings")
    def create_mapping(rate_id: str, body: CreateMappingRequest) -> dict[str, Any]:
        if body.mapping_mode not in MAPPING_MODES:
            raise HTTPException(422, "Invalid mapping_mode")
        with lock:
            catalog = load()
            item = next((row for row in catalog.items if row.id == rate_id), None)
            if item is None:
                raise HTTPException(404, "Rate not found")
            mapper = WorkRateMappingService(taxonomy_file)
            if body.operation_code and body.operation_code not in mapper.operations:
                raise HTTPException(422, "Unknown operation_code")
            section_id = subtype_id = None
            if body.taxonomy_code:
                if not mapper.validate_taxonomy_code(body.taxonomy_code):
                    raise HTTPException(422, "Unknown taxonomy_code")
                section_id, subtype_id = body.taxonomy_code.split("/", 1)
            mapping = WorkRateMapping(
                rate_item_id=rate_id,
                operation_code=body.operation_code,
                taxonomy_section_id=section_id,
                taxonomy_subtype_id=subtype_id,
                taxonomy_code=body.taxonomy_code,
                object_scope_code=body.object_scope_code,
                mapping_mode=body.mapping_mode,
                priority=body.priority,
                confidence=body.confidence,
                mapping_source="manual",
                taxonomy_version=mapper.taxonomy_version,
                operation_policy_version=mapper.policy_version,
                is_primary=body.is_primary,
                included_operations=list(body.included_operations),
            )
            catalog.mappings.append(mapping)
            catalog.refresh_mapping_aggregates()
            save(catalog)
            return mapping.as_dict()

    @router.patch("/mappings/{mapping_id}")
    def update_mapping(mapping_id: str, body: UpdateMappingRequest) -> dict[str, Any]:
        with lock:
            catalog = load()
            mapping = next((row for row in catalog.mappings if row.id == mapping_id), None)
            if mapping is None:
                raise HTTPException(404, "Mapping not found")
            changes = _body_dict(body)
            mapper = WorkRateMappingService(taxonomy_file)
            mapping_mode = changes.get("mapping_mode")
            if mapping_mode is not None and mapping_mode not in MAPPING_MODES:
                raise HTTPException(422, "Invalid mapping_mode")
            operation_code = changes.get("operation_code")
            if operation_code is not None and operation_code not in mapper.operations:
                raise HTTPException(422, "Unknown operation_code")
            if "taxonomy_code" in changes:
                code = changes.pop("taxonomy_code")
                if code:
                    if not mapper.validate_taxonomy_code(code):
                        raise HTTPException(422, "Unknown taxonomy_code")
                    section_id, subtype_id = code.split("/", 1)
                    mapping.taxonomy_code = code
                    mapping.taxonomy_section_id = section_id
                    mapping.taxonomy_subtype_id = subtype_id
                else:
                    mapping.taxonomy_code = None
                    mapping.taxonomy_section_id = None
                    mapping.taxonomy_subtype_id = None
            for key, value in changes.items():
                setattr(mapping, key, value)
            mapping.mapping_source = "manual"
            catalog.refresh_mapping_aggregates()
            save(catalog)
            return mapping.as_dict()

    @router.delete("/mappings/{mapping_id}")
    def delete_mapping(mapping_id: str) -> dict[str, Any]:
        with lock:
            catalog = load()
            mapping = next((row for row in catalog.mappings if row.id == mapping_id), None)
            if mapping is None:
                raise HTTPException(404, "Mapping not found")
            mapping.is_active = False
            catalog.refresh_mapping_aggregates()
            save(catalog)
            return {"deleted": True, "mapping_id": mapping_id}

    @router.post("/mappings/{mapping_id}/approve")
    def approve_mapping(mapping_id: str, body: ApproveMappingRequest) -> dict[str, Any]:
        with lock:
            catalog = load()
            mapping = next((row for row in catalog.mappings if row.id == mapping_id), None)
            if mapping is None:
                raise HTTPException(404, "Mapping not found")
            item = next((row for row in catalog.items if row.id == mapping.rate_item_id), None)
            if item is None:
                raise HTTPException(409, "Mapping rate item not found")
            WorkRateMappingService(taxonomy_file).approve_mapping(
                item, mapping, approved_by=body.approved_by
            )
            catalog.refresh_mapping_aggregates()
            save(catalog)
            return mapping.as_dict()

    @router.post("/auto-map")
    def auto_map() -> dict[str, Any]:
        with lock:
            catalog = load()
            results = catalog.auto_map(WorkRateMappingService(taxonomy_file), remap_existing=False)
            save(catalog)
            return {
                "processed": len(results),
                "needs_review": sum(1 for result in results if result.item.review_status == "needs_review"),
            }

    @router.post("/{rate_id}/auto-map")
    def auto_map_one(rate_id: str) -> dict[str, Any]:
        with lock:
            catalog = load()
            item = next((row for row in catalog.items if row.id == rate_id), None)
            if item is None:
                raise HTTPException(404, "Rate not found")
            for mapping in catalog.mappings:
                if mapping.rate_item_id == rate_id and mapping.mapping_source != "manual":
                    mapping.is_active = False
            result = WorkRateMappingService(taxonomy_file).map_item(item)
            catalog.mappings.extend(result.mappings)
            catalog.refresh_mapping_aggregates()
            save(catalog)
            return {
                "item": item.as_dict(),
                "mappings": [mapping.as_dict() for mapping in result.mappings],
                "diagnostics": result.diagnostics,
            }

    @router.post("/{rate_id}/approve-observation-as-rate")
    def approve_observation(rate_id: str, body: ApproveObservationRequest) -> dict[str, Any]:
        with lock:
            catalog = load()
            item = next((row for row in catalog.items if row.id == rate_id), None)
            if item is None:
                raise HTTPException(404, "Rate not found")
            mappings = [
                row for row in catalog.mappings
                if row.rate_item_id == rate_id and row.is_active
            ]
            if not mappings:
                raise HTTPException(409, "Rate has no mapping to approve")
            mapper = WorkRateMappingService(taxonomy_file)
            mapper.approve_mapping(item, mappings[0], approved_by=body.approved_by)
            catalog.refresh_mapping_aggregates()
            save(catalog)
            return item.as_dict()

    @router.post("/calculate-preview")
    def calculate_preview(body: CalculatePreviewRequest) -> dict[str, Any]:
        catalog = load()
        item = next((row for row in catalog.items if row.id == body.rate_item_id), None)
        if item is None:
            raise HTTPException(404, "Rate not found")
        calculation = WorkRateSelectionService.calculate_labor(
            quantity=body.quantity,
            quantity_unit=body.unit_code,
            rate_item=item,
        )
        duration = WorkRateSelectionService.calculate_duration(
            calculation.get("labor_avg_total"),
            crew_size=body.crew_size,
            hours_per_day=body.hours_per_day,
        )
        return {"rate": item.as_dict(), "calculation": calculation, "working_days": duration}

    return router
