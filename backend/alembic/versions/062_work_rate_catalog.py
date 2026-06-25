"""Create work-rate catalog tables."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "062_work_rate_catalog"
down_revision = "061_work_tax_v6_4_2_seed"
branch_labels = None
depends_on = None


def _execute_sql_script(sql: str) -> None:
    without_line_comments = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )
    for statement in without_line_comments.split(";"):
        stripped = statement.strip()
        if stripped:
            op.execute(stripped)


def upgrade() -> None:
    sql_path = Path(__file__).with_name("062_work_rate_catalog.sql")
    _execute_sql_script(sql_path.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS work_rate_item_assignments")
    op.execute("DROP TABLE IF EXISTS work_rate_unit_aliases")
    op.execute("DROP TABLE IF EXISTS work_rate_import_runs")
    op.execute("DROP TABLE IF EXISTS work_rate_package_components")
    op.execute("DROP TABLE IF EXISTS work_rate_mappings")
    op.execute("DROP TABLE IF EXISTS work_rate_items")
    op.execute("DROP TABLE IF EXISTS work_rate_sources")
