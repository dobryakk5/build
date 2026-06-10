"""Promote construction_work_dictionary_v3 to canonical work taxonomy.

JSON v3 becomes the canonical source for item work typing. The legacy CSV
codes remain only as aliases/default-transfer hints.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert


revision = "054_work_taxonomy_v3"
down_revision = "053_subtype_prod_seed"
branch_labels = None
depends_on = None


_DATA_DIR = Path(__file__).resolve().parents[2] / "app" / "data"
_DICT_FILE = _DATA_DIR / "construction_work_dictionary_v3.json"
_UNKNOWN_CODE = "unknown/needs_review"


def _dictionary() -> dict:
    with open(_DICT_FILE, encoding="utf-8") as fh:
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


def _subtype_rows(payload: dict) -> list[dict]:
    meta = payload.get("meta") or {}
    schema_version = str(meta.get("schema_version") or "")
    dictionary_name = str(meta.get("dictionary_name") or "")
    source_version = f"construction_work_dictionary_v3@{schema_version}"
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
                    "dictionary_source": "construction_work_dictionary_v3",
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

    # Removed CSV-only duplicates from v3. Keep them as inactive redirects so
    # old operator codes can be explained without becoming canonical targets.
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


def upgrade() -> None:
    jsonb = postgresql.JSONB()
    op.add_column("work_subtypes", sa.Column("section_code", sa.Text(), nullable=True))
    op.add_column("work_subtypes", sa.Column("section_name", sa.Text(), nullable=True))
    op.add_column("work_subtypes", sa.Column("section_scope", sa.Text(), nullable=True))
    op.add_column("work_subtypes", sa.Column("dictionary_source", sa.String(32), nullable=True))
    op.add_column("work_subtypes", sa.Column("dictionary_name", sa.Text(), nullable=True))
    op.add_column("work_subtypes", sa.Column("dictionary_schema_version", sa.String(32), nullable=True))
    op.add_column("work_subtypes", sa.Column("dictionary_source_version", sa.String(64), nullable=True))
    op.add_column("work_subtypes", sa.Column("legacy_code", sa.Text(), nullable=True))
    op.add_column("work_subtypes", sa.Column("display_code", sa.Text(), nullable=True))
    op.add_column("work_subtypes", sa.Column("legacy_csv_codes", jsonb, nullable=True))
    op.add_column("work_subtypes", sa.Column("terms_json", jsonb, nullable=True))
    op.add_column("work_subtypes", sa.Column("scoring_json", jsonb, nullable=True))
    op.add_column("work_subtypes", sa.Column("aliases_json", jsonb, nullable=True))

    op.create_table(
        "work_subtype_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alias_code", sa.Text(), nullable=False),
        sa.Column("alias_source", sa.String(64), nullable=False),
        sa.Column("target_level", sa.String(16), nullable=False),
        sa.Column("target_code", sa.Text(), nullable=False),
        sa.Column("canonical_code", sa.Text(), nullable=True),
        sa.Column("mapping_type", sa.String(32), nullable=False),
        sa.Column("confidence", sa.String(16), nullable=True),
        sa.Column("transfer_defaults", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "alias_source",
            "alias_code",
            "target_level",
            "target_code",
            name="uq_work_subtype_alias_target",
        ),
    )
    op.create_index("ix_work_subtype_aliases_alias", "work_subtype_aliases", ["alias_source", "alias_code"])
    op.create_index("ix_work_subtype_aliases_canonical", "work_subtype_aliases", ["canonical_code"])

    for table_name in ("estimates",):
        op.add_column(table_name, sa.Column("work_section_code", sa.Text(), nullable=True))
        op.add_column(table_name, sa.Column("work_section_name", sa.Text(), nullable=True))
        op.add_column(table_name, sa.Column("work_subtype_code", sa.Text(), nullable=True))
        op.add_column(table_name, sa.Column("work_subtype_name", sa.Text(), nullable=True))
        op.add_column(table_name, sa.Column("classification_score", sa.Numeric(12, 4), nullable=True))
        op.add_column(table_name, sa.Column("classification_confidence", sa.String(16), nullable=True))
        op.add_column(
            table_name,
            sa.Column(
                "classification_needs_review",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
        op.add_column(table_name, sa.Column("classification_source", sa.String(32), nullable=True))
        op.add_column(table_name, sa.Column("classification_candidates", jsonb, nullable=True))
        op.add_column(table_name, sa.Column("classification_matched_terms", jsonb, nullable=True))
        op.add_column(
            table_name,
            sa.Column(
                "operator_review_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
        op.add_column(table_name, sa.Column("operator_review_status", sa.String(16), nullable=True))
        op.add_column(table_name, sa.Column("operator_review_reason", sa.String(64), nullable=True))
        op.add_column(table_name, sa.Column("dictionary_version", sa.String(96), nullable=True))
        op.add_column(
            table_name,
            sa.Column("manual_override", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
        op.add_column(table_name, sa.Column("manual_changed_by", postgresql.UUID(as_uuid=False), nullable=True))
        op.add_column(table_name, sa.Column("manual_changed_at", sa.TIMESTAMP(timezone=True), nullable=True))

    op.add_column("ktp_wbs_groups", sa.Column("work_section_code", sa.Text(), nullable=True))
    op.add_column("ktp_wbs_groups", sa.Column("work_section_name", sa.Text(), nullable=True))
    op.add_column("ktp_wbs_groups", sa.Column("work_type_confidence", sa.String(16), nullable=True))
    op.add_column("ktp_wbs_groups", sa.Column("work_type_source", sa.String(32), nullable=True))

    op.add_column("ktp_wbs_items", sa.Column("work_section_code", sa.Text(), nullable=True))
    op.add_column("ktp_wbs_items", sa.Column("work_section_name", sa.Text(), nullable=True))
    op.add_column("ktp_wbs_items", sa.Column("work_subtype_code", sa.Text(), nullable=True))
    op.add_column("ktp_wbs_items", sa.Column("work_subtype_name", sa.Text(), nullable=True))
    op.add_column("ktp_wbs_items", sa.Column("work_type_confidence", sa.String(16), nullable=True))
    op.add_column(
        "ktp_wbs_items",
        sa.Column("work_type_needs_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("ktp_wbs_items", sa.Column("work_type_candidates", jsonb, nullable=True))
    op.add_column("ktp_wbs_items", sa.Column("work_type_source", sa.String(32), nullable=True))
    op.add_column(
        "ktp_wbs_items",
        sa.Column("operator_review_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "ktp_wbs_items",
        sa.Column("manual_override", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "ktp_wbs_items",
        sa.Column("gpr_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.add_column("ktp_session_subtypes", sa.Column("work_subtype_code", sa.Text(), nullable=True))
    op.add_column("ktp_session_subtypes", sa.Column("work_subtype_name", sa.Text(), nullable=True))
    op.add_column(
        "ktp_session_subtypes",
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("ktp_wbs_items.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column("ktp_session_subtypes", sa.Column("session_subtype_key", sa.Text(), nullable=True))
    op.create_index("ix_ktp_session_subtypes_item", "ktp_session_subtypes", ["item_id"])

    bind = op.get_bind()
    payload = _dictionary()

    bind.execute(
        sa.text(
            """
            UPDATE work_subtypes
               SET dictionary_source = COALESCE(dictionary_source, 'legacy_csv'),
                   legacy_code = COALESCE(legacy_code, code),
                   display_code = COALESCE(display_code, code),
                   legacy_csv_codes = COALESCE(legacy_csv_codes, jsonb_build_array(code))
             WHERE dictionary_source IS NULL
            """
        )
    )

    work_subtypes = sa.table(
        "work_subtypes",
        sa.column("macro_id", sa.Integer),
        sa.column("macro_name", sa.Text),
        sa.column("code", sa.Text),
        sa.column("name", sa.Text),
        sa.column("keywords", postgresql.ARRAY(sa.Text)),
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
    subtype_rows = _subtype_rows(payload)
    if subtype_rows:
        stmt = pg_insert(work_subtypes).values(subtype_rows)
        stmt = stmt.on_conflict_do_update(
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
        bind.execute(stmt)

    aliases = sa.table(
        "work_subtype_aliases",
        sa.column("alias_code", sa.Text),
        sa.column("alias_source", sa.String),
        sa.column("target_level", sa.String),
        sa.column("target_code", sa.Text),
        sa.column("canonical_code", sa.Text),
        sa.column("mapping_type", sa.String),
        sa.column("confidence", sa.String),
        sa.column("transfer_defaults", sa.Boolean),
        sa.column("is_active", sa.Boolean),
        sa.column("notes", sa.Text),
    )
    alias_rows = _alias_rows(payload)
    if alias_rows:
        stmt = pg_insert(aliases).values(alias_rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_work_subtype_alias_target",
            set_={
                "canonical_code": stmt.excluded.canonical_code,
                "mapping_type": stmt.excluded.mapping_type,
                "confidence": stmt.excluded.confidence,
                "transfer_defaults": stmt.excluded.transfer_defaults,
                "is_active": stmt.excluded.is_active,
                "notes": stmt.excluded.notes,
            },
        )
        bind.execute(stmt)


def downgrade() -> None:
    op.drop_index("ix_ktp_session_subtypes_item", table_name="ktp_session_subtypes")
    for col in ("session_subtype_key", "item_id", "work_subtype_name", "work_subtype_code"):
        op.drop_column("ktp_session_subtypes", col)

    for col in (
        "gpr_confirmed",
        "manual_override",
        "operator_review_required",
        "work_type_source",
        "work_type_candidates",
        "work_type_needs_review",
        "work_type_confidence",
        "work_subtype_name",
        "work_subtype_code",
        "work_section_name",
        "work_section_code",
    ):
        op.drop_column("ktp_wbs_items", col)

    for col in ("work_type_source", "work_type_confidence", "work_section_name", "work_section_code"):
        op.drop_column("ktp_wbs_groups", col)

    for col in (
        "manual_changed_at",
        "manual_changed_by",
        "manual_override",
        "dictionary_version",
        "operator_review_reason",
        "operator_review_status",
        "operator_review_required",
        "classification_matched_terms",
        "classification_candidates",
        "classification_source",
        "classification_needs_review",
        "classification_confidence",
        "classification_score",
        "work_subtype_name",
        "work_subtype_code",
        "work_section_name",
        "work_section_code",
    ):
        op.drop_column("estimates", col)

    op.drop_index("ix_work_subtype_aliases_canonical", table_name="work_subtype_aliases")
    op.drop_index("ix_work_subtype_aliases_alias", table_name="work_subtype_aliases")
    op.drop_table("work_subtype_aliases")

    op.execute(
        """
        DELETE FROM work_subtypes
         WHERE dictionary_source IN ('construction_work_dictionary_v3', 'system')
        """
    )

    for col in (
        "aliases_json",
        "scoring_json",
        "terms_json",
        "legacy_csv_codes",
        "display_code",
        "legacy_code",
        "dictionary_source_version",
        "dictionary_schema_version",
        "dictionary_name",
        "dictionary_source",
        "section_scope",
        "section_name",
        "section_code",
    ):
        op.drop_column("work_subtypes", col)
