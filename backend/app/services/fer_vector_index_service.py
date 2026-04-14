from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.fer_hybrid_search_service import build_fts_document_text


@dataclass(slots=True)
class PilotFerRow:
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


@dataclass(slots=True)
class VectorIndexRecord:
    entity_kind: str
    entity_id: int
    parent_entity_kind: str | None
    parent_entity_id: int | None
    collection_id: int
    section_id: int | None
    subsection_id: int | None
    table_id: int | None
    row_id: int | None
    source_field: str
    source_text: str
    search_text: str
    fts_document: str
    provider: str
    model: str
    text_checksum: str
    embedding: list[float]


def build_row_search_text(row: PilotFerRow) -> str:
    table_label = (row.common_work_name or "").strip() or row.table_title.strip()
    parts = [
        f"Сборник {row.collection_num} {row.collection_name.strip()}",
    ]
    if row.section_title:
        parts.append(f"Раздел: {row.section_title.strip()}")
    if row.subsection_title:
        parts.append(f"Подраздел: {row.subsection_title.strip()}")
    parts.append(f"Таблица: {table_label}")
    parts.append(f"Уточнение: {row.clarification.strip()}")
    return "\n".join(parts)


def build_row_record(row: PilotFerRow, embedding: list[float]) -> VectorIndexRecord:
    search_text = build_row_search_text(row)
    return VectorIndexRecord(
        entity_kind="row",
        entity_id=row.row_id,
        parent_entity_kind="table",
        parent_entity_id=row.table_id,
        collection_id=row.collection_id,
        section_id=row.section_id,
        subsection_id=row.subsection_id,
        table_id=row.table_id,
        row_id=row.row_id,
        source_field="clarification",
        source_text=row.clarification.strip(),
        search_text=search_text,
        fts_document=build_fts_document_text(search_text, row.clarification),
        provider="openrouter",
        model=settings.EMBEDDING_MODEL,
        text_checksum=checksum_text(search_text),
        embedding=embedding,
    )


def checksum_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def format_vector(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{value:.12f}" for value in values) + "]"


async def fetch_pilot_rows(
    db: AsyncSession,
    *,
    table_id: int = 1,
    row_ids: Sequence[int] | None = None,
    limit: int = 2,
) -> list[PilotFerRow]:
    if row_ids:
        stmt = text(
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
            WHERE r.id = ANY(:row_ids)
              AND r.clarification IS NOT NULL
              AND btrim(r.clarification) <> ''
            ORDER BY r.id
            """
        )
        rows = (
            await db.execute(stmt.bindparams(row_ids=list(row_ids)))
        ).mappings().all()
    else:
        stmt = text(
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
            WHERE r.table_id = :table_id
              AND r.clarification IS NOT NULL
              AND btrim(r.clarification) <> ''
            ORDER BY r.id
            LIMIT :limit
            """
        )
        rows = (
            await db.execute(stmt, {"table_id": table_id, "limit": limit})
        ).mappings().all()

    return [PilotFerRow(**dict(row)) for row in rows]


async def upsert_vector_index_records(
    db: AsyncSession,
    records: Iterable[VectorIndexRecord],
    *,
    fts_config: str = "russian",
) -> list[int]:
    inserted_ids: list[int] = []
    stmt = text(
        """
        INSERT INTO fer.vector_index (
            entity_kind,
            entity_id,
            parent_entity_kind,
            parent_entity_id,
            collection_id,
            section_id,
            subsection_id,
            table_id,
            row_id,
            source_field,
            source_text,
            search_text,
            fts_document,
            embedding,
            provider,
            model,
            text_checksum,
            created_at,
            updated_at
        ) VALUES (
            :entity_kind,
            :entity_id,
            :parent_entity_kind,
            :parent_entity_id,
            :collection_id,
            :section_id,
            :subsection_id,
            :table_id,
            :row_id,
            :source_field,
            :source_text,
            :search_text,
            to_tsvector(CAST(:fts_config AS regconfig), :fts_document),
            CAST(:embedding AS fer.vector),
            :provider,
            :model,
            :text_checksum,
            NOW(),
            NOW()
        )
        ON CONFLICT (entity_kind, entity_id, source_field, model)
        DO UPDATE SET
            parent_entity_kind = EXCLUDED.parent_entity_kind,
            parent_entity_id = EXCLUDED.parent_entity_id,
            collection_id = EXCLUDED.collection_id,
            section_id = EXCLUDED.section_id,
            subsection_id = EXCLUDED.subsection_id,
            table_id = EXCLUDED.table_id,
            row_id = EXCLUDED.row_id,
            source_text = EXCLUDED.source_text,
            search_text = EXCLUDED.search_text,
            fts_document = EXCLUDED.fts_document,
            embedding = EXCLUDED.embedding,
            provider = EXCLUDED.provider,
            text_checksum = EXCLUDED.text_checksum,
            updated_at = NOW()
        RETURNING id
        """
    )

    for record in records:
        result = await db.execute(
            stmt,
            {
                "entity_kind": record.entity_kind,
                "entity_id": record.entity_id,
                "parent_entity_kind": record.parent_entity_kind,
                "parent_entity_id": record.parent_entity_id,
                "collection_id": record.collection_id,
                "section_id": record.section_id,
                "subsection_id": record.subsection_id,
                "table_id": record.table_id,
                "row_id": record.row_id,
                "source_field": record.source_field,
                "source_text": record.source_text,
                "search_text": record.search_text,
                "fts_document": record.fts_document,
                "embedding": format_vector(record.embedding),
                "provider": record.provider,
                "model": record.model,
                "text_checksum": record.text_checksum,
                "fts_config": fts_config,
            },
        )
        inserted_ids.append(result.scalar_one())

    await db.commit()
    return inserted_ids


