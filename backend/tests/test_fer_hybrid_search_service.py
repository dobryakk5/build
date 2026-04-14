from pathlib import Path
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services.fer_hybrid_search_service import (
    HybridCandidate,
    build_fts_document_text,
    build_normalization_input,
    hybrid_search_candidates,
    should_rerank,
)


def test_build_normalization_input_includes_all_parts():
    text = build_normalization_input(
        section="Кладка",
        work_name="Кл. кирп. ст. нар.",
        unit="м3",
    )

    assert "Раздел: Кладка" in text
    assert "Строка сметы: Кл. кирп. ст. нар." in text
    assert "Единица измерения: м3" in text


def test_build_fts_document_text_flattens_newlines():
    value = build_fts_document_text("Раздел: 1\nТаблица: кладка", "кладка стен")

    assert "\n" not in value
    assert "кладка стен" in value


def test_should_rerank_false_when_disabled():
    candidates = [HybridCandidate(1, 10, "Работа", "src", "search", 0.8, 0.2, 0.7)]
    original = settings.RERANK_ENABLED
    settings.RERANK_ENABLED = False
    try:
        assert should_rerank(candidates) is False
    finally:
        settings.RERANK_ENABLED = original


def test_should_rerank_true_for_close_scores():
    candidates = [
        HybridCandidate(1, 10, "Работа 1", "src1", "search1", 0.8, 0.2, 0.74),
        HybridCandidate(2, 11, "Работа 2", "src2", "search2", 0.79, 0.2, 0.71),
    ]
    original_enabled = settings.RERANK_ENABLED
    original_threshold = settings.RERANK_SCORE_THRESHOLD
    original_gap = settings.RERANK_GAP_THRESHOLD
    settings.RERANK_ENABLED = True
    settings.RERANK_SCORE_THRESHOLD = 0.6
    settings.RERANK_GAP_THRESHOLD = 0.05
    try:
        assert should_rerank(candidates) is True
    finally:
        settings.RERANK_ENABLED = original_enabled
        settings.RERANK_SCORE_THRESHOLD = original_threshold
        settings.RERANK_GAP_THRESHOLD = original_gap


@pytest.mark.asyncio
async def test_hybrid_search_candidates_returns_empty_without_allowed_sections():
    candidates = await hybrid_search_candidates(
        db=None,
        normalized_text="кладка наружных стен",
        embedding_literal="[0.1,0.2]",
        allowed_section_ids=[],
    )

    assert candidates == []
