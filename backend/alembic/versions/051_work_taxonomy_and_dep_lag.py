"""Work taxonomy (subtypes + precedence) tables and task_dependencies.lag_days.

Создаёт справочник видов работ (work_subtypes), граф предшествования
(work_precedence) и добавляет технологический лаг к зависимостям Ганта.
Seed читается из backend/app/data/*.csv и накатывается идемпотентно
(INSERT ... ON CONFLICT DO UPDATE), чтобы повторные прогоны не ломали БД.
"""
from __future__ import annotations

import csv
from pathlib import Path

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert


revision = "051_work_taxonomy_and_dep_lag"
down_revision = "050_est_batch_parser_profile"
branch_labels = None
depends_on = None


# backend/app/data/  (versions/ → alembic/ → backend/)
_DATA_DIR = Path(__file__).resolve().parents[2] / "app" / "data"


def _read_csv(name: str) -> list[dict]:
    with open(_DATA_DIR / name, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def upgrade() -> None:
    work_subtypes = op.create_table(
        "work_subtypes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("macro_id", sa.Integer, nullable=False),
        sa.Column("macro_name", sa.Text, nullable=False),
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("keywords", postgresql.ARRAY(sa.Text), nullable=False),
        sa.UniqueConstraint("code", name="uq_work_subtypes_code"),
    )
    work_precedence = op.create_table(
        "work_precedence",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("predecessor_code", sa.Text, nullable=False),
        sa.Column("successor_code", sa.Text, nullable=False),
        sa.Column("lag_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("note", sa.Text, nullable=True),
        sa.UniqueConstraint("predecessor_code", "successor_code", name="uq_work_precedence_pair"),
    )

    op.add_column(
        "task_dependencies",
        sa.Column("lag_days", sa.Integer, nullable=False, server_default="0"),
    )

    # ── Seed (идемпотентно) ──────────────────────────────────────────────────
    subtype_rows = [
        {
            "macro_id": int(r["macro_id"]),
            "macro_name": r["macro_name"],
            "code": r["subtype_code"],
            "name": r["subtype_name"],
            "keywords": [k.strip() for k in r["keywords"].split(";") if k.strip()],
        }
        for r in _read_csv("work_subtypes.csv")
    ]
    if subtype_rows:
        stmt = pg_insert(work_subtypes).values(subtype_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["code"],
            set_={
                "macro_id": stmt.excluded.macro_id,
                "macro_name": stmt.excluded.macro_name,
                "name": stmt.excluded.name,
                "keywords": stmt.excluded.keywords,
            },
        )
        op.get_bind().execute(stmt)

    precedence_rows = [
        {
            "predecessor_code": r["predecessor_code"],
            "successor_code": r["successor_code"],
            "lag_days": int(r["lag_days"] or 0),
            "note": r.get("note") or None,
        }
        for r in _read_csv("work_precedence.csv")
    ]
    if precedence_rows:
        stmt = pg_insert(work_precedence).values(precedence_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["predecessor_code", "successor_code"],
            set_={
                "lag_days": stmt.excluded.lag_days,
                "note": stmt.excluded.note,
            },
        )
        op.get_bind().execute(stmt)


def downgrade() -> None:
    op.drop_column("task_dependencies", "lag_days")
    op.drop_table("work_precedence")
    op.drop_table("work_subtypes")
