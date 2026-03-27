"""
006_enir_paragraph_links.py
Добавляет HTML-якоря параграфов и ссылки на внешние источники для ENIR.
"""

from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("enir_paragraphs", sa.Column("html_anchor", sa.String(length=100), nullable=True))
    op.create_index(
        "idx_enir_paragraphs_html_anchor",
        "enir_paragraphs",
        ["html_anchor"],
        unique=False,
        postgresql_where=sa.text("html_anchor IS NOT NULL"),
    )

    op.create_table(
        "enir_paragraph_refs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "paragraph_id",
            sa.BigInteger(),
            sa.ForeignKey("enir_paragraphs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ref_type", sa.String(length=20), nullable=False),
        sa.Column("link_text", sa.Text(), nullable=True),
        sa.Column("href", sa.Text(), nullable=True),
        sa.Column("abs_url", sa.Text(), nullable=True),
        sa.Column("context_text", sa.Text(), nullable=True),
        sa.Column("is_meganorm", sa.Boolean(), nullable=True, server_default=sa.text("false")),
    )
    op.create_index(
        "idx_enir_paragraph_refs_paragraph_id",
        "enir_paragraph_refs",
        ["paragraph_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("idx_enir_paragraph_refs_paragraph_id", table_name="enir_paragraph_refs")
    op.drop_table("enir_paragraph_refs")
    op.drop_index("idx_enir_paragraphs_html_anchor", table_name="enir_paragraphs")
    op.drop_column("enir_paragraphs", "html_anchor")
