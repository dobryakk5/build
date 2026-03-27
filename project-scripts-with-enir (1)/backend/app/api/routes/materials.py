from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps         import require_action, get_db
from app.core.permissions import Action
from app.models           import Material, ProjectMember

router = APIRouter(prefix="/projects/{project_id}/materials", tags=["materials"])


class MaterialCreate(BaseModel):
    task_id:       str | None = None
    name:          str        = Field(min_length=1)
    unit:          str | None = None
    quantity:      float | None = None
    type:          str        = Field(default="small", pattern="^(small|major)$")
    order_date:    date | None = None
    lead_days:     int | None  = None
    delivery_date: date | None = None
    supplier_note: str | None  = None


class MaterialUpdate(BaseModel):
    name:          str | None  = None
    quantity:      float | None = None
    order_date:    date | None  = None
    lead_days:     int | None   = None
    delivery_date: date | None  = None
    status:        str | None   = Field(default=None, pattern="^(planned|ordered|delivered)$")
    supplier_note: str | None   = None


@router.get("")
async def list_materials(
    project_id: str,
    type:       str | None = Query(default=None, pattern="^(small|major)$"),
    status:     str | None = Query(default=None),
    member:     ProjectMember = Depends(require_action(Action.VIEW)),
    db:         AsyncSession  = Depends(get_db),
):
    q = (
        select(Material)
        .where(Material.project_id == project_id)
        .where(Material.deleted_at == None)
        .order_by(Material.delivery_date.asc().nullslast(), Material.created_at)
    )
    if type:
        q = q.where(Material.type == type)
    if status:
        q = q.where(Material.status == status)

    mats = await db.scalars(q)
    return [
        {
            "id":            m.id,
            "task_id":       m.task_id,
            "name":          m.name,
            "unit":          m.unit,
            "quantity":      float(m.quantity) if m.quantity else None,
            "type":          m.type,
            "order_date":    str(m.order_date)    if m.order_date    else None,
            "lead_days":     m.lead_days,
            "delivery_date": str(m.delivery_date) if m.delivery_date else None,
            "status":        m.status,
            "supplier_note": m.supplier_note,
        }
        for m in mats
    ]


@router.post("", status_code=201)
async def create_material(
    project_id: str,
    body:       MaterialCreate,
    member:     ProjectMember = Depends(require_action(Action.EDIT)),
    db:         AsyncSession  = Depends(get_db),
):
    mat = Material(id=str(uuid4()), project_id=project_id, **body.model_dump())
    db.add(mat)
    await db.commit()
    return {"id": mat.id}


@router.patch("/{material_id}")
async def update_material(
    project_id:  str,
    material_id: str,
    body:        MaterialUpdate,
    member:      ProjectMember = Depends(require_action(Action.EDIT)),
    db:          AsyncSession  = Depends(get_db),
):
    mat = await db.get(Material, material_id)
    if not mat or mat.project_id != project_id or mat.deleted_at:
        raise HTTPException(404)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(mat, field, value)
    await db.commit()
    return {"id": mat.id, "status": mat.status}


@router.delete("/{material_id}", status_code=204)
async def delete_material(
    project_id:  str,
    material_id: str,
    member:      ProjectMember = Depends(require_action(Action.EDIT)),
    db:          AsyncSession  = Depends(get_db),
):
    from datetime import datetime
    mat = await db.get(Material, material_id)
    if not mat or mat.project_id != project_id:
        raise HTTPException(404)
    mat.deleted_at = datetime.utcnow()
    await db.commit()
