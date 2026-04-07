from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from sqlalchemy import text


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.fer_vector_index_service import (
    PilotFerRow,
    VectorIndexRecord,
    bulk_upsert_vector_index_records,
    build_row_record,
)
from app.services.openrouter_embeddings import create_embeddings, get_openrouter_api_key


@dataclass(slots=True)
class CollectionNode:
    collection_id: int
    collection_num: str
    collection_name: str


@dataclass(slots=True)
class SectionNode:
    section_id: int
    collection_id: int
    collection_num: str
    collection_name: str
    section_title: str


@dataclass(slots=True)
class SubsectionNode:
    subsection_id: int
    section_id: int
    collection_id: int
    collection_num: str
    collection_name: str
    section_title: str
    subsection_title: str


@dataclass(slots=True)
class TableNode:
    table_id: int
    collection_id: int
    collection_num: str
    collection_name: str
    section_id: int | None
    section_title: str | None
    subsection_id: int | None
    subsection_title: str | None
    table_title: str
    common_work_name: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Embed full FER hierarchy into fer.vector_index")
    parser.add_argument("--batch-size", type=int, default=100, help="Embedding request batch size.")
    parser.add_argument("--reset", action="store_true", help="Truncate fer.vector_index before processing.")
    return parser.parse_args()


def build_collection_record(node: CollectionNode, embedding: Sequence[float]) -> VectorIndexRecord:
    source_text = node.collection_name.strip()
    return VectorIndexRecord(
        entity_kind="collection",
        entity_id=node.collection_id,
        parent_entity_kind=None,
        parent_entity_id=None,
        collection_id=node.collection_id,
        section_id=None,
        subsection_id=None,
        table_id=None,
        row_id=None,
        source_field="name",
        source_text=source_text,
        search_text=f"Сборник {node.collection_num} {source_text}",
        provider="openrouter",
        model=settings.EMBEDDING_MODEL,
        text_checksum=checksum_text(f"Сборник {node.collection_num} {source_text}"),
        embedding=list(embedding),
    )


def build_section_record(node: SectionNode, embedding: Sequence[float]) -> VectorIndexRecord:
    source_text = node.section_title.strip()
    search_text = "\n".join(
        [
            f"Сборник {node.collection_num} {node.collection_name.strip()}",
            f"Раздел: {source_text}",
        ]
    )
    return VectorIndexRecord(
        entity_kind="section",
        entity_id=node.section_id,
        parent_entity_kind="collection",
        parent_entity_id=node.collection_id,
        collection_id=node.collection_id,
        section_id=node.section_id,
        subsection_id=None,
        table_id=None,
        row_id=None,
        source_field="title",
        source_text=source_text,
        search_text=search_text,
        provider="openrouter",
        model=settings.EMBEDDING_MODEL,
        text_checksum=checksum_text(search_text),
        embedding=list(embedding),
    )


def build_subsection_record(node: SubsectionNode, embedding: Sequence[float]) -> VectorIndexRecord:
    source_text = node.subsection_title.strip()
    search_text = "\n".join(
        [
            f"Сборник {node.collection_num} {node.collection_name.strip()}",
            f"Раздел: {node.section_title.strip()}",
            f"Подраздел: {source_text}",
        ]
    )
    return VectorIndexRecord(
        entity_kind="subsection",
        entity_id=node.subsection_id,
        parent_entity_kind="section",
        parent_entity_id=node.section_id,
        collection_id=node.collection_id,
        section_id=node.section_id,
        subsection_id=node.subsection_id,
        table_id=None,
        row_id=None,
        source_field="title",
        source_text=source_text,
        search_text=search_text,
        provider="openrouter",
        model=settings.EMBEDDING_MODEL,
        text_checksum=checksum_text(search_text),
        embedding=list(embedding),
    )


def build_table_record(node: TableNode, embedding: Sequence[float]) -> VectorIndexRecord:
    source_field = "common_work_name" if node.common_work_name and node.common_work_name.strip() else "title"
    table_label = (node.common_work_name or "").strip() or node.table_title.strip()
    parts = [f"Сборник {node.collection_num} {node.collection_name.strip()}"]
    if node.section_title:
        parts.append(f"Раздел: {node.section_title.strip()}")
    if node.subsection_title:
        parts.append(f"Подраздел: {node.subsection_title.strip()}")
    parts.append(f"Таблица: {table_label}")
    search_text = "\n".join(parts)

    if node.subsection_id is not None:
        parent_kind = "subsection"
        parent_id = node.subsection_id
    elif node.section_id is not None:
        parent_kind = "section"
        parent_id = node.section_id
    else:
        parent_kind = "collection"
        parent_id = node.collection_id

    return VectorIndexRecord(
        entity_kind="table",
        entity_id=node.table_id,
        parent_entity_kind=parent_kind,
        parent_entity_id=parent_id,
        collection_id=node.collection_id,
        section_id=node.section_id,
        subsection_id=node.subsection_id,
        table_id=node.table_id,
        row_id=None,
        source_field=source_field,
        source_text=table_label,
        search_text=search_text,
        provider="openrouter",
        model=settings.EMBEDDING_MODEL,
        text_checksum=checksum_text(search_text),
        embedding=list(embedding),
    )


def checksum_text(value: str) -> str:
    from hashlib import sha256

    return sha256(value.encode("utf-8")).hexdigest()


async def truncate_vector_index() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text("TRUNCATE TABLE fer.vector_index RESTART IDENTITY"))
        await db.commit()


