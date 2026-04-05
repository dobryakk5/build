"""
014_estimate_batches_and_complex_uploads.py
Добавляет блоки смет внутри одного объекта.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import TIMESTAMP

TIMESTAMPTZ = TIMESTAMP(timezone=True)


revision = "014"
down_revision = "013"


def upgrade():
    op.create_table(
        "estimate_batches",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("estimate_kind", sa.String(32), nullable=False, server_default="non_residential"),
        sa.Column("source_filename", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.text("NOW()")),
        sa.Column("deleted_at", TIMESTAMPTZ, nullable=True),
    )
    op.create_index(
        "idx_estimate_batches_project",
        "estimate_batches",
        ["project_id", "created_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.add_column(
        "estimates",
        sa.Column("estimate_batch_id", UUID, sa.ForeignKey("estimate_batches.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column(
        "gantt_tasks",
        sa.Column("estimate_batch_id", UUID, sa.ForeignKey("estimate_batches.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("idx_estimates_batch", "estimates", ["estimate_batch_id"])
    op.create_index("idx_gantt_batch", "gantt_tasks", ["estimate_batch_id"])

    op.execute(
        """
        INSERT INTO estimate_batches (id, project_id, name, estimate_kind, source_filename, created_at)
        SELECT
            gen_random_uuid(),
            src.project_id,
            'Смета объекта',
            'non_residential',
            NULL,
            NOW()
        FROM (
            SELECT DISTINCT project_id
            FROM estimates
            WHERE deleted_at IS NULL
            UNION
            SELECT DISTINCT project_id
            FROM gantt_tasks
            WHERE deleted_at IS NULL
        ) AS src
        """
    )

    op.execute(
        """
        UPDATE estimates e
        SET estimate_batch_id = b.id
        FROM estimate_batches b
        WHERE b.project_id = e.project_id
          AND b.deleted_at IS NULL
          AND e.deleted_at IS NULL
          AND e.estimate_batch_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE gantt_tasks gt
        SET estimate_batch_id = b.id
        FROM estimate_batches b
        WHERE b.project_id = gt.project_id
          AND b.deleted_at IS NULL
          AND gt.deleted_at IS NULL
          AND gt.estimate_batch_id IS NULL
        """
    )


def downgrade():
    op.drop_index("idx_gantt_batch", table_name="gantt_tasks")
    op.drop_index("idx_estimates_batch", table_name="estimates")
    op.drop_column("gantt_tasks", "estimate_batch_id")
    op.drop_column("estimates", "estimate_batch_id")
    op.drop_index("idx_estimate_batches_project", table_name="estimate_batches")
    op.drop_table("estimate_batches")
