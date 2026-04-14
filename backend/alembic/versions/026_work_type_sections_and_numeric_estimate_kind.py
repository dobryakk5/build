"""
026_work_type_sections_and_numeric_estimate_kind.py
Добавляет fer.work_type_sections и переводит estimate_kind в smallint (1..9).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "026"
down_revision = "025_fer_words_dictionary"
branch_labels = None
depends_on = None

FER_SCHEMA = "fer"


def upgrade():
    op.create_table(
        "work_type_sections",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("work_name", sa.Text(), nullable=False),
        sa.Column("section_ids", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.UniqueConstraint("work_name", name="uq_fer_work_type_sections_work_name"),
        schema=FER_SCHEMA,
    )

    op.execute(
        sa.text(
            f"""
            INSERT INTO {FER_SCHEMA}.work_type_sections (id, work_name, section_ids) VALUES
            (1, 'земляные грунтовые работы', '{{1}}'),
            (2, 'строительство жилого помещения', '{{1,4,5,6,7,8,9,10,11,12,13,15,16,17,18,19,20,21,26}}'),
            (3, 'строительство нежилого помещения', '{{1,4,5,6,7,8,9,10,11,12,13,15,16,17,18,19,20,21,22,23,26}}'),
            (4, 'реконструкция нежилого помещения', '{{1,4,6,7,8,9,10,11,12,13,15,16,17,18,19,20,21,22,23,24,26,46}}'),
            (5, 'отделка жилого помещения', '{{11,13,15,16,17,18,19,20,26}}'),
            (6, 'отделка нежилого помещения', '{{11,13,15,16,17,18,19,20,26}}'),
            (7, 'инженерные работы внутренние', '{{16,17,18,19,20}}'),
            (8, 'инженерные работы наружные', '{{1,4,5,6,7,22,23,26}}'),
            (9, 'ландшафтные работы', '{{1,47}}')
            """
        )
    )

    op.alter_column(
        "estimate_batches",
        "estimate_kind",
        existing_type=sa.String(length=32),
        server_default=None,
    )
    op.alter_column(
        "estimate_batches",
        "estimate_kind",
        existing_type=sa.String(length=32),
        type_=sa.SmallInteger(),
        postgresql_using="""
        CASE estimate_kind
            WHEN 'country_house' THEN 2
            WHEN 'apartment' THEN 2
            WHEN 'non_residential' THEN 3
            ELSE 3
        END
        """,
    )


def downgrade():
    op.alter_column(
        "estimate_batches",
        "estimate_kind",
        existing_type=sa.SmallInteger(),
        type_=sa.String(length=32),
        postgresql_using="""
        CASE
            WHEN estimate_kind IN (2, 5, 7) THEN 'apartment'
            WHEN estimate_kind IN (1, 9) THEN 'country_house'
            ELSE 'non_residential'
        END
        """,
        server_default="non_residential",
    )

    op.drop_table("work_type_sections", schema=FER_SCHEMA)
