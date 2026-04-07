# backend/app/api/deps.py
"""
FastAPI dependencies для аутентификации и авторизации.
Используются через Depends() в роутерах.
"""
from uuid import UUID
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.security import decode_token

from app.core.database    import get_db
from app.core.permissions import Action, can
from app.models           import User, ProjectMember


bearer_scheme = HTTPBearer(auto_error=False)


# ── Аутентификация ────────────────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = None
    if credentials is not None:
        token = credentials.credentials
    if token is None:
        token = request.cookies.get(settings.AUTH_ACCESS_COOKIE_NAME)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(token)
        user_id: str = payload.get("sub")
        if not user_id:
            raise ValueError("no sub")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен недействителен или истёк",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user


async def require_verified_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.email_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Подтвердите email для выполнения этого действия",
        )
    return current_user


# ── Авторизация по проекту ────────────────────────────────────────────────────

async def get_project_member(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectMember:
    """
    Возвращает членство пользователя в проекте.
    Если пользователь не участник — 403.
    """
    member = await db.scalar(
        select(ProjectMember)
        .where(ProjectMember.project_id == str(project_id))
        .where(ProjectMember.user_id    == current_user.id)
    )
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к проекту",
        )
    return member


def require_action(action: Action):
    """
    Dependency-фабрика: проверяет что роль участника разрешает действие.

    Использование:
        @router.delete(...)
        async def delete_task(
            member = Depends(require_action(Action.DELETE)),
        ): ...
    """
    async def _check(
        member: ProjectMember = Depends(get_project_member),
    ) -> ProjectMember:
        if not can(member.role, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Роль «{member.role}» не может выполнить «{action}»",
            )
        return member

    return _check


def require_task_in_project(action: Action | None = None):
    """
    Проверяет что задача принадлежит проекту (защита от IDOR).
    Опционально проверяет право на действие.
    """
    from app.models import GanttTask

    async def _check(
        project_id: UUID,
        task_id: UUID,
        member: ProjectMember = Depends(get_project_member),
        db: AsyncSession = Depends(get_db),
    ) -> tuple[ProjectMember, "GanttTask"]:
        task = await db.scalar(
            select(GanttTask)
            .where(GanttTask.id         == str(task_id))
            .where(GanttTask.project_id == str(project_id))
            .where(GanttTask.deleted_at == None)
        )
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")

        if action and not can(member.role, action):
            raise HTTPException(
                status_code=403,
                detail=f"Роль «{member.role}» не может выполнить «{action}»",
            )
        return member, task

    return _check
