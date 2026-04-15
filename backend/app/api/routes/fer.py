from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

router = APIRouter(prefix="/fer", tags=["fer"])


def _collection_label(collection: dict[str, Any]) -> str:
    return f"Сборник {collection['num']}. {collection['name']}"


def _section_label(section: dict[str, Any]) -> str:
    return section["title"]


def _subsection_label(subsection: dict[str, Any]) -> str:
    return subsection["title"]


async def _fetch_one(db: AsyncSession, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    result = await db.execute(text(sql), params)
    row = result.mappings().first()
    return dict(row) if row is not None else None


async def _fetch_all(db: AsyncSession, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    result = await db.execute(text(sql), params)
    return [dict(row) for row in result.mappings().all()]


async def _get_collection(db: AsyncSession, collection_id: int) -> dict[str, Any]:
    collection = await _fetch_one(
        db,
        """
        SELECT
            c.id,
            c.num,
            c.name,
            COALESCE(c.ignored, FALSE) AS ignored,
            COALESCE(c.ignored, FALSE) AS effective_ignored
        FROM fer.collections c
        WHERE c.id = :collection_id
        """,
        {"collection_id": collection_id},
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="FER collection not found")
    return collection


async def _get_section(db: AsyncSession, collection_id: int, section_id: int) -> dict[str, Any]:
    section = await _fetch_one(
        db,
        """
        SELECT
            s.id,
            s.collection_id,
            s.title,
            COALESCE(s.ignored, FALSE) AS ignored,
            (COALESCE(c.ignored, FALSE) OR COALESCE(s.ignored, FALSE)) AS effective_ignored
        FROM fer.sections s
        JOIN fer.collections c ON c.id = s.collection_id
        WHERE s.id = :section_id AND s.collection_id = :collection_id
        """,
        {"collection_id": collection_id, "section_id": section_id},
    )
    if section is None:
        raise HTTPException(status_code=404, detail="FER section not found")
    return section


async def _get_subsection(
    db: AsyncSession,
    collection_id: int,
    section_id: int,
    subsection_id: int,
) -> dict[str, Any]:
    subsection = await _fetch_one(
        db,
        """
        SELECT
            ss.id,
            ss.section_id,
            ss.title,
            COALESCE(ss.ignored, FALSE) AS ignored,
            (
                COALESCE(c.ignored, FALSE)
                OR COALESCE(s.ignored, FALSE)
                OR COALESCE(ss.ignored, FALSE)
            ) AS effective_ignored
        FROM fer.subsections ss
        JOIN fer.sections s ON s.id = ss.section_id
        JOIN fer.collections c ON c.id = s.collection_id
        WHERE ss.id = :subsection_id
          AND ss.section_id = :section_id
          AND s.collection_id = :collection_id
        """,
        {
            "collection_id": collection_id,
            "section_id": section_id,
            "subsection_id": subsection_id,
        },
    )
    if subsection is None:
        raise HTTPException(status_code=404, detail="FER subsection not found")
    return subsection


@router.get("/collections")
async def fer_collections(db: AsyncSession = Depends(get_db)):
    return await _fetch_all(
        db,
        """
        SELECT
            c.id,
            c.num,
            c.name,
            COALESCE(c.ignored, FALSE) AS ignored,
            COALESCE(c.ignored, FALSE) AS effective_ignored,
            COUNT(DISTINCT s.id)::int AS sections_count,
            COUNT(DISTINCT ss.id)::int AS subsections_count,
            COUNT(DISTINCT t.id)::int AS total_tables_count,
            COUNT(DISTINCT t.id) FILTER (WHERE t.section_id IS NULL)::int AS root_tables_count
        FROM fer.collections c
        LEFT JOIN fer.sections s ON s.collection_id = c.id
        LEFT JOIN fer.subsections ss ON ss.section_id = s.id
        LEFT JOIN fer.fer_tables t ON t.collection_id = c.id
        GROUP BY c.id, c.num, c.name, c.ignored
        ORDER BY c.num
        """,
        {},
    )


@router.get("/browse")
async def fer_browse(
    collection_id: int = Query(...),
    section_id: int | None = Query(None),
    subsection_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if subsection_id is not None and section_id is None:
        raise HTTPException(status_code=400, detail="subsection_id requires section_id")

    collection = await _get_collection(db, collection_id)
    section = await _get_section(db, collection_id, section_id) if section_id is not None else None
    subsection = (
        await _get_subsection(db, collection_id, section_id, subsection_id)
        if subsection_id is not None and section_id is not None
        else None
    )

    breadcrumb = [
        {
            "kind": "collection",
            "id": collection["id"],
            "label": _collection_label(collection),
            "num": collection["num"],
            "ignored": collection["ignored"],
            "effective_ignored": collection["effective_ignored"],
        }
    ]
    if section is not None:
        breadcrumb.append(
            {
                "kind": "section",
                "id": section["id"],
                "label": _section_label(section),
                "ignored": section["ignored"],
                "effective_ignored": section["effective_ignored"],
            }
        )
    if subsection is not None:
        breadcrumb.append(
            {
                "kind": "subsection",
                "id": subsection["id"],
                "label": _subsection_label(subsection),
                "ignored": subsection["ignored"],
                "effective_ignored": subsection["effective_ignored"],
            }
        )

    if subsection is not None:
        items = await _fetch_all(
            db,
            """
            SELECT
                'table' AS kind,
                t.id,
                t.table_title AS title,
                t.row_count::int AS row_count,
                t.table_url,
                t.common_work_name,
                COALESCE(t.ignored, FALSE) AS ignored,
                (
                    COALESCE(c.ignored, FALSE)
                    OR COALESCE(s.ignored, FALSE)
                    OR COALESCE(ss.ignored, FALSE)
                    OR COALESCE(t.ignored, FALSE)
                ) AS effective_ignored
            FROM fer.fer_tables t
            JOIN fer.collections c ON c.id = t.collection_id
            LEFT JOIN fer.sections s ON s.id = t.section_id
            LEFT JOIN fer.subsections ss ON ss.id = t.subsection_id
            WHERE t.collection_id = :collection_id
              AND t.section_id = :section_id
              AND t.subsection_id = :subsection_id
            ORDER BY t.id
            """,
            {
                "collection_id": collection_id,
                "section_id": section_id,
                "subsection_id": subsection_id,
            },
        )
        level = "subsection"
    elif section is not None:
        subsections = await _fetch_all(
            db,
            """
            SELECT
                'subsection' AS kind,
                ss.id,
                ss.title,
                COALESCE(ss.ignored, FALSE) AS ignored,
                (
                    COALESCE(c.ignored, FALSE)
                    OR COALESCE(s.ignored, FALSE)
                    OR COALESCE(ss.ignored, FALSE)
                ) AS effective_ignored,
                COUNT(t.id)::int AS table_count
            FROM fer.subsections ss
            JOIN fer.sections s ON s.id = ss.section_id
            JOIN fer.collections c ON c.id = s.collection_id
            LEFT JOIN fer.fer_tables t ON t.subsection_id = ss.id
            WHERE ss.section_id = :section_id
            GROUP BY ss.id, ss.title, ss.ignored, s.ignored, c.ignored
            ORDER BY ss.id
            """,
            {"section_id": section_id},
        )
        tables = await _fetch_all(
            db,
            """
            SELECT
                'table' AS kind,
                t.id,
                t.table_title AS title,
                t.row_count::int AS row_count,
                t.table_url,
                t.common_work_name,
                COALESCE(t.ignored, FALSE) AS ignored,
                (
                    COALESCE(c.ignored, FALSE)
                    OR COALESCE(s.ignored, FALSE)
                    OR COALESCE(t.ignored, FALSE)
                ) AS effective_ignored
            FROM fer.fer_tables t
            JOIN fer.collections c ON c.id = t.collection_id
            JOIN fer.sections s ON s.id = t.section_id
            WHERE t.collection_id = :collection_id
              AND t.section_id = :section_id
              AND t.subsection_id IS NULL
            ORDER BY t.id
            """,
            {"collection_id": collection_id, "section_id": section_id},
        )
        items = [*subsections, *tables]
        level = "section"
    else:
        sections = await _fetch_all(
            db,
            """
            SELECT
                'section' AS kind,
                s.id,
                s.title,
                COALESCE(s.ignored, FALSE) AS ignored,
                (COALESCE(c.ignored, FALSE) OR COALESCE(s.ignored, FALSE)) AS effective_ignored,
                COUNT(DISTINCT ss.id)::int AS subsection_count,
                COUNT(DISTINCT t.id) FILTER (WHERE t.subsection_id IS NULL)::int AS table_count
            FROM fer.sections s
            JOIN fer.collections c ON c.id = s.collection_id
            LEFT JOIN fer.subsections ss ON ss.section_id = s.id
            LEFT JOIN fer.fer_tables t ON t.section_id = s.id
            WHERE s.collection_id = :collection_id
            GROUP BY s.id, s.title, s.ignored, c.ignored
            ORDER BY s.id
            """,
            {"collection_id": collection_id},
        )
        tables = await _fetch_all(
            db,
            """
            SELECT
                'table' AS kind,
                t.id,
                t.table_title AS title,
                t.row_count::int AS row_count,
                t.table_url,
                t.common_work_name,
                COALESCE(t.ignored, FALSE) AS ignored,
                (
                    COALESCE(c.ignored, FALSE)
                    OR COALESCE(t.ignored, FALSE)
                ) AS effective_ignored
            FROM fer.fer_tables t
            JOIN fer.collections c ON c.id = t.collection_id
            WHERE t.collection_id = :collection_id
              AND t.section_id IS NULL
              AND t.subsection_id IS NULL
            ORDER BY t.id
            """,
            {"collection_id": collection_id},
        )
        items = [*sections, *tables]
        level = "collection"

    return {
        "level": level,
        "collection": collection,
        "section": section,
        "subsection": subsection,
        "breadcrumb": breadcrumb,
        "items": items,
    }


@router.get("/search")
async def fer_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=100),
    collection_id: int | None = Query(None),
    section_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if collection_id is not None and section_id is not None:
        raise HTTPException(status_code=400, detail="Use either collection_id or section_id, not both")

    query = q.strip()
    if not query:
        return []

    rows = await _fetch_all(
        db,
        """
        WITH matched AS (
            SELECT
                t.id AS table_id,
                t.table_title,
                t.row_count::int AS row_count,
                t.table_url,
                t.common_work_name,
                c.id AS collection_id,
                c.num AS collection_num,
                c.name AS collection_name,
                COALESCE(c.ignored, FALSE) AS collection_ignored,
                s.id AS section_id,
                s.title AS section_title,
                COALESCE(s.ignored, FALSE) AS section_ignored,
                ss.id AS subsection_id,
                ss.title AS subsection_title,
                COALESCE(ss.ignored, FALSE) AS subsection_ignored,
                COALESCE(t.ignored, FALSE) AS ignored,
                (
                    COALESCE(c.ignored, FALSE)
                    OR COALESCE(s.ignored, FALSE)
                    OR COALESCE(ss.ignored, FALSE)
                    OR COALESCE(t.ignored, FALSE)
                ) AS effective_ignored,
                CASE
                    WHEN t.table_title ILIKE :pattern THEN 7
                    WHEN COALESCE(t.common_work_name, '') ILIKE :pattern THEN 6
                    WHEN COALESCE(ss.title, '') ILIKE :pattern THEN 5
                    WHEN COALESCE(s.title, '') ILIKE :pattern THEN 4
                    WHEN c.num ILIKE :pattern OR c.name ILIKE :pattern THEN 3
                    WHEN COALESCE(fr.row_slug, '') ILIKE :pattern THEN 2
                    ELSE 1
                END AS match_rank,
                CASE
                    WHEN t.table_title ILIKE :pattern THEN 'table_title'
                    WHEN COALESCE(t.common_work_name, '') ILIKE :pattern THEN 'common_work_name'
                    WHEN COALESCE(ss.title, '') ILIKE :pattern THEN 'subsection'
                    WHEN COALESCE(s.title, '') ILIKE :pattern THEN 'section'
                    WHEN c.num ILIKE :pattern OR c.name ILIKE :pattern THEN 'collection'
                    WHEN COALESCE(fr.row_slug, '') ILIKE :pattern THEN 'row_slug'
                    ELSE 'clarification'
                END AS match_scope,
                CASE
                    WHEN t.table_title ILIKE :pattern THEN t.table_title
                    WHEN COALESCE(t.common_work_name, '') ILIKE :pattern THEN t.common_work_name
                    WHEN COALESCE(ss.title, '') ILIKE :pattern THEN ss.title
                    WHEN COALESCE(s.title, '') ILIKE :pattern THEN s.title
                    WHEN c.num ILIKE :pattern OR c.name ILIKE :pattern THEN CONCAT('Сборник ', c.num, '. ', c.name)
                    WHEN COALESCE(fr.row_slug, '') ILIKE :pattern THEN fr.row_slug
                    ELSE fr.clarification
                END AS matched_text
            FROM fer.fer_tables t
            JOIN fer.collections c ON c.id = t.collection_id
            LEFT JOIN fer.sections s ON s.id = t.section_id
            LEFT JOIN fer.subsections ss ON ss.id = t.subsection_id
            LEFT JOIN fer.fer_rows fr ON fr.table_id = t.id
            WHERE (
                   t.table_title ILIKE :pattern
                OR COALESCE(t.common_work_name, '') ILIKE :pattern
                OR c.num ILIKE :pattern
                OR c.name ILIKE :pattern
                OR COALESCE(s.title, '') ILIKE :pattern
                OR COALESCE(ss.title, '') ILIKE :pattern
                OR COALESCE(fr.row_slug, '') ILIKE :pattern
                OR COALESCE(fr.clarification, '') ILIKE :pattern
            )
              AND (CAST(:collection_id AS integer) IS NULL OR t.collection_id = CAST(:collection_id AS integer))
              AND (CAST(:section_id AS integer) IS NULL OR t.section_id = CAST(:section_id AS integer))
        )
        SELECT
            table_id,
            table_title,
            row_count,
            table_url,
            common_work_name,
            collection_id,
            collection_num,
            collection_name,
            collection_ignored,
            section_id,
            section_title,
            section_ignored,
            subsection_id,
            subsection_title,
            subsection_ignored,
            ignored,
            effective_ignored,
            MAX(match_rank)::int AS match_rank,
            COUNT(*) FILTER (WHERE match_scope IN ('row_slug', 'clarification'))::int AS matching_rows_count,
            (ARRAY_AGG(match_scope ORDER BY match_rank DESC, matched_text NULLS LAST))[1] AS match_scope,
            (ARRAY_REMOVE(ARRAY_AGG(matched_text ORDER BY match_rank DESC, matched_text NULLS LAST), NULL))[1] AS matched_text
        FROM matched
        GROUP BY
            table_id,
            table_title,
            row_count,
            table_url,
            common_work_name,
            collection_id,
            collection_num,
            collection_name,
            collection_ignored,
            section_id,
            section_title,
            section_ignored,
            subsection_id,
            subsection_title,
            subsection_ignored,
            ignored,
            effective_ignored
        ORDER BY
            MAX(match_rank) DESC,
            collection_num,
            table_id
        LIMIT :limit
        """,
        {
            "pattern": f"%{query}%",
            "limit": limit,
            "collection_id": collection_id,
            "section_id": section_id,
        },
    )

    return [
        {
            "table_id": row["table_id"],
            "table_title": row["table_title"],
            "row_count": row["row_count"],
            "table_url": row["table_url"],
            "common_work_name": row["common_work_name"],
            "collection": {
                "id": row["collection_id"],
                "num": row["collection_num"],
                "name": row["collection_name"],
                "ignored": row["collection_ignored"],
                "effective_ignored": row["collection_ignored"],
            },
            "section": (
                {
                    "id": row["section_id"],
                    "title": row["section_title"],
                    "ignored": row["section_ignored"],
                    "effective_ignored": row["collection_ignored"] or row["section_ignored"],
                }
                if row["section_id"] is not None
                else None
            ),
            "subsection": (
                {
                    "id": row["subsection_id"],
                    "title": row["subsection_title"],
                    "ignored": row["subsection_ignored"],
                    "effective_ignored": (
                        row["collection_ignored"]
                        or row["section_ignored"]
                        or row["subsection_ignored"]
                    ),
                }
                if row["subsection_id"] is not None
                else None
            ),
            "ignored": row["ignored"],
            "effective_ignored": row["effective_ignored"],
            "match_scope": row["match_scope"],
            "matched_text": row["matched_text"],
            "matching_rows_count": row["matching_rows_count"],
        }
        for row in rows
    ]


@router.get("/table/{table_id}")
async def fer_table(table_id: int, db: AsyncSession = Depends(get_db)):
    table = await _fetch_one(
        db,
        """
        SELECT
            t.id,
            t.table_title,
            t.table_url,
            t.row_count::int AS row_count,
            t.common_work_name,
            c.id AS collection_id,
            c.num AS collection_num,
            c.name AS collection_name,
            COALESCE(c.ignored, FALSE) AS collection_ignored,
            s.id AS section_id,
            s.title AS section_title,
            COALESCE(s.ignored, FALSE) AS section_ignored,
            ss.id AS subsection_id,
            ss.title AS subsection_title,
            COALESCE(ss.ignored, FALSE) AS subsection_ignored,
            COALESCE(t.ignored, FALSE) AS ignored,
            (
                COALESCE(c.ignored, FALSE)
                OR COALESCE(s.ignored, FALSE)
                OR COALESCE(ss.ignored, FALSE)
                OR COALESCE(t.ignored, FALSE)
            ) AS effective_ignored
        FROM fer.fer_tables t
        JOIN fer.collections c ON c.id = t.collection_id
        LEFT JOIN fer.sections s ON s.id = t.section_id
        LEFT JOIN fer.subsections ss ON ss.id = t.subsection_id
        WHERE t.id = :table_id
        """,
        {"table_id": table_id},
    )
    if table is None:
        raise HTTPException(status_code=404, detail="FER table not found")

    rows = await _fetch_all(
        db,
        """
        SELECT
            id,
            row_slug,
            clarification,
            h_hour::double precision AS h_hour,
            m_hour::double precision AS m_hour
        FROM fer.fer_rows
        WHERE table_id = :table_id
        ORDER BY id
        """,
        {"table_id": table_id},
    )

    breadcrumb = [
        {
            "kind": "collection",
            "id": table["collection_id"],
            "label": f"Сборник {table['collection_num']}. {table['collection_name']}",
            "num": table["collection_num"],
            "ignored": table["collection_ignored"],
            "effective_ignored": table["collection_ignored"],
        }
    ]
    section = None
    subsection = None
    if table["section_id"] is not None:
        section = {
            "id": table["section_id"],
            "title": table["section_title"],
            "ignored": table["section_ignored"],
            "effective_ignored": table["collection_ignored"] or table["section_ignored"],
        }
        breadcrumb.append(
            {
                "kind": "section",
                "id": table["section_id"],
                "label": table["section_title"],
                "ignored": table["section_ignored"],
                "effective_ignored": table["collection_ignored"] or table["section_ignored"],
            }
        )
    if table["subsection_id"] is not None:
        subsection = {
            "id": table["subsection_id"],
            "title": table["subsection_title"],
            "ignored": table["subsection_ignored"],
            "effective_ignored": (
                table["collection_ignored"]
                or table["section_ignored"]
                or table["subsection_ignored"]
            ),
        }
        breadcrumb.append(
            {
                "kind": "subsection",
                "id": table["subsection_id"],
                "label": table["subsection_title"],
                "ignored": table["subsection_ignored"],
                "effective_ignored": (
                    table["collection_ignored"]
                    or table["section_ignored"]
                    or table["subsection_ignored"]
                ),
            }
        )
    breadcrumb.append(
        {
            "kind": "table",
            "id": table["id"],
            "label": table["table_title"],
            "ignored": table["ignored"],
            "effective_ignored": table["effective_ignored"],
        }
    )

    return {
        "id": table["id"],
        "table_title": table["table_title"],
        "table_url": table["table_url"],
        "row_count": table["row_count"],
        "common_work_name": table["common_work_name"],
        "collection": {
            "id": table["collection_id"],
            "num": table["collection_num"],
            "name": table["collection_name"],
            "ignored": table["collection_ignored"],
            "effective_ignored": table["collection_ignored"],
        },
        "section": section,
        "subsection": subsection,
        "ignored": table["ignored"],
        "effective_ignored": table["effective_ignored"],
        "breadcrumb": breadcrumb,
        "rows": rows,
    }
