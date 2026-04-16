from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Estimate, EstimateBatch, Job
from app.services.fer_hybrid_search_service import normalize_smeta_item
from app.services.fer_vector_index_service import format_vector
from app.services.openrouter_embeddings import create_embeddings

FER_KNOWLEDGE_IMPORT_JOB_TYPE = "fer_knowledge_import"
FER_KNOWLEDGE_IMPORT_BATCH_SIZE = 100
FER_KNOWLEDGE_IMPORT_PAUSE_SECONDS = 0.2


@dataclass(slots=True)
class FerExampleMatch:
    fer_table_id: int
    fer_work_type: str
    fer_code: str | None
    score: float


async def import_fer_knowledge_batch(
    *,
    batch_id: str,
    admin_user_id: str | None,
    db: AsyncSession,
) -> dict[str, Any]:
    batch = await db.scalar(
        select(EstimateBatch)
        .where(EstimateBatch.id == batch_id)
        .where(EstimateBatch.deleted_at.is_(None))
    )
    if batch is None:
        raise HTTPException(404, "Блок сметы не найден")

    matched_estimates = list(
        await db.scalars(
            select(Estimate)
            .where(Estimate.estimate_batch_id == batch_id)
            .where(Estimate.deleted_at.is_(None))
            .where(Estimate.fer_table_id.is_not(None))
            .order_by(Estimate.row_order, Estimate.id)
        )
    )
    total_matched_rows = len(matched_estimates)
    if not matched_estimates:
        return {
            "batch_id": batch_id,
            "total_matched_rows": 0,
            "imported_count": 0,
            "skipped_duplicates": 0,
            "embedding_job_id": None,
            "status": "no_matched_rows",
            "reason": "no_matched_rows",
        }

    payload_rows = [
        {
            "estimate_text": str(estimate.work_name).strip(),
            "fer_table_id": int(estimate.fer_table_id),
            "fer_work_type": str(estimate.fer_work_type or "").strip() or None,
            "fer_code": None,
            "source_batch_id": batch_id,
            "confirmed_by": "admin_import",
        }
        for estimate in matched_estimates
        if str(estimate.work_name or "").strip()
    ]

    inserted_ids = await _insert_fer_match_examples(payload_rows, db)
    imported_count = len(inserted_ids)
    skipped_duplicates = total_matched_rows - imported_count

    if not inserted_ids:
        return {
            "batch_id": batch_id,
            "total_matched_rows": total_matched_rows,
            "imported_count": 0,
            "skipped_duplicates": skipped_duplicates,
            "embedding_job_id": None,
            "status": "already_imported",
        }

    job = Job(
        id=str(uuid4()),
        type=FER_KNOWLEDGE_IMPORT_JOB_TYPE,
        status="pending",
        project_id=batch.project_id,
        created_by=admin_user_id,
        input={
            "batch_id": batch_id,
            "estimate_batch_name": batch.name,
            "total_matched_rows": total_matched_rows,
            "imported_count": imported_count,
            "skipped_duplicates": skipped_duplicates,
            "example_ids": inserted_ids,
        },
        result={
            "batch_id": batch_id,
            "total": imported_count,
            "embedded": 0,
            "failed_rows": 0,
            "imported_count": imported_count,
            "total_matched_rows": total_matched_rows,
            "skipped_duplicates": skipped_duplicates,
        },
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    asyncio.create_task(_process_fer_knowledge_import_job(job.id))

    return {
        "batch_id": batch_id,
        "total_matched_rows": total_matched_rows,
        "imported_count": imported_count,
        "skipped_duplicates": skipped_duplicates,
        "embedding_job_id": job.id,
        "status": "import_queued",
    }


async def get_fer_knowledge_import_job_status(
    *,
    job_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    job = await db.get(Job, job_id)
    if job is None or job.type != FER_KNOWLEDGE_IMPORT_JOB_TYPE:
        raise HTTPException(404, "Задача импорта не найдена")
    return _serialize_fer_knowledge_import_job(job)


async def list_recent_fer_knowledge_imports(
    *,
    db: AsyncSession,
    limit: int = 10,
) -> list[dict[str, Any]]:
    jobs = list(
        await db.scalars(
            select(Job)
            .where(Job.type == FER_KNOWLEDGE_IMPORT_JOB_TYPE)
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
    )
    return [_serialize_fer_knowledge_import_job(job) for job in jobs]


async def search_fer_match_example(
    db: AsyncSession,
    *,
    query_text: str,
    threshold: float | None = None,
) -> FerExampleMatch | None:
    cleaned = str(query_text or "").strip()
    if not cleaned:
        return None

    query_embedding = (await create_embeddings([cleaned]))[0]
    return await search_fer_match_example_by_embedding(
        db,
        query_embedding=query_embedding,
        threshold=threshold,
    )


async def search_fer_match_example_by_embedding(
    db: AsyncSession,
    *,
    query_embedding: Sequence[float],
    threshold: float | None = None,
) -> FerExampleMatch | None:
    row = (
        await db.execute(
            text(
                """
                SELECT
                    fer_table_id,
                    fer_work_type,
                    fer_code,
                    1 - (embedding OPERATOR(fer.<=>) CAST(:embedding AS fer.vector)) AS score
                FROM fer_match_examples
                WHERE embedding IS NOT NULL
                ORDER BY embedding OPERATOR(fer.<=>) CAST(:embedding AS fer.vector), id
                LIMIT 1
                """
            ),
            {"embedding": format_vector(query_embedding)},
        )
    ).mappings().first()
    if row is None:
        return None

    score = float(row["score"] or 0.0)
    threshold_value = float(threshold if threshold is not None else settings.FER_EXAMPLE_MATCH_THRESHOLD)
    if score < threshold_value:
        return None

    return FerExampleMatch(
        fer_table_id=int(row["fer_table_id"]),
        fer_work_type=str(row["fer_work_type"] or "").strip(),
        fer_code=str(row["fer_code"]).strip() if row["fer_code"] is not None else None,
        score=score,
    )


def _serialize_fer_knowledge_import_job(job: Job) -> dict[str, Any]:
    result = job.result or {}
    return {
        "job_id": job.id,
        "batch_id": str(result.get("batch_id") or job.input.get("batch_id") or ""),
        "status": job.status,
        "total": int(result.get("total") or 0),
        "embedded": int(result.get("embedded") or 0),
        "failed_rows": int(result.get("failed_rows") or 0),
        "imported_count": int(result.get("imported_count") or job.input.get("imported_count") or 0),
        "total_matched_rows": int(result.get("total_matched_rows") or job.input.get("total_matched_rows") or 0),
        "skipped_duplicates": int(result.get("skipped_duplicates") or job.input.get("skipped_duplicates") or 0),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error": result.get("error"),
    }


async def _insert_fer_match_examples(
    rows: Sequence[dict[str, Any]],
    db: AsyncSession,
) -> list[int]:
    if not rows:
        return []

    inserted = (
        await db.execute(
            text(
                """
                WITH payload AS (
                    SELECT *
                    FROM jsonb_to_recordset(CAST(:rows_json AS jsonb)) AS x(
                        estimate_text text,
                        fer_table_id integer,
                        fer_work_type text,
                        fer_code text,
                        source_batch_id uuid,
                        confirmed_by text
                    )
                )
                INSERT INTO fer_match_examples (
                    estimate_text,
                    fer_table_id,
                    fer_work_type,
                    fer_code,
                    source_batch_id,
                    confirmed_by
                )
                SELECT
                    payload.estimate_text,
                    payload.fer_table_id,
                    payload.fer_work_type,
                    payload.fer_code,
                    payload.source_batch_id,
                    payload.confirmed_by
                FROM payload
                WHERE payload.estimate_text IS NOT NULL
                  AND btrim(payload.estimate_text) <> ''
                ON CONFLICT (estimate_text, fer_table_id) DO NOTHING
                RETURNING id
                """
            ),
            {"rows_json": json.dumps(rows, ensure_ascii=False)},
        )
    ).scalars().all()
    return [int(item) for item in inserted]


async def _process_fer_knowledge_import_job(job_id: str) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if job is None:
            return

        example_ids = [int(item) for item in (job.input or {}).get("example_ids", [])]
        total = len(example_ids)
        job.status = "processing"
        job.started_at = datetime.utcnow()
        job.result = {
            **(job.result or {}),
            "batch_id": str((job.input or {}).get("batch_id") or ""),
            "total": total,
            "embedded": 0,
            "failed_rows": 0,
        }
        await db.commit()

        try:
            embedded = 0
            failed_rows = 0
            for index in range(0, total, FER_KNOWLEDGE_IMPORT_BATCH_SIZE):
                chunk_ids = example_ids[index : index + FER_KNOWLEDGE_IMPORT_BATCH_SIZE]
                chunk_rows = await _load_examples_for_embedding(chunk_ids, db)
                if not chunk_rows:
                    continue

                normalized_rows: list[dict[str, Any]] = []
                for row in chunk_rows:
                    estimate_text = str(row["estimate_text"] or "").strip()
                    if not estimate_text:
                        failed_rows += 1
                        continue
                    try:
                        estimate_text_norm = await normalize_smeta_item(
                            section=None,
                            work_name=estimate_text,
                            unit=None,
                        )
                    except Exception:
                        estimate_text_norm = estimate_text

                    normalized_rows.append(
                        {
                            "id": int(row["id"]),
                            "estimate_text_norm": estimate_text_norm or estimate_text,
                        }
                    )

                chunk_embedded, chunk_failed = await _embed_example_rows(normalized_rows, db)
                embedded += chunk_embedded
                failed_rows += chunk_failed

                job.result = {
                    **(job.result or {}),
                    "total": total,
                    "embedded": embedded,
                    "failed_rows": failed_rows,
                }
                await db.commit()

                if index + FER_KNOWLEDGE_IMPORT_BATCH_SIZE < total:
                    await asyncio.sleep(FER_KNOWLEDGE_IMPORT_PAUSE_SECONDS)

            job.status = "done"
        except Exception as exc:
            job.status = "failed"
            job.result = {
                **(job.result or {}),
                "error": str(exc),
            }
        finally:
            job.finished_at = datetime.utcnow()
            await db.commit()


async def _load_examples_for_embedding(
    example_ids: Sequence[int],
    db: AsyncSession,
) -> list[dict[str, Any]]:
    if not example_ids:
        return []
    rows = (
        await db.execute(
            text(
                """
                SELECT id, estimate_text
                FROM fer_match_examples
                WHERE id = ANY(:example_ids)
                  AND embedding IS NULL
                ORDER BY id
                """
            ),
            {"example_ids": [int(example_id) for example_id in example_ids]},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def _embed_example_rows(
    rows: Sequence[dict[str, Any]],
    db: AsyncSession,
) -> tuple[int, int]:
    if not rows:
        return 0, 0

    texts = [str(row["estimate_text_norm"]) for row in rows]
    try:
        embeddings = await create_embeddings(texts)
        await _update_example_embeddings(
            [
                {
                    "id": int(row["id"]),
                    "estimate_text_norm": str(row["estimate_text_norm"]),
                    "embedding": format_vector(embedding),
                }
                for row, embedding in zip(rows, embeddings)
            ],
            db,
        )
        return len(rows), 0
    except Exception:
        embedded = 0
        failed_rows = 0
        for row in rows:
            try:
                embedding = (await create_embeddings([str(row["estimate_text_norm"])]))[0]
                await _update_example_embeddings(
                    [
                        {
                            "id": int(row["id"]),
                            "estimate_text_norm": str(row["estimate_text_norm"]),
                            "embedding": format_vector(embedding),
                        }
                    ],
                    db,
                )
                embedded += 1
            except Exception:
                failed_rows += 1
        return embedded, failed_rows


async def _update_example_embeddings(
    rows: Sequence[dict[str, Any]],
    db: AsyncSession,
) -> None:
    if not rows:
        return

    await db.execute(
        text(
            """
            WITH payload AS (
                SELECT *
                FROM jsonb_to_recordset(CAST(:rows_json AS jsonb)) AS x(
                    id bigint,
                    estimate_text_norm text,
                    embedding text
                )
            )
            UPDATE fer_match_examples AS target
            SET
                estimate_text_norm = payload.estimate_text_norm,
                embedding = CAST(payload.embedding AS fer.vector)
            FROM payload
            WHERE target.id = payload.id
            """
        ),
        {"rows_json": json.dumps(rows, ensure_ascii=False)},
    )
