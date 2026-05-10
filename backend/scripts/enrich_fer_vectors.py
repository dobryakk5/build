"""
Обогащение векторов fer.vector_index NW-описаниями.

Идея:
  Сейчас table-эмбеддинги построены только из table_title + section/collection.
  Это сухой технический язык ФЕР. Прорабы пишут «залить фундамент», «положить
  плитку» — без NW-контекста vector search не находит хороших совпадений.

  Через nw_fer_table_mapping мы знаем, какие NW сматчены на каждую FER таблицу.
  У NW есть человеческие unique_label, subtype, notes. Если добавить их к search_text,
  embedding ФЕР приближается к человеческой формулировке.

Алгоритм:
  1. SELECT все table-записи из fer.vector_index
  2. Для каждой — SELECT NW мапинги (mapping_type IN direct/partial)
  3. Сформировать новый search_text: оригинал + NW-блок
  4. SHA256 → если совпадает с БД, пропустить
  5. OpenRouter create_embeddings (batch'ами по 50)
  6. UPDATE fer.vector_index in place

Запуск:
    cd backend
    python scripts/enrich_fer_vectors.py --dry-run            # показать что изменится
    python scripts/enrich_fer_vectors.py                       # реальный прогон
    python scripts/enrich_fer_vectors.py --limit 100           # на 100 записях для теста
    python scripts/enrich_fer_vectors.py --batch 100           # размер batch для embeddings
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from hashlib import sha256
from pathlib import Path

# Добавим корень backend в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Загружаем .env
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
for line in ENV_PATH.read_text().splitlines():
    line = line.strip()
    if line.startswith("DATABASE_URL="):
        os.environ["DATABASE_URL"] = line.split("=", 1)[1]
        break

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker  # noqa: E402

from app.services.openrouter_embeddings import create_embeddings  # noqa: E402


def build_enriched_search_text(
    original: str,
    nw_mappings: list[dict],
) -> str:
    """
    Добавляет к оригинальному search_text блок с NW-описаниями.
    Если nw_mappings пусто — возвращает оригинал без изменений.
    """
    if not nw_mappings:
        return original

    # Primary первыми, потом по убыванию confidence
    sorted_nw = sorted(
        nw_mappings,
        key=lambda x: (
            not x["is_primary"],
            {"high": 0, "medium": 1, "low": 2}.get(x["confidence"], 3),
        ),
    )

    labels = [n["unique_label"] for n in sorted_nw if n.get("unique_label")]
    subtypes = [n["subtype"] for n in sorted_nw if n.get("subtype")]
    notes = [n["notes"] for n in sorted_nw if n.get("notes") and "agg" not in (n.get("notes") or "").lower()]

    parts = [original.strip()]
    if labels:
        parts.append("Виды работ: " + "; ".join(dict.fromkeys(labels)))
    if subtypes:
        parts.append("Действия: " + "; ".join(dict.fromkeys(subtypes)))
    # notes даём ограниченно — иначе раздуется промпт
    short_notes = [n for n in notes if len(n) < 120][:3]
    if short_notes:
        parts.append("Контекст: " + "; ".join(dict.fromkeys(short_notes)))

    return "\n".join(parts)


def compute_checksum(text_value: str, model: str) -> str:
    """Хэш как в fer_vector_index_service: SHA256(model + '\\n' + text)."""
    return sha256(f"{model}\n{text_value}".encode("utf-8")).hexdigest()


async def fetch_table_records(db, limit: int | None = None) -> list[dict]:
    sql = """
        SELECT id, entity_id AS table_id, source_text, search_text, model, text_checksum
        FROM fer.vector_index
        WHERE entity_kind = 'table'
        ORDER BY id
    """
    if limit:
        sql += f" LIMIT {limit}"
    rows = await db.execute(text(sql))
    return [dict(r) for r in rows.mappings()]


async def fetch_nw_mappings(db, table_ids: list[int]) -> dict[int, list[dict]]:
    """Для каждого table_id — список NW мапингов (только direct/partial)."""
    if not table_ids:
        return {}
    rows = await db.execute(
        text(
            """
            SELECT m.fer_table_id, m.is_primary, m.confidence, m.notes,
                   i.unique_label, i.subtype
            FROM fer.nw_fer_table_mapping m
            JOIN fer.nw_item i ON i.code = m.nw_item_code
            WHERE m.fer_table_id = ANY(:ids)
              AND m.mapping_type IN ('direct', 'partial')
            """
        ),
        {"ids": table_ids},
    )
    out: dict[int, list[dict]] = {}
    for r in rows.mappings():
        out.setdefault(r["fer_table_id"], []).append(dict(r))
    return out


async def main(dry_run: bool, limit: int | None, batch: int):
    engine = create_async_engine(os.environ["DATABASE_URL"])
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    print(f"[start] dry_run={dry_run} limit={limit} batch={batch}")
    t0 = time.time()

    async with SessionLocal() as db:
        # 1. Все table-записи
        records = await fetch_table_records(db, limit=limit)
        print(f"[load] table-records: {len(records)}")

        # 2. NW мапинги для них
        table_ids = [r["table_id"] for r in records]
        nw_map = await fetch_nw_mappings(db, table_ids)
        with_nw = sum(1 for tid in table_ids if tid in nw_map)
        print(f"[load] из них есть NW мапинги: {with_nw}")

        # 3. Считаем что нужно обновить
        to_update: list[dict] = []
        for r in records:
            mappings = nw_map.get(r["table_id"], [])
            new_text = build_enriched_search_text(r["search_text"] or "", mappings)
            if new_text == (r["search_text"] or "").strip():
                continue
            new_checksum = compute_checksum(new_text, r["model"] or "text-embedding-3-small")
            if new_checksum == r["text_checksum"]:
                continue
            to_update.append({
                "id": r["id"], "table_id": r["table_id"],
                "old_text": r["search_text"], "new_text": new_text,
                "new_checksum": new_checksum,
            })

        print(f"[diff] нужно обновить: {len(to_update)} записей")

        if dry_run:
            print("\n=== DRY-RUN: примеры изменений ===")
            for u in to_update[:5]:
                print(f"\n--- table_id={u['table_id']} (vec_id={u['id']}) ---")
                print(f"  ДО ({len(u['old_text'] or '')}c):\n    {(u['old_text'] or '')[:200]}")
                print(f"  ПОСЛЕ ({len(u['new_text'])}c):\n    {u['new_text'][:400]}")
            print(f"\n[dry-run] завершён. Чтобы записать — запустите без --dry-run")
            return

        if not to_update:
            print("[done] нечего обновлять")
            return

        # 4. Embeddings batch'ами
        updated = 0
        failed = 0
        for i in range(0, len(to_update), batch):
            chunk = to_update[i:i + batch]
            texts = [c["new_text"] for c in chunk]
            print(f"[embed] {i+1}..{i+len(chunk)} из {len(to_update)}", end=" ", flush=True)
            try:
                embeddings = await create_embeddings(texts)
            except Exception as e:
                print(f"\n[error] embeddings batch failed: {e}")
                failed += len(chunk)
                continue

            for c, emb in zip(chunk, embeddings):
                try:
                    await db.execute(
                        text(
                            """
                            UPDATE fer.vector_index
                            SET search_text   = :st,
                                text_checksum = :cs,
                                embedding     = CAST(:emb AS fer.vector),
                                updated_at    = NOW()
                            WHERE id = :id
                            """
                        ),
                        {"st": c["new_text"], "cs": c["new_checksum"],
                         "emb": str(emb), "id": c["id"]},
                    )
                    updated += 1
                except Exception as e:
                    print(f"[error] update id={c['id']}: {e}")
                    failed += 1

            await db.commit()
            elapsed = time.time() - t0
            rate = (i + len(chunk)) / max(elapsed, 0.1)
            print(f"OK ({elapsed:.0f}s, {rate:.1f}/sec)")

        print(f"\n[done] updated: {updated}, failed: {failed}")
        print(f"Всего времени: {time.time() - t0:.1f}s")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Показать diff без записи")
    parser.add_argument("--limit", type=int, default=None, help="Ограничить число table-записей")
    parser.add_argument("--batch", type=int, default=50, help="Размер batch для embeddings (default 50)")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run, args.limit, args.batch))
