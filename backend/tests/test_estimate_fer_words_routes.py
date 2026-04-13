from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))


@pytest.mark.asyncio
async def test_update_estimate_fer_words_assigns_selected_entry(monkeypatch):
    from app.api.routes.estimates import FerWordsMappingUpdate, update_estimate_fer_words

    estimate = SimpleNamespace(
        id="est-1",
        project_id="project-1",
        deleted_at=None,
        fer_words_entry_id=None,
        fer_words_code=None,
        fer_words_name=None,
        fer_words_human_hours=None,
        fer_words_machine_hours=None,
        fer_words_match_score=None,
        fer_words_match_count=None,
        fer_words_matched_at=None,
        work_name="Разработка грунта экскаватором",
        section=None,
        unit="м3",
    )
    entry = SimpleNamespace(
        id=77,
        fer_code="01.01.006",
        display_name="Разработка грунта · отвал · котлован",
        search_tokens=["разработка", "грунта", "отвал", "котлован"],
        human_hours=0,
        machine_hours=29,
    )
    db = AsyncMock()
    db.get = AsyncMock(side_effect=[estimate, entry])

    monkeypatch.setattr(
        "app.api.routes.estimates.build_fer_words_candidate_for_entry",
        lambda estimate_text, selected_entry: SimpleNamespace(
            entry_id=selected_entry.id,
            fer_code=selected_entry.fer_code,
            display_name=selected_entry.display_name,
            human_hours=0,
            machine_hours=29,
            matched_tokens=3,
            exact_matches=2,
            numeric_matches=0,
            average_ratio=0.92,
            score=3.0,
        ),
    )

    result = await update_estimate_fer_words(
        "project-1",
        "est-1",
        FerWordsMappingUpdate(entry_id=77),
        member=object(),
        db=db,
    )

    assert result["fer_words_entry_id"] == 77
    assert result["fer_words_code"] == "01.01.006"
    assert result["fer_words_match_count"] == 3


@pytest.mark.asyncio
async def test_update_estimate_fer_words_resets_mapping():
    from app.api.routes.estimates import FerWordsMappingUpdate, update_estimate_fer_words

    estimate = SimpleNamespace(
        id="est-1",
        project_id="project-1",
        deleted_at=None,
        fer_words_entry_id=77,
        fer_words_code="01.01.006",
        fer_words_name="Разработка грунта",
        fer_words_human_hours=0,
        fer_words_machine_hours=29,
        fer_words_match_score=0.92,
        fer_words_match_count=3,
        fer_words_matched_at="2024-01-01T00:00:00",
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=estimate)

    result = await update_estimate_fer_words(
        "project-1",
        "est-1",
        FerWordsMappingUpdate(entry_id=None),
        member=object(),
        db=db,
    )

    assert result["fer_words_entry_id"] is None
    assert estimate.fer_words_name is None
