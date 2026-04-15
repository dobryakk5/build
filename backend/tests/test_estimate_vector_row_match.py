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


@pytest.mark.asyncio
async def test_match_estimate_fer_group_vector_updates_row_from_match(monkeypatch):
    from app.api.routes.estimates import match_estimate_fer_group_vector
    from app.services.estimate_fer_matcher import GroupMatchResult, FerGroupCandidate

    estimate = SimpleNamespace(
        id="est-2",
        project_id="project-1",
        deleted_at=None,
        fer_group_kind=None,
        fer_group_ref_id=None,
        fer_group_title=None,
        fer_group_collection_id=None,
        fer_group_collection_num=None,
        fer_group_collection_name=None,
        fer_group_match_score=None,
        fer_group_matched_at=None,
        fer_group_is_ambiguous=False,
        fer_group_candidates=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=estimate)
    monkeypatch.setattr(
        "app.api.routes.estimates.match_estimate_group_with_vector",
        AsyncMock(
            return_value=GroupMatchResult(
                kind="collection",
                ref_id=8,
                title="Сборник 08. Конструкции из кирпича",
                collection_id=8,
                collection_num="08",
                collection_name="Конструкции из кирпича",
                score=0.54,
                is_ambiguous=True,
                candidates=[
                    FerGroupCandidate("collection", 8, "Сборник 08. Конструкции из кирпича", 8, "08", "Конструкции из кирпича", 0.54),
                ],
                no_match=False,
            )
        ),
    )
    monkeypatch.setattr(
        "app.api.routes.estimates._load_group_estimates",
        AsyncMock(return_value=[estimate]),
    )

    result = await match_estimate_fer_group_vector("project-1", "est-2", member=object(), db=db)

    assert result["fer_group_kind"] == "collection"
    assert result["fer_group_ref_id"] == 8
    assert result["fer_group_is_ambiguous"] is True
    assert result["no_match"] is False
    assert result["updated_rows_count"] == 1


@pytest.mark.asyncio
async def test_confirm_estimate_fer_group_confirms_existing_candidate(monkeypatch):
    from app.api.routes.estimates import FerGroupConfirmUpdate, confirm_estimate_fer_group

    estimate = SimpleNamespace(
        id="est-3",
        project_id="project-1",
        deleted_at=None,
        fer_group_kind="collection",
        fer_group_ref_id=8,
        fer_group_title="Сборник 08. Конструкции из кирпича",
        fer_group_collection_id=8,
        fer_group_collection_num="08",
        fer_group_collection_name="Конструкции из кирпича",
        fer_group_match_score=0.54,
        fer_group_matched_at=None,
        fer_group_is_ambiguous=True,
        fer_group_candidates=[
            {
                "kind": "collection",
                "ref_id": 8,
                "title": "Сборник 08. Конструкции из кирпича",
                "collection_id": 8,
                "collection_num": "08",
                "collection_name": "Конструкции из кирпича",
                "score": 0.54,
            }
        ],
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=estimate)
    monkeypatch.setattr(
        "app.api.routes.estimates._load_group_estimates",
        AsyncMock(return_value=[estimate]),
    )

    result = await confirm_estimate_fer_group(
        "project-1",
        "est-3",
        FerGroupConfirmUpdate(kind="collection", ref_id=8),
        member=object(),
        db=db,
    )

    assert result["fer_group_kind"] == "collection"
    assert result["fer_group_ref_id"] == 8
    assert result["fer_group_is_ambiguous"] is False
    assert result["fer_group_candidates"] is None
    assert result["updated_rows_count"] == 1


@pytest.mark.asyncio
async def test_get_estimate_fer_group_options_returns_allowed_structure(monkeypatch):
    from app.api.routes.estimates import get_estimate_fer_group_options

    estimate = SimpleNamespace(
        id="est-4",
        project_id="project-1",
        deleted_at=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=estimate)
    monkeypatch.setattr(
        "app.api.routes.estimates.get_manual_group_options",
        AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "num": "01",
                    "name": "Земляные работы",
                    "sections": [{"id": 1, "title": "Раздел 1"}],
                }
            ]
        ),
    )

    result = await get_estimate_fer_group_options("project-1", "est-4", member=object(), db=db)

    assert result["collections"][0]["id"] == 1
    assert result["collections"][0]["sections"][0]["id"] == 1


@pytest.mark.asyncio
async def test_update_estimate_fer_group_manual_applies_selection(monkeypatch):
    from app.api.routes.estimates import FerGroupConfirmUpdate, update_estimate_fer_group_manual
    from app.services.estimate_fer_matcher import GroupMatchResult

    estimate = SimpleNamespace(
        id="est-5",
        project_id="project-1",
        deleted_at=None,
        fer_group_kind=None,
        fer_group_ref_id=None,
        fer_group_title=None,
        fer_group_collection_id=None,
        fer_group_collection_num=None,
        fer_group_collection_name=None,
        fer_group_match_score=None,
        fer_group_matched_at=None,
        fer_group_is_ambiguous=False,
        fer_group_candidates=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=estimate)
    monkeypatch.setattr(
        "app.api.routes.estimates._load_group_estimates",
        AsyncMock(return_value=[estimate]),
    )
    monkeypatch.setattr(
        "app.api.routes.estimates.resolve_manual_group_match",
        AsyncMock(
            return_value=GroupMatchResult(
                kind="section",
                ref_id=1,
                title="Раздел 1. Земляные работы",
                collection_id=1,
                collection_num="01",
                collection_name="Земляные работы",
                score=1.0,
                is_ambiguous=False,
                candidates=None,
                no_match=False,
            )
        ),
    )

    result = await update_estimate_fer_group_manual(
        "project-1",
        "est-5",
        FerGroupConfirmUpdate(kind="section", ref_id=1),
        member=object(),
        db=db,
    )

    assert result["fer_group_kind"] == "section"
    assert result["fer_group_ref_id"] == 1
    assert result["updated_rows_count"] == 1
