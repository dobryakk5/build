from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps         import get_current_user, get_project_member, require_action, get_db, require_verified_user
from app.core.permissions import Action
from app.models           import Project, ProjectMember, User, GanttTask, Estimate
from app.services.auth_service import is_effectively_email_verified

router = APIRouter(prefix="/projects", tags=["projects"])


# ── Схемы ─────────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name:       str            = Field(min_length=1, max_length=255)
    address:    str | None     = None
    start_date: date | None    = None
    end_date:   date | None    = None
    color:      str | None     = None


class ProjectUpdate(BaseModel):
    name:             str | None  = None
    address:          str | None  = None
    start_date:       date | None = None
    end_date:         date | None = None
    color:            str | None  = None
    status:           str | None  = None


class MemberAdd(BaseModel):
    user_id: str
    role:    str = Field(pattern="^(owner|pm|foreman|supplier|viewer)$")


class MemberUpdate(BaseModel):
    role: str = Field(pattern="^(owner|pm|foreman|supplier|viewer)$")


# ── Список проектов ───────────────────────────────────────────────────────────

@router.get("")
async def list_projects(
    current_user: User         = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    """Проекты, в которых состоит текущий пользователь."""
    members = await db.scalars(
        select(ProjectMember).where(ProjectMember.user_id == current_user.id)
    )
    project_ids = [m.project_id for m in members]
    member_roles = {m.project_id: m.role for m in await db.scalars(
        select(ProjectMember).where(ProjectMember.user_id == current_user.id)
    )}

    projects = await db.scalars(
        select(Project)
        .where(Project.id.in_(project_ids))
        .where(Project.deleted_at == None)
        .order_by(Project.created_at.desc())
    )

    result = []
    for p in projects:
        members_count = await db.scalar(
            select(func.count()).select_from(ProjectMember)
            .where(ProjectMember.project_id == p.id)
        )
        tasks_count = await db.scalar(
            select(func.count()).select_from(GanttTask)
            .where(GanttTask.project_id == p.id)
            .where(GanttTask.deleted_at == None)
        )
        budget = await db.scalar(
            select(func.sum(Estimate.total_price))
            .where(Estimate.project_id == p.id)
            .where(Estimate.deleted_at == None)
        )
        result.append({
            "id":               p.id,
            "name":             p.name,
            "address":          p.address,
            "status":           p.status,
            "dashboard_status": p.dashboard_status,
            "color":            p.color,
            "start_date":       str(p.start_date) if p.start_date else None,
            "end_date":         str(p.end_date)   if p.end_date   else None,
            "my_role":          member_roles.get(p.id),
            "members_count":    members_count or 0,
            "tasks_count":      tasks_count   or 0,
            "budget":           float(budget) if budget else 0,
            "created_at":       p.created_at.isoformat(),
        })
    return result


# ── Создать проект ────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_project(
    body:         ProjectCreate,
    current_user: User         = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    project = Project(
        id              = str(uuid4()),
        organization_id = current_user.organization_id,
        created_by      = current_user.id,
        name            = body.name,
        address         = body.address,
        start_date      = body.start_date,
        end_date        = body.end_date,
        color           = body.color,
    )
    db.add(project)
    await db.flush()

    # Создатель автоматически становится owner
    db.add(ProjectMember(
        id         = str(uuid4()),
        project_id = project.id,
        user_id    = current_user.id,
        role       = "owner",
    ))

    await db.commit()
    return {"id": project.id, "name": project.name, "my_role": "owner"}


# ── Получить проект ───────────────────────────────────────────────────────────

@router.get("/{project_id}")
async def get_project(
    project_id: str,
    member:     ProjectMember = Depends(require_action(Action.VIEW)),
    db:         AsyncSession  = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if not project or project.deleted_at:
        raise HTTPException(404, "Проект не найден")

    budget = await db.scalar(
        select(func.sum(Estimate.total_price))
        .where(Estimate.project_id == project_id)
        .where(Estimate.deleted_at == None)
    )

    return {
        "id":               project.id,
        "name":             project.name,
        "address":          project.address,
        "status":           project.status,
        "dashboard_status": project.dashboard_status,
        "color":            project.color,
        "start_date":       str(project.start_date) if project.start_date else None,
        "end_date":         str(project.end_date)   if project.end_date   else None,
        "budget":           float(budget) if budget else 0,
        "my_role":          member.role,
    }


# ── Редактировать проект ──────────────────────────────────────────────────────

@router.patch("/{project_id}")
async def update_project(
    project_id: str,
    body:       ProjectUpdate,
    member:     ProjectMember = Depends(require_action(Action.MANAGE_PROJECTS)),
    db:         AsyncSession  = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if not project or project.deleted_at:
        raise HTTPException(404)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(project, field, value)

    await db.commit()
    return {"id": project.id, "name": project.name}


# ── Удалить проект ────────────────────────────────────────────────────────────

@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    member:     ProjectMember = Depends(require_action(Action.DELETE)),
    db:         AsyncSession  = Depends(get_db),
):
    from datetime import datetime
    project = await db.get(Project, project_id)
    if not project or project.deleted_at:
        raise HTTPException(404)
    project.deleted_at = datetime.utcnow()
    await db.commit()


# ── Участники ─────────────────────────────────────────────────────────────────

@router.get("/{project_id}/members")
async def list_members(
    project_id: str,
    member:     ProjectMember = Depends(require_action(Action.VIEW)),
    db:         AsyncSession  = Depends(get_db),
):
    members = await db.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project_id)
    )
    result = []
    for m in members:
        user = await db.get(User, m.user_id)
        result.append({
            "id":         m.id,
            "role":       m.role,
            "created_at": m.created_at.isoformat(),
            "user": {
                "id":         user.id,
                "name":       user.name,
                "email":      user.email,
                "avatar_url": user.avatar_url,
                "email_verified": is_effectively_email_verified(user),
            } if user else None,
        })
    return result


