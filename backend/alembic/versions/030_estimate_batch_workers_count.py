"""
030_estimate_batch_workers_count.py
Сохраняет количество рабочих бригады на уровне блока сметы.
"""

from alembic import op
import sqlalchemy as sa


revision = "030_estimate_batch_workers"
down_revision = "029_fer_match_examples"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "estimate_batches",
        sa.Column("workers_count", sa.SmallInteger(), nullable=True),
    )
    op.execute(
        """
        UPDATE estimate_batches eb
        SET workers_count = task_workers.workers_count
        FROM (
            SELECT
                estimate_batch_id,
                MIN(workers_count)::smallint AS workers_count
            FROM gantt_tasks
            WHERE deleted_at IS NULL
              AND COALESCE(is_group, FALSE) = FALSE
              AND workers_count IS NOT NULL
            GROUP BY estimate_batch_id
        ) AS task_workers
        WHERE task_workers.estimate_batch_id = eb.id
          AND eb.workers_count IS NULL
        """
    )


def downgrade():
    op.drop_column("estimate_batches", "workers_count")
