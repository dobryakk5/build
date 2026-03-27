"""
007_enir_norm_column_label_text.py
Расширяет поле label у колонок таблиц норм ENIR до TEXT для E3.
"""

from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "enir_norm_columns",
        "label",
        existing_type=sa.String(length=20),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade():
    op.alter_column(
        "enir_norm_columns",
        "label",
        existing_type=sa.Text(),
        type_=sa.String(length=20),
        existing_nullable=True,
    )
