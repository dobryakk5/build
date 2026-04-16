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
    _resolve_row_match_scope,
    confirm_group_candidate,
    has_fer_vector_index_rows,
    match_estimate_group_with_vector,
    match_estimate_with_vector,
)
from app.services.estimate_fer_matcher import FerGroupCandidate
from app.services.fer_match_examples_service import FerExampleMatch
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


@pytest.mark.asyncio
async def test_match_estimate_with_vector_returns_example_match_without_normalization(monkeypatch):
    estimate = SimpleNamespace(work_name="Кладка стен", estimate_batch_id="batch-1")

    monkeypatch.setattr(
        "app.services.estimate_fer_matcher.search_fer_match_example",
        AsyncMock(
            return_value=FerExampleMatch(
                fer_table_id=101,
                fer_work_type="Кладка кирпичных стен",
                fer_code=None,
                score=0.96,
            )
        ),
    )
    monkeypatch.setattr(
        "app.services.estimate_fer_matcher.has_fer_vector_index_rows",
        AsyncMock(side_effect=AssertionError("vector index should not be checked when example match exists")),
    )
    monkeypatch.setattr(
        "app.services.estimate_fer_matcher._normalize_estimates",
        AsyncMock(side_effect=AssertionError("normalization should not run when example match exists")),
    )

    match = await match_estimate_with_vector(AsyncMock(), estimate)

    assert match is not None
    assert match.table_id == 101
    assert match.strategy == "example_match"
    assert match.normalized_text is None


@pytest.mark.asyncio
async def test_match_estimate_with_vector_falls_back_to_hybrid_on_example_miss(monkeypatch):
    estimate = SimpleNamespace(work_name="Кладка стен", estimate_batch_id="batch-1")

    monkeypatch.setattr(
        "app.services.estimate_fer_matcher.search_fer_match_example",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.services.estimate_fer_matcher.has_fer_vector_index_rows",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.estimate_fer_matcher._normalize_estimates",
        AsyncMock(return_value=(["Кладка кирпичных стен"], 0)),
    )
    monkeypatch.setattr(
        "app.services.estimate_fer_matcher.create_embeddings",
        AsyncMock(return_value=[[0.1, 0.2]]),
    )
    monkeypatch.setattr(
        "app.services.estimate_fer_matcher._get_allowed_section_ids_for_batch",
        AsyncMock(return_value=[8]),
    )
    monkeypatch.setattr(
        "app.services.estimate_fer_matcher._match_estimate_hybrid",
        AsyncMock(
            return_value=SimpleNamespace(
                match=SimpleNamespace(
                    table_id=101,
                    work_type="Кладка кирпичных стен",
                    score=0.74,
                    strategy="hybrid_match",
                )
            )
        ),
    )

    match = await match_estimate_with_vector(AsyncMock(), estimate)

    assert match is not None
    assert match.table_id == 101
    assert match.strategy == "hybrid_match"


def test_resolve_row_match_scope_uses_confirmed_section_group():
    estimate = SimpleNamespace(
        fer_group_ref_id=12,
        fer_group_kind="section",
        fer_group_collection_id=8,
        fer_group_is_ambiguous=False,
    )

    allowed, filter_section_id, filter_collection_id = _resolve_row_match_scope(estimate, [1, 2, 3])

    assert allowed is None
    assert filter_section_id == 12
    assert filter_collection_id is None


def test_confirm_group_candidate_accepts_only_existing_payload():
    estimate = SimpleNamespace(
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
        ]
    )

    match = confirm_group_candidate(estimate, kind="collection", ref_id=8)

    assert match.kind == "collection"
    assert match.ref_id == 8
    assert match.is_ambiguous is False
    assert match.candidates is None


