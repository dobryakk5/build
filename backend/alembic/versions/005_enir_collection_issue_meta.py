"""
005_enir_collection_issue_meta.py
Добавляет issue metadata для сборников ENIR.
"""

from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("enir_collections", sa.Column("issue", sa.String(length=100), nullable=True))
    op.add_column("enir_collections", sa.Column("issue_title", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("enir_collections", "issue_title")
    op.drop_column("enir_collections", "issue")
