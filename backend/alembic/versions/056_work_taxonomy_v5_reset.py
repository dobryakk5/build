"""Reset prototype work taxonomy to construction_work_dictionary_v6_3_3_draft.

This migration intentionally drops v4/v3 taxonomy compatibility. The prototype
uses the canonical JSON taxonomy and does not support downgrade.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert


revision = "056_work_taxonomy_v5_reset"
down_revision = "055_work_taxonomy_v4"
branch_labels = None
depends_on = None


_DATA_DIR = Path(__file__).resolve().parents[2] / "app" / "data"
_V5_FILE = _DATA_DIR / "construction_work_dictionary_v6_3_3_draft.json"
_V5_SOURCE = "construction_work_dictionary_v6_3_3_draft"
_UNKNOWN_CODE = "unknown/needs_review"

_RAW_TAXONOMY_KEYS = (
    "macro_id",
    "subtype_code",
    "subtype_name",
    "work_section_code",
    "work_section_name",
    "work_subtype_code",
    "work_subtype_name",
    "classification_score",
    "classification_confidence",
    "classification_needs_review",
    "classification_source",
    "classification_candidates",
    "classification_matched_terms",
    "classification_reason",
    "classification_related_sections",
    "operator_review_required",
    "operator_review_status",
    "operator_review_reason",
    "dictionary_version",
    "manual_override",
    "manual_changed_by",
    "manual_changed_at",
    "parent_context_source",
    "parent_context_code",
    "context_inherited",
    "context_inheritance_reason",
)


def _dictionary(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
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
    source_version = str(meta.get("dictionary_version") or f"{_V5_SOURCE}@{schema_version}")
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
                    "dictionary_source": _V5_SOURCE,
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


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {col["name"] for col in inspector.get_columns(table_name)}


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _reset_columns(table_name: str, values: dict[str, Any]) -> None:
    if not _table_exists(table_name):
        return
    existing = _columns(table_name)
    patch = {key: value for key, value in values.items() if key in existing}
    if not patch:
        return
    table = sa.table(
        table_name,
        *(sa.column(key) for key in patch.keys()),
    )
    op.execute(table.update().values(**patch))


def _drop_raw_taxonomy_keys(table_name: str) -> None:
    if not _table_exists(table_name) or "raw_data" not in _columns(table_name):
        return
    expression = "raw_data"
    for key in _RAW_TAXONOMY_KEYS:
        expression += f" - '{key}'"
    op.execute(sa.text(f"UPDATE {table_name} SET raw_data = {expression} WHERE raw_data IS NOT NULL"))


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


def _seed_subtypes(payload: dict[str, Any]) -> None:
    rows = _subtype_rows(payload)
    if not rows:
        return
    work_subtypes = _work_subtypes_table()
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


def upgrade() -> None:
    payload = _dictionary(_V5_FILE)

    if _table_exists("work_subtypes"):
        op.alter_column(
            "work_subtypes",
            "dictionary_source",
            existing_type=sa.String(length=32),
            type_=sa.String(length=64),
            existing_nullable=True,
        )

    if _table_exists("ktp_session_subtypes"):
        op.execute(sa.text("DELETE FROM ktp_session_subtypes"))

    _reset_columns(
        "estimates",
        {
            "work_section_code": None,
            "work_section_name": None,
            "work_subtype_code": None,
            "work_subtype_name": None,
            "classification_score": None,
            "classification_confidence": None,
            "classification_needs_review": False,
            "classification_source": None,
            "classification_candidates": None,
            "classification_matched_terms": None,
            "operator_review_required": False,
            "operator_review_status": None,
            "operator_review_reason": None,
            "dictionary_version": None,
            "manual_override": False,
            "manual_changed_by": None,
            "manual_changed_at": None,
        },
    )
    _drop_raw_taxonomy_keys("estimates")

    _reset_columns(
        "ktp_wbs_items",
        {
            "work_subtype_code": None,
            "work_subtype_name": None,
            "work_section_code": None,
            "work_section_name": None,
            "work_type_confidence": None,
            "work_type_needs_review": False,
            "work_type_candidates": None,
            "work_type_source": None,
            "operator_review_required": False,
            "manual_override": False,
            "gpr_confirmed": False,
        },
    )

    _reset_columns(
        "ktp_wbs_groups",
        {
            "work_section_code": None,
            "work_section_name": None,
            "work_type_confidence": None,
            "work_type_source": None,
        },
    )

    if _table_exists("work_subtype_aliases"):
        op.execute(sa.text("DELETE FROM work_subtype_aliases"))
    if _table_exists("work_subtypes"):
        op.execute(sa.text("DELETE FROM work_subtypes"))

    _seed_subtypes(payload)


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade is intentionally not supported for prototype taxonomy reset"
    )
