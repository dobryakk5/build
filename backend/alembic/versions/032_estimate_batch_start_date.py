"""
032_estimate_batch_start_date.py
Сохраняет дату старта графика на уровне блока сметы.
"""

from alembic import op
import sqlalchemy as sa


revision = "032_estimate_batch_start_date"
down_revision = "031_estimate_fer_multiplier"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "estimate_batches",
        sa.Column("start_date", sa.Date(), nullable=True),
    )
    op.execute(
        """
        UPDATE estimate_batches eb
        SET start_date = COALESCE(task_dates.start_date, eb.created_at::date)
        FROM (
            SELECT estimate_batch_id, MIN(start_date) AS start_date
            FROM gantt_tasks
            WHERE estimate_batch_id IS NOT NULL
              AND deleted_at IS NULL
            GROUP BY estimate_batch_id
        ) AS task_dates
        WHERE task_dates.estimate_batch_id = eb.id
          AND eb.start_date IS NULL
        """
    )
    op.execute(
        """
        UPDATE estimate_batches
        SET start_date = created_at::date
        WHERE start_date IS NULL
        """
    )


def downgrade():
    op.drop_column("estimate_batches", "start_date")
