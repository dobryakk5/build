from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_action
from app.core.config import settings
from app.core.database import get_db
from app.core.permissions import Action
from app.models import Estimate, EstimateBatch, ProjectMember, User, UserWorkRate
from app.services.taxonomy_snapshot_service import resolve_config_path
from app.services.user_work_rate_service import (
    UserWorkRateRecord,
    UserWorkRateRepository,
    build_work_rate_key,
    validate_labor_hours,
)
from app.services.work_rate_catalog_service import WorkRateCatalog
from app.services.work_rate_import_service import normalize_unit
from app.services.work_rate_ktp_integration import apply_rate_to_raw_data
from app.services.work_rate_selection_service import WorkRateSelectionService
from app.services.work_taxonomy_service import _load_dictionary, _tz_operation_package_additions


router = APIRouter(tags=["user-work-rates"])


class SaveUserRateRequest(BaseModel):
    labor_hours_per_unit: Decimal = Field(gt=0, max_digits=18, decimal_places=6)


class UpdateUserRateRequest(BaseModel):
    labor_hours_per_unit: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=6,
    )
    work_name_snapshot: str | None = Field(default=None, min_length=1, max_length=2000)


def _record_dict(record: UserWorkRateRecord) -> dict[str, Any]:
    payload = record.as_dict()
    payload["labor_hours_per_unit"] = float(record.labor_hours_per_unit)
    return payload


@lru_cache(maxsize=2)
def _catalog(path_text: str) -> WorkRateCatalog:
    path = Path(path_text)
    if not path.exists():
        return WorkRateCatalog()
    return WorkRateCatalog.load(path)


@lru_cache(maxsize=1)
def _operation_packages() -> dict[str, dict[str, Any]]:
    policy = (_load_dictionary().get("operation_object_resolution_policy") or {})
    packages = dict(policy.get("operation_packages") or {})
    packages.update(_tz_operation_package_additions())
    return packages


def _raw(row: Estimate) -> dict[str, Any]:
    return dict(row.raw_data) if isinstance(row.raw_data, dict) else {}


def _is_unresolved(row: Estimate) -> bool:
    raw = _raw(row)
    row_role = str(
        raw.get("row_role")
        or getattr(row, "row_role", None)
        or ("work" if getattr(row, "item_type", None) == "work" else "")
    ).strip()
    return (
        row_role == "work"
        and raw.get("rate_status") == "needs_user_rate"
        and raw.get("rate_source") is None
    )


def _selection_key(selection: Any):
    return build_work_rate_key(
        taxonomy_code=selection.taxonomy_code,
        operation_code=selection.operation_code,
        object_scope_code=selection.object_scope_code,
        rate_context_code=selection.rate_context_code,
        rate_variant_code=selection.rate_variant_code,
        unit_code=selection.unit_code,
    )


async def _estimate_row_in_project(
    db: AsyncSession,
    *,
    project_id: UUID,
    estimate_batch_id: UUID,
    row_id: UUID,
) -> tuple[EstimateBatch, Estimate] | None:
    batch = await db.scalar(
        select(EstimateBatch).where(
            EstimateBatch.id == str(estimate_batch_id),
            EstimateBatch.project_id == str(project_id),
            EstimateBatch.deleted_at.is_(None),
        ).with_for_update()
    )
    if batch is None:
        return None
    row = await db.scalar(
        select(Estimate).where(
            Estimate.id == str(row_id),
            Estimate.project_id == str(project_id),
            Estimate.estimate_batch_id == str(estimate_batch_id),
            Estimate.deleted_at.is_(None),
        ).with_for_update()
    )
    return (batch, row) if row is not None else None


