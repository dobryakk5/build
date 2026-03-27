"""
010_enir_technical_coefficient_scopes.py
Добавляет M:N-область применения технических коэффициентов по списку параграфов.
"""

from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "enir_technical_coefficient_paragraphs",
        sa.Column(
            "technical_coefficient_id",
            sa.BigInteger(),
            sa.ForeignKey("enir_technical_coefficients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "paragraph_id",
            sa.BigInteger(),
            sa.ForeignKey("enir_paragraphs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "technical_coefficient_id",
            "paragraph_id",
            name="pk_enir_tc_paragraphs",
        ),
    )
    op.create_index(
        "ix_enir_tcp_paragraph_id",
        "enir_technical_coefficient_paragraphs",
        ["paragraph_id"],
    )


def downgrade():
    op.drop_index("ix_enir_tcp_paragraph_id", table_name="enir_technical_coefficient_paragraphs")
    op.drop_table("enir_technical_coefficient_paragraphs")
