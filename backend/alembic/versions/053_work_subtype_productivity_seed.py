"""Seed примерных значений производительности в справочник work_subtypes.

Читает ``backend/app/data/work_subtypes.csv`` (колонки output_per_day / crew_size /
lag_after_days / default_unit) и проставляет дефолты по subtype_code. Это ПРИМЕРНЫЕ
значения — в сессии они подтягиваются как ``*_source='default'`` и помечаются в UI.
Идемпотентно: повторный прогон просто переписывает дефолты по коду.
"""
from __future__ import annotations

import csv
from pathlib import Path

from alembic import op
import sqlalchemy as sa


revision = "053_subtype_prod_seed"
down_revision = "052_ktp_session_subtypes"
branch_labels = None
depends_on = None

_DATA_DIR = Path(__file__).resolve().parents[2] / "app" / "data"


def upgrade() -> None:
    with open(_DATA_DIR / "work_subtypes.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    bind = op.get_bind()
    stmt = sa.text(
        """
        UPDATE work_subtypes
           SET output_per_day = :output_per_day,
               crew_size      = :crew_size,
               lag_after_days = :lag_after_days,
               default_unit   = :default_unit
         WHERE code = :code
        """
    )
    for r in rows:
        opd = r.get("output_per_day")
        crew = r.get("crew_size")
        lag = r.get("lag_after_days")
        if not opd:  # строки без дефолтов пропускаем
            continue
        bind.execute(
            stmt,
            {
                "code": r["subtype_code"],
                "output_per_day": float(opd),
                "crew_size": int(crew) if crew else None,
                "lag_after_days": int(lag) if lag else 0,
                "default_unit": (r.get("default_unit") or None),
            },
        )


def downgrade() -> None:
    op.execute(
        """
        UPDATE work_subtypes
           SET output_per_day = NULL,
               crew_size      = NULL,
               lag_after_days = 0,
               default_unit   = NULL
        """
    )
