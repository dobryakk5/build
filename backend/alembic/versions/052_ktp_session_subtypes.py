"""КТП: этап производительности вместо ФЕР.

Добавляет дефолты производительности в справочник ``work_subtypes`` и создаёт
per-session таблицу ``ktp_session_subtypes`` (оператор задаёт объём,
производительность бригады за смену, размер бригады и техпаузу после подтипа).
Старые сессии в ФЕР-статусах переводятся в новый этап ``prod_review``.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "052_ktp_session_subtypes"
down_revision = "051_work_taxonomy_and_dep_lag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Дефолты справочника ──────────────────────────────────────────────────
    op.add_column("work_subtypes", sa.Column("output_per_day", sa.Numeric(12, 3), nullable=True))
    op.add_column("work_subtypes", sa.Column("crew_size", sa.SmallInteger, nullable=True))
    op.add_column(
        "work_subtypes",
        sa.Column("lag_after_days", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column("work_subtypes", sa.Column("default_unit", sa.Text, nullable=True))

    # ── per-session таблица производительности ───────────────────────────────
    op.create_table(
        "ktp_session_subtypes",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "session_id",
            UUID(as_uuid=False),
            sa.ForeignKey("ktp_estimate_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subtype_code", sa.Text, nullable=False),
        sa.Column("subtype_name", sa.Text, nullable=False),
        sa.Column("macro_name", sa.Text, nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("volume", sa.Numeric(12, 3), nullable=True),
        sa.Column("output_per_day", sa.Numeric(12, 3), nullable=True),
        sa.Column("crew_size", sa.SmallInteger, nullable=True),
        sa.Column("lag_after_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_source", sa.String(8), nullable=False, server_default="default"),
        sa.Column("crew_source", sa.String(8), nullable=False, server_default="default"),
        sa.Column("lag_source", sa.String(8), nullable=False, server_default="default"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "session_id", "subtype_code", "unit",
            name="uq_ktp_session_subtypes_session_code_unit",
        ),
        sa.CheckConstraint("output_per_day IS NULL OR output_per_day > 0", name="ck_kss_output_pos"),
        sa.CheckConstraint("crew_size IS NULL OR crew_size > 0", name="ck_kss_crew_pos"),
        sa.CheckConstraint("lag_after_days >= 0", name="ck_kss_lag_nonneg"),
        sa.CheckConstraint("volume IS NULL OR volume > 0", name="ck_kss_volume_pos"),
    )
    op.create_index(
        "ix_ktp_session_subtypes_session", "ktp_session_subtypes", ["session_id"]
    )

    # ── Совместимость: старые ФЕР-сессии → этап производительности ────────────
    op.execute(
        """
        UPDATE ktp_estimate_sessions
           SET status = 'prod_review'
         WHERE status IN ('fer_pending', 'fer_processing', 'fer_review', 'fer_failed')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE ktp_estimate_sessions
           SET status = 'fer_pending'
         WHERE status IN ('prod_pending', 'prod_review')
        """
    )
    op.drop_index("ix_ktp_session_subtypes_session", table_name="ktp_session_subtypes")
    op.drop_table("ktp_session_subtypes")
    op.drop_column("work_subtypes", "default_unit")
    op.drop_column("work_subtypes", "lag_after_days")
    op.drop_column("work_subtypes", "crew_size")
    op.drop_column("work_subtypes", "output_per_day")
