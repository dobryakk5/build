"""020_merge_016_019_heads.py

Merge alembic heads 016 and 019 into a single linear tip.
"""

from alembic import op


revision = "020"
down_revision = ("016", "019")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
