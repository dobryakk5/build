from __future__ import annotations

import inspect
import json
import logging
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user, get_db
from app.services.dynamic_floor_feature_flag import FeatureFlagError
from app.services.estimate_preview_db_service import EstimatePreviewService, PreviewDomainError
from app.services.parser_factory import parse_estimate
from app.services.source_file_fingerprint_service import SourceFileFingerprintError


router = APIRouter(prefix="/api/estimate-previews", tags=["estimate-previews"])
logger = logging.getLogger(__name__)


class ConfirmRowDecision(BaseModel):
    source_row_key: str
    approved: bool | None = None
    manual_override: dict[str, Any] | None = None


class ConfirmEstimatePreviewRequest(BaseModel):
    expected_preview_content_hash: str = Field(min_length=64, max_length=64)
    row_decisions: list[ConfirmRowDecision] = Field(default_factory=list)


def _raise(exc: Exception) -> None:
    if isinstance(exc, (PreviewDomainError, FeatureFlagError)):
        detail: dict[str, Any] = {"code": exc.code}
        if isinstance(exc, PreviewDomainError) and exc.details is not None:
            detail["details"] = exc.details
        raise HTTPException(exc.http_status, detail=detail) from exc
    if isinstance(exc, SourceFileFingerprintError):
        raise HTTPException(422, detail={"code": exc.code}) from exc
    if isinstance(exc, (json.JSONDecodeError, KeyError, TypeError, ValueError)):
        raise HTTPException(422, detail={"code": "invalid_preview_request"}) from exc
    raise exc


async def _parse_preview_rows(raw: bytes, metadata: dict[str, Any], filename: str | None) -> list[Any]:
    suffix = Path(filename or "estimate.xlsx").suffix or ".xlsx"
    parser_profile = str(metadata.get("parser_profile") or "auto")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as fh:
        fh.write(raw)
        fh.flush()
        rows, _meta = await run_in_threadpool(parse_estimate, fh.name, parser_profile)
        return list(rows)


async def _create_preview_impl(
    *,
    file: UploadFile,
    metadata_json: str,
    current_user: Any,
    db: AsyncSession,
    parse_preview_rows: Callable[[bytes, dict[str, Any], str | None], Any] = _parse_preview_rows,
) -> dict[str, Any]:
    try:
        metadata = json.loads(metadata_json)
        raw = await file.read()
        parsed = parse_preview_rows(raw, metadata, file.filename)
        rows = await parsed if inspect.isawaitable(parsed) else parsed
        service = EstimatePreviewService(db=db)
        return await service.create_and_activate_preview(
            owner_user_id=current_user.id,
            project_id=str(metadata["project_id"]),
            estimate_type_id=str(metadata["estimate_type_id"]),
            project_variant_id=str(metadata["project_variant_id"]),
            building_params=dict(metadata.get("building_params") or {}),
            project_structure_options=dict(metadata.get("project_structure_options") or {}),
            raw_uploaded_bytes=raw,
            parsed_rows=rows,
        )
    except Exception as exc:  # noqa: BLE001
        _raise(exc)


@router.post("")
async def create_preview(
    file: UploadFile = File(...),
    metadata_json: str = Form(...),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _create_preview_impl(
        file=file,
        metadata_json=metadata_json,
        current_user=current_user,
        db=db,
    )


@router.get("/{preview_session_id}")
async def get_preview(
    preview_session_id: str,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await EstimatePreviewService(db=db).get_preview(
            owner_user_id=current_user.id,
            preview_session_id=preview_session_id,
        )
    except Exception as exc:  # noqa: BLE001
        _raise(exc)


@router.post("/{preview_session_id}/cancel", status_code=204, response_class=Response, response_model=None)
async def cancel_preview(
    preview_session_id: str,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await EstimatePreviewService(db=db).cancel_preview(
            owner_user_id=current_user.id,
            preview_session_id=preview_session_id,
        )
    except Exception as exc:  # noqa: BLE001
        _raise(exc)


@router.post("/{preview_session_id}/confirm")
async def confirm_preview(
    preview_session_id: str,
    body: ConfirmEstimatePreviewRequest,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    try:
        decisions = [
            item.model_dump() if hasattr(item, "model_dump") else item.dict()
            for item in body.row_decisions
        ]
        result = (
            await EstimatePreviewService(db=db).confirm_preview(
                owner_user_id=current_user.id,
                preview_session_id=preview_session_id,
                expected_preview_content_hash=body.expected_preview_content_hash,
                row_decisions=decisions,
            )
        ).as_dict()
        try:
            from app.tasks.estimate_import_tasks import process_stage10_estimate_import_queue

            process_stage10_estimate_import_queue.delay()
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stage10 import drain task was not enqueued after preview confirm %s: %s",
                preview_session_id,
                exc,
            )
        return result
    except Exception as exc:  # noqa: BLE001
        _raise(exc)
