# backend/app/api/routes/comments.py
"""
Fix 9: URL через проект — /projects/{pid}/tasks/{tid}/comments
Защита от IDOR: task_id проверяется через project_id.
"""
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps         import require_task_in_project, get_current_user, get_db
from app.core.permissions import Action
from app.models           import Comment, GanttTask, User
from app.schemas          import CommentCreate, CommentUpdate, CommentResponse

router = APIRouter(
    prefix="/projects/{project_id}/tasks/{task_id}/comments",
    tags=["comments"],
)


async def _build_response(comment: Comment, db: AsyncSession) -> CommentResponse:
    author = await db.get(User, comment.author_id)
    return CommentResponse(
        id          = comment.id,
        task_id     = comment.task_id,
        author      = {"id": author.id, "name": author.name, "avatar_url": author.avatar_url},
        author_role = comment.author_role,
        text        = comment.text,
        attachments = comment.attachments or [],
        edited_at   = comment.edited_at,
        created_at  = comment.created_at,
    )


@router.get("", response_model=list[CommentResponse])
async def list_comments(
    project_id: UUID,
    task_id: UUID,
    member_and_task = Depends(require_task_in_project(Action.VIEW)),
    db: AsyncSession = Depends(get_db),
):
    _, task = member_and_task

    comments = await db.scalars(
        select(Comment)
        .where(Comment.task_id    == task.id)
        .where(Comment.deleted_at == None)
        .order_by(Comment.created_at)
    )
    return [await _build_response(c, db) for c in comments]


@router.post("", response_model=CommentResponse, status_code=201)
async def create_comment(
    project_id: UUID,
    task_id: UUID,
    body: CommentCreate,
    current_user = Depends(get_current_user),
    member_and_task = Depends(require_task_in_project(Action.VIEW)),
    db: AsyncSession = Depends(get_db),
):
    member, task = member_and_task
    from uuid import uuid4

    comment = Comment(
        id          = str(uuid4()),
        task_id     = task.id,
        author_id   = current_user.id,
        author_role = member.role,      # роль фиксируется на момент написания
        text        = body.text,
        attachments = body.attachments,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return await _build_response(comment, db)


@router.patch("/{comment_id}", response_model=CommentResponse)
async def update_comment(
    project_id: UUID,
    task_id: UUID,
    comment_id: str,
    body: CommentUpdate,
    current_user = Depends(get_current_user),
    member_and_task = Depends(require_task_in_project(Action.VIEW)),
    db: AsyncSession = Depends(get_db),
):
    member, _ = member_and_task
    comment = await db.get(Comment, comment_id)

    if not comment or comment.deleted_at:
        raise HTTPException(404, "Комментарий не найден")

    # Редактировать может только автор или owner
    if comment.author_id != current_user.id and member.role != "owner":
        raise HTTPException(403, "Только автор или владелец может редактировать комментарий")

    comment.text      = body.text
    comment.edited_at = datetime.utcnow()
    await db.commit()
    return await _build_response(comment, db)


@router.delete("/{comment_id}")
async def delete_comment(
    project_id: UUID,
    task_id: UUID,
    comment_id: str,
    current_user = Depends(get_current_user),
    member_and_task = Depends(require_task_in_project(Action.VIEW)),
    db: AsyncSession = Depends(get_db),
):
    member, _ = member_and_task
    comment = await db.get(Comment, comment_id)

    if not comment or comment.deleted_at:
        raise HTTPException(404, "Комментарий не найден")

    if comment.author_id != current_user.id and member.role != "owner":
        raise HTTPException(403, "Только автор или владелец может удалить комментарий")

    comment.deleted_at = datetime.utcnow()
    await db.commit()
    return {"deleted": True}
