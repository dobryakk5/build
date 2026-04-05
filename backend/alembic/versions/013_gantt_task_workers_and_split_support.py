"""
013_gantt_task_workers_and_split_support.py
Добавляет плановое количество исполнителей на задачу Ганта.
"""

from alembic import op
import sqlalchemy as sa


revision = "013"
down_revision = "012"


def upgrade():
    op.add_column(
        "gantt_tasks",
        sa.Column("workers_count", sa.SmallInteger(), nullable=True),
    )
    op.execute("UPDATE gantt_tasks SET workers_count = 1 WHERE is_group = false")
    op.create_check_constraint(
        "ck_task_workers_count",
        "gantt_tasks",
        "workers_count IS NULL OR workers_count > 0",
    )


def downgrade():
    op.drop_constraint("ck_task_workers_count", "gantt_tasks", type_="check")
    op.drop_column("gantt_tasks", "workers_count")
