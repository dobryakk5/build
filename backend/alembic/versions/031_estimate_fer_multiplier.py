"""
031_estimate_fer_multiplier.py
Добавляет множитель нормы ФЕР на строку сметы.
"""

from alembic import op
import sqlalchemy as sa


revision = "031_estimate_fer_multiplier"
down_revision = "030_estimate_batch_workers"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "estimates",
        sa.Column("fer_multiplier", sa.Numeric(6, 2), nullable=False, server_default=sa.text("1.0")),
    )


def downgrade():
    op.drop_column("estimates", "fer_multiplier")
