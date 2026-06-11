"""Promote construction_work_dictionary_v4 to canonical work taxonomy.

The previous migration introduced the JSON-backed taxonomy schema and seeded v3.
This migration keeps that schema and replaces generated dictionary rows with v4.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert


revision = "055_work_taxonomy_v4"
down_revision = "054_work_taxonomy_v3"
branch_labels = None
depends_on = None


_DATA_DIR = Path(__file__).resolve().parents[2] / "app" / "data"
_V3_FILE = _DATA_DIR / "construction_work_dictionary_v3.json"
_V4_FILE = _DATA_DIR / "construction_work_dictionary_v4.json"
_V3_SOURCE = "construction_work_dictionary_v3"
_V4_SOURCE = "construction_work_dictionary_v4"
_UNKNOWN_CODE = "unknown/needs_review"


def _dictionary(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _as_list(value) -> list:
    return list(value or [])


def _canonical_code(section_id: str, subtype_id: str) -> str:
    return f"{section_id}/{subtype_id}"


def _term_keywords(section: dict, subtype: dict) -> list[str]:
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
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            result.append(text)
    return result


def _subtype_rows(payload: dict, dictionary_source: str) -> list[dict]:
    meta = payload.get("meta") or {}
    schema_version = str(meta.get("schema_version") or "")
    dictionary_name = str(meta.get("dictionary_name") or "")
    source_version = f"{dictionary_source}@{schema_version}"
    scoring = payload.get("scoring") or {}
    rows: list[dict] = []
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
                    "dictionary_source": dictionary_source,
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


def _alias_rows(payload: dict) -> list[dict]:
    subtype_targets: list[tuple[str, str]] = []
    section_targets: list[tuple[str, str]] = []
    for section in payload.get("sections") or []:
        section_id = str(section["id"])
        for legacy_code in _as_list(section.get("legacy_csv_codes")):
            section_targets.append((str(legacy_code), section_id))
        for subtype in section.get("subtypes") or []:
            canonical = _canonical_code(section_id, str(subtype["id"]))
            for legacy_code in _as_list(subtype.get("legacy_csv_codes")):
                subtype_targets.append((str(legacy_code), canonical))

    subtype_counts = Counter(code for code, _target in subtype_targets)
    rows: list[dict] = []
    for legacy_code, section_id in section_targets:
        rows.append(
            {
                "alias_code": legacy_code,
                "alias_source": "legacy_csv",
                "target_level": "section",
                "target_code": section_id,
                "canonical_code": None,
                "mapping_type": "legacy_section",
                "confidence": "medium",
                "transfer_defaults": False,
                "is_active": True,
                "notes": "Legacy CSV macro/section alias.",
            }
        )
    for legacy_code, canonical in subtype_targets:
        rows.append(
            {
                "alias_code": legacy_code,
                "alias_source": "legacy_csv",
                "target_level": "subtype",
                "target_code": canonical,
                "canonical_code": canonical,
                "mapping_type": (
                    "legacy_subtype" if subtype_counts[legacy_code] == 1 else "legacy_ambiguous"
                ),
                "confidence": "high" if subtype_counts[legacy_code] == 1 else "medium",
                "transfer_defaults": subtype_counts[legacy_code] == 1,
                "is_active": True,
                "notes": "Legacy CSV subtype alias.",
            }
        )

    for legacy_code, section_id, note in (
        ("3.3", "load_bearing_walls", "Removed duplicate: non_res_walls."),
        ("3.4", "floor_slabs", "Removed duplicate: non_res_floor_slabs."),
        ("4.4", "partitions", "Removed duplicate: new_partitions."),
    ):
        rows.append(
            {
                "alias_code": legacy_code,
                "alias_source": "legacy_csv",
                "target_level": "section",
                "target_code": section_id,
                "canonical_code": None,
                "mapping_type": "inactive_redirect",
                "confidence": "medium",
                "transfer_defaults": False,
                "is_active": False,
                "notes": note,
            }
        )
    return rows


def _work_subtypes_table():
    jsonb = postgresql.JSONB()
    return sa.table(
        "work_subtypes",
        sa.column("macro_id", sa.Integer),
        sa.column("macro_name", sa.String),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("keywords", postgresql.ARRAY(sa.Text())),
        sa.column("section_code", sa.String),
        sa.column("section_name", sa.String),
        sa.column("section_scope", sa.String),
        sa.column("dictionary_source", sa.String),
        sa.column("dictionary_name", sa.String),
        sa.column("dictionary_schema_version", sa.String),
        sa.column("dictionary_source_version", sa.String),
        sa.column("legacy_code", sa.String),
        sa.column("display_code", sa.String),
        sa.column("legacy_csv_codes", jsonb),
        sa.column("terms_json", jsonb),
        sa.column("scoring_json", jsonb),
        sa.column("aliases_json", jsonb),
    )


def _aliases_table():
    return sa.table(
        "work_subtype_aliases",
        sa.column("alias_code", sa.String),
        sa.column("alias_source", sa.String),
        sa.column("target_level", sa.String),
        sa.column("target_code", sa.String),
        sa.column("canonical_code", sa.String),
        sa.column("mapping_type", sa.String),
        sa.column("confidence", sa.String),
        sa.column("transfer_defaults", sa.Boolean),
        sa.column("is_active", sa.Boolean),
        sa.column("notes", sa.String),
    )


def _seed_subtypes(payload: dict, dictionary_source: str) -> None:
    work_subtypes = _work_subtypes_table()
    rows = _subtype_rows(payload, dictionary_source)
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


def _replace_aliases(payload: dict) -> None:
    aliases = _aliases_table()
    op.execute(
        sa.text("DELETE FROM work_subtype_aliases WHERE alias_source = 'legacy_csv'")
    )
    rows = _alias_rows(payload)
    if not rows:
        return
    stmt = pg_insert(aliases).values(rows)
    op.execute(
        stmt.on_conflict_do_update(
            index_elements=["alias_source", "alias_code", "target_level", "target_code"],
            set_={
                "canonical_code": stmt.excluded.canonical_code,
                "mapping_type": stmt.excluded.mapping_type,
                "confidence": stmt.excluded.confidence,
                "transfer_defaults": stmt.excluded.transfer_defaults,
                "is_active": stmt.excluded.is_active,
                "notes": stmt.excluded.notes,
            },
        )
    )


def _canonical_codes(payload: dict) -> set[str]:
    return {
        _canonical_code(str(section["id"]), str(subtype["id"]))
        for section in payload.get("sections") or []
        for subtype in section.get("subtypes") or []
    }


def upgrade() -> None:
    payload = _dictionary(_V4_FILE)
    _seed_subtypes(payload, _V4_SOURCE)
    _replace_aliases(payload)


def downgrade() -> None:
    v3_payload = _dictionary(_V3_FILE)
    v4_payload = _dictionary(_V4_FILE)
    _seed_subtypes(v3_payload, _V3_SOURCE)
    _replace_aliases(v3_payload)

    v4_only_codes = sorted(_canonical_codes(v4_payload) - _canonical_codes(v3_payload))
    if v4_only_codes:
        work_subtypes = _work_subtypes_table()
        op.execute(work_subtypes.delete().where(work_subtypes.c.code.in_(v4_only_codes)))
