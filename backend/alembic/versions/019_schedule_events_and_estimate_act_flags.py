"""
019_schedule_events_and_estimate_act_flags.py
Добавляет флаги актов для строк сметы, события переноса поставки и baseline-срезы графика.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "019"
down_revision = "018"


def upgrade():
    op.add_column(
        "estimates",
        sa.Column("req_hidden_work_act", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "estimates",
        sa.Column("req_intermediate_act", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "estimates",
        sa.Column("req_ks2_ks3", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_table(
        "material_delay_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("material_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("materials.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reported_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("material_name", sa.Text(), nullable=False),
        sa.Column("old_delivery_date", sa.Date(), nullable=True),
        sa.Column("new_delivery_date", sa.Date(), nullable=False),
        sa.Column("days_shifted", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reported_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_material_delay_events_project_id", "material_delay_events", ["project_id"])
    op.create_index("ix_material_delay_events_reported_at", "material_delay_events", ["reported_at"])

    op.create_table(
        "schedule_baselines",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="accepted_overdue"),
        sa.Column("baseline_year", sa.Integer(), nullable=False),
        sa.Column("baseline_week", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("project_id", "kind", "baseline_year", "baseline_week", name="uq_schedule_baseline_project_week_kind"),
    )
    op.create_index("ix_schedule_baselines_project_id", "schedule_baselines", ["project_id"])
    op.create_index("ix_schedule_baselines_created_at", "schedule_baselines", ["created_at"])

    op.create_table(
        "schedule_baseline_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("baseline_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("schedule_baselines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("gantt_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("estimate_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("estimates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("estimate_batch_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("estimate_batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("parent_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("working_days", sa.Integer(), nullable=False),
        sa.Column("workers_count", sa.SmallInteger(), nullable=True),
        sa.Column("labor_hours", sa.Numeric(10, 2), nullable=True),
        sa.Column("hours_per_day", sa.Numeric(6, 2), nullable=True),
        sa.Column("progress", sa.SmallInteger(), nullable=False),
        sa.Column("is_group", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("color", sa.String(length=20), nullable=True),
        sa.Column("row_order", sa.Numeric(20, 10), nullable=False),
        sa.Column("depends_on", sa.Text(), nullable=True),
    )
    op.create_index("ix_schedule_baseline_tasks_baseline_id", "schedule_baseline_tasks", ["baseline_id"])


def downgrade():
    op.drop_index("ix_schedule_baseline_tasks_baseline_id", table_name="schedule_baseline_tasks")
    op.drop_table("schedule_baseline_tasks")

    op.drop_index("ix_schedule_baselines_created_at", table_name="schedule_baselines")
    op.drop_index("ix_schedule_baselines_project_id", table_name="schedule_baselines")
    op.drop_table("schedule_baselines")

    op.drop_index("ix_material_delay_events_reported_at", table_name="material_delay_events")
    op.drop_index("ix_material_delay_events_project_id", table_name="material_delay_events")
    op.drop_table("material_delay_events")

    op.drop_column("estimates", "req_ks2_ks3")
    op.drop_column("estimates", "req_intermediate_act")
    op.drop_column("estimates", "req_hidden_work_act")
