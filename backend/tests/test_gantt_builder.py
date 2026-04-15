from datetime import date
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.gantt_builder import GanttBuilder


def _estimate(
    estimate_id: str,
    row_order: int,
    section: str | None,
    work_name: str,
):
    return SimpleNamespace(
        id=estimate_id,
        row_order=row_order,
        section=section,
        work_name=work_name,
        quantity=1,
        total_price=1000,
        labor_hours=None,
    )


def test_build_keeps_repeated_section_runs_as_separate_gantt_groups():
    builder = GanttBuilder()
    estimates = [
        _estimate("est-1", 0, "Отделка", "Штукатурка"),
        _estimate("est-2", 1, "Отделка", "Шпаклевка"),
        _estimate("est-3", 2, "Электрика", "Прокладка кабеля"),
        _estimate("est-4", 3, "Отделка", "Покраска"),
    ]

    tasks = builder.build(
        project_id="project-1",
        estimates=estimates,
        start_date=date(2026, 4, 15),
        workers=3,
    )

    group_tasks = [task for task in tasks if task.is_group]
    leaf_tasks = [task for task in tasks if not task.is_group]

    assert [task.name for task in group_tasks] == ["Отделка", "Электрика", "Отделка"]
    assert len(group_tasks) == 3
    assert leaf_tasks[0].parent_id == group_tasks[0].id
    assert leaf_tasks[1].parent_id == group_tasks[0].id
    assert leaf_tasks[2].parent_id == group_tasks[1].id
    assert leaf_tasks[3].parent_id == group_tasks[2].id


def test_build_groups_consecutive_rows_without_section_into_single_fallback_group():
    builder = GanttBuilder()
    estimates = [
        _estimate("est-1", 0, None, "Работа 1"),
        _estimate("est-2", 1, "", "Работа 2"),
        _estimate("est-3", 2, "Фундамент", "Работа 3"),
    ]

    tasks = builder.build(
        project_id="project-1",
        estimates=estimates,
        start_date=date(2026, 4, 15),
        workers=3,
    )

    group_tasks = [task for task in tasks if task.is_group]

    assert [task.name for task in group_tasks] == ["Прочие работы", "Фундамент"]
