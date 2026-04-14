"""
027_fer_vector_index_fts.py
Добавляет FTS-колонку и GIN-индекс для гибридного поиска по fer.vector_index.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "027_fer_vector_index_fts"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "vector_index",
        sa.Column("fts_document", postgresql.TSVECTOR(), nullable=True),
        schema="fer",
    )
    op.execute(
        """
        CREATE INDEX ix_fer_vector_index_fts_document
        ON fer.vector_index
        USING gin (fts_document)
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS fer.ix_fer_vector_index_fts_document")
    op.drop_column("vector_index", "fts_document", schema="fer")
