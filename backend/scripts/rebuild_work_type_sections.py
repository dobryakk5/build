from __future__ import annotations

import asyncio
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import bindparam, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def _database_url() -> str:
    env = dotenv_values(ENV_PATH)
    url = env.get("DATABASE_URL")
    if not url:
        raise RuntimeError(f"DATABASE_URL not found in {ENV_PATH}")
    return str(url)


SELECT_SECTION_IDS_SQL = text(
    """
    SELECT s.id
    FROM fer.sections s
    JOIN fer.collections c ON c.id = s.collection_id
    WHERE CAST(c.num AS integer) = ANY(:collection_nums)
    ORDER BY CAST(c.num AS integer), s.id
    """
).bindparams(bindparam("collection_nums", type_=postgresql.ARRAY(postgresql.INTEGER)))


UPDATE_WORK_TYPE_SQL = text(
    """
    UPDATE fer.work_type_sections
    SET section_ids = :section_ids
    WHERE id = :work_type_id
    """
).bindparams(bindparam("section_ids", type_=postgresql.ARRAY(postgresql.INTEGER)))


async def main() -> None:
    engine = create_async_engine(_database_url())
    async with engine.begin() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT id, section_ids
                    FROM fer.work_type_sections
                    ORDER BY id
                    """
                )
            )
        ).mappings().all()

        print(f"Found {len(rows)} work_type_sections rows")
        for row in rows:
            collection_nums = [int(value) for value in (row["section_ids"] or [])]
            section_ids = (
                await conn.execute(
                    SELECT_SECTION_IDS_SQL,
                    {"collection_nums": collection_nums},
                )
            ).scalars().all()
            section_ids = [int(value) for value in section_ids]
            await conn.execute(
                UPDATE_WORK_TYPE_SQL,
                {
                    "work_type_id": int(row["id"]),
                    "section_ids": section_ids,
                },
            )
            print(
                f"work_type={int(row['id'])}: "
                f"collections={collection_nums} -> sections={len(section_ids)}"
            )

    await engine.dispose()
    print("fer.work_type_sections rebuilt successfully")


if __name__ == "__main__":
    asyncio.run(main())
