"""
012_fer_drop_unused_columns_reset_sequences.py
Убирает неиспользуемые колонки из схемы fer и синхронизирует sequence.
"""

from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def _sync_sequence(table_name: str) -> None:
    op.execute(
        sa.text(
            f"""
            SELECT setval(
                pg_get_serial_sequence('fer.{table_name}', 'id'),
                COALESCE((SELECT MAX(id) FROM fer.{table_name}), 1),
                (SELECT COALESCE(MAX(id), 0) > 0 FROM fer.{table_name})
            )
            """
        )
    )


def upgrade():
    op.drop_column("collections", "full_title", schema="fer")
    op.drop_column("fer_tables", "description_header", schema="fer")

    _sync_sequence("collections")
    _sync_sequence("sections")
    _sync_sequence("subsections")
    _sync_sequence("fer_tables")
    _sync_sequence("fer_rows")


def downgrade():
    op.add_column(
        "collections",
        sa.Column("full_title", sa.Text(), nullable=True),
        schema="fer",
    )
    op.execute(sa.text("UPDATE fer.collections SET full_title = name WHERE full_title IS NULL"))
    op.alter_column("collections", "full_title", nullable=False, schema="fer")

    op.add_column(
        "fer_tables",
        sa.Column("description_header", sa.Text(), nullable=True),
        schema="fer",
    )

    _sync_sequence("collections")
    _sync_sequence("sections")
    _sync_sequence("subsections")
    _sync_sequence("fer_tables")
    _sync_sequence("fer_rows")