@router.post("/{project_id}/members", status_code=201)
async def add_member(
    project_id: str,
    body:       MemberAdd,
    member:     ProjectMember = Depends(require_action(Action.MANAGE_USERS)),
    current_user: User        = Depends(require_verified_user),
    db:         AsyncSession  = Depends(get_db),
):
    # Проверяем нет ли уже такого участника
    existing = await db.scalar(
        select(ProjectMember)
        .where(ProjectMember.project_id == project_id)
        .where(ProjectMember.user_id    == body.user_id)
    )
    if existing:
        raise HTTPException(409, "Пользователь уже является участником проекта")

    user = await db.get(User, body.user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    new_member = ProjectMember(
        id         = str(uuid4()),
        project_id = project_id,
        user_id    = body.user_id,
        invited_by = member.user_id,
        role       = body.role,
    )
    db.add(new_member)
    await db.commit()
    return {"id": new_member.id, "user_id": body.user_id, "role": body.role}


@router.patch("/{project_id}/members/{user_id}")
async def update_member_role(
    project_id: str,
    user_id:    str,
    body:       MemberUpdate,
    member:     ProjectMember = Depends(require_action(Action.MANAGE_USERS)),
    current_user: User        = Depends(require_verified_user),
    db:         AsyncSession  = Depends(get_db),
):
    target = await db.scalar(
        select(ProjectMember)
        .where(ProjectMember.project_id == project_id)
        .where(ProjectMember.user_id    == user_id)
    )
    if not target:
        raise HTTPException(404)

    # Нельзя сменить роль единственному owner
    if target.role == "owner":
        owners_count = await db.scalar(
            select(func.count()).select_from(ProjectMember)
            .where(ProjectMember.project_id == project_id)
            .where(ProjectMember.role       == "owner")
        )
        if (owners_count or 0) <= 1 and body.role != "owner":
            raise HTTPException(400, "В проекте должен быть хотя бы один owner")

    target.role = body.role
    await db.commit()
    return {"user_id": user_id, "role": body.role}


@router.delete("/{project_id}/members/{user_id}", status_code=204)
async def remove_member(
    project_id: str,
    user_id:    str,
    member:     ProjectMember = Depends(require_action(Action.MANAGE_USERS)),
    current_user: User        = Depends(require_verified_user),
    db:         AsyncSession  = Depends(get_db),
):
    target = await db.scalar(
        select(ProjectMember)
        .where(ProjectMember.project_id == project_id)
        .where(ProjectMember.user_id    == user_id)
    )
    if not target:
        raise HTTPException(404)
    await db.delete(target)
    await db.commit()
