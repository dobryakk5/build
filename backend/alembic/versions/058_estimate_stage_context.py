"""Add estimate row stage/context classification fields."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "058_est_stage_context"
down_revision = "057_est_batch_hierarchy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("estimates", sa.Column("estimate_type_id", sa.Text(), nullable=True))
    op.add_column("estimates", sa.Column("estimate_type_number", sa.String(length=16), nullable=True))
    op.add_column("estimates", sa.Column("project_variant_id", sa.Text(), nullable=True))
    op.add_column("estimates", sa.Column("project_variant_number", sa.String(length=16), nullable=True))
    op.add_column("estimates", sa.Column("canonical_stage_id", sa.Text(), nullable=True))
    op.add_column("estimates", sa.Column("work_stage_number", sa.String(length=32), nullable=True))
    op.add_column("estimates", sa.Column("work_stage_title", sa.Text(), nullable=True))
    op.add_column("estimates", sa.Column("stage_occurrence_index", sa.Integer(), nullable=True))
    op.add_column("estimates", sa.Column("stage_occurrence_label", sa.Text(), nullable=True))
    op.add_column("estimates", sa.Column("stage_options_mode", sa.String(length=32), nullable=True))
    op.add_column("estimates", sa.Column("stage_option_id", sa.Text(), nullable=True))
    op.add_column("estimates", sa.Column("stage_option_title", sa.Text(), nullable=True))
    op.add_column("estimates", sa.Column("section_id", sa.Text(), nullable=True))
    op.add_column("estimates", sa.Column("subtype_id", sa.Text(), nullable=True))
    op.add_column("estimates", sa.Column("row_role", sa.String(length=32), nullable=True))
    op.add_column("estimates", sa.Column("parent_row_id", postgresql.UUID(as_uuid=False), nullable=True))
    op.add_column("estimates", sa.Column("inherited_from_row_id", postgresql.UUID(as_uuid=False), nullable=True))
    op.add_column("estimates", sa.Column("stage_confidence", sa.String(length=16), nullable=True))
    op.add_column("estimates", sa.Column("work_type_confidence", sa.String(length=16), nullable=True))
    op.add_column("estimates", sa.Column("autofill_enabled", sa.Boolean(), nullable=True))
    op.add_column("estimates", sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("estimates", sa.Column("review_reason", sa.Text(), nullable=True))
    op.add_column("estimates", sa.Column("stage_match_type", sa.String(length=64), nullable=True))
    op.add_column("estimates", sa.Column("stage_match_score_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("estimates", sa.Column("work_type_match_score_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("estimates", sa.Column("prompt_version", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("estimates", "prompt_version")
    op.drop_column("estimates", "work_type_match_score_json")
    op.drop_column("estimates", "stage_match_score_json")
    op.drop_column("estimates", "stage_match_type")
    op.drop_column("estimates", "review_reason")
    op.drop_column("estimates", "needs_review")
    op.drop_column("estimates", "autofill_enabled")
    op.drop_column("estimates", "work_type_confidence")
    op.drop_column("estimates", "stage_confidence")
    op.drop_column("estimates", "inherited_from_row_id")
    op.drop_column("estimates", "parent_row_id")
    op.drop_column("estimates", "row_role")
    op.drop_column("estimates", "subtype_id")
    op.drop_column("estimates", "section_id")
    op.drop_column("estimates", "stage_option_title")
    op.drop_column("estimates", "stage_option_id")
    op.drop_column("estimates", "stage_options_mode")
    op.drop_column("estimates", "stage_occurrence_label")
    op.drop_column("estimates", "stage_occurrence_index")
    op.drop_column("estimates", "work_stage_title")
    op.drop_column("estimates", "work_stage_number")
    op.drop_column("estimates", "canonical_stage_id")
    op.drop_column("estimates", "project_variant_number")
    op.drop_column("estimates", "project_variant_id")
    op.drop_column("estimates", "estimate_type_number")
    op.drop_column("estimates", "estimate_type_id")