def _select_for_row(
    *,
    row: Estimate,
    user_id: str,
    user_rates: list[UserWorkRateRecord],
    catalog: WorkRateCatalog,
) -> tuple[Any, Any, str | None]:
    raw = _raw(row)
    row_role = str(
        raw.get("row_role")
        or row.row_role
        or ("work" if getattr(row, "item_type", None) == "work" else "")
    ).strip()
    taxonomy_code = str(raw.get("work_subtype_code") or row.work_subtype_code or "").strip()
    operation_code = str(
        raw.get("operation_package_code")
        or raw.get("operation_code")
        or raw.get("selected_operation_code")
        or ""
    ).strip()
    object_scope_code = raw.get("selected_object_scope_code") or raw.get("object_scope_code")
    unit_code, _dimension, _factor = normalize_unit(row.unit)

    selector = WorkRateSelectionService(_operation_packages())
    if row_role != "work":
        from app.services.work_rate_models import RateSelectionResult

        return (
            RateSelectionResult(
                status="needs_clarification",
                taxonomy_code=taxonomy_code or None,
                operation_code=operation_code or None,
                object_scope_code=object_scope_code,
                unit_code=unit_code,
                needs_review=True,
                review_reason="estimate_row_is_not_work",
            ),
            None,
            unit_code,
        )

    selection = selector.select_rate(
        taxonomy_code=taxonomy_code,
        operation_code=operation_code,
        object_scope_code=object_scope_code,
        rate_context_code=raw.get("rate_context_code"),
        quantity=float(row.quantity) if row.quantity is not None else None,
        unit_code=unit_code,
        work_name=row.work_name,
        item_text=raw.get("item_text"),
        spec=raw.get("spec"),
        section_title=raw.get("section_title") or row.section,
        section_description=raw.get("section_description"),
        section_parent_context=raw.get("section_parent_context"),
        items=catalog.items,
        mappings=catalog.mappings,
        sources=catalog.sources,
        user_id=user_id,
        user_rates=user_rates,
        applicability={
            # These fields restrict only global catalogue entries. Personal
            # reuse is based on the stable canonical key returned by selector.
            "project_variant_id": row.project_variant_id,
            "template_stage_number": row.template_stage_number or row.work_stage_number,
            "semantic_stage_option_id": raw.get("semantic_stage_option_id") or raw.get("preferred_stage_option_id"),
            "floor_number": row.floor_number,
            "floor_kind": row.floor_kind,
            "rate_context_code": raw.get("rate_context_code"),
            "object_scope_required": bool(raw.get("object_scope_required")),
        },
    )
    rate_item = next(
        (item for item in catalog.items if item.id == selection.rate_item_id and item.is_active),
        None,
    ) if selection.rate_item_id else None
    return selection, rate_item, unit_code


def _apply_selection_to_row(
    *,
    row: Estimate,
    batch: EstimateBatch,
    selection: Any,
    rate_item: Any,
    unit_code: str | None,
) -> dict[str, Any]:
    raw = _raw(row)
    quantity = float(row.quantity) if row.quantity is not None else None
    manual_labor = raw.get("manual_labor_hours")
    if manual_labor is None and raw.get("labor_value_source") == "manual":
        manual_labor = raw.get("resolved_labor_hours") or raw.get("labor_hours")
    if manual_labor is None and row.labor_hours is not None and quantity:
        # Estimate.labor_hours is a manual norm per unit. The calculated total
        # lives only in raw_data snapshots.
        manual_labor = float(row.labor_hours) * quantity

    updated = apply_rate_to_raw_data(
        raw,
        selection=selection,
        rate_item=rate_item,
        quantity=quantity,
        quantity_unit=unit_code,
        labor_source_mode=str(raw.get("labor_source_mode") or "hybrid"),
        manual_labor_hours=manual_labor,
        project_specific_labor_hours=raw.get("project_specific_labor_hours"),
        fer_labor_hours=raw.get("fer_labor_hours"),
        subtype_output_per_day=raw.get("subtype_output_per_day"),
        crew_size=raw.get("crew_size") or batch.workers_count,
        hours_per_day=float(raw.get("hours_per_day") or batch.hours_per_day or 8),
        calculation_group_key=raw.get("calculation_group_key"),
        work_name=row.work_name,
    )
    row.raw_data = updated
    return updated

def _http_error(exc: ValueError) -> HTTPException:
    code = str(exc)
    status = 422 if code in {
        "estimate_row_is_not_work",
        "labor_hours_per_unit_invalid",
        "labor_hours_per_unit_must_be_positive",
        "labor_hours_per_unit_scale_exceeded",
        "labor_hours_per_unit_range_exceeded",
    } else 409
    return HTTPException(status, code)


