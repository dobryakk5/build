"""Add parser_profile and import_meta to estimate batches."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "050_est_batch_parser_profile"
down_revision = "049_ktp_item_fer_match"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "estimate_batches",
        sa.Column("parser_profile", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "estimate_batches",
        sa.Column("import_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("estimate_batches", "import_meta")
    op.drop_column("estimate_batches", "parser_profile")
