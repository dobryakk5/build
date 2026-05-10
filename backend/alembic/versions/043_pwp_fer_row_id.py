"""
043_pwp_fer_row_id.py
В project_work_plan добавляем fer_row_id — конкретная строка из fer.fer_rows
выбранная для расчёта длительности (вместо AVG по всем строкам ФЕР таблицы).
"""

from alembic import op
import sqlalchemy as sa


revision = "043_pwp_fer_row_id"
down_revision = "042_project_work_plan"
branch_labels = None
depends_on = None

FER_SCHEMA = "fer"


def upgrade():
    op.add_column(
        "project_work_plan",
        sa.Column("fer_row_id", sa.Integer(), nullable=True),
        schema=FER_SCHEMA,
    )
    # FK без CASCADE — если строку удалят, оставим карточку с null
    op.create_foreign_key(
        "fk_pwp_fer_row",
        "project_work_plan", "fer_rows",
        ["fer_row_id"], ["id"],
        source_schema=FER_SCHEMA, referent_schema=FER_SCHEMA,
        ondelete="SET NULL",
    )
    op.create_index("ix_pwp_fer_row", "project_work_plan", ["fer_row_id"], schema=FER_SCHEMA)


def downgrade():
    op.drop_index("ix_pwp_fer_row", table_name="project_work_plan", schema=FER_SCHEMA)
    op.drop_constraint("fk_pwp_fer_row", "project_work_plan", schema=FER_SCHEMA, type_="foreignkey")
    op.drop_column("project_work_plan", "fer_row_id", schema=FER_SCHEMA)
