"""Seed work taxonomy rows from construction_work_dictionary_v6_4_draft."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert


revision = "059_work_tax_v6_4_seed"
down_revision = "058_est_stage_context"
branch_labels = None
depends_on = None


_DATA_DIR = Path(__file__).resolve().parents[2] / "app" / "data"
_DICTIONARY_FILE = _DATA_DIR / "construction_work_dictionary_v6_4_draft.json"
_DICTIONARY_SOURCE = "construction_work_dictionary_v6_4"
_UNKNOWN_CODE = "unknown/needs_review"


def _dictionary() -> dict[str, Any]:
    with open(_DICTIONARY_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def _as_list(value: Any) -> list:
    return list(value or [])


def _canonical_code(section_id: str, subtype_id: str) -> str:
    return f"{section_id}/{subtype_id}"


def _term_keywords(section: dict[str, Any], subtype: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for key in ("strong_terms", "weak_terms"):
        terms.extend(_as_list(subtype.get(key)))
    for pair in _as_list(subtype.get("action_object_pairs")):
        if isinstance(pair, list):
            terms.extend(str(part) for part in pair if part)
    if not terms:
        terms.extend(_as_list(section.get("strong_terms")))

    seen: set[str] = set()
    result: list[str] = []
    for raw in terms:
        text = str(raw).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _subtype_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    meta = payload.get("meta") or {}
    schema_version = str(meta.get("schema_version") or "")
    dictionary_name = str(meta.get("dictionary_name") or "")
    source_version = str(
        meta.get("dictionary_version")
        or payload.get("dictionary_version")
        or f"{_DICTIONARY_SOURCE}@{schema_version}"
    )
    scoring = payload.get("scoring") or {}
    rows: list[dict[str, Any]] = []
    for macro_id, section in enumerate(payload.get("sections") or [], start=1):
        section_id = str(section["id"])
        for subtype in section.get("subtypes") or []:
            legacy_codes = [str(v) for v in _as_list(subtype.get("legacy_csv_codes"))]
            code = _canonical_code(section_id, str(subtype["id"]))
            rows.append(
                {
                    "macro_id": macro_id,
                    "macro_name": section.get("title") or section_id,
                    "code": code,
                    "name": subtype.get("title") or subtype["id"],
                    "keywords": _term_keywords(section, subtype),
                    "section_code": section_id,
                    "section_name": section.get("title"),
                    "section_scope": section.get("scope"),
                    "dictionary_source": _DICTIONARY_SOURCE,
                    "dictionary_name": dictionary_name,
                    "dictionary_schema_version": schema_version,
                    "dictionary_source_version": source_version,
                    "legacy_code": legacy_codes[0] if legacy_codes else None,
                    "display_code": legacy_codes[0] if legacy_codes else None,
                    "legacy_csv_codes": legacy_codes,
                    "terms_json": {
                        "section": {
                            key: section.get(key) or []
                            for key in (
                                "strong_terms",
                                "weak_terms",
                                "action_terms",
                                "object_terms",
                                "material_terms",
                                "document_terms",
                                "unit_hints",
                                "negative_terms",
                            )
                        },
                        "subtype": {
                            key: subtype.get(key) or []
                            for key in (
                                "strong_terms",
                                "weak_terms",
                                "action_object_pairs",
                                "negative_terms",
                            )
                        },
                    },
                    "scoring_json": scoring,
                    "aliases_json": [],
                }
            )
    rows.append(
        {
            "macro_id": 0,
            "macro_name": "Не определено",
            "code": _UNKNOWN_CODE,
            "name": "Требует ручной классификации",
            "keywords": [],
            "section_code": "unknown",
            "section_name": "Не определено",
            "section_scope": None,
            "dictionary_source": "system",
            "dictionary_name": dictionary_name,
            "dictionary_schema_version": schema_version,
            "dictionary_source_version": source_version,
            "legacy_code": None,
            "display_code": None,
            "legacy_csv_codes": [],
            "terms_json": {},
            "scoring_json": scoring,
            "aliases_json": [],
        }
    )
    return rows


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _work_subtypes_table() -> sa.Table:
    jsonb = postgresql.JSONB()
    return sa.table(
        "work_subtypes",
        sa.column("macro_id", sa.Integer),
        sa.column("macro_name", sa.Text),
        sa.column("code", sa.Text),
        sa.column("name", sa.Text),
        sa.column("keywords", postgresql.ARRAY(sa.Text())),
        sa.column("section_code", sa.Text),
        sa.column("section_name", sa.Text),
        sa.column("section_scope", sa.Text),
        sa.column("dictionary_source", sa.String),
        sa.column("dictionary_name", sa.Text),
        sa.column("dictionary_schema_version", sa.String),
        sa.column("dictionary_source_version", sa.String),
        sa.column("legacy_code", sa.Text),
        sa.column("display_code", sa.Text),
        sa.column("legacy_csv_codes", jsonb),
        sa.column("terms_json", jsonb),
        sa.column("scoring_json", jsonb),
        sa.column("aliases_json", jsonb),
    )


def upgrade() -> None:
    if not _table_exists("work_subtypes"):
        return

    rows = _subtype_rows(_dictionary())
    work_subtypes = _work_subtypes_table()
    codes = [row["code"] for row in rows]

    if _table_exists("work_subtype_aliases"):
        op.execute(sa.text("DELETE FROM work_subtype_aliases"))

    stmt = pg_insert(work_subtypes).values(rows)
    op.execute(
        stmt.on_conflict_do_update(
            index_elements=["code"],
            set_={
                "macro_id": stmt.excluded.macro_id,
                "macro_name": stmt.excluded.macro_name,
                "name": stmt.excluded.name,
                "keywords": stmt.excluded.keywords,
                "section_code": stmt.excluded.section_code,
                "section_name": stmt.excluded.section_name,
                "section_scope": stmt.excluded.section_scope,
                "dictionary_source": stmt.excluded.dictionary_source,
                "dictionary_name": stmt.excluded.dictionary_name,
                "dictionary_schema_version": stmt.excluded.dictionary_schema_version,
                "dictionary_source_version": stmt.excluded.dictionary_source_version,
                "legacy_code": stmt.excluded.legacy_code,
                "display_code": stmt.excluded.display_code,
                "legacy_csv_codes": stmt.excluded.legacy_csv_codes,
                "terms_json": stmt.excluded.terms_json,
                "scoring_json": stmt.excluded.scoring_json,
                "aliases_json": stmt.excluded.aliases_json,
            },
        )
    )
    op.execute(work_subtypes.delete().where(work_subtypes.c.code.not_in(codes)))


def downgrade() -> None:
    raise NotImplementedError("Downgrade is intentionally not supported for taxonomy v6.4 seed")
