from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))


@pytest.mark.asyncio
async def test_match_estimate_fer_vector_updates_row_from_match(monkeypatch):
    from app.api.routes.estimates import match_estimate_fer_vector
    from app.services.estimate_fer_matcher import MatchResult

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
    monkeypatch.setattr(
        "app.api.routes.estimates.match_estimate_with_vector",
        AsyncMock(return_value=MatchResult(table_id=55, work_type="Разработка грунта", score=0.81)),
    )

    result = await match_estimate_fer_vector("project-1", "est-1", member=object(), db=db)

    assert result["fer_table_id"] == 55
    assert result["fer_work_type"] == "Разработка грунта"
    assert result["fer_match_score"] == 0.81