@pytest.mark.asyncio
async def test_match_estimate_group_with_vector_falls_back_to_ambiguous_collection(monkeypatch):
    estimate = SimpleNamespace(section="Кирпичные конструкции", estimate_batch_id="batch-1")

    monkeypatch.setattr("app.services.estimate_fer_matcher.has_fer_vector_index_rows", AsyncMock(return_value=True))
    monkeypatch.setattr("app.services.estimate_fer_matcher._get_allowed_section_ids_for_batch", AsyncMock(return_value=[8, 11]))
    monkeypatch.setattr("app.services.estimate_fer_matcher._normalize_group_title", AsyncMock(return_value="кирпичные конструкции"))
    monkeypatch.setattr("app.services.estimate_fer_matcher.create_embeddings", AsyncMock(return_value=[[0.1, 0.2]]))
    monkeypatch.setattr(
        "app.services.estimate_fer_matcher._search_section_group_candidates",
        AsyncMock(
            return_value=[
                FerGroupCandidate("section", 80, "Каменные конструкции", 8, "08", "Конструкции из кирпича", 0.68),
                FerGroupCandidate("section", 81, "Перегородки", 8, "08", "Конструкции из кирпича", 0.65),
            ]
        ),
    )
    monkeypatch.setattr("app.services.estimate_fer_matcher._get_allowed_collection_ids", AsyncMock(return_value=[8, 15]))
    monkeypatch.setattr(
        "app.services.estimate_fer_matcher._search_collection_group_candidates",
        AsyncMock(
            return_value=[
                FerGroupCandidate("collection", 8, "Сборник 08. Конструкции из кирпича", 8, "08", "Конструкции из кирпича", 0.54),
                FerGroupCandidate("collection", 15, "Сборник 15. Отделочные работы", 15, "15", "Отделочные работы", 0.49),
            ]
        ),
    )

    match = await match_estimate_group_with_vector(AsyncMock(), estimate)

    assert match.kind == "collection"
    assert match.ref_id == 8
    assert match.is_ambiguous is True
    assert match.no_match is False
    assert match.candidates is not None
    assert len(match.candidates) == 2


@pytest.mark.asyncio
async def test_match_estimate_group_with_vector_auto_assigns_single_weak_collection(monkeypatch):
    estimate = SimpleNamespace(section="Неизвестная группа", estimate_batch_id="batch-1")

    monkeypatch.setattr("app.services.estimate_fer_matcher.has_fer_vector_index_rows", AsyncMock(return_value=True))
    monkeypatch.setattr("app.services.estimate_fer_matcher._get_allowed_section_ids_for_batch", AsyncMock(return_value=[8, 11]))
    monkeypatch.setattr("app.services.estimate_fer_matcher._normalize_group_title", AsyncMock(return_value="неизвестная группа"))
    monkeypatch.setattr("app.services.estimate_fer_matcher.create_embeddings", AsyncMock(return_value=[[0.1, 0.2]]))
    monkeypatch.setattr("app.services.estimate_fer_matcher._search_section_group_candidates", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.estimate_fer_matcher._get_allowed_collection_ids", AsyncMock(return_value=[8, 15]))
    monkeypatch.setattr(
        "app.services.estimate_fer_matcher._search_collection_group_candidates",
        AsyncMock(
            return_value=[
                FerGroupCandidate("collection", 8, "Сборник 08. Конструкции из кирпича", 8, "08", "Конструкции из кирпича", 0.31),
            ]
        ),
    )

    match = await match_estimate_group_with_vector(AsyncMock(), estimate)

    assert match.no_match is False
    assert match.kind == "collection"
    assert match.ref_id == 8
    assert match.is_ambiguous is False
    assert match.candidates is None


@pytest.mark.asyncio
async def test_match_estimate_group_with_vector_returns_ambiguous_when_multiple_weak_collections(monkeypatch):
    estimate = SimpleNamespace(section="Неизвестная группа", estimate_batch_id="batch-1")

    monkeypatch.setattr("app.services.estimate_fer_matcher.has_fer_vector_index_rows", AsyncMock(return_value=True))
    monkeypatch.setattr("app.services.estimate_fer_matcher._get_allowed_section_ids_for_batch", AsyncMock(return_value=[8, 11]))
    monkeypatch.setattr("app.services.estimate_fer_matcher._normalize_group_title", AsyncMock(return_value="неизвестная группа"))
    monkeypatch.setattr("app.services.estimate_fer_matcher.create_embeddings", AsyncMock(return_value=[[0.1, 0.2]]))
    monkeypatch.setattr("app.services.estimate_fer_matcher._search_section_group_candidates", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.estimate_fer_matcher._get_allowed_collection_ids", AsyncMock(return_value=[8, 15]))
    monkeypatch.setattr(
        "app.services.estimate_fer_matcher._search_collection_group_candidates",
        AsyncMock(
            return_value=[
                FerGroupCandidate("collection", 8, "Сборник 08. Конструкции из кирпича", 8, "08", "Конструкции из кирпича", 0.31),
                FerGroupCandidate("collection", 15, "Сборник 15. Отделочные работы", 15, "15", "Отделочные работы", 0.22),
            ]
        ),
    )

    match = await match_estimate_group_with_vector(AsyncMock(), estimate)

    assert match.no_match is False
    assert match.kind == "collection"
    assert match.ref_id == 8
    assert match.is_ambiguous is True
    assert match.candidates is not None
    assert len(match.candidates) == 2
