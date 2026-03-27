#!/usr/bin/env python3
"""
import_enir.py — загрузка ЕНИР из JSON-файла в PostgreSQL.

Использование:
    python import_enir.py enir_e3.json \
        --cross-ref-json cross_references_annotated.json \
        --sort-order 3

    # Или указать DATABASE_URL явно:
    DATABASE_URL=postgresql+psycopg2://user:pass@localhost/db \
        python import_enir.py enir_e3.json ...

    # Явно переопределить код/название коллекции:
    python import_enir.py enir_e3.json \
        --collection-code "Е3" \
        --collection-title "Каменные работы"

    # Принудительно перезаписать существующий сборник:
    python import_enir.py enir_e3.json --overwrite \
        --cross-ref-json cross_references_annotated.json

Переменная окружения DATABASE_URL (sync-драйвер psycopg2):
    Пример: postgresql+psycopg2://postgres:secret@localhost:5432/construction

Если DATABASE_URL не задан — читается из backend/.env как DATABASE_URL=...
"""

import argparse
import ast
import json
import os
import re
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


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


def _detect_payload_format(payload: Any) -> str:
    if isinstance(payload, list):
        return "paragraphs_v1"
    if isinstance(payload, dict):
        required = {
            "paragraphs",
            "paragraph_work_items",
            "paragraph_crew_items",
            "paragraph_notes",
            "norm_tables",
            "norm_columns",
            "norm_rows",
            "norm_values",
        }
        if required.issubset(payload.keys()):
            return "e1_db"
    raise ValueError("Unsupported ENIR JSON format")


