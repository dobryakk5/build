from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1]))


def _entry(entry_id: int, fer_code: str, display_name: str):
    from app.services.fer_words_service import tokenize_fer_words_text

    return SimpleNamespace(
        id=entry_id,
        fer_code=fer_code,
        display_name=display_name,
        search_tokens=tokenize_fer_words_text(display_name),
        human_hours=0,
        machine_hours=29,
    )


def test_tokenize_fer_words_text_splits_numbers_and_units():
    from app.services.fer_words_service import tokenize_fer_words_text

    tokens = tokenize_fer_words_text("Объем до 500м3, экскаватор 0,5м3")

    assert "500" in tokens
    assert "м3" in tokens
    assert "0.5" in tokens


def test_build_fer_words_candidates_prefers_best_word_overlap():
    from app.services.fer_words_service import build_fer_words_candidates

    entries = [
        _entry(1, "01.01.006", "Разработка грунта отвал котлован объемом до 500 м3 экскаватор ковш 0.4 м3 группа грунтов 1"),
        _entry(2, "01.01.020", "Разработка основания вручную"),
    ]

    candidates = build_fer_words_candidates(
        "Разработка грунта экскаватором в отвал котлован объемом до 500 м3",
        entries,
        limit=5,
    )

    assert candidates
    assert candidates[0].entry_id == 1
    assert len(candidates) >= 2
    assert candidates[0].matched_tokens > candidates[1].matched_tokens


def test_should_auto_apply_fer_words_rejects_equal_best_match_count():
    from app.services.fer_words_service import FerWordsCandidate, should_auto_apply_fer_words

    candidates = [
        FerWordsCandidate(1, "01.01.006", "A", 0, 10, 3, 3, 1, 0.95, 3.0),
        FerWordsCandidate(2, "01.01.007", "B", 0, 11, 3, 2, 1, 0.91, 3.0),
    ]

    assert should_auto_apply_fer_words(candidates) is False
