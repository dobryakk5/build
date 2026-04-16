from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))


@pytest.mark.asyncio
async def test_import_fer_knowledge_batch_returns_404_for_missing_batch():
    from fastapi import HTTPException
    from app.services.fer_match_examples_service import import_fer_knowledge_batch

    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await import_fer_knowledge_batch(batch_id="missing-batch", admin_user_id="admin-1", db=db)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_import_fer_knowledge_batch_returns_no_matched_rows_when_batch_empty():
    from app.services.fer_match_examples_service import import_fer_knowledge_batch

    db = MagicMock()
    db.scalar = AsyncMock(return_value=SimpleNamespace(id="batch-1", project_id="project-1", name="Batch"))
    db.scalars = AsyncMock(return_value=[])

    result = await import_fer_knowledge_batch(batch_id="batch-1", admin_user_id="admin-1", db=db)

    assert result == {
        "batch_id": "batch-1",
        "total_matched_rows": 0,
        "imported_count": 0,
        "skipped_duplicates": 0,
        "embedding_job_id": None,
        "status": "no_matched_rows",
        "reason": "no_matched_rows",
    }


@pytest.mark.asyncio
async def test_import_fer_knowledge_batch_skips_duplicates_without_creating_job(monkeypatch):
    from app.services.fer_match_examples_service import import_fer_knowledge_batch

    db = MagicMock()
    db.scalar = AsyncMock(return_value=SimpleNamespace(id="batch-1", project_id="project-1", name="Batch"))
    db.scalars = AsyncMock(
        return_value=[
            SimpleNamespace(work_name="Кладка стен", fer_table_id=101, fer_work_type="Кладка стен", row_order=1, id="e-1"),
            SimpleNamespace(work_name="Монтаж каркаса", fer_table_id=102, fer_work_type="Монтаж каркаса", row_order=2, id="e-2"),
        ]
    )
    monkeypatch.setattr(
        "app.services.fer_match_examples_service._insert_fer_match_examples",
        AsyncMock(return_value=[]),
    )

    result = await import_fer_knowledge_batch(batch_id="batch-1", admin_user_id="admin-1", db=db)

    assert result == {
        "batch_id": "batch-1",
        "total_matched_rows": 2,
        "imported_count": 0,
        "skipped_duplicates": 2,
        "embedding_job_id": None,
        "status": "already_imported",
    }
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_import_fer_knowledge_batch_creates_job_for_new_rows(monkeypatch):
    from app.services.fer_match_examples_service import import_fer_knowledge_batch

    db = MagicMock()
    db.scalar = AsyncMock(return_value=SimpleNamespace(id="batch-1", project_id="project-1", name="Batch"))
    db.scalars = AsyncMock(
        return_value=[
            SimpleNamespace(work_name="Кладка стен", fer_table_id=101, fer_work_type="Кладка стен", row_order=1, id="e-1"),
            SimpleNamespace(work_name="Монтаж каркаса", fer_table_id=102, fer_work_type="Монтаж каркаса", row_order=2, id="e-2"),
        ]
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    monkeypatch.setattr(
        "app.services.fer_match_examples_service._insert_fer_match_examples",
        AsyncMock(return_value=[11, 12]),
    )

    task_calls: list[object] = []

    def fake_create_task(coro):
        task_calls.append(coro)
        coro.close()
        return MagicMock()

    monkeypatch.setattr("app.services.fer_match_examples_service.asyncio.create_task", fake_create_task)

    result = await import_fer_knowledge_batch(batch_id="batch-1", admin_user_id="admin-1", db=db)

    assert result["batch_id"] == "batch-1"
    assert result["total_matched_rows"] == 2
    assert result["imported_count"] == 2
    assert result["skipped_duplicates"] == 0
    assert result["status"] == "import_queued"
    assert result["embedding_job_id"]
    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once()
    assert len(task_calls) == 1
