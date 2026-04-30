from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))


def _mapping_result(row):
    result = MagicMock()
    mappings = MagicMock()
    mappings.first.return_value = row
    result.mappings.return_value = mappings
    return result


def _scalar_list(items):
    class _ScalarResult:
        def __iter__(self):
            return iter(items)

    return _ScalarResult()


@pytest.mark.asyncio
async def test_update_estimate_batch_workers_saves_count(monkeypatch):
    from app.api.routes.estimates import EstimateBatchWorkersUpdate, update_estimate_batch_workers

    batch = SimpleNamespace(
        id="batch-1",
        project_id="project-1",
        deleted_at=None,
        workers_count=3,
    )
    task = SimpleNamespace(
        workers_count=3,
        labor_hours=80,
        hours_per_day=8,
        working_days=4,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=batch)
    db.scalars = AsyncMock(return_value=[task])
    resolve_dates = AsyncMock(return_value=[])
    monkeypatch.setattr("app.api.routes.estimates.resolve_project_dates", resolve_dates)

    result = await update_estimate_batch_workers(
        "project-1",
        "batch-1",
        EstimateBatchWorkersUpdate(workers_count=7),
        member=object(),
        db=db,
    )

    assert batch.workers_count == 7
    assert task.workers_count == 7
    assert task.working_days == 2
    assert result == {"id": "batch-1", "workers_count": 7, "updated_gantt_tasks_count": 1}
    db.flush.assert_awaited_once()
    resolve_dates.assert_awaited_once_with("project-1", db)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_estimate_batch_schedule_saves_workers_and_hours(monkeypatch):
    from app.api.routes.estimates import EstimateBatchScheduleUpdate, update_estimate_batch_schedule

    batch = SimpleNamespace(
        id="batch-1",
        project_id="project-1",
        deleted_at=None,
        workers_count=3,
        hours_per_day=8,
    )
    task = SimpleNamespace(
        workers_count=3,
        labor_hours=80,
        hours_per_day=8,
        working_days=4,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=batch)
    db.scalars = AsyncMock(return_value=[task])
    resolve_dates = AsyncMock(return_value=[])
    monkeypatch.setattr("app.api.routes.estimates.resolve_project_dates", resolve_dates)

    result = await update_estimate_batch_schedule(
        "project-1",
        "batch-1",
        EstimateBatchScheduleUpdate(workers_count=5, hours_per_day=10),
        member=object(),
        db=db,
    )

    assert batch.workers_count == 5
    assert float(batch.hours_per_day) == 10
    assert task.workers_count == 5
    assert float(task.hours_per_day) == 10
    assert task.working_days == 2
    assert result == {"id": "batch-1", "workers_count": 5, "hours_per_day": 10.0, "updated_gantt_tasks_count": 1}
    db.flush.assert_awaited_once()
    resolve_dates.assert_awaited_once_with("project-1", db)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_estimate_fer_assigns_manual_override():
    from app.api.routes.estimates import FerMappingUpdate, update_estimate_fer

    estimate = SimpleNamespace(
        id="est-1",
        project_id="project-1",
        deleted_at=None,
        fer_table_id=None,
        fer_work_type=None,
        fer_match_score=None,
        fer_matched_at=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=estimate)
    db.execute = AsyncMock(return_value=_mapping_result({
        "id": 77,
        "table_title": "Монтаж металлических конструкций",
        "common_work_name": "Монтаж каркаса",
    }))

    payload = FerMappingUpdate(fer_table_id=77)
    result = await update_estimate_fer("project-1", "est-1", payload, member=object(), db=db)

    assert estimate.fer_table_id == 77
    assert estimate.fer_work_type == "Монтаж каркаса"
    assert float(estimate.fer_match_score) == 1.0
    assert estimate.fer_matched_at is not None
    assert result["fer_table_id"] == 77
    assert result["fer_work_type"] == "Монтаж каркаса"


@pytest.mark.asyncio
async def test_update_estimate_fer_resets_mapping():
    from app.api.routes.estimates import FerMappingUpdate, update_estimate_fer

    estimate = SimpleNamespace(
        id="est-1",
        project_id="project-1",
        deleted_at=None,
        fer_table_id=77,
        fer_work_type="Монтаж каркаса",
        fer_match_score=1.0,
        fer_matched_at="2024-01-01T00:00:00",
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=estimate)

    result = await update_estimate_fer("project-1", "est-1", FerMappingUpdate(fer_table_id=None), member=object(), db=db)

    assert estimate.fer_table_id is None
    assert estimate.fer_work_type is None
    assert estimate.fer_match_score is None
    assert estimate.fer_matched_at is None
    assert result["fer_table_id"] is None


