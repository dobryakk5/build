"""
042_project_work_plan.py
План работ проекта (КТП) — основная сущность для построения графика работ.

Архитектура:
  estimate_batch (загруженная смета, readonly)
       │
       ▼
  project_work_plan (детальные карточки работ — наш продукт)
       │
       ├─ project_work_plan_estimate_link (откуда взяты объёмы из сметы)
       └─ self.parent_id (декомпозиция: дом-под-ключ → подкарточки)

В смете НИЧЕГО не меняется — она остаётся источником данных.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "042_project_work_plan"
down_revision = "041_nw_reclassify_v2"
branch_labels = None
depends_on = None

FER_SCHEMA = "fer"


def upgrade():
    op.create_table(
        "project_work_plan",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "estimate_batch_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("estimate_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Декомпозиция: NW-021 «дом под ключ» → подкарточки (parent_id ссылается на родителя)
        sa.Column(
            "parent_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{FER_SCHEMA}.project_work_plan.id", ondelete="CASCADE"),
            nullable=True,
        ),

        # ── ЧТО (NW + конкретизация атрибутов из справочников) ──
        sa.Column(
            "nw_item_code",
            sa.String(length=10),
            sa.ForeignKey(f"{FER_SCHEMA}.nw_item.code", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("object_type_code",         sa.String(length=10), nullable=True),
        sa.Column("building_technology_code", sa.String(length=10), nullable=True),
        sa.Column("location_scope_code",      sa.String(length=10), nullable=True),
        sa.Column("stage_code",               sa.String(length=10), nullable=True),
        sa.Column("is_capital_repair",        sa.Boolean(),         nullable=True),

        # ── СКОЛЬКО (объём из сметы или ручной) ──
        sa.Column("unit",     sa.String(length=20),  nullable=True),
        sa.Column("quantity", sa.Numeric(12, 3),     nullable=True),

        # ── ЗА СКОЛЬКО (ФЕР, шаг 4 — пока NULL, заполняется отдельным сервисом) ──
        sa.Column("fer_table_id",         sa.BigInteger(),     nullable=True),
        sa.Column("fer_match_score",      sa.Numeric(5, 4),    nullable=True),
        sa.Column("fer_match_source",     sa.String(length=16), nullable=True),  # auto/llm/manual
        sa.Column("fer_candidates",       postgresql.JSONB(),  nullable=True),
        sa.Column("fer_matched_at",       sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("human_hours_per_unit", sa.Numeric(12, 3),   nullable=True),

        # ── КОГДА (шаг 5 — рассчитывается отдельно) ──
        sa.Column("workers_count", sa.SmallInteger(),  nullable=True),
        sa.Column("duration_days", sa.Numeric(8, 2),   nullable=True),

        # ── СТАТУС ──
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="auto_proposed",
        ),

        # ── МЕТА ──
        sa.Column("notes",      sa.Text(),                                 nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),

        sa.CheckConstraint(
            "status IN ('auto_proposed','confirmed','removed','custom_added',"
            "'fer_mapped','scheduled','needs_volume','needs_review')",
            name="ck_pwp_status",
        ),
        schema=FER_SCHEMA,
    )
    op.create_index("ix_pwp_batch",     "project_work_plan", ["estimate_batch_id"], schema=FER_SCHEMA)
    op.create_index("ix_pwp_nw",        "project_work_plan", ["nw_item_code"],      schema=FER_SCHEMA)
    op.create_index("ix_pwp_parent",    "project_work_plan", ["parent_id"],         schema=FER_SCHEMA)
    op.create_index("ix_pwp_fer_table", "project_work_plan", ["fer_table_id"],      schema=FER_SCHEMA)
    op.create_index("ix_pwp_status",    "project_work_plan", ["status"],            schema=FER_SCHEMA)

    # Связь карточка плана ↔ строки сметы (traceability «откуда объём»)
    op.create_table(
        "project_work_plan_estimate_link",
        sa.Column(
            "plan_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{FER_SCHEMA}.project_work_plan.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "estimate_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("estimates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "share",
            sa.Numeric(5, 4),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
        sa.PrimaryKeyConstraint("plan_id", "estimate_id"),
        schema=FER_SCHEMA,
    )
    op.create_index(
        "ix_pwp_link_estimate",
        "project_work_plan_estimate_link",
        ["estimate_id"],
        schema=FER_SCHEMA,
    )


def downgrade():
    op.drop_index("ix_pwp_link_estimate",
                  table_name="project_work_plan_estimate_link",
                  schema=FER_SCHEMA)
    op.drop_table("project_work_plan_estimate_link", schema=FER_SCHEMA)

    for ix in ("ix_pwp_status", "ix_pwp_fer_table", "ix_pwp_parent", "ix_pwp_nw", "ix_pwp_batch"):
        op.drop_index(ix, table_name="project_work_plan", schema=FER_SCHEMA)
    op.drop_table("project_work_plan", schema=FER_SCHEMA)
