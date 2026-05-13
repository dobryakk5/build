from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "045_ktp_group_wt_match_fields"
down_revision = "044_pwp_source_label"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ktp_groups", sa.Column("wt_code", sa.String(10), nullable=True))
    op.add_column("ktp_groups", sa.Column("wt_name", sa.Text(), nullable=True))
    op.add_column("ktp_groups", sa.Column("wt_match_reason", sa.Text(), nullable=True))
    op.add_column("ktp_groups", sa.Column("wt_match_confidence", sa.Numeric(5, 4), nullable=True))
    op.add_column("ktp_groups", sa.Column("wt_match_candidates", JSONB(), nullable=True))
    op.add_column("ktp_groups", sa.Column("wt_matched_at", sa.TIMESTAMP(timezone=True), nullable=True))


def downgrade():
    op.drop_column("ktp_groups", "wt_matched_at")
    op.drop_column("ktp_groups", "wt_match_candidates")
    op.drop_column("ktp_groups", "wt_match_confidence")
    op.drop_column("ktp_groups", "wt_match_reason")
    op.drop_column("ktp_groups", "wt_name")
    op.drop_column("ktp_groups", "wt_code")
