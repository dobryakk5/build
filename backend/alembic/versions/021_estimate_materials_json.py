"""
021_estimate_materials_json.py
Добавляет JSONB-колонку для материалов, прикреплённых к строке работы.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "estimates",
        sa.Column("materials", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("estimates", "materials")
