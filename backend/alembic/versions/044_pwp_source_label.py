"""
044_pwp_source_label.py
В project_work_plan добавляем source_label — исходный текст из строки сметы
(estimate.work_name). Показывается на карточке как primary заголовок,
NW тип идёт ниже мелким шрифтом.

С этой миграции меняется логика auto_create — 1 строка сметы = 1 карточка
(больше не агрегируем).
"""

from alembic import op
import sqlalchemy as sa


revision = "044_pwp_source_label"
down_revision = "043_pwp_fer_row_id"
branch_labels = None
depends_on = None

FER_SCHEMA = "fer"


def upgrade():
    op.add_column(
        "project_work_plan",
        sa.Column("source_label", sa.Text(), nullable=True),
        schema=FER_SCHEMA,
    )
    op.add_column(
        "project_work_plan",
        sa.Column("source_section", sa.Text(), nullable=True),
        schema=FER_SCHEMA,
    )


def downgrade():
    op.drop_column("project_work_plan", "source_section", schema=FER_SCHEMA)
    op.drop_column("project_work_plan", "source_label", schema=FER_SCHEMA)
