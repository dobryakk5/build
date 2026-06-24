from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.services.estimate_batch_revalidation_service import (
    EstimateBatchRevalidationService,
    RevalidationDomainError,
)


router = APIRouter(prefix="/api/estimate-batches", tags=["estimate-batches"])


def raise_revalidation_error(exc: Exception) -> None:
    if isinstance(exc, RevalidationDomainError):
        detail: dict[str, Any] = {"code": exc.code}
        if exc.details:
            detail["details"] = exc.details
        raise HTTPException(exc.http_status, detail=detail) from exc
    raise exc


@router.post("/{batch_id}/revalidate")
async def revalidate_batch(
    batch_id: str,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return (
            await EstimateBatchRevalidationService(db).revalidate(
                batch_id=batch_id,
                requested_by_user_id=current_user.id,
            )
        ).as_dict()
    except Exception as exc:  # noqa: BLE001
        raise_revalidation_error(exc)
