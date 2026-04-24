"""
033_estimate_batch_hours_per_day.py
Сохраняет норму часов в дне на уровне блока сметы.
"""

from alembic import op
import sqlalchemy as sa


revision = "033_estimate_batch_hours_per_day"
down_revision = "032_estimate_batch_start_date"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "estimate_batches",
        sa.Column("hours_per_day", sa.Numeric(6, 2), nullable=False, server_default=sa.text("8")),
    )
    op.execute(
        """
        UPDATE estimate_batches eb
        SET hours_per_day = COALESCE(task_hours.hours_per_day, 8)
        FROM (
            SELECT estimate_batch_id, MIN(hours_per_day) AS hours_per_day
            FROM gantt_tasks
            WHERE estimate_batch_id IS NOT NULL
              AND deleted_at IS NULL
            GROUP BY estimate_batch_id
        ) AS task_hours
        WHERE task_hours.estimate_batch_id = eb.id
        """
    )
    op.execute(
        """
        UPDATE estimate_batches
        SET hours_per_day = 8
        WHERE hours_per_day IS NULL
        """
    )


def downgrade():
    op.drop_column("estimate_batches", "hours_per_day")