def _safe_parse_work_item(raw_text: str) -> dict[str, Any] | None:
    try:
        parsed = ast.literal_eval(raw_text)
    except (ValueError, SyntaxError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_paragraph_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper().replace("З", "3")
    return normalized or None


def _resolve_paragraph_db_id(paragraph_lookup: dict[str, int], raw_value: str | None) -> int | None:
    key = _normalize_paragraph_key(raw_value)
    if key is None:
        return None
    return paragraph_lookup.get(key)


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value is None:
            continue
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _parse_value_numeric(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None

    raw = str(value).strip().replace("\xa0", " ")
    if not raw or raw in {"-", "—"}:
        return None

    compact = raw.replace(" ", "").replace(",", ".")

    if re.fullmatch(r"-?\d+(?:\.\d+)?", compact):
        try:
            return Decimal(compact)
        except InvalidOperation:
            return None

    m_price = re.fullmatch(r"(-?\d+)-(\d+)", compact)
    if m_price:
        left, right = m_price.groups()
        try:
            return Decimal(f"{left}.{right}")
        except InvalidOperation:
            return None

    m_mixed = re.fullmatch(r"(-?\d+)\s+(\d+)/(\d+)", raw)
    if m_mixed:
        whole, num, den = m_mixed.groups()
        if den != "0":
            try:
                return Decimal(whole) + (Decimal(num) / Decimal(den))
            except InvalidOperation:
                return None

    m_fraction = re.fullmatch(r"(-?\d+)/(\d+)", compact)
    if m_fraction:
        num, den = m_fraction.groups()
        if den != "0":
            try:
                return Decimal(num) / Decimal(den)
            except InvalidOperation:
                return None

    return None


def _resolve_collection_metadata(
    payload: Any,
    cli_collection_code: str | None,
    cli_collection_title: str | None,
) -> tuple[str, str]:
    payload_collection_code = None
    payload_collection_title = None

    if isinstance(payload, dict):
        payload_collection_code = _first_non_empty(
            payload.get("collection_code"),
            payload.get("collection_name"),
        )
        payload_collection_title = _first_non_empty(
            payload.get("collection_title"),
            payload.get("issue_title"),
        )

    collection_code = _first_non_empty(cli_collection_code, payload_collection_code)
    collection_title = _first_non_empty(cli_collection_title, payload_collection_title)

    if not collection_code:
        raise ValueError(
            "Collection code is missing. Pass --collection-code or provide "
            "'collection_code'/'collection_name' in the JSON."
        )
    if not collection_title:
        raise ValueError(
            "Collection title is missing. Pass --collection-title or provide "
            "'collection_title'/'issue_title' in the JSON."
        )

    return collection_code, collection_title


def _upsert_collection(
    session,
    text,
    collection_code: str,
    collection_title: str,
    collection_description: str | None,
    issue: str | None,
    issue_title: str | None,
    sort_order: int,
    overwrite: bool,
    source_file: str | None,
    source_format: str,
) -> int:
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
        session.execute(
            text("DELETE FROM enir_technical_coefficients WHERE collection_id = :cid"),
            {"cid": collection_id},
        )
        session.execute(
            text("DELETE FROM enir_paragraphs WHERE collection_id = :cid"),
            {"cid": collection_id},
        )
        session.execute(
            text("DELETE FROM enir_sections WHERE collection_id = :cid"),
            {"cid": collection_id},
        )
        session.execute(
            text(
                "UPDATE enir_collections "
                "SET title=:title, description=:desc, issue=:issue, issue_title=:issue_title, "
                "    source_file=:source_file, source_format=:source_format, sort_order=:so "
                "WHERE id=:cid"
            ),
            {
                "title": collection_title,
                "desc": collection_description,
                "issue": issue,
                "issue_title": issue_title,
                "source_file": source_file,
                "source_format": source_format,
                "so": sort_order,
                "cid": collection_id,
            },
        )
        return collection_id

    res = session.execute(
        text(
            "INSERT INTO enir_collections "
            "(code, title, description, issue, issue_title, source_file, source_format, sort_order) "
            "VALUES (:code, :title, :desc, :issue, :issue_title, :source_file, :source_format, :so) "
            "RETURNING id"
        ),
        {
            "code": collection_code,
            "title": collection_title,
            "desc": collection_description,
            "issue": issue,
            "issue_title": issue_title,
            "source_file": source_file,
            "source_format": source_format,
            "so": sort_order,
        },
    )
    collection_id = res.scalar_one()
    print(f"Created collection '{collection_code}' (id={collection_id})")
    return collection_id


def _insert_paragraph(
    session,
    text,
    collection_id: int,
    *,
    section_id: int | None = None,
    chapter_id: int | None = None,
    source_paragraph_id: str | None,
    code: str,
    title: str,
    unit: str | None,
    sort_order: int,
) -> int:
    res = session.execute(
        text(
            "INSERT INTO enir_paragraphs "
            "(collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order) "
            "VALUES (:cid, :sid, :chid, :spid, :code, :title, :unit, :so) "
            "RETURNING id"
        ),
        {
            "cid": collection_id,
            "sid": section_id,
            "chid": chapter_id,
            "spid": source_paragraph_id,
            "code": code,
            "title": title,
            "unit": unit,
            "so": sort_order,
        },
    )
    return res.scalar_one()


def _insert_section(
    session,
    text,
    collection_id: int,
    *,
    source_section_id: str,
    title: str,
    sort_order: int,
    has_tech: bool,
) -> int:
    res = session.execute(
        text(
            "INSERT INTO enir_sections "
            "(collection_id, source_section_id, title, sort_order, has_tech) "
            "VALUES (:cid, :ssid, :title, :so, :has_tech) "
            "RETURNING id"
        ),
        {
            "cid": collection_id,
            "ssid": source_section_id,
            "title": title,
            "so": sort_order,
            "has_tech": has_tech,
        },
    )
    return res.scalar_one()


def _insert_chapter(
    session,
    text,
    collection_id: int,
    section_id: int,
    *,
    source_chapter_id: str,
    title: str,
    sort_order: int,
    has_tech: bool,
) -> int:
    res = session.execute(
        text(
            "INSERT INTO enir_chapters "
            "(collection_id, section_id, source_chapter_id, title, sort_order, has_tech) "
            "VALUES (:cid, :sid, :schid, :title, :so, :has_tech) "
            "RETURNING id"
        ),
        {
            "cid": collection_id,
            "sid": section_id,
            "schid": source_chapter_id,
            "title": title,
            "so": sort_order,
            "has_tech": has_tech,
        },
    )
    return res.scalar_one()


def _import_nested_paragraphs(session, text, collection_id: int, paragraphs_data: list[dict]) -> int:
    for sort_idx, para in enumerate(paragraphs_data):
        code = para.get("code", "")
        title = para.get("title", "")
        unit = para.get("unit")
        para_id = _insert_paragraph(
            session,
            text,
            collection_id,
            source_paragraph_id=para.get("source_paragraph_id") or code,
            code=code,
            title=title,
            unit=unit,
            sort_order=sort_idx,
        )

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

        for member in para.get("crew") or []:
            session.execute(
                text(
                    "INSERT INTO enir_crew_members "
                    "(paragraph_id, profession, grade, count) "
                    "VALUES (:pid, :prof, :grade, :cnt)"
                ),
                {
                    "pid": para_id,
                    "prof": member.get("profession", ""),
                    "grade": member.get("grade"),
                    "cnt": member.get("count", 1),
                },
            )

        for norm in para.get("norms") or []:
            session.execute(
                text(
                    "INSERT INTO enir_norms "
                    "(paragraph_id, row_num, work_type, condition, "
                    " thickness_mm, column_label, norm_time, price_rub) "
                    "VALUES (:pid, :rn, :wt, :cond, :thick, :col, :nt, :pr)"
                ),
                {
                    "pid": para_id,
                    "rn": norm.get("row_num"),
                    "wt": norm.get("work_type"),
                    "cond": norm.get("condition"),
                    "thick": norm.get("thickness_mm"),
                    "col": norm.get("column_label"),
                    "nt": norm.get("norm_time"),
                    "pr": norm.get("price_rub"),
                },
            )

        for note in para.get("notes") or []:
            session.execute(
                text(
                    "INSERT INTO enir_notes "
                    "(paragraph_id, num, text, coefficient, pr_code, conditions, formula) "
                    "VALUES (:pid, :num, :text, :coef, :prc, :cond, :formula)"
                ),
                {
                    "pid": para_id,
                    "num": note.get("num", 0),
                    "text": note.get("text", ""),
                    "coef": note.get("coefficient"),
                    "prc": note.get("code"),
                    "cond": note.get("conditions"),
                    "formula": note.get("formula"),
                },
            )

        print(f"  [{sort_idx+1:3d}/{len(paragraphs_data)}] {code}  {title[:60]}")

    return len(paragraphs_data)


def _import_e1_db(session, text, collection_id: int, payload: dict[str, Any]) -> int:
    paragraph_id_map: dict[str, int] = {}
    paragraph_lookup_map: dict[str, int] = {}
    section_id_map: dict[str, int] = {}
    chapter_id_map: dict[str, int] = {}
    chapter_section_map: dict[str, int] = {}
    table_id_map: dict[str, int] = {}
    column_id_map: dict[tuple[str, str], int] = {}
    row_id_map: dict[str, int] = {}
    row_table_map: dict[str, str] = {}

    sections = sorted(payload.get("sections") or [], key=lambda item: item.get("section_order", 0))
    for section in sections:
        source_section_id = section.get("section_id")
        if not source_section_id:
            raise ValueError("Section entry is missing section_id")
        section_id_map[source_section_id] = _insert_section(
            session,
            text,
            collection_id,
            source_section_id=source_section_id,
            title=section.get("title") or source_section_id,
            sort_order=max((section.get("section_order") or 1) - 1, 0),
            has_tech=bool(section.get("has_tech", False)),
        )

    chapters = sorted(
        payload.get("chapters") or [],
        key=lambda item: (item.get("section_id") or "", item.get("chapter_order", 0)),
    )
    for chapter in chapters:
        source_chapter_id = chapter.get("chapter_id")
        source_section_id = chapter.get("section_id")
        if not source_chapter_id:
            raise ValueError("Chapter entry is missing chapter_id")
        if not source_section_id:
            raise ValueError(f"Chapter '{source_chapter_id}' is missing section_id")
        section_db_id = section_id_map.get(source_section_id)
        if section_db_id is None:
            raise ValueError(
                f"Chapter '{source_chapter_id}' references unknown section_id '{source_section_id}'"
            )
        chapter_id_map[source_chapter_id] = _insert_chapter(
            session,
            text,
            collection_id,
            section_db_id,
            source_chapter_id=source_chapter_id,
            title=chapter.get("title") or source_chapter_id,
            sort_order=max((chapter.get("chapter_order") or 1) - 1, 0),
            has_tech=bool(chapter.get("has_tech", False)),
        )
        chapter_section_map[source_chapter_id] = section_db_id

    paragraphs = sorted(payload.get("paragraphs") or [], key=lambda item: item.get("paragraph_order", 0))
    for para in paragraphs:
        source_paragraph_id = para.get("paragraph_id") or para.get("code")
        code = para.get("code", source_paragraph_id or "")
        title = para.get("title", "")
        unit = para.get("unit")
        source_section_id = para.get("section_id")
        source_chapter_id = para.get("chapter_id")
        section_db_id = section_id_map.get(source_section_id) if source_section_id else None
        chapter_db_id = chapter_id_map.get(source_chapter_id) if source_chapter_id else None

        if source_section_id and section_db_id is None:
            raise ValueError(
                f"Paragraph '{source_paragraph_id}' references unknown section_id '{source_section_id}'"
            )
        if source_chapter_id and chapter_db_id is None:
            raise ValueError(
                f"Paragraph '{source_paragraph_id}' references unknown chapter_id '{source_chapter_id}'"
            )
        if chapter_db_id is not None and section_db_id is None:
            section_db_id = chapter_section_map.get(source_chapter_id)

        para_id = _insert_paragraph(
            session,
            text,
            collection_id,
            section_id=section_db_id,
            chapter_id=chapter_db_id,
            source_paragraph_id=source_paragraph_id,
            code=code,
            title=title,
            unit=unit,
            sort_order=para.get("paragraph_order", 0) - 1,
        )
        paragraph_id_map[source_paragraph_id] = para_id
        for candidate in (source_paragraph_id, code):
            normalized_candidate = _normalize_paragraph_key(candidate)
            if normalized_candidate:
                paragraph_lookup_map[normalized_candidate] = para_id

        for idx, raw_text in enumerate(para.get("technical_characteristics") or []):
            session.execute(
                text(
                    "INSERT INTO enir_paragraph_technical_characteristics "
                    "(paragraph_id, sort_order, raw_text) "
                    "VALUES (:pid, :so, :raw)"
                ),
                {"pid": para_id, "so": idx, "raw": raw_text},
            )

        for idx, app_note in enumerate(para.get("application_notes") or []):
            session.execute(
                text(
                    "INSERT INTO enir_paragraph_application_notes "
                    "(paragraph_id, sort_order, text) "
                    "VALUES (:pid, :so, :text)"
                ),
                {"pid": para_id, "so": idx, "text": app_note},
            )

        print(f"  [{len(paragraph_id_map):3d}/{len(paragraphs)}] {code}  {title[:60]}")

    technical_coefficients = sorted(
        payload.get("technical_coefficients") or [],
        key=lambda item: (
            item.get("sort_order", 0),
            item.get("code") or "",
        ),
    )
    for item in technical_coefficients:
        source_section_id = item.get("section_id")
        source_chapter_id = item.get("chapter_id")
        source_paragraph_id = item.get("paragraph_id")

        section_db_id = section_id_map.get(source_section_id) if source_section_id else None
        chapter_db_id = chapter_id_map.get(source_chapter_id) if source_chapter_id else None
        paragraph_db_id = _resolve_paragraph_db_id(paragraph_lookup_map, source_paragraph_id)

        if source_section_id and section_db_id is None:
            raise ValueError(
                f"Technical coefficient '{item.get('code')}' references unknown "
                f"section_id '{source_section_id}'"
            )
        if source_chapter_id and chapter_db_id is None:
            raise ValueError(
                f"Technical coefficient '{item.get('code')}' references unknown "
                f"chapter_id '{source_chapter_id}'"
            )
        if source_paragraph_id and paragraph_db_id is None:
            raise ValueError(
                f"Technical coefficient '{item.get('code')}' references unknown "
                f"paragraph_id '{source_paragraph_id}'"
            )

        coeff_res = session.execute(
            text(
                "INSERT INTO enir_technical_coefficients "
                "(collection_id, section_id, chapter_id, paragraph_id, code, description, "
                " multiplier, conditions, formula, sort_order) "
                "VALUES (:cid, :sid, :chid, :pid, :code, :descr, :mult, :cond, :formula, :so) "
                "RETURNING id"
            ),
            {
                "cid": collection_id,
                "sid": section_db_id,
                "chid": chapter_db_id,
                "pid": paragraph_db_id,
                "code": item.get("code"),
                "descr": item.get("description") or "",
                "mult": item.get("multiplier"),
                "cond": item.get("conditions"),
                "formula": item.get("formula"),
                "so": item.get("sort_order", 0),
            },
        )
        coeff_id = coeff_res.scalar_one()

        for para_code in item.get("applicable_paragraphs") or []:
            linked_paragraph_id = _resolve_paragraph_db_id(paragraph_lookup_map, para_code)
            if linked_paragraph_id is None:
                raise ValueError(
                    f"Technical coefficient '{item.get('code')}' references unknown "
                    f"applicable paragraph '{para_code}'"
                )
            session.execute(
                text(
                    "INSERT INTO enir_technical_coefficient_paragraphs "
                    "(technical_coefficient_id, paragraph_id) "
                    "VALUES (:tcid, :pid)"
                ),
                {"tcid": coeff_id, "pid": linked_paragraph_id},
            )

    work_items = sorted(
        payload.get("paragraph_work_items") or [],
        key=lambda item: (item.get("paragraph_id", ""), item.get("item_order", 0)),
    )
    for item in work_items:
        para_id = paragraph_id_map[item["paragraph_id"]]
        sort_order = max((item.get("item_order") or 1) - 1, 0)
        raw_text = item.get("text", "")
        session.execute(
            text(
                "INSERT INTO enir_source_work_items "
                "(paragraph_id, sort_order, raw_text) "
                "VALUES (:pid, :so, :raw)"
            ),
            {"pid": para_id, "so": sort_order, "raw": raw_text},
        )

        parsed = _safe_parse_work_item(raw_text)
        if not parsed:
            continue

        res = session.execute(
            text(
                "INSERT INTO enir_work_compositions "
                "(paragraph_id, condition, sort_order) "
                "VALUES (:pid, :cond, :so) RETURNING id"
            ),
            {"pid": para_id, "cond": parsed.get("condition"), "so": sort_order},
        )
        composition_id = res.scalar_one()

        for op_idx, op_text in enumerate(parsed.get("operations") or []):
            session.execute(
                text(
                    "INSERT INTO enir_work_operations "
                    "(composition_id, text, sort_order) "
                    "VALUES (:cid, :text, :so)"
                ),
                {"cid": composition_id, "text": op_text, "so": op_idx},
            )

    crew_items = sorted(
        payload.get("paragraph_crew_items") or [],
        key=lambda item: (item.get("paragraph_id", ""), item.get("item_order", 0)),
    )
    for item in crew_items:
        para_id = paragraph_id_map[item["paragraph_id"]]
        sort_order = max((item.get("item_order") or 1) - 1, 0)
        profession = item.get("profession")
        count = item.get("count")
        session.execute(
            text(
                "INSERT INTO enir_source_crew_items "
                "(paragraph_id, sort_order, profession, grade, count, raw_text) "
                "VALUES (:pid, :so, :prof, :grade, :cnt, :raw)"
            ),
            {
                "pid": para_id,
                "so": sort_order,
                "prof": profession,
                "grade": item.get("grade"),
                "cnt": count,
                "raw": item.get("raw"),
            },
        )
        if profession:
            session.execute(
                text(
                    "INSERT INTO enir_crew_members "
                    "(paragraph_id, profession, grade, count) "
                    "VALUES (:pid, :prof, :grade, :cnt)"
                ),
                {
                    "pid": para_id,
                    "prof": profession,
                    "grade": item.get("grade"),
                    "cnt": count if count is not None else 1,
                },
            )

    notes = sorted(
        payload.get("paragraph_notes") or [],
        key=lambda item: (item.get("paragraph_id", ""), item.get("item_order", 0)),
    )
    for item in notes:
        para_id = paragraph_id_map[item["paragraph_id"]]
        sort_order = max((item.get("item_order") or 1) - 1, 0)
        session.execute(
            text(
                "INSERT INTO enir_source_notes "
                "(paragraph_id, sort_order, code, text, coefficient, conditions, formula) "
                "VALUES (:pid, :so, :code, :text, :coef, :cond, :formula)"
            ),
            {
                "pid": para_id,
                "so": sort_order,
                "code": item.get("code"),
                "text": item.get("text", ""),
                "coef": item.get("coefficient"),
                "cond": item.get("conditions"),
                "formula": item.get("formula"),
            },
        )
        session.execute(
            text(
                "INSERT INTO enir_notes "
                "(paragraph_id, num, text, coefficient, pr_code, conditions, formula) "
                "VALUES (:pid, :num, :text, :coef, :prc, :cond, :formula)"
            ),
            {
                "pid": para_id,
                "num": item.get("item_order", 0),
                "text": item.get("text", ""),
                "coef": item.get("coefficient"),
                "prc": item.get("code"),
                "cond": item.get("conditions"),
                "formula": item.get("formula"),
            },
        )

    norm_tables = sorted(
        payload.get("norm_tables") or [],
        key=lambda item: (item.get("paragraph_id", ""), item.get("table_order", 0)),
    )
    for item in norm_tables:
        para_id = paragraph_id_map[item["paragraph_id"]]
        res = session.execute(
            text(
                "INSERT INTO enir_norm_tables "
                "(paragraph_id, source_table_id, sort_order, title, row_count) "
                "VALUES (:pid, :stid, :so, :title, :row_count) RETURNING id"
            ),
            {
                "pid": para_id,
                "stid": item["table_id"],
                "so": max((item.get("table_order") or 1) - 1, 0),
                "title": item.get("title"),
                "row_count": item.get("row_count"),
            },
        )
        table_id_map[item["table_id"]] = res.scalar_one()

    norm_columns = sorted(
        payload.get("norm_columns") or [],
        key=lambda item: (item.get("table_id", ""), item.get("column_order", 0)),
    )
    for item in norm_columns:
        table_db_id = table_id_map[item["table_id"]]
        res = session.execute(
            text(
                "INSERT INTO enir_norm_columns "
                "(norm_table_id, source_column_key, sort_order, header, label) "
                "VALUES (:tid, :ckey, :so, :header, :label) RETURNING id"
            ),
            {
                "tid": table_db_id,
                "ckey": item["column_key"],
                "so": max((item.get("column_order") or 1) - 1, 0),
                "header": item.get("header") or item.get("column_key") or "",
                "label": item.get("label"),
            },
        )
        column_id_map[(item["table_id"], item["column_key"])] = res.scalar_one()

    norm_rows = sorted(
        payload.get("norm_rows") or [],
        key=lambda item: (item.get("table_id", ""), item.get("row_order", 0)),
    )
    for item in norm_rows:
        table_db_id = table_id_map[item["table_id"]]
        res = session.execute(
            text(
                "INSERT INTO enir_norm_rows "
                "(norm_table_id, source_row_id, sort_order, source_row_num, params) "
                "VALUES (:tid, :rid, :so, :rnum, :params) RETURNING id"
            ),
            {
                "tid": table_db_id,
                "rid": item["row_id"],
                "so": max((item.get("row_order") or 1) - 1, 0),
                "rnum": item.get("source_row_num"),
                "params": item.get("params"),
            },
        )
        row_id_map[item["row_id"]] = res.scalar_one()
        row_table_map[item["row_id"]] = item["table_id"]

    for item in payload.get("norm_values") or []:
        source_table_id = row_table_map[item["row_id"]]
        column_db_id = column_id_map[(source_table_id, item["column_key"])]
        row_db_id = row_id_map[item["row_id"]]
        session.execute(
            text(
                "INSERT INTO enir_norm_values "
                "(norm_row_id, norm_column_id, value_type, value_text, value_numeric) "
                "VALUES (:rid, :cid, :vtype, :vtext, :vnum)"
            ),
            {
                "rid": row_db_id,
                "cid": column_db_id,
                "vtype": item.get("value_type", "cell"),
                "vtext": item.get("value_text", ""),
                "vnum": _parse_value_numeric(item.get("value_text")),
            },
        )

    return len(paragraphs)


def _build_paragraph_lookup(session, text, collection_id: int) -> dict[str, int]:
    rows = session.execute(
        text(
            "SELECT id, code, source_paragraph_id "
            "FROM enir_paragraphs "
            "WHERE collection_id = :cid"
        ),
        {"cid": collection_id},
    ).fetchall()

    lookup: dict[str, int] = {}
    for row in rows:
        for candidate in (row.code, row.source_paragraph_id):
            normalized = _normalize_paragraph_key(candidate)
            if normalized:
                lookup[normalized] = row.id
    return lookup


def _import_cross_refs(
    session,
    text,
    collection_id: int,
    cross_ref_json_path: str,
) -> None:
    with open(cross_ref_json_path, encoding="utf-8") as f:
        cross_refs = json.load(f)

    if not isinstance(cross_refs, dict):
        raise ValueError("Cross-reference JSON must be an object")

    paragraph_lookup = _build_paragraph_lookup(session, text, collection_id)

    anchor_updates: dict[int, str] = {}
    unresolved_toc_ids: set[str] = set()
    conflicting_anchors: list[tuple[str, str, str]] = []

    for link in cross_refs.get("internal_links") or []:
        if link.get("link_type") != "toc":
            continue

        paragraph_key = _normalize_paragraph_key(link.get("paragraph_id"))
        fragment = (link.get("fragment") or "").strip()
        if not paragraph_key or not fragment:
            unresolved_toc_ids.add(str(link.get("paragraph_id") or "<missing>"))
            continue

        paragraph_id = paragraph_lookup.get(paragraph_key)
        if paragraph_id is None:
            unresolved_toc_ids.add(str(link.get("paragraph_id")))
            continue

        previous_fragment = anchor_updates.get(paragraph_id)
        if previous_fragment and previous_fragment != fragment:
            conflicting_anchors.append((str(link.get("paragraph_id")), previous_fragment, fragment))
            continue

        anchor_updates[paragraph_id] = fragment

    for paragraph_id, fragment in anchor_updates.items():
        session.execute(
            text(
                "UPDATE enir_paragraphs "
                "SET html_anchor = :fragment "
                "WHERE id = :paragraph_id"
            ),
            {"fragment": fragment, "paragraph_id": paragraph_id},
        )

    resolved_external_refs: list[dict[str, Any]] = []
    unresolved_external_ids: set[str] = set()
    sort_order_by_paragraph: dict[int, int] = defaultdict(int)

    for link in cross_refs.get("external_links") or []:
        paragraph_key = _normalize_paragraph_key(link.get("paragraph_id"))
        if not paragraph_key:
            unresolved_external_ids.add(str(link.get("paragraph_id") or "<missing>"))
            continue

        paragraph_id = paragraph_lookup.get(paragraph_key)
        if paragraph_id is None:
            unresolved_external_ids.add(str(link.get("paragraph_id")))
            continue

        resolved_external_refs.append(
            {
                "paragraph_id": paragraph_id,
                "sort_order": sort_order_by_paragraph[paragraph_id],
                "ref_type": "external",
                "link_text": link.get("text"),
                "href": link.get("href"),
                "abs_url": link.get("abs_url"),
                "context_text": link.get("context"),
                "is_meganorm": bool(link.get("is_meganorm", False)),
            }
        )
        sort_order_by_paragraph[paragraph_id] += 1

    for row in resolved_external_refs:
        session.execute(
            text(
                "INSERT INTO enir_paragraph_refs "
                "(paragraph_id, sort_order, ref_type, link_text, href, abs_url, context_text, is_meganorm) "
                "VALUES "
                "(:paragraph_id, :sort_order, :ref_type, :link_text, :href, :abs_url, :context_text, :is_meganorm)"
            ),
            row,
        )

    print(
        f"[xref] applied {len(anchor_updates)} html anchors and "
        f"{len(resolved_external_refs)} external refs from {cross_ref_json_path}"
    )
    if unresolved_toc_ids:
        print(
            "[xref] skipped TOC anchors for unknown/malformed paragraph_id values: "
            + ", ".join(sorted(unresolved_toc_ids))
        )
    if conflicting_anchors:
        for paragraph_id, old_fragment, new_fragment in conflicting_anchors:
            print(
                f"[xref] conflicting TOC anchor for {paragraph_id}: "
                f"keeping '{old_fragment}', skipping '{new_fragment}'"
            )
    if unresolved_external_ids:
        print(
            "[xref] skipped external refs for unknown/malformed paragraph_id values: "
            + ", ".join(sorted(unresolved_external_ids))
        )


# ─── основная логика ──────────────────────────────────────────────────────────
def import_collection(
    json_path: str,
    collection_code: str | None,
    collection_title: str | None,
    collection_description: str | None,
    sort_order: int,
    overwrite: bool,
    cross_ref_json_path: str | None = None,
) -> None:
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import Session
    except ImportError:
        print("pip install sqlalchemy psycopg2-binary", file=sys.stderr)
        sys.exit(1)

    with open(json_path, encoding="utf-8") as f:
        payload = json.load(f)

    payload_format = _detect_payload_format(payload)
    effective_collection_code, effective_collection_title = _resolve_collection_metadata(
        payload,
        collection_code,
        collection_title,
    )
    source_file = payload.get("source_file") if isinstance(payload, dict) else None
    issue = payload.get("issue") if isinstance(payload, dict) else None
    issue_title = payload.get("issue_title") if isinstance(payload, dict) else None
    effective_description = collection_description
    if effective_description is None and isinstance(payload, dict):
        effective_description = payload.get("description")

    engine = create_engine(get_db_url(), echo=False)
    with Session(engine) as session:
        collection_id = _upsert_collection(
            session=session,
            text=text,
            collection_code=effective_collection_code,
            collection_title=effective_collection_title,
            collection_description=effective_description,
            issue=issue,
            issue_title=issue_title,
            sort_order=sort_order,
            overwrite=overwrite,
            source_file=source_file,
            source_format=payload_format,
        )

        if payload_format == "paragraphs_v1":
            paragraph_count = _import_nested_paragraphs(session, text, collection_id, payload)
        else:
            paragraph_count = _import_e1_db(session, text, collection_id, payload)

        if cross_ref_json_path:
            _import_cross_refs(session, text, collection_id, cross_ref_json_path)

        session.commit()

    print(
        f"\nDone. {paragraph_count} paragraphs imported into collection "
        f"'{effective_collection_code}' using format '{payload_format}'."
    )


# ─── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import ENIR collection from JSON into PostgreSQL"
    )
    parser.add_argument("json_file", help="Path to enir_*.json")
    parser.add_argument("--collection-code",        default=None, help="Optional override, e.g. Е3")
    parser.add_argument("--collection-title",       default=None, help="Optional override, e.g. 'Каменные работы'")
    parser.add_argument("--collection-description", default=None,   help="Optional description")
    parser.add_argument("--sort-order",             type=int, default=0)
    parser.add_argument("--overwrite", action="store_true",
                        help="Replace paragraphs if collection already exists")
    parser.add_argument(
        "--cross-ref-json",
        default=None,
        help="Optional path to annotated cross_references JSON",
    )

    args = parser.parse_args()

    import_collection(
        json_path               = args.json_file,
        collection_code         = args.collection_code,
        collection_title        = args.collection_title,
        collection_description  = args.collection_description,
        sort_order              = args.sort_order,
        overwrite               = args.overwrite,
        cross_ref_json_path     = args.cross_ref_json,
    )
