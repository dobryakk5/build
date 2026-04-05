"""
015_estimate_fer_match_fields.py
Добавляет поля результата сопоставления сметы с ФЕР.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import TIMESTAMP

TIMESTAMPTZ = TIMESTAMP(timezone=True)


revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("estimates", sa.Column("fer_table_id", sa.Integer(), nullable=True))
    op.add_column("estimates", sa.Column("fer_work_type", sa.Text(), nullable=True))
    op.add_column("estimates", sa.Column("fer_match_score", sa.Numeric(5, 4), nullable=True))
    op.add_column("estimates", sa.Column("fer_matched_at", TIMESTAMPTZ, nullable=True))
    op.create_index("idx_estimates_fer_table_id", "estimates", ["fer_table_id"])


def downgrade():
    op.drop_index("idx_estimates_fer_table_id", table_name="estimates")
    op.drop_column("estimates", "fer_matched_at")
    op.drop_column("estimates", "fer_match_score")
    op.drop_column("estimates", "fer_work_type")
    op.drop_column("estimates", "fer_table_id")