async def fetch_total_count(table_name: str) -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(f"SELECT COUNT(*) FROM fer.{table_name}"))
        return int(result.scalar_one())


async def fetch_collection_batch(offset: int, limit: int) -> list[CollectionNode]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        c.id AS collection_id,
                        c.num AS collection_num,
                        c.name AS collection_name
                    FROM fer.collections c
                    ORDER BY c.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": limit, "offset": offset},
            )
        ).mappings().all()
    return [CollectionNode(**dict(row)) for row in rows]


async def fetch_section_batch(offset: int, limit: int) -> list[SectionNode]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        s.id AS section_id,
                        s.collection_id,
                        c.num AS collection_num,
                        c.name AS collection_name,
                        s.title AS section_title
                    FROM fer.sections s
                    JOIN fer.collections c ON c.id = s.collection_id
                    ORDER BY s.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": limit, "offset": offset},
            )
        ).mappings().all()
    return [SectionNode(**dict(row)) for row in rows]


async def fetch_subsection_batch(offset: int, limit: int) -> list[SubsectionNode]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        ss.id AS subsection_id,
                        s.id AS section_id,
                        c.id AS collection_id,
                        c.num AS collection_num,
                        c.name AS collection_name,
                        s.title AS section_title,
                        ss.title AS subsection_title
                    FROM fer.subsections ss
                    JOIN fer.sections s ON s.id = ss.section_id
                    JOIN fer.collections c ON c.id = s.collection_id
                    ORDER BY ss.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": limit, "offset": offset},
            )
        ).mappings().all()
    return [SubsectionNode(**dict(row)) for row in rows]


async def fetch_table_batch(offset: int, limit: int) -> list[TableNode]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        t.id AS table_id,
                        c.id AS collection_id,
                        c.num AS collection_num,
                        c.name AS collection_name,
                        s.id AS section_id,
                        s.title AS section_title,
                        ss.id AS subsection_id,
                        ss.title AS subsection_title,
                        t.table_title,
                        t.common_work_name
                    FROM fer.fer_tables t
                    JOIN fer.collections c ON c.id = t.collection_id
                    LEFT JOIN fer.sections s ON s.id = t.section_id
                    LEFT JOIN fer.subsections ss ON ss.id = t.subsection_id
                    ORDER BY t.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": limit, "offset": offset},
            )
        ).mappings().all()
    return [TableNode(**dict(row)) for row in rows]


async def fetch_row_batch(offset: int, limit: int) -> list[PilotFerRow]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT
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
                    FROM fer.fer_rows r
                    JOIN fer.fer_tables t ON t.id = r.table_id
                    JOIN fer.collections c ON c.id = t.collection_id
                    LEFT JOIN fer.sections s ON s.id = t.section_id
                    LEFT JOIN fer.subsections ss ON ss.id = t.subsection_id
                    ORDER BY r.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": limit, "offset": offset},
            )
        ).mappings().all()
    return [PilotFerRow(**dict(row)) for row in rows]


async def process_batches[T](
    *,
    label: str,
    total_count: int,
    batch_size: int,
    fetch_batch: Callable[[int, int], asyncio.Future],
    build_record: Callable[[T, Sequence[float]], VectorIndexRecord],
) -> int:
    processed = 0
    for offset in range(0, total_count, batch_size):
        batch: list[T] = await fetch_batch(offset, batch_size)
        if not batch:
            continue

        preview_records = [build_record(item, []) for item in batch]
        embeddings = await create_embeddings(record.search_text for record in preview_records)
        records = [build_record(item, embedding) for item, embedding in zip(batch, embeddings)]

        async with AsyncSessionLocal() as db:
            await bulk_upsert_vector_index_records(db, records)

        processed += len(records)
        print(f"{label}: {processed}/{total_count}")

    return processed


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

    if args.reset:
        await truncate_vector_index()
        print("fer.vector_index truncated with RESTART IDENTITY")

    counts = {
        "collection": await fetch_total_count("collections"),
        "section": await fetch_total_count("sections"),
        "subsection": await fetch_total_count("subsections"),
        "table": await fetch_total_count("fer_tables"),
        "row": await fetch_total_count("fer_rows"),
    }
    print("Planned counts:", counts)

    total_processed = 0
    total_processed += await process_batches(
        label="collections",
        total_count=counts["collection"],
        batch_size=args.batch_size,
        fetch_batch=fetch_collection_batch,
        build_record=build_collection_record,
    )
    total_processed += await process_batches(
        label="sections",
        total_count=counts["section"],
        batch_size=args.batch_size,
        fetch_batch=fetch_section_batch,
        build_record=build_section_record,
    )
    total_processed += await process_batches(
        label="subsections",
        total_count=counts["subsection"],
        batch_size=args.batch_size,
        fetch_batch=fetch_subsection_batch,
        build_record=build_subsection_record,
    )
    total_processed += await process_batches(
        label="tables",
        total_count=counts["table"],
        batch_size=args.batch_size,
        fetch_batch=fetch_table_batch,
        build_record=build_table_record,
    )
    total_processed += await process_batches(
        label="rows",
        total_count=counts["row"],
        batch_size=args.batch_size,
        fetch_batch=fetch_row_batch,
        build_record=build_row_record,
    )

    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT COUNT(*) FROM fer.vector_index"))
        current_count = int(result.scalar_one())

    print("Done.")
    print("Processed records:", total_processed)
    print("Rows in fer.vector_index:", current_count)


if __name__ == "__main__":
    asyncio.run(main())
