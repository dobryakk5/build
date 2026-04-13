"""
025_fer_words_dictionary.py
Добавляет отдельный справочник fer_words и поля результата сопоставления в смете.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import TIMESTAMP


TIMESTAMPTZ = TIMESTAMP(timezone=True)

revision = "025_fer_words_dictionary"
down_revision = "024_fer_ignore_flags"
branch_labels = None
depends_on = None

FER_WORDS_SCHEMA = "fer_words"


def upgrade():
    op.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {FER_WORDS_SCHEMA}"))

    op.create_table(
        "entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("source_sheet", sa.String(length=255), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("fer_code", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("search_tokens", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("human_hours", sa.Numeric(12, 3), nullable=True),
        sa.Column("machine_hours", sa.Numeric(12, 3), nullable=True),
        sa.Column("part_1", sa.Text(), nullable=True),
        sa.Column("part_2", sa.Text(), nullable=True),
        sa.Column("part_3", sa.Text(), nullable=True),
        sa.Column("part_4", sa.Text(), nullable=True),
        sa.Column("part_5", sa.Text(), nullable=True),
        sa.Column("part_6", sa.Text(), nullable=True),
        sa.Column("part_7", sa.Text(), nullable=True),
        sa.Column("part_8", sa.Text(), nullable=True),
        sa.Column("part_9", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("source_sheet", "source_row_number", name="uq_fer_words_entries_sheet_row"),
        schema=FER_WORDS_SCHEMA,
    )
    op.create_index(
        "ix_fer_words_entries_fer_code",
        "entries",
        ["fer_code"],
        schema=FER_WORDS_SCHEMA,
    )

    op.add_column("estimates", sa.Column("fer_words_entry_id", sa.Integer(), nullable=True))
    op.add_column("estimates", sa.Column("fer_words_code", sa.String(length=50), nullable=True))
    op.add_column("estimates", sa.Column("fer_words_name", sa.Text(), nullable=True))
    op.add_column("estimates", sa.Column("fer_words_human_hours", sa.Numeric(12, 3), nullable=True))
    op.add_column("estimates", sa.Column("fer_words_machine_hours", sa.Numeric(12, 3), nullable=True))
    op.add_column("estimates", sa.Column("fer_words_match_score", sa.Numeric(5, 4), nullable=True))
    op.add_column("estimates", sa.Column("fer_words_match_count", sa.Integer(), nullable=True))
    op.add_column("estimates", sa.Column("fer_words_matched_at", TIMESTAMPTZ, nullable=True))


def downgrade():
    op.drop_column("estimates", "fer_words_matched_at")
    op.drop_column("estimates", "fer_words_match_count")
    op.drop_column("estimates", "fer_words_match_score")
    op.drop_column("estimates", "fer_words_machine_hours")
    op.drop_column("estimates", "fer_words_human_hours")
    op.drop_column("estimates", "fer_words_name")
    op.drop_column("estimates", "fer_words_code")
    op.drop_column("estimates", "fer_words_entry_id")
    op.drop_index("ix_fer_words_entries_fer_code", table_name="entries", schema=FER_WORDS_SCHEMA)
    op.drop_table("entries", schema=FER_WORDS_SCHEMA)
    op.execute(sa.text(f"DROP SCHEMA IF EXISTS {FER_WORDS_SCHEMA}"))
