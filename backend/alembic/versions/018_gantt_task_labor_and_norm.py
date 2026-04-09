"""
018_gantt_task_labor_and_norm.py
Добавляет трудоемкость и норму часов в день для задач Ганта.
"""

from alembic import op
import sqlalchemy as sa


revision = "018"
down_revision = "017"


def upgrade():
    op.add_column(
        "gantt_tasks",
        sa.Column("labor_hours", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "gantt_tasks",
        sa.Column("hours_per_day", sa.Numeric(6, 2), nullable=False, server_default=sa.text("8")),
    )

    op.execute(
        """
        UPDATE gantt_tasks
           SET labor_hours = ROUND(working_days * COALESCE(workers_count, 1) * hours_per_day, 2)
         WHERE is_group = false
           AND deleted_at IS NULL
        """
    )

    op.create_check_constraint(
        "ck_task_hours_per_day_positive",
        "gantt_tasks",
        "hours_per_day > 0",
    )
    op.create_check_constraint(
        "ck_task_labor_hours_nonnegative",
        "gantt_tasks",
        "labor_hours IS NULL OR labor_hours >= 0",
    )


def downgrade():
    op.drop_constraint("ck_task_labor_hours_nonnegative", "gantt_tasks", type_="check")
    op.drop_constraint("ck_task_hours_per_day_positive", "gantt_tasks", type_="check")
    op.drop_column("gantt_tasks", "hours_per_day")
    op.drop_column("gantt_tasks", "labor_hours")
