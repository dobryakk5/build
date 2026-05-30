from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.fer_hybrid_search_service import HybridCandidate
from app.services.ktp_item_fer_service import (
    classify_disposition,
    extract_fer_unit,
    normalize_unit,
    _decide_fer_match,
)


def _cand(table_id, row_id, final, vec=None, fts=0.0):
    return HybridCandidate(
        vector_index_id=row_id,
        table_id=table_id,
        work_type="Работа",
        source_text="src",
        search_text="search",
        vec_score=vec if vec is not None else final,
        fts_score=fts,
        final_score=final,
        row_id=row_id,
    )


# ── Step A — disposition ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "name,expected",
    [
        ("ИТОГО ЗА ДЕМОНТАЖНЫЕ РАБОТЫ ПО СТЕНАМ:", "excluded"),
        ("Всего по разделу", "excluded"),
        ("Накладные расходы", "excluded"),
        ("Выезд мастера на рынок по просьбе клиента", "excluded"),
        ("", "excluded"),
        ("Облицовка стен керамической плиткой", "work"),
        ("Установка унитаза", "work"),
    ],
)
def test_classify_disposition(name, expected):
    disp, reason, source = classify_disposition(name)
    assert disp == expected
    if expected == "excluded":
        assert reason and source == "regex" or name == ""


# ── Unit reconciliation ──────────────────────────────────────────────────────

def test_normalize_unit():
    assert normalize_unit("м2") == "м2"
    assert normalize_unit("кв.м") == "м2"
    assert normalize_unit("м.пог") == "м"
    assert normalize_unit("шт.") == "шт"
    assert normalize_unit("м3") == "м3"
    assert normalize_unit("") is None
    assert normalize_unit(None) is None


def test_extract_fer_unit_multiplier():
    assert extract_fer_unit("Устройство покрытий на 100 м2 поверхности", None, None) == ("м2", 100.0)
    assert extract_fer_unit("Разработка грунта, м3", None, None) == ("м3", 1.0)
    assert extract_fer_unit("на 1000 м3 кладки", None, None) == ("м3", 1000.0)
    assert extract_fer_unit(None, None, None) == (None, 1.0)


# ── Step C — acceptance policy ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_decide_strong_auto_accept():
    cands = [_cand(10, 101, 0.85), _cand(11, 102, 0.4)]
    cand, source, score = await _decide_fer_match(
        cands, original_text="o", normalized_text="n"
    )
    assert source == "auto"
    assert cand.row_id == 101
    assert score == 0.85


@pytest.mark.asyncio
async def test_decide_weak_goes_to_review_when_rerank_disabled():
    cands = [_cand(10, 101, 0.5), _cand(11, 102, 0.48)]
    with patch("app.services.ktp_item_fer_service.settings.RERANK_ENABLED", False):
        cand, source, score = await _decide_fer_match(
            cands, original_text="o", normalized_text="n"
        )
    assert source == "review"
    assert cand.row_id == 101


@pytest.mark.asyncio
async def test_decide_small_gap_goes_to_review():
    # high top1 but tiny gap → not strong
    cands = [_cand(10, 101, 0.9), _cand(11, 102, 0.89)]
    with patch("app.services.ktp_item_fer_service.settings.RERANK_ENABLED", False):
        _cand_, source, _score = await _decide_fer_match(
            cands, original_text="o", normalized_text="n"
        )
    assert source == "review"


@pytest.mark.asyncio
async def test_decide_rerank_confident_auto_accept():
    cands = [_cand(10, 101, 0.6), _cand(11, 102, 0.58)]
    decision = SimpleNamespace(
        selected_candidate=cands[0], confidence=0.95, reason="", corrected=False
    )
    with (
        patch("app.services.ktp_item_fer_service.settings.RERANK_ENABLED", True),
        patch(
            "app.services.ktp_item_fer_service.llm_rerank",
            AsyncMock(return_value=decision),
        ),
    ):
        cand, source, score = await _decide_fer_match(
            cands, original_text="o", normalized_text="n"
        )
    assert source == "auto"
    assert score == 0.95


@pytest.mark.asyncio
async def test_decide_rerank_corrected_goes_to_review():
    cands = [_cand(10, 101, 0.6), _cand(11, 102, 0.58)]
    decision = SimpleNamespace(
        selected_candidate=cands[1], confidence=0.95, reason="", corrected=True
    )
    with (
        patch("app.services.ktp_item_fer_service.settings.RERANK_ENABLED", True),
        patch(
            "app.services.ktp_item_fer_service.llm_rerank",
            AsyncMock(return_value=decision),
        ),
    ):
        cand, source, _score = await _decide_fer_match(
            cands, original_text="o", normalized_text="n"
        )
    assert source == "review"
    assert cand.row_id == 102


@pytest.mark.asyncio
async def test_decide_no_candidates():
    cand, source, score = await _decide_fer_match(
        [], original_text="o", normalized_text="n"
    )
    assert cand is None and source == "review" and score is None
