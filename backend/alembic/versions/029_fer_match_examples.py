"""
029_fer_match_examples.py
Добавляет таблицу эталонных примеров сопоставления строк сметы с ФЕР.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "029_fer_match_examples"
down_revision = "028_fer_group_match"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fer_match_examples",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("estimate_text", sa.Text(), nullable=False),
        sa.Column("estimate_text_norm", sa.Text(), nullable=True),
        sa.Column("fer_table_id", sa.Integer(), nullable=False),
        sa.Column("fer_work_type", sa.Text(), nullable=True),
        sa.Column("fer_code", sa.Text(), nullable=True),
        sa.Column(
            "source_batch_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("estimate_batches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "confirmed_by",
            sa.String(length=100),
            nullable=False,
            server_default=sa.text("'admin_import'"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("estimate_text", "fer_table_id", name="fer_match_examples_dedup_idx"),
    )
    op.execute("ALTER TABLE fer_match_examples ADD COLUMN embedding fer.vector(1536)")
    op.create_index(
        "ix_fer_match_examples_source_batch_id",
        "fer_match_examples",
        ["source_batch_id"],
    )
    op.execute(
        """
        CREATE INDEX fer_match_examples_embedding_idx
        ON fer_match_examples
        USING ivfflat (embedding fer.vector_cosine_ops)
        WITH (lists = 50)
        """
    )
    op.alter_column("fer_match_examples", "confirmed_by", server_default=None)


def downgrade():
    op.execute("DROP INDEX IF EXISTS fer_match_examples_embedding_idx")
    op.drop_index("ix_fer_match_examples_source_batch_id", table_name="fer_match_examples")
    op.drop_table("fer_match_examples")
