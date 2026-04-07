"""
017_fer_vector_index.py
Separate vector index storage for FER hierarchy embeddings.
"""

from alembic import op
import sqlalchemy as sa


revision = "017"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE fer.vector_index (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            entity_kind VARCHAR(32) NOT NULL,
            entity_id BIGINT NOT NULL,
            parent_entity_kind VARCHAR(32) NULL,
            parent_entity_id BIGINT NULL,
            collection_id SMALLINT NOT NULL,
            section_id SMALLINT NULL,
            subsection_id SMALLINT NULL,
            table_id SMALLINT NULL,
            row_id INTEGER NULL,
            source_field VARCHAR(32) NOT NULL,
            source_text TEXT NOT NULL,
            search_text TEXT NOT NULL,
            embedding fer.vector(1536) NOT NULL,
            provider VARCHAR(32) NOT NULL,
            model VARCHAR(128) NOT NULL,
            text_checksum VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_fer_vector_index_entity_source_model
                UNIQUE (entity_kind, entity_id, source_field, model)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_fer_vector_index_entity
        ON fer.vector_index (entity_kind, entity_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_fer_vector_index_hierarchy
        ON fer.vector_index (collection_id, section_id, subsection_id, table_id, row_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_fer_vector_index_embedding_hnsw
        ON fer.vector_index USING hnsw (embedding fer.vector_cosine_ops)
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS fer.ix_fer_vector_index_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS fer.ix_fer_vector_index_hierarchy")
    op.execute("DROP INDEX IF EXISTS fer.ix_fer_vector_index_entity")
    op.execute("DROP TABLE IF EXISTS fer.vector_index")
