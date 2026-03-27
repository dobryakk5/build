#!/usr/bin/env python3
"""
import_enir.py — загрузка ЕНИР из JSON-файла в PostgreSQL.

Использование:
    python import_enir.py enir_e3.json \
        --collection-code "Е3" \
        --collection-title "Каменные работы" \
        --sort-order 3

    # Или указать DATABASE_URL явно:
    DATABASE_URL=postgresql+psycopg2://user:pass@localhost/db \
        python import_enir.py enir_e3.json --collection-code "Е3" ...

    # Принудительно перезаписать существующий сборник:
    python import_enir.py enir_e3.json --collection-code "Е3" --overwrite

Переменная окружения DATABASE_URL (sync-драйвер psycopg2):
    Пример: postgresql+psycopg2://postgres:secret@localhost:5432/construction

Если DATABASE_URL не задан — читается из backend/.env как DATABASE_URL=...
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path


# ─── подтягиваем .env если он рядом ──────────────────────────────────────────
def _load_dotenv():
    candidates = [
        Path(__file__).parent / ".env",
        Path(__file__).parent / "backend" / ".env",
    ]
    for p in candidates:
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            print(f"[env] loaded {p}")
            return


_load_dotenv()


def get_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print(
            "ERROR: DATABASE_URL not set.\n"
            "Set it via environment variable or .env file.\n"
            "Example: postgresql+psycopg2://postgres:secret@localhost:5432/construction",
            file=sys.stderr,
        )
        sys.exit(1)
    # asyncpg → psycopg2 для синхронного скрипта
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://") \
              .replace("postgresql://",          "postgresql+psycopg2://")


def _load_payload(json_path: str) -> tuple[dict, list[dict]]:
    with open(json_path, encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, list):
        return {}, payload
    if isinstance(payload, dict):
        paragraphs = payload.get("paragraphs") or []
        if not isinstance(paragraphs, list):
            raise ValueError("'paragraphs' must be a list")
        return payload, paragraphs
    raise ValueError("ENIR JSON must be either a list of paragraphs or a canonical object")


def _normalize_string(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_string_list(value: object | None) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_amendments(value: object | None) -> list[dict]:
    if not isinstance(value, list):
        return []

    items: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        items.append({
            "amendment_date": _normalize_string(item.get("amendment_date")),
            "amendment_number": _normalize_string(item.get("amendment_number")),
            "issuing_bodies": _normalize_string_list(item.get("issuing_bodies")),
        })
    return items


def _normalize_date(value: object | None) -> date | None:
    raw = _normalize_string(value)
    if not raw:
        return None
    return date.fromisoformat(raw)


# ─── основная логика ──────────────────────────────────────────────────────────
def import_collection(
    json_path: str,
    collection_code: str,
    collection_title: str,
    collection_description: str | None,
    sort_order: int,
    overwrite: bool,
) -> None:
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import Session
    except ImportError:
        print("pip install sqlalchemy psycopg2-binary", file=sys.stderr)
        sys.exit(1)

    payload, paragraphs_data = _load_payload(json_path)

    collection_code = _normalize_string(payload.get("collection_name")) or collection_code
    collection_title = _normalize_string(payload.get("collection_title")) or collection_title
    collection_description = payload.get("description") if payload.get("description") is not None else collection_description

    if not collection_code or not collection_title:
        print(
            "ERROR: collection code/title are required.\n"
            "Provide --collection-code and --collection-title or include collection_name and collection_title in JSON.",
            file=sys.stderr,
        )
        sys.exit(1)

    schema_version = int(payload.get("schema_version") or 1)
    source_file = _normalize_string(payload.get("source_file")) or Path(json_path).name
    issuing_bodies = _normalize_string_list(payload.get("issuing_bodies"))
    approval_date = _normalize_date(payload.get("approval_date"))
    approval_number = _normalize_string(payload.get("approval_number"))
    developer = _normalize_string(payload.get("developer"))
    coordination = _normalize_string(payload.get("coordination"))
    amendments = _normalize_amendments(payload.get("amendments"))
    top_level_norm_tables = payload.get("norm_tables") if isinstance(payload.get("norm_tables"), list) else []
    norm_tables_by_paragraph: dict[str, list[dict]] = {}
    for table in top_level_norm_tables:
        if not isinstance(table, dict):
            continue
        para_ref = _normalize_string(table.get("paragraph_id"))
        if not para_ref:
            continue
        norm_tables_by_paragraph.setdefault(para_ref, []).append(table)

    engine = create_engine(get_db_url(), echo=False)

    with Session(engine) as session:
        # ── сборник ──────────────────────────────────────────────────────────
        row = session.execute(
            text("SELECT id FROM enir_collections WHERE code = :code"),
            {"code": collection_code},
        ).fetchone()

        if row:
            if not overwrite:
                print(
                    f"Collection '{collection_code}' already exists (id={row.id}).\n"
                    "Use --overwrite to replace it."
                )
                sys.exit(1)
            collection_id = row.id
            print(f"Overwriting collection '{collection_code}' (id={collection_id}) …")
            # Каскадное удаление параграфов и всего ниже
            session.execute(
                text("DELETE FROM enir_paragraphs WHERE collection_id = :cid"),
                {"cid": collection_id},
            )
            session.execute(
                text(
                    "UPDATE enir_collections "
                    "SET title=:title, schema_version=:schema_version, source_file=:source_file, "
                    " description=:desc, issuing_bodies=CAST(:issuing_bodies AS jsonb), "
                    " approval_date=:approval_date, approval_number=:approval_number, "
                    " developer=:developer, coordination=:coordination, "
                    " amendments=CAST(:amendments AS jsonb), sort_order=:so "
                    "WHERE id=:cid"
                ),
                {
                    "title": collection_title,
                    "schema_version": schema_version,
                    "source_file": source_file,
                    "desc":  collection_description,
                    "issuing_bodies": json.dumps(issuing_bodies, ensure_ascii=False),
                    "approval_date": approval_date,
                    "approval_number": approval_number,
                    "developer": developer,
                    "coordination": coordination,
                    "amendments": json.dumps(amendments, ensure_ascii=False),
                    "so":    sort_order,
                    "cid":   collection_id,
                },
            )
        else:
            res = session.execute(
                text(
                    "INSERT INTO enir_collections "
                    "(code, title, schema_version, source_file, description, issuing_bodies, "
                    " approval_date, approval_number, developer, coordination, amendments, sort_order) "
                    "VALUES ("
                    " :code, :title, :schema_version, :source_file, :desc, CAST(:issuing_bodies AS jsonb),"
                    " :approval_date, :approval_number, :developer, :coordination, CAST(:amendments AS jsonb), :so"
                    ") RETURNING id"
                ),
                {
                    "code":  collection_code,
                    "title": collection_title,
                    "schema_version": schema_version,
                    "source_file": source_file,
                    "desc":  collection_description,
                    "issuing_bodies": json.dumps(issuing_bodies, ensure_ascii=False),
                    "approval_date": approval_date,
                    "approval_number": approval_number,
                    "developer": developer,
                    "coordination": coordination,
                    "amendments": json.dumps(amendments, ensure_ascii=False),
                    "so":    sort_order,
                },
            )
            collection_id = res.scalar_one()
            print(f"Created collection '{collection_code}' (id={collection_id})")

        # ── параграфы ─────────────────────────────────────────────────────────
        for sort_idx, para in enumerate(paragraphs_data):
            para_ref = _normalize_string(para.get("paragraph_id")) or _normalize_string(para.get("code"))
            code  = para.get("code", "")
            title = para.get("title", "")
            unit  = para.get("unit")

            res = session.execute(
                text(
                    "INSERT INTO enir_paragraphs "
                    "(collection_id, code, title, unit, sort_order) "
                    "VALUES (:cid, :code, :title, :unit, :so) RETURNING id"
                ),
                {
                    "cid":   collection_id,
                    "code":  code,
                    "title": title,
                    "unit":  unit,
                    "so":    sort_idx,
                },
            )
            para_id = res.scalar_one()

            # ── состав работ ─────────────────────────────────────────────────
            for comp_idx, comp in enumerate(para.get("work_compositions") or []):
                res2 = session.execute(
                    text(
                        "INSERT INTO enir_work_compositions "
                        "(paragraph_id, condition, sort_order) "
                        "VALUES (:pid, :cond, :so) RETURNING id"
                    ),
                    {"pid": para_id, "cond": comp.get("condition"), "so": comp_idx},
                )
                comp_id = res2.scalar_one()

                for op_idx, op_text in enumerate(comp.get("operations") or []):
                    session.execute(
                        text(
                            "INSERT INTO enir_work_operations "
                            "(composition_id, text, sort_order) "
                            "VALUES (:cid, :text, :so)"
                        ),
                        {"cid": comp_id, "text": op_text, "so": op_idx},
                    )

            # ── состав звена ──────────────────────────────────────────────────
            for member in para.get("crew") or []:
                session.execute(
                    text(
                        "INSERT INTO enir_crew_members "
                        "(paragraph_id, profession, grade, count) "
                        "VALUES (:pid, :prof, :grade, :cnt)"
                    ),
                    {
                        "pid":   para_id,
                        "prof":  member.get("profession", ""),
                        "grade": member.get("grade"),
                        "cnt":   member.get("count", 1),
                    },
                )

            # ── таблицы норм (JSONB) ─────────────────────────────────────────
            para_norm_tables = norm_tables_by_paragraph.get(para_ref)
            if para_norm_tables is None:
                para_norm_tables = para.get("norm_tables") if isinstance(para.get("norm_tables"), list) else []

            for table_idx, table in enumerate(para_norm_tables):
                if not isinstance(table, dict):
                    continue
                session.execute(
                    text(
                        "INSERT INTO enir_norm_tables "
                        "(table_id, paragraph_id, table_order, title, row_count, columns, rows) "
                        "VALUES ("
                        " :table_id, :pid, :table_order, :title, :row_count,"
                        " CAST(:columns AS jsonb), CAST(:rows AS jsonb)"
                        ")"
                    ),
                    {
                        "pid":   para_id,
                        "table_id": _normalize_string(table.get("table_id")) or f"{para_ref}_t{table_idx + 1}",
                        "table_order": table.get("table_order", table_idx),
                        "title": _normalize_string(table.get("title")),
                        "row_count": int(table.get("row_count") or len(table.get("rows") or [])),
                        "columns": json.dumps(table.get("columns") or [], ensure_ascii=False),
                        "rows": json.dumps(table.get("rows") or [], ensure_ascii=False),
                    },
                )

            # ── примечания ────────────────────────────────────────────────────
            for note in para.get("notes") or []:
                session.execute(
                    text(
                        "INSERT INTO enir_notes "
                        "(paragraph_id, num, text, coefficient, pr_code) "
                        "VALUES (:pid, :num, :text, :coef, :prc)"
                    ),
                    {
                        "pid":  para_id,
                        "num":  note.get("num", 0),
                        "text": note.get("text", ""),
                        "coef": note.get("coefficient"),
                        "prc":  note.get("code"),
                    },
                )

            print(f"  [{sort_idx+1:3d}/{len(paragraphs_data)}] {code}  {title[:60]}")

        session.commit()

    print(f"\nDone. {len(paragraphs_data)} paragraphs imported into collection '{collection_code}'.")


# ─── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import ENIR collection from JSON into PostgreSQL"
    )
    parser.add_argument("json_file", help="Path to enir_*.json")
    parser.add_argument("--collection-code",        default="",     help="e.g. Е3")
    parser.add_argument("--collection-title",       default="",     help="e.g. 'Каменные работы'")
    parser.add_argument("--collection-description", default=None,   help="Optional description")
    parser.add_argument("--sort-order",             type=int, default=0)
    parser.add_argument("--overwrite", action="store_true",
                        help="Replace paragraphs if collection already exists")

    args = parser.parse_args()

    import_collection(
        json_path               = args.json_file,
        collection_code         = args.collection_code,
        collection_title        = args.collection_title,
        collection_description  = args.collection_description,
        sort_order              = args.sort_order,
        overwrite               = args.overwrite,
    )
