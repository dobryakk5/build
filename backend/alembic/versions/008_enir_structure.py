"""
008_enir_structure.py
Добавляет в ENIR структуру разделов/глав и связи параграфов с ними.
"""

from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "enir_sections",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "collection_id",
            sa.BigInteger(),
            sa.ForeignKey("enir_collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_section_id", sa.String(length=60), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("has_tech", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("collection_id", "source_section_id", name="uq_enir_section_source_id"),
    )
    op.create_index("ix_enir_sections_collection_id", "enir_sections", ["collection_id"])

    op.create_table(
        "enir_chapters",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "collection_id",
            sa.BigInteger(),
            sa.ForeignKey("enir_collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "section_id",
            sa.BigInteger(),
            sa.ForeignKey("enir_sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_chapter_id", sa.String(length=60), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("has_tech", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("collection_id", "source_chapter_id", name="uq_enir_chapter_source_id"),
    )
    op.create_index("ix_enir_chapters_collection_id", "enir_chapters", ["collection_id"])
    op.create_index("ix_enir_chapters_section_id", "enir_chapters", ["section_id"])

    op.add_column("enir_paragraphs", sa.Column("section_id", sa.BigInteger(), nullable=True))
    op.add_column("enir_paragraphs", sa.Column("chapter_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_enir_paragraphs_section_id", "enir_paragraphs", ["section_id"])
    op.create_index("ix_enir_paragraphs_chapter_id", "enir_paragraphs", ["chapter_id"])
    op.create_foreign_key(
        "fk_enir_paragraphs_section_id",
        "enir_paragraphs",
        "enir_sections",
        ["section_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_enir_paragraphs_chapter_id",
        "enir_paragraphs",
        "enir_chapters",
        ["chapter_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_enir_paragraphs_chapter_id", "enir_paragraphs", type_="foreignkey")
    op.drop_constraint("fk_enir_paragraphs_section_id", "enir_paragraphs", type_="foreignkey")
    op.drop_index("ix_enir_paragraphs_chapter_id", table_name="enir_paragraphs")
    op.drop_index("ix_enir_paragraphs_section_id", table_name="enir_paragraphs")
    op.drop_column("enir_paragraphs", "chapter_id")
    op.drop_column("enir_paragraphs", "section_id")

    op.drop_index("ix_enir_chapters_section_id", table_name="enir_chapters")
    op.drop_index("ix_enir_chapters_collection_id", table_name="enir_chapters")
    op.drop_table("enir_chapters")

    op.drop_index("ix_enir_sections_collection_id", table_name="enir_sections")
    op.drop_table("enir_sections")
