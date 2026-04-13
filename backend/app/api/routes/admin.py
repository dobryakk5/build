from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import Organization, Project, User

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_superadmin(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_superadmin:
        raise HTTPException(403, "Доступ запрещён")
    return current_user


class OrgPlanUpdate(BaseModel):
    plan: str = Field(pattern="^(free|pro|enterprise)$")


class UserAdminUpdate(BaseModel):
    is_active: bool | None = None
    is_superadmin: bool | None = None
    name: str | None = None


class FerIgnoreUpdate(BaseModel):
    ignored: bool


_FER_ENTITY_TABLES = {
    "collection": "fer.collections",
    "section": "fer.sections",
    "subsection": "fer.subsections",
    "table": "fer.fer_tables",
}


@router.get("/stats")
async def platform_stats(
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    orgs_count = await db.scalar(select(func.count()).select_from(Organization))
    users_count = await db.scalar(select(func.count()).select_from(User))
    active_users = await db.scalar(
        select(func.count()).select_from(User).where(User.is_active == True)
    )
    projects_count = await db.scalar(
        select(func.count()).select_from(Project).where(Project.deleted_at.is_(None))
    )
    plans = await db.execute(
        select(Organization.plan, func.count().label("count")).group_by(Organization.plan)
    )

    return {
        "orgs_count": orgs_count or 0,
        "users_count": users_count or 0,
        "active_users": active_users or 0,
        "projects_count": projects_count or 0,
        "plans": {row.plan: row.count for row in plans},
    }


@router.get("/organizations")
async def list_organizations(
    q: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Organization)
    if q:
        stmt = stmt.where(Organization.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(Organization.created_at.desc())

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    orgs = list(await db.scalars(stmt.offset(offset).limit(limit)))

    items = []
    for org in orgs:
        users_count = await db.scalar(
            select(func.count()).select_from(User).where(User.organization_id == org.id)
        )
        projects_count = await db.scalar(
            select(func.count())
            .select_from(Project)
                .where(Project.organization_id == org.id)
                .where(Project.deleted_at.is_(None))
        )
        items.append(
            {
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "plan": org.plan,
                "logo_url": org.logo_url,
                "created_at": org.created_at.isoformat(),
                "users_count": users_count or 0,
                "projects_count": projects_count or 0,
            }
        )

    return {"items": items, "total": total or 0, "limit": limit, "offset": offset}


@router.patch("/organizations/{org_id}/plan")
async def update_org_plan(
    org_id: str,
    body: OrgPlanUpdate,
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Организация не найдена")
    org.plan = body.plan
    await db.commit()
    return {"id": org.id, "plan": org.plan}


@router.delete("/organizations/{org_id}", status_code=204)
async def delete_organization(
    org_id: str,
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Организация не найдена")
    await db.delete(org)
    await db.commit()
    return Response(status_code=204)


@router.patch("/fer/{entity_kind}/{entity_id}")
async def update_fer_ignore(
    entity_kind: str,
    entity_id: int,
    body: FerIgnoreUpdate,
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    table_name = _FER_ENTITY_TABLES.get(entity_kind)
    if table_name is None:
        raise HTTPException(404, "Сущность ФЕР не найдена")

    row = (
        await db.execute(
            text(
                f"""
                UPDATE {table_name}
                SET ignored = :ignored
                WHERE id = :entity_id
                RETURNING id, ignored
                """
            ),
            {
                "entity_id": entity_id,
                "ignored": body.ignored,
            },
        )
    ).mappings().first()

    if row is None:
        raise HTTPException(404, "Сущность ФЕР не найдена")

    await db.commit()
    return {
        "entity_kind": entity_kind,
        "id": int(row["id"]),
        "ignored": bool(row["ignored"]),
    }


@router.get("/users")
async def list_users(
    q: str | None = Query(None),
    org_id: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User)
    if q:
        stmt = stmt.where(
            or_(User.email.ilike(f"%{q}%"), User.name.ilike(f"%{q}%"))
        )
    if org_id:
        stmt = stmt.where(User.organization_id == org_id)
    stmt = stmt.order_by(User.created_at.desc())

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    users = list(await db.scalars(stmt.offset(offset).limit(limit)))

    items = []
    for user in users:
        org = await db.get(Organization, user.organization_id) if user.organization_id else None
        items.append(
            {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "avatar_url": user.avatar_url,
                "is_active": user.is_active,
                "is_superadmin": user.is_superadmin,
                "email_verified": user.email_verified_at is not None,
                "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
                "created_at": user.created_at.isoformat(),
                "organization": (
                    {"id": org.id, "name": org.name, "plan": org.plan}
                    if org is not None
                    else None
                ),
            }
        )

    return {"items": items, "total": total or 0, "limit": limit, "offset": offset}


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UserAdminUpdate,
    current_admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    if user.id == current_admin.id:
        raise HTTPException(400, "Нельзя редактировать самого себя через этот эндпоинт")

    if body.is_active is not None:
        user.is_active = body.is_active
    if body.is_superadmin is not None:
        user.is_superadmin = body.is_superadmin
    if body.name is not None:
        user.name = body.name

    user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {
        "id": user.id,
        "name": user.name,
        "is_active": user.is_active,
        "is_superadmin": user.is_superadmin,
    }


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    current_admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == current_admin.id:
        raise HTTPException(400, "Нельзя удалить самого себя")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    await db.delete(user)
    await db.commit()
    return Response(status_code=204)
