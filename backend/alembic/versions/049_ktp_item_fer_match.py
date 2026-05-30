"""Add NW/ФЕР matching + disposition columns to ktp_wbs_items.

Supports grounding task durations in fer_rows.h_hour via item-level ФЕР matching
(see plan: Item-Level Duration via Estimate → ФЕР Labor Norms).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "049_ktp_item_fer_match"
down_revision = "048_user_activity_events"
branch_labels = None
depends_on = None


def upgrade():
    # disposition: work | excluded
    op.add_column(
        "ktp_wbs_items",
        sa.Column(
            "disposition",
            sa.String(length=16),
            nullable=False,
            server_default="work",
        ),
    )
    op.add_column(
        "ktp_wbs_items", sa.Column("disposition_reason", sa.Text(), nullable=True)
    )
    op.add_column(
        "ktp_wbs_items",
        sa.Column("disposition_source", sa.String(length=16), nullable=True),
    )

    # NW scope (diagnostic — narrows ФЕР search only)
    op.add_column(
        "ktp_wbs_items", sa.Column("nw_item_code", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "ktp_wbs_items",
        sa.Column("nw_match_source", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "ktp_wbs_items", sa.Column("nw_match_reason", sa.Text(), nullable=True)
    )
    op.add_column(
        "ktp_wbs_items",
        sa.Column("nw_match_candidates", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "ktp_wbs_items",
        sa.Column(
            "nw_manual_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # ФЕР row match (labor-norm source)
    op.add_column(
        "ktp_wbs_items", sa.Column("fer_table_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "ktp_wbs_items", sa.Column("fer_row_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "ktp_wbs_items",
        sa.Column("fer_match_source", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "ktp_wbs_items", sa.Column("fer_match_score", sa.Numeric(5, 4), nullable=True)
    )
    op.add_column(
        "ktp_wbs_items",
        sa.Column("fer_match_candidates", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "ktp_wbs_items",
        sa.Column(
            "fer_manual_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "ktp_wbs_items", sa.Column("fer_h_hour", sa.Numeric(12, 4), nullable=True)
    )
    op.add_column(
        "ktp_wbs_items", sa.Column("fer_unit", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "ktp_wbs_items",
        sa.Column("fer_unit_multiplier", sa.Numeric(12, 4), nullable=True),
    )

    op.create_index(
        "ix_ktp_wbs_items_disposition",
        "ktp_wbs_items",
        ["disposition"],
    )


def downgrade():
    op.drop_index("ix_ktp_wbs_items_disposition", table_name="ktp_wbs_items")
    for col in (
        "fer_unit_multiplier",
        "fer_unit",
        "fer_h_hour",
        "fer_manual_override",
        "fer_match_candidates",
        "fer_match_score",
        "fer_match_source",
        "fer_row_id",
        "fer_table_id",
        "nw_manual_override",
        "nw_match_candidates",
        "nw_match_reason",
        "nw_match_source",
        "nw_item_code",
        "disposition_source",
        "disposition_reason",
        "disposition",
    ):
        op.drop_column("ktp_wbs_items", col)
