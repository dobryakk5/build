"""
005_enir_collection_metadata.py
Добавляет метаданные сборника ЕНИР в enir_collections.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "enir_collections",
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "enir_collections",
        sa.Column("source_file", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "enir_collections",
        sa.Column("issuing_bodies", JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "enir_collections",
        sa.Column("approval_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "enir_collections",
        sa.Column("approval_number", sa.String(length=100), nullable=False, server_default=""),
    )
    op.add_column(
        "enir_collections",
        sa.Column("developer", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "enir_collections",
        sa.Column("coordination", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "enir_collections",
        sa.Column("amendments", JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade():
    op.drop_column("enir_collections", "amendments")
    op.drop_column("enir_collections", "coordination")
    op.drop_column("enir_collections", "developer")
    op.drop_column("enir_collections", "approval_number")
    op.drop_column("enir_collections", "approval_date")
    op.drop_column("enir_collections", "issuing_bodies")
    op.drop_column("enir_collections", "source_file")
    op.drop_column("enir_collections", "schema_version")
