from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_verified_user
from app.core.database import get_db
from app.models import ProjectMember, User

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/search")
async def search_users(
    email: str = Query(..., min_length=2, max_length=255),
    project_id: str | None = Query(None),
    limit: int = Query(10, ge=1, le=30),
    current_user: User = Depends(require_verified_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.organization_id:
        return []

    users = list(
        await db.scalars(
            select(User)
            .where(User.organization_id == current_user.organization_id)
            .where(User.is_active == True)
            .where(User.id != current_user.id)
            .where(User.email.ilike(f"%{email}%"))
            .order_by(User.email)
            .limit(limit)
        )
    )

    excluded_ids: set[str] = set()
    if project_id:
        excluded_ids = {
            member.user_id
            for member in await db.scalars(
                select(ProjectMember).where(ProjectMember.project_id == project_id)
            )
        }

    return [
        {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "avatar_url": user.avatar_url,
        }
        for user in users
        if user.id not in excluded_ids
    ]


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "avatar_url": current_user.avatar_url,
        "organization_id": current_user.organization_id,
        "is_superadmin": current_user.is_superadmin,
    }
