"""Add estimate batch project hierarchy selection fields."""

from alembic import op
import sqlalchemy as sa


revision = "057_est_batch_hierarchy"
down_revision = "056_work_taxonomy_v5_reset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("estimate_batches", sa.Column("estimate_type_id", sa.Text(), nullable=True))
    op.add_column("estimate_batches", sa.Column("estimate_type_title", sa.Text(), nullable=True))
    op.add_column("estimate_batches", sa.Column("estimate_type_number", sa.String(length=16), nullable=True))
    op.add_column("estimate_batches", sa.Column("project_variant_id", sa.Text(), nullable=True))
    op.add_column("estimate_batches", sa.Column("project_variant_title", sa.Text(), nullable=True))
    op.add_column("estimate_batches", sa.Column("project_variant_number", sa.String(length=16), nullable=True))
    op.add_column("estimate_batches", sa.Column("taxonomy_dictionary_version", sa.String(length=128), nullable=True))
    op.alter_column(
        "work_subtypes",
        "dictionary_source",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "work_subtypes",
        "dictionary_source",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=True,
    )
    op.drop_column("estimate_batches", "taxonomy_dictionary_version")
    op.drop_column("estimate_batches", "project_variant_number")
    op.drop_column("estimate_batches", "project_variant_title")
    op.drop_column("estimate_batches", "project_variant_id")
    op.drop_column("estimate_batches", "estimate_type_number")
    op.drop_column("estimate_batches", "estimate_type_title")
    op.drop_column("estimate_batches", "estimate_type_id")
