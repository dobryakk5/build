from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.fer_hybrid_search_service import build_fts_document_text, resolve_fts_config
from app.services.fer_vector_index_service import build_row_search_text, checksum_text, format_vector
from app.services.openrouter_embeddings import create_embeddings, get_openrouter_api_key


@dataclass(slots=True)
class RowVectorIndexSource:
    vector_index_id: int
    collection_id: int
    collection_num: str
    collection_name: str
    section_id: int | None
    section_title: str | None
    subsection_id: int | None
    subsection_title: str | None
    table_id: int
    table_title: str
    common_work_name: str | None
    row_id: int
    row_slug: str | None
    clarification: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild row-level FER embeddings and FTS documents in fer.vector_index",
    )
    parser.add_argument("--batch-size", type=int, default=100, help="Embedding request batch size.")
    return parser.parse_args()


async def fetch_total_count() -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("SELECT COUNT(*) FROM fer.vector_index WHERE entity_kind = 'row'")
        )
        return int(result.scalar_one())


async def fetch_batch(offset: int, limit: int) -> list[RowVectorIndexSource]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        vi.id AS vector_index_id,
                        c.id AS collection_id,
                        c.num AS collection_num,
                        c.name AS collection_name,
                        s.id AS section_id,
                        s.title AS section_title,
                        ss.id AS subsection_id,
                        ss.title AS subsection_title,
                        t.id AS table_id,
                        t.table_title,
                        t.common_work_name,
                        r.id AS row_id,
                        r.row_slug,
                        r.clarification
                    FROM fer.vector_index vi
                    JOIN fer.fer_rows r ON r.id = vi.row_id
                    JOIN fer.fer_tables t ON t.id = r.table_id
                    JOIN fer.collections c ON c.id = t.collection_id
                    LEFT JOIN fer.sections s ON s.id = t.section_id
                    LEFT JOIN fer.subsections ss ON ss.id = t.subsection_id
                    WHERE vi.entity_kind = 'row'
                    ORDER BY vi.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": limit, "offset": offset},
            )
        ).mappings().all()
    return [RowVectorIndexSource(**dict(row)) for row in rows]


async def update_batch(
    rows: list[RowVectorIndexSource],
    embeddings: list[list[float]],
    *,
    fts_config: str,
) -> None:
    params = []
    for row, embedding in zip(rows, embeddings):
        search_text = build_row_search_text(row)
        fts_text = build_fts_document_text(search_text, row.clarification)
        params.append(
            {
                "id": row.vector_index_id,
                "source_text": row.clarification.strip(),
                "search_text": search_text,
                "fts_document": fts_text,
                "text_checksum": checksum_text(search_text),
                "embedding": format_vector(embedding),
                "provider": "openrouter",
                "model": settings.EMBEDDING_MODEL,
                "fts_config": fts_config,
            }
        )

    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                """
                UPDATE fer.vector_index AS vi
                SET
                    source_text = batch.source_text,
                    search_text = batch.search_text,
                    fts_document = to_tsvector(CAST(batch.fts_config AS regconfig), batch.fts_document),
                    text_checksum = batch.text_checksum,
                    embedding = CAST(batch.embedding AS fer.vector),
                    provider = batch.provider,
                    model = batch.model,
                    updated_at = NOW()
                FROM (
                    SELECT
                        CAST(:id AS bigint) AS id,
                        CAST(:source_text AS text) AS source_text,
                        CAST(:search_text AS text) AS search_text,
                        CAST(:fts_document AS text) AS fts_document,
                        CAST(:text_checksum AS varchar(64)) AS text_checksum,
                        CAST(:embedding AS text) AS embedding,
                        CAST(:provider AS varchar(32)) AS provider,
                        CAST(:model AS varchar(128)) AS model,
                        CAST(:fts_config AS text) AS fts_config
                ) AS batch
                WHERE vi.id = batch.id
                """
            ),
            params,
        )
        await db.commit()


async def main() -> None:
    args = parse_args()
    key = get_openrouter_api_key()
    print(
        "OpenRouter key loaded:",
        f"{key[:6]}...{key[-4:]}" if len(key) > 12 else "***",
    )
    print("Embedding model:", settings.EMBEDDING_MODEL)
    print("Embedding dim:", settings.EMBEDDING_DIM)
    print("Batch size:", args.batch_size)

    async with AsyncSessionLocal() as db:
        fts_config = await resolve_fts_config(db)
    print("FTS config:", fts_config)

    total_count = await fetch_total_count()
    print("Rows to reindex:", total_count)

    processed = 0
    for offset in range(0, total_count, args.batch_size):
        batch = await fetch_batch(offset, args.batch_size)
        if not batch:
            continue

        texts = [build_row_search_text(row) for row in batch]
        embeddings = await create_embeddings(texts)
        await update_batch(batch, embeddings, fts_config=fts_config)

        processed += len(batch)
        print(f"rows: {processed}/{total_count}")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM fer.vector_index
                WHERE entity_kind = 'row'
                  AND fts_document IS NOT NULL
                """
            )
        )
        fts_ready_count = int(result.scalar_one())

    print("Done.")
    print("Rows processed:", processed)
    print("Rows with populated fts_document:", fts_ready_count)


if __name__ == "__main__":
    asyncio.run(main())
