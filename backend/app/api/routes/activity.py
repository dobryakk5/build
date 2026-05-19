from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_action
from app.core.permissions import Action
from app.models import ActivityEvent, Project, ProjectMember, User


router = APIRouter(tags=["activity"])


class ActivityEventCreate(BaseModel):
    project_id: UUID | None = None
    session_id: UUID | None = None
    event_type: str = Field(min_length=1, max_length=80)
    entity_type: str | None = Field(default=None, max_length=50)
    entity_id: UUID | None = None
    path: str | None = Field(default=None, max_length=2048)
    metadata: dict = Field(default_factory=dict)


def serialize_event(event: ActivityEvent, user: User | None = None) -> dict:
    return {
        "id": event.id,
        "organization_id": event.organization_id,
        "project_id": event.project_id,
        "user_id": event.user_id,
        "user": (
            {
                "id": user.id,
                "name": user.name,
                "email": user.email,
            }
            if user
            else None
        ),
        "session_id": event.session_id,
        "event_type": event.event_type,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "path": event.path,
        "metadata": event.meta or {},
        "created_at": event.created_at.isoformat(),
    }


@router.post("/activity-events", status_code=201)
async def create_activity_event(
    body: ActivityEventCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project_id = str(body.project_id) if body.project_id else None
    if project_id:
        member = await db.scalar(
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id)
            .where(ProjectMember.user_id == current_user.id)
        )
        if not member:
            raise HTTPException(403, "Нет доступа к проекту")

        project = await db.get(Project, project_id)
        if not project or project.deleted_at:
            raise HTTPException(404, "Проект не найден")
        organization_id = project.organization_id
    else:
        organization_id = current_user.organization_id

    event = ActivityEvent(
        organization_id=organization_id,
        project_id=project_id,
        user_id=current_user.id,
        session_id=str(body.session_id) if body.session_id else None,
        event_type=body.event_type,
        entity_type=body.entity_type,
        entity_id=str(body.entity_id) if body.entity_id else None,
        path=body.path,
        meta=body.metadata,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return serialize_event(event, current_user)


@router.get("/projects/{project_id}/activity-events")
async def list_project_activity_events(
    project_id: UUID,
    event_type: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    member: ProjectMember = Depends(require_action(Action.VIEW)),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ActivityEvent, User)
        .outerjoin(User, User.id == ActivityEvent.user_id)
        .where(ActivityEvent.project_id == str(project_id))
        .order_by(ActivityEvent.created_at.desc(), ActivityEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if event_type:
        stmt = stmt.where(ActivityEvent.event_type == event_type)

    rows = await db.execute(stmt)
    return [serialize_event(event, user) for event, user in rows]
