from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps  import get_current_user, get_db
from app.models    import Notification, User

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    unread_only:  bool         = Query(default=False),
    limit:        int          = Query(default=50, le=100),
    current_user: User         = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    q = (
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        q = q.where(Notification.is_read == False)

    notifications = await db.scalars(q)
    return [
        {
            "id":          n.id,
            "type":        n.type,
            "title":       n.title,
            "body":        n.body,
            "entity_type": n.entity_type,
            "entity_id":   n.entity_id,
            "is_read":     n.is_read,
            "created_at":  n.created_at.isoformat(),
        }
        for n in notifications
    ]


@router.post("/{notification_id}/read", status_code=204)
async def mark_read(
    notification_id: str,
    current_user:    User         = Depends(get_current_user),
    db:              AsyncSession = Depends(get_db),
):
    await db.execute(
        update(Notification)
        .where(Notification.id      == notification_id)
        .where(Notification.user_id == current_user.id)
        .values(is_read=True)
    )
    await db.commit()


@router.post("/read-all", status_code=204)
async def mark_all_read(
    current_user: User         = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    await db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id)
        .where(Notification.is_read == False)
        .values(is_read=True)
    )
    await db.commit()
