from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.fer_vector_index_service import (
    build_row_record,
    fetch_nearest_neighbors,
    fetch_pilot_rows,
    upsert_vector_index_records,
)
from app.services.openrouter_embeddings import create_embeddings, get_openrouter_api_key


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pilot FER embeddings into fer.vector_index")
    parser.add_argument("--table-id", type=int, default=1, help="FER table_id to sample from when --row-id is not used.")
    parser.add_argument("--limit", type=int, default=2, help="How many rows to vectorize in pilot mode.")
    parser.add_argument("--row-id", type=int, action="append", default=[], help="Explicit fer_rows.id to vectorize.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    key = get_openrouter_api_key()
    print(
        "OpenRouter key loaded:",
        f"{key[:6]}...{key[-4:]}" if len(key) > 12 else "***",
    )
    print("Embedding model:", settings.EMBEDDING_MODEL)

    async with AsyncSessionLocal() as db:
        rows = await fetch_pilot_rows(
            db,
            table_id=args.table_id,
            row_ids=args.row_id or None,
            limit=args.limit,
        )
        if len(rows) < 2:
            raise RuntimeError(
                "Pilot requires at least 2 FER rows with non-empty clarification."
            )

        search_texts = []
        records_preview = []
        for row in rows:
            record = build_row_record(row, embedding=[])
            records_preview.append((row, record))
            search_texts.append(record.search_text)

        embeddings = await create_embeddings(search_texts)
        if any(len(embedding) != settings.EMBEDDING_DIM for embedding in embeddings):
            raise RuntimeError("Embedding dimension mismatch with EMBEDDING_DIM.")

        records = []
        for (row, record_preview), embedding in zip(records_preview, embeddings):
            records.append(build_row_record(row, embedding))

        inserted_ids = await upsert_vector_index_records(db, records)

        print()
        print("Inserted / updated rows:")
        for row, record, inserted_id, embedding in zip(rows, records, inserted_ids, embeddings):
            print(
                f"- vector_index.id={inserted_id} row_id={row.row_id} table_id={row.table_id} "
                f"source_text={record.source_text!r}"
            )
            preview = record.search_text.replace("\n", " | ")
            print(f"  search_text={preview[:240]}")
            print(f"  embedding_dim={len(embedding)}")

        print()
        print("Retrieval smoke test:")
        nearest = await fetch_nearest_neighbors(db, embedding=records[0].embedding, limit=5)
        for item in nearest:
            print(
                f"- id={item['id']} row_id={item['row_id']} table_id={item['table_id']} "
                f"distance={item['distance']:.6f} source_text={item['source_text']!r}"
            )


if __name__ == "__main__":
    asyncio.run(main())