async def bulk_upsert_vector_index_records(
    db: AsyncSession,
    records: Iterable[VectorIndexRecord],
    *,
    fts_config: str = "russian",
) -> int:
    params = [
        {
            "entity_kind": record.entity_kind,
            "entity_id": record.entity_id,
            "parent_entity_kind": record.parent_entity_kind,
            "parent_entity_id": record.parent_entity_id,
            "collection_id": record.collection_id,
            "section_id": record.section_id,
            "subsection_id": record.subsection_id,
            "table_id": record.table_id,
            "row_id": record.row_id,
            "source_field": record.source_field,
            "source_text": record.source_text,
            "search_text": record.search_text,
            "fts_document": record.fts_document,
            "embedding": format_vector(record.embedding),
            "provider": record.provider,
            "model": record.model,
            "text_checksum": record.text_checksum,
            "fts_config": fts_config,
        }
        for record in records
    ]
    if not params:
        return 0

    stmt = text(
        """
        INSERT INTO fer.vector_index (
            entity_kind,
            entity_id,
            parent_entity_kind,
            parent_entity_id,
            collection_id,
            section_id,
            subsection_id,
            table_id,
            row_id,
            source_field,
            source_text,
            search_text,
            fts_document,
            embedding,
            provider,
            model,
            text_checksum,
            created_at,
            updated_at
        ) VALUES (
            :entity_kind,
            :entity_id,
            :parent_entity_kind,
            :parent_entity_id,
            :collection_id,
            :section_id,
            :subsection_id,
            :table_id,
            :row_id,
            :source_field,
            :source_text,
            :search_text,
            to_tsvector(CAST(:fts_config AS regconfig), :fts_document),
            CAST(:embedding AS fer.vector),
            :provider,
            :model,
            :text_checksum,
            NOW(),
            NOW()
        )
        ON CONFLICT (entity_kind, entity_id, source_field, model)
        DO UPDATE SET
            parent_entity_kind = EXCLUDED.parent_entity_kind,
            parent_entity_id = EXCLUDED.parent_entity_id,
            collection_id = EXCLUDED.collection_id,
            section_id = EXCLUDED.section_id,
            subsection_id = EXCLUDED.subsection_id,
            table_id = EXCLUDED.table_id,
            row_id = EXCLUDED.row_id,
            source_text = EXCLUDED.source_text,
            search_text = EXCLUDED.search_text,
            fts_document = EXCLUDED.fts_document,
            embedding = EXCLUDED.embedding,
            provider = EXCLUDED.provider,
            text_checksum = EXCLUDED.text_checksum,
            updated_at = NOW()
        """
    )

    await db.execute(stmt, params)
    await db.commit()
    return len(params)


async def fetch_nearest_neighbors(
    db: AsyncSession,
    *,
    embedding: list[float],
    limit: int = 5,
) -> list[dict]:
    stmt = text(
        """
        SELECT
            id,
            entity_kind,
            entity_id,
            table_id,
            row_id,
            source_field,
            source_text,
            search_text,
            model,
            provider,
            embedding OPERATOR(fer.<=>) CAST(:embedding AS fer.vector) AS distance
        FROM fer.vector_index
        ORDER BY embedding OPERATOR(fer.<=>) CAST(:embedding AS fer.vector), id
        LIMIT :limit
        """
    )
    rows = (
        await db.execute(
            stmt,
            {"embedding": format_vector(embedding), "limit": limit},
        )
    ).mappings().all()
    return [dict(row) for row in rows]
