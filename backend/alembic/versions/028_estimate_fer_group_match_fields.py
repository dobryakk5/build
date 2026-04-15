"""
028_estimate_fer_group_match_fields.py
Добавляет общие поля привязки группы работ строки сметы к разделу или сборнику ФЕР.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "028_fer_group_match"
down_revision = "027_fer_vector_index_fts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("estimates", sa.Column("fer_group_kind", sa.String(length=32), nullable=True))
    op.add_column("estimates", sa.Column("fer_group_ref_id", sa.Integer(), nullable=True))
    op.add_column("estimates", sa.Column("fer_group_title", sa.Text(), nullable=True))
    op.add_column("estimates", sa.Column("fer_group_collection_id", sa.Integer(), nullable=True))
    op.add_column("estimates", sa.Column("fer_group_collection_num", sa.String(length=32), nullable=True))
    op.add_column("estimates", sa.Column("fer_group_collection_name", sa.Text(), nullable=True))
    op.add_column("estimates", sa.Column("fer_group_match_score", sa.Numeric(5, 4), nullable=True))
    op.add_column("estimates", sa.Column("fer_group_matched_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column(
        "estimates",
        sa.Column("fer_group_is_ambiguous", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
    )
    op.add_column("estimates", sa.Column("fer_group_candidates", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.alter_column("estimates", "fer_group_is_ambiguous", server_default=None)


def downgrade():
    op.drop_column("estimates", "fer_group_candidates")
    op.drop_column("estimates", "fer_group_is_ambiguous")
    op.drop_column("estimates", "fer_group_matched_at")
    op.drop_column("estimates", "fer_group_match_score")
    op.drop_column("estimates", "fer_group_collection_name")
    op.drop_column("estimates", "fer_group_collection_num")
    op.drop_column("estimates", "fer_group_collection_id")
    op.drop_column("estimates", "fer_group_title")
    op.drop_column("estimates", "fer_group_ref_id")
    op.drop_column("estimates", "fer_group_kind")