@pytest.mark.asyncio
async def test_update_estimate_fer_rejects_estimate_from_other_project():
    from fastapi import HTTPException
    from app.api.routes.estimates import FerMappingUpdate, update_estimate_fer

    estimate = SimpleNamespace(
        id="est-1",
        project_id="project-2",
        deleted_at=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=estimate)

    with pytest.raises(HTTPException) as exc:
        await update_estimate_fer("project-1", "est-1", FerMappingUpdate(fer_table_id=10), member=object(), db=db)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_estimate_fer_rejects_missing_table():
    from fastapi import HTTPException
    from app.api.routes.estimates import FerMappingUpdate, update_estimate_fer

    estimate = SimpleNamespace(
        id="est-1",
        project_id="project-1",
        deleted_at=None,
        fer_table_id=None,
        fer_work_type=None,
        fer_match_score=None,
        fer_matched_at=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=estimate)
    db.execute = AsyncMock(return_value=_mapping_result(None))

    with pytest.raises(HTTPException) as exc:
        await update_estimate_fer("project-1", "est-1", FerMappingUpdate(fer_table_id=999), member=object(), db=db)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_estimate_fer_rejects_ignored_table():
    from fastapi import HTTPException
    from app.api.routes.estimates import FerMappingUpdate, update_estimate_fer

    estimate = SimpleNamespace(
        id="est-1",
        project_id="project-1",
        deleted_at=None,
        fer_table_id=None,
        fer_work_type=None,
        fer_match_score=None,
        fer_matched_at=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=estimate)
    db.execute = AsyncMock(
        return_value=_mapping_result(
            {
                "id": 77,
                "table_title": "Монтаж металлических конструкций",
                "common_work_name": "Монтаж каркаса",
                "effective_ignored": True,
            }
        )
    )

    with pytest.raises(HTTPException) as exc:
        await update_estimate_fer("project-1", "est-1", FerMappingUpdate(fer_table_id=77), member=object(), db=db)

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_estimate_mechanism_creates_manual_row():
    from app.api.routes.estimates import MechanismCreateRequest, create_estimate_mechanism

    batch_id = "00000000-0000-0000-0000-000000000001"
    batch = SimpleNamespace(
        id=batch_id,
        project_id="project-1",
        deleted_at=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=batch)
    db.scalar = AsyncMock(return_value=4)
    db.add = MagicMock()

    result = await create_estimate_mechanism(
        "project-1",
        MechanismCreateRequest(
            estimate_batch_id=batch_id,
            section="Кровля",
            name="Автовышка",
            unit="смена",
            quantity=2,
            unit_price=15000,
        ),
        member=object(),
        db=db,
    )

    created = db.add.call_args.args[0]
    assert created.estimate_batch_id == batch_id
    assert created.section == "Кровля"
    assert created.work_name == "Автовышка"
    assert created.raw_data == {"item_type": "mechanism"}
    assert float(created.total_price) == 30000
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(created)
    assert result is created


@pytest.mark.asyncio
async def test_delete_estimate_mechanism_soft_deletes_row():
    from app.api.routes.estimates import delete_estimate_mechanism

    mechanism = SimpleNamespace(
        id="est-1",
        project_id="project-1",
        deleted_at=None,
        raw_data={"item_type": "mechanism"},
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=mechanism)

    await delete_estimate_mechanism("project-1", "est-1", member=object(), db=db)

    assert mechanism.deleted_at is not None
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_estimate_summary_ignores_mechanism_rows():
    from app.api.routes.estimates import estimate_summary

    db = AsyncMock()
    db.scalars = AsyncMock(
        return_value=_scalar_list(
            [
                SimpleNamespace(section="Кровля", total_price=1000, raw_data=None),
                SimpleNamespace(section="Кровля", total_price=500, raw_data={"item_type": "mechanism"}),
                SimpleNamespace(section="Кровля", total_price=2000, raw_data=None),
            ]
        )
    )

    result = await estimate_summary("project-1", estimate_batch_id=None, member=object(), db=db)

    assert result.total == 3000
    assert result.sections == [{"name": "Кровля", "subtotal": 3000.0, "items": 2}]