@router.get("/api/v1/user-work-rates")
async def list_user_work_rates(
    search: str | None = Query(default=None),
    taxonomy_code: str | None = Query(default=None),
    operation_code: str | None = Query(default=None),
    unit_code: str | None = Query(default=None),
    is_active: bool | None = Query(default=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(UserWorkRate).where(UserWorkRate.user_id == current_user.id)
    if is_active is not None:
        stmt = stmt.where(UserWorkRate.is_active.is_(is_active))
    if taxonomy_code:
        stmt = stmt.where(UserWorkRate.taxonomy_code == taxonomy_code)
    if operation_code:
        stmt = stmt.where(UserWorkRate.operation_code == operation_code)
    if unit_code:
        stmt = stmt.where(UserWorkRate.unit_code == unit_code)
    if search:
        stmt = stmt.where(UserWorkRate.work_name_snapshot.ilike(f"%{search.strip()}%"))
    stmt = stmt.order_by(UserWorkRate.updated_at.desc(), UserWorkRate.id)
    rows = list(await db.scalars(stmt))
    return [_record_dict(UserWorkRateRecord.from_model(row)) for row in rows]


@router.get("/api/v1/user-work-rates/{rate_id}")
async def get_user_work_rate(
    rate_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await UserWorkRateRepository().get_owned(
        db,
        user_id=current_user.id,
        rate_id=rate_id,
    )
    if row is None:
        raise HTTPException(404, "user_work_rate_not_found")
    return _record_dict(UserWorkRateRecord.from_model(row))


@router.patch("/api/v1/user-work-rates/{rate_id}")
async def update_user_work_rate(
    rate_id: str,
    body: UpdateUserRateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if body.labor_hours_per_unit is None and body.work_name_snapshot is None:
        raise HTTPException(422, "no_changes")
    repository = UserWorkRateRepository()
    current = await repository.get_owned(db, user_id=current_user.id, rate_id=rate_id)
    if current is None:
        raise HTTPException(404, "user_work_rate_not_found")
    try:
        value = validate_labor_hours(
            body.labor_hours_per_unit
            if body.labor_hours_per_unit is not None
            else current.labor_hours_per_unit
        )
    except ValueError as exc:
        raise _http_error(exc) from exc
    record = await repository.update_value(
        db,
        user_id=current_user.id,
        rate_id=rate_id,
        labor_hours_per_unit=value,
        work_name_snapshot=body.work_name_snapshot,
    )
    await db.commit()
    assert record is not None
    return _record_dict(record)


@router.delete("/api/v1/user-work-rates/{rate_id}")
async def deactivate_user_work_rate(
    rate_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    changed = await UserWorkRateRepository().deactivate(
        db,
        user_id=current_user.id,
        rate_id=rate_id,
    )
    if not changed:
        raise HTTPException(404, "user_work_rate_not_found")
    await db.commit()
    return {"id": rate_id, "is_active": False}


@router.put("/api/v1/projects/{project_id}/estimate-batches/{estimate_batch_id}/rows/{row_id}/user-rate")
async def save_user_rate_from_estimate_row(
    project_id: UUID,
    estimate_batch_id: UUID,
    row_id: UUID,
    body: SaveUserRateRequest,
    _member: ProjectMember = Depends(require_action(Action.EDIT)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    owned = await _estimate_row_in_project(
        db,
        project_id=project_id,
        estimate_batch_id=estimate_batch_id,
        row_id=row_id,
    )
    if owned is None:
        raise HTTPException(404, "estimate_row_not_found")
    batch, row = owned

    rate_owner_user_id = str(batch.rate_owner_user_id or "")
    if not rate_owner_user_id:
        raise HTTPException(409, "rate_owner_user_id_required")
    if rate_owner_user_id != str(current_user.id):
        raise HTTPException(403, "rate_catalog_owner_required")

    stored_raw = _raw(row)
    if (
        stored_raw.get("rate_status") != "needs_user_rate"
        or stored_raw.get("rate_source") is not None
    ):
        raise HTTPException(409, "estimate_row_not_awaiting_user_rate")

    try:
        labor_hours = validate_labor_hours(body.labor_hours_per_unit)
    except ValueError as exc:
        raise _http_error(exc) from exc

    catalog_path = resolve_config_path(settings.WORK_RATE_CATALOG_PATH)
    catalog = _catalog(str(catalog_path))

    # Resolve and normalize the canonical key in one place. A personal rate may
    # be saved only when the selector explicitly requests it. Clarifications,
    # package decomposition and available global rates are not writable states.
    global_selection, _global_item, _unit_code = _select_for_row(
        row=row,
        user_id=rate_owner_user_id,
        user_rates=[],
        catalog=catalog,
    )
    if global_selection.status == "resolved" and global_selection.rate_source == "global_catalog":
        raise HTTPException(409, "global_rate_already_available")
    if (
        global_selection.status != "needs_user_rate"
        or global_selection.rate_source is not None
    ):
        reason = global_selection.review_reason or global_selection.status or "user_rate_not_allowed"
        status_code = 422 if reason == "estimate_row_is_not_work" else 409
        raise HTTPException(status_code, reason)

    try:
        key = _selection_key(global_selection)
    except ValueError as exc:
        raise _http_error(exc) from exc

    # Lock all potentially affected rows in a deterministic order before the
    # upsert. Selection below remains authoritative; this persisted status is
    # only a narrow candidate filter.
    estimate_rows = list(
        await db.scalars(
            select(Estimate)
            .where(
                Estimate.project_id == str(project_id),
                Estimate.estimate_batch_id == str(estimate_batch_id),
                Estimate.deleted_at.is_(None),
            )
            .order_by(Estimate.id)
            .with_for_update()
        )
    )

    repository = UserWorkRateRepository()
    record = await repository.upsert(
        db,
        user_id=rate_owner_user_id,
        key=key,
        labor_hours_per_unit=labor_hours,
        work_name_snapshot=str(getattr(row, "work_name", None) or key.taxonomy_code),
        source_estimate_batch_id=str(estimate_batch_id),
        source_estimate_row_id=str(row_id),
        taxonomy_version_at_creation=getattr(row, "dictionary_version", None),
    )
    active_rates = await repository.list_records(db, user_id=rate_owner_user_id)

    updated_rows: list[dict[str, Any]] = []
    matched_rows = 0
    current_row_applied = False

    for candidate in estimate_rows:
        is_current = str(candidate.id) == str(row_id)
        if not is_current and not _is_unresolved(candidate):
            continue
        selection, rate_item, candidate_unit = _select_for_row(
            row=candidate,
            user_id=rate_owner_user_id,
            user_rates=active_rates,
            catalog=catalog,
        )
        if selection.status != "resolved" or selection.rate_source != "user_catalog":
            continue
        if str(selection.user_rate_id or "") != str(record.id):
            continue
        try:
            if _selection_key(selection) != key or selection.unit_code != key.unit_code:
                continue
        except ValueError:
            continue

        matched_rows += 1
        candidate_raw = _apply_selection_to_row(
            row=candidate,
            batch=batch,
            selection=selection,
            rate_item=rate_item,
            unit_code=candidate_unit,
        )
        if is_current:
            current_row_applied = True
        updated_rows.append(
            {
                "id": str(candidate.id),
                "rate_status": candidate_raw.get("rate_status"),
                "rate_source": candidate_raw.get("rate_source"),
                "selected_user_rate_id": candidate_raw.get("selected_user_rate_id"),
                "calculated_labor_hours": candidate_raw.get("calculated_labor_hours"),
                "resolved_labor_hours": candidate_raw.get("resolved_labor_hours"),
            }
        )

    if not current_row_applied:
        await db.rollback()
        raise HTTPException(409, "saved_user_rate_not_applied")

    await db.commit()
    return {
        "user_rate": _record_dict(record),
        "recalculation": {
            "matched_rows": matched_rows,
            "updated_rows": len(updated_rows),
        },
        "rows": updated_rows,
    }
