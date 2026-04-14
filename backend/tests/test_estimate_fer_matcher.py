from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.estimate_fer_matcher import (
    _build_estimate_search_text,
    _get_allowed_section_ids_for_batch,
    _match_estimate_hybrid,
    _normalize_estimates,
    has_fer_vector_index_rows,
)
from app.services.fer_hybrid_search_service import HybridCandidate


def _mapping_result(row):
    result = MagicMock()
    mappings = MagicMock()
    mappings.first.return_value = row
    result.mappings.return_value = mappings
    return result


def test_build_estimate_search_text_includes_section_work_and_unit():
    estimate = SimpleNamespace(
        section="Фундамент",
        work_name="Устройство монолитной плиты",
        unit="м3",
    )

    text = _build_estimate_search_text(estimate)

    assert "Раздел: Фундамент" in text
    assert "Работа: Устройство монолитной плиты" in text
    assert "Единица: м3" in text


def test_build_estimate_search_text_omits_empty_fields():
    estimate = SimpleNamespace(
        section="",
        work_name="Монтаж каркаса",
        unit=None,
    )

    text = _build_estimate_search_text(estimate)

    assert text == "Работа: Монтаж каркаса"


@pytest.mark.asyncio
async def test_has_fer_vector_index_rows_uses_bool_result():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=3)

    assert await has_fer_vector_index_rows(db) is True


@pytest.mark.asyncio
async def test_get_allowed_section_ids_for_batch_returns_ids():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_mapping_result({"section_ids": [1, 4, 26]}))

    section_ids = await _get_allowed_section_ids_for_batch(db, "batch-1")

    assert section_ids == [1, 4, 26]


@pytest.mark.asyncio
async def test_get_allowed_section_ids_for_batch_returns_empty_list_when_mapping_missing():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_mapping_result(None))

    section_ids = await _get_allowed_section_ids_for_batch(db, "batch-1")

    assert section_ids == []


@pytest.mark.asyncio
async def test_normalize_estimates_uses_fallback_on_failure(monkeypatch):
    estimates = [
        SimpleNamespace(section="Кладка", work_name="Кл. кирп. ст.", unit="м3"),
        SimpleNamespace(section=None, work_name="Монтаж каркаса", unit=None),
    ]

    async def fake_normalize(*, section, work_name, unit):
        if "Кл." in work_name:
            return "Кладка кирпичных стен"
        raise RuntimeError("normalization failed")

    monkeypatch.setattr(
        "app.services.estimate_fer_matcher.normalize_smeta_item",
        fake_normalize,
    )

    normalized, fallback_count = await _normalize_estimates(estimates)

    assert normalized[0] == "Кладка кирпичных стен"
    assert normalized[1] == "Работа: Монтаж каркаса"
    assert fallback_count == 1


@pytest.mark.asyncio
async def test_match_estimate_hybrid_returns_top_candidate_without_rerank(monkeypatch):
    estimate = SimpleNamespace(work_name="Кладка стен")
    candidates = [
        HybridCandidate(1, 101, "Кладка стен кирпичных", "src1", "search1", 0.8, 0.3, 0.71),
        HybridCandidate(2, 102, "Кладка стен бетонных", "src2", "search2", 0.7, 0.1, 0.52),
    ]

    monkeypatch.setattr(
        "app.services.estimate_fer_matcher.hybrid_search_candidates",
        AsyncMock(return_value=candidates),
    )
    monkeypatch.setattr(
        "app.services.estimate_fer_matcher.should_rerank",
        lambda _: False,
    )

    decision = await _match_estimate_hybrid(
        AsyncMock(),
        estimate=estimate,
        normalized_text="Кладка кирпичных стен",
        embedding=[0.1, 0.2],
        allowed_section_ids=[1],
    )

    assert decision.match is not None
    assert decision.match.table_id == 101
    assert decision.match.work_type == "Кладка стен кирпичных"
    assert decision.match.score == pytest.approx(0.71)
    assert decision.reranked is False
    assert decision.rerank_corrected is False
    assert decision.fallback_used is False


@pytest.mark.asyncio
async def test_match_estimate_hybrid_marks_rerank_corrected_on_table_change(monkeypatch):
    estimate = SimpleNamespace(work_name="Кладка стен")
    candidates = [
        HybridCandidate(1, 101, "Кладка стен кирпичных", "src1", "search1", 0.8, 0.3, 0.71),
        HybridCandidate(2, 102, "Кладка наружных стен", "src2", "search2", 0.79, 0.29, 0.70),
    ]

    monkeypatch.setattr(
        "app.services.estimate_fer_matcher.hybrid_search_candidates",
        AsyncMock(return_value=candidates),
    )
    monkeypatch.setattr(
        "app.services.estimate_fer_matcher.should_rerank",
        lambda _: True,
    )
    monkeypatch.setattr(
        "app.services.estimate_fer_matcher.llm_rerank",
        AsyncMock(
            return_value=SimpleNamespace(
                selected_candidate=candidates[1],
                confidence=0.93,
                reason="Точнее совпадают наружные стены",
                corrected=True,
            )
        ),
    )

    decision = await _match_estimate_hybrid(
        AsyncMock(),
        estimate=estimate,
        normalized_text="Кладка наружных кирпичных стен",
        embedding=[0.1, 0.2],
        allowed_section_ids=[1],
    )

    assert decision.match is not None
    assert decision.match.table_id == 102
    assert decision.reranked is True
    assert decision.rerank_corrected is True
    assert decision.fallback_used is False


@pytest.mark.asyncio
async def test_match_estimate_hybrid_falls_back_when_rerank_fails(monkeypatch):
    estimate = SimpleNamespace(work_name="Кладка стен")
    candidates = [
        HybridCandidate(1, 101, "Кладка стен кирпичных", "src1", "search1", 0.8, 0.3, 0.71),
    ]

    monkeypatch.setattr(
        "app.services.estimate_fer_matcher.hybrid_search_candidates",
        AsyncMock(return_value=candidates),
    )
    monkeypatch.setattr(
        "app.services.estimate_fer_matcher.should_rerank",
        lambda _: True,
    )

    async def fail_rerank(**kwargs):
        raise RuntimeError("rerank failed")

    monkeypatch.setattr(
        "app.services.estimate_fer_matcher.llm_rerank",
        fail_rerank,
    )

    decision = await _match_estimate_hybrid(
        AsyncMock(),
        estimate=estimate,
        normalized_text="Кладка кирпичных стен",
        embedding=[0.1, 0.2],
        allowed_section_ids=[1],
    )

    assert decision.match is not None
    assert decision.match.table_id == 101
    assert decision.reranked is False
    assert decision.rerank_corrected is False
    assert decision.fallback_used is True
