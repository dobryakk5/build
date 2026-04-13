"""
024_fer_ignore_flags.py
Добавляет системный флаг ignored для иерархии ФЕР.
"""

from alembic import op
import sqlalchemy as sa


revision = "024_fer_ignore_flags"
down_revision = "023"
branch_labels = None
depends_on = None

FER_SCHEMA = "fer"


def upgrade():
    for table_name in ("collections", "sections", "subsections", "fer_tables"):
        op.add_column(
            table_name,
            sa.Column("ignored", sa.Boolean(), nullable=False, server_default=sa.false()),
            schema=FER_SCHEMA,
        )


def downgrade():
    for table_name in ("fer_tables", "subsections", "sections", "collections"):
        op.drop_column(table_name, "ignored", schema=FER_SCHEMA)
