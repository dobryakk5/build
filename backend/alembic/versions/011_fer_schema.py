"""
011_fer_schema.py
Создаёт схему fer и таблицы справочника ФЕР.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import TIMESTAMP

TIMESTAMPTZ = TIMESTAMP(timezone=True)

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None

FER_SCHEMA = "fer"


def upgrade():
    op.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {FER_SCHEMA}"))

    op.create_table(
        "collections",
        sa.Column("id", sa.SmallInteger(), primary_key=True, autoincrement=True),
        sa.Column("num", sa.String(length=10), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("full_title", sa.Text(), nullable=False),
        sa.UniqueConstraint("num", name="uq_fer_collections_num"),
        schema=FER_SCHEMA,
    )

    op.create_table(
        "sections",
        sa.Column("id", sa.SmallInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "collection_id",
            sa.SmallInteger(),
            sa.ForeignKey(f"{FER_SCHEMA}.collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.UniqueConstraint("collection_id", "title", name="uq_fer_sections_collection_title"),
        schema=FER_SCHEMA,
    )
    op.create_index(
        "ix_fer_sections_collection_id",
        "sections",
        ["collection_id"],
        schema=FER_SCHEMA,
    )

    op.create_table(
        "subsections",
        sa.Column("id", sa.SmallInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "section_id",
            sa.SmallInteger(),
            sa.ForeignKey(f"{FER_SCHEMA}.sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.UniqueConstraint("section_id", "title", name="uq_fer_subsections_section_title"),
        schema=FER_SCHEMA,
    )
    op.create_index(
        "ix_fer_subsections_section_id",
        "subsections",
        ["section_id"],
        schema=FER_SCHEMA,
    )

    op.create_table(
        "fer_tables",
        sa.Column("id", sa.SmallInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "collection_id",
            sa.SmallInteger(),
            sa.ForeignKey(f"{FER_SCHEMA}.collections.id"),
            nullable=False,
        ),
        sa.Column(
            "section_id",
            sa.SmallInteger(),
            sa.ForeignKey(f"{FER_SCHEMA}.sections.id"),
            nullable=True,
        ),
        sa.Column(
            "subsection_id",
            sa.SmallInteger(),
            sa.ForeignKey(f"{FER_SCHEMA}.subsections.id"),
            nullable=True,
        ),
        sa.Column("table_title", sa.Text(), nullable=False),
        sa.Column("table_url", sa.Text(), nullable=False),
        sa.Column("row_count", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("description_header", sa.Text(), nullable=True),
        sa.Column("common_work_name", sa.Text(), nullable=True),
        sa.Column("scraped_at", TIMESTAMPTZ, nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("table_url", name="uq_fer_tables_table_url"),
        schema=FER_SCHEMA,
    )
    op.create_index(
        "ix_fer_tables_collection_id",
        "fer_tables",
        ["collection_id"],
        schema=FER_SCHEMA,
    )
    op.create_index(
        "ix_fer_tables_section_id",
        "fer_tables",
        ["section_id"],
        schema=FER_SCHEMA,
    )
    op.create_index(
        "ix_fer_tables_subsection_id",
        "fer_tables",
        ["subsection_id"],
        schema=FER_SCHEMA,
    )

    op.create_table(
        "fer_rows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "table_id",
            sa.SmallInteger(),
            sa.ForeignKey(f"{FER_SCHEMA}.fer_tables.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_slug", sa.Text(), nullable=True),
        sa.Column("clarification", sa.Text(), nullable=True),
        sa.Column("h_hour", sa.Numeric(), nullable=True),
        sa.Column("m_hour", sa.Numeric(), nullable=True),
        sa.UniqueConstraint("table_id", "row_slug", name="uq_fer_rows_table_row_slug"),
        schema=FER_SCHEMA,
    )
    op.create_index(
        "ix_fer_rows_table_id",
        "fer_rows",
        ["table_id"],
        schema=FER_SCHEMA,
    )


def downgrade():
    op.drop_index("ix_fer_rows_table_id", table_name="fer_rows", schema=FER_SCHEMA)
    op.drop_table("fer_rows", schema=FER_SCHEMA)

    op.drop_index("ix_fer_tables_subsection_id", table_name="fer_tables", schema=FER_SCHEMA)
    op.drop_index("ix_fer_tables_section_id", table_name="fer_tables", schema=FER_SCHEMA)
    op.drop_index("ix_fer_tables_collection_id", table_name="fer_tables", schema=FER_SCHEMA)
    op.drop_table("fer_tables", schema=FER_SCHEMA)

    op.drop_index("ix_fer_subsections_section_id", table_name="subsections", schema=FER_SCHEMA)
    op.drop_table("subsections", schema=FER_SCHEMA)

    op.drop_index("ix_fer_sections_collection_id", table_name="sections", schema=FER_SCHEMA)
    op.drop_table("sections", schema=FER_SCHEMA)

    op.drop_table("collections", schema=FER_SCHEMA)
    op.execute(sa.text(f"DROP SCHEMA IF EXISTS {FER_SCHEMA}"))
