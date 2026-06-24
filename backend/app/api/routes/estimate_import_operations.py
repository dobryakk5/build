from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.routes.admin import require_superadmin
from app.services.estimate_import_worker import TransactionalOutboxPublisher


router = APIRouter(prefix="/api/import-outbox", tags=["estimate-import-operations"])


@router.post("/{outbox_record_id}/replay")
async def replay_dead_letter(
    outbox_record_id: str,
    _current_user=Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    try:
        row = await TransactionalOutboxPublisher(db).replay_dead_letter(outbox_record_id)
    except KeyError as exc:
        raise HTTPException(404, detail={"code": "outbox_record_not_found"}) from exc
    except ValueError as exc:
        raise HTTPException(409, detail={"code": "outbox_record_not_dead_letter"}) from exc
    return {
        "outbox_record_id": row.id,
        "idempotency_key": row.idempotency_key,
        "status": row.status,
    }
