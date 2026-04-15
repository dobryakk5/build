from pathlib import Path
from datetime import date
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))


@pytest.mark.asyncio
async def test_enrich_task_returns_fer_labor_hours_scaled_by_quantity():
    from app.api.routes.gantt import _enrich_task

    task = SimpleNamespace(
        id="task-1",
        project_id="project-1",
        estimate_batch_id="batch-1",
        parent_id=None,
        estimate_id="estimate-1",
        name="Разработка грунта",
        start_date=date(2026, 4, 1),
        working_days=3,
        workers_count=2,
        labor_hours=18,
        hours_per_day=8,
        is_group=False,
        progress=0,
        type="task",
        color="#3b82f6",
        requires_act=False,
        act_signed=False,
        row_order=1000,
        assignee_id=None,
    )
    estimate = SimpleNamespace(
        fer_words_human_hours=2.5,
        quantity=4,
        req_hidden_work_act=False,
        req_intermediate_act=False,
        req_ks2_ks3=False,
        materials=[],
    )

    db = AsyncMock()
    db.scalars = AsyncMock(return_value=[])
    db.scalar = AsyncMock(return_value=0)
    db.get = AsyncMock(side_effect=[estimate])

    result = await _enrich_task(task, db)

    assert result.fer_labor_hours == 10.0


@pytest.mark.asyncio
async def test_enrich_task_returns_null_fer_labor_hours_without_mapping():
    from app.api.routes.gantt import _enrich_task

    task = SimpleNamespace(
        id="task-1",
        project_id="project-1",
        estimate_batch_id="batch-1",
        parent_id=None,
        estimate_id="estimate-1",
        name="Разработка грунта",
        start_date=date(2026, 4, 1),
        working_days=3,
        workers_count=2,
        labor_hours=18,
        hours_per_day=8,
        is_group=False,
        progress=0,
        type="task",
        color="#3b82f6",
        requires_act=False,
        act_signed=False,
        row_order=1000,
        assignee_id=None,
    )
    estimate = SimpleNamespace(
        fer_words_human_hours=None,
        quantity=4,
        req_hidden_work_act=False,
        req_intermediate_act=False,
        req_ks2_ks3=False,
        materials=[],
    )

    db = AsyncMock()
    db.scalars = AsyncMock(return_value=[])
    db.scalar = AsyncMock(return_value=0)
    db.get = AsyncMock(side_effect=[estimate])

    result = await _enrich_task(task, db)

    assert result.fer_labor_hours is None
