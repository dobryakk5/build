from pathlib import Path
import sys
from unittest.mock import MagicMock

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))


def make_session(sid: str = "sess-1", project_id: str = "p1"):
    s = MagicMock()
    s.id = sid
    s.project_id = project_id
    return s


def make_est(eid: str, work_name: str, unit: str = "м2", quantity: float = 10.0):
    e = MagicMock()
    e.id = eid
    e.work_name = work_name
    e.unit = unit
    e.quantity = quantity
    return e


# ── инвариант покрытия ───────────────────────────────────────────────────────

def test_materialize_wbs_missing_row_goes_to_fallback_group():
    from app.services.ktp_estimate_service import (
        FALLBACK_GROUP_TITLE,
        _materialize_wbs,
    )

    e1 = make_est("e1", "Кладка стен")
    e2 = make_est("e2", "Штукатурка")
    row_keys = {"R001": e1, "R002": e2}
    raw_groups = [
        {
            "title": "Каменные работы",
            "items": [
                {"name": "Кладка стен", "origin": "from_estimate", "row_key": "R001"}
            ],
        }
    ]

    groups, items, warnings = _materialize_wbs(make_session(), raw_groups, row_keys)

    fallback = [g for g in groups if g.title == FALLBACK_GROUP_TITLE]
    assert len(fallback) == 1
    covered = {it.estimate_id for it in items if it.origin == "from_estimate"}
    assert covered == {"e1", "e2"}
    assert any("не распределены" in w for w in warnings)


def test_materialize_wbs_duplicate_estimate_kept_once_with_warning():
    from app.services.ktp_estimate_service import _materialize_wbs

    e1 = make_est("e1", "Кладка стен")
    row_keys = {"R001": e1}
    raw_groups = [
        {
            "title": "Каменные работы",
            "items": [
                {"name": "Кладка стен", "origin": "from_estimate", "row_key": "R001"},
                {"name": "Кладка (дубль)", "origin": "from_estimate", "row_key": "R001"},
            ],
        }
    ]

    groups, items, warnings = _materialize_wbs(make_session(), raw_groups, row_keys)

    from_estimate = [it for it in items if it.estimate_id == "e1"]
    assert len(from_estimate) == 1
    assert any("продублирована" in w for w in warnings)


def test_materialize_wbs_unknown_row_key_becomes_ai_added():
    from app.services.ktp_estimate_service import _materialize_wbs

    e1 = make_est("e1", "Кладка стен")
    row_keys = {"R001": e1}
    raw_groups = [
        {
            "title": "Каменные работы",
            "items": [
                {"name": "Кладка стен", "origin": "from_estimate", "row_key": "R001"},
                {"name": "Призрак", "origin": "from_estimate", "row_key": "R999"},
            ],
        }
    ]

    groups, items, warnings = _materialize_wbs(make_session(), raw_groups, row_keys)

    ghost = [it for it in items if it.name == "Призрак"][0]
    assert ghost.origin == "ai_added"
    assert ghost.estimate_id is None
    assert ghost.review_status == "pending"


def test_materialize_wbs_ai_added_is_pending():
    from app.services.ktp_estimate_service import _materialize_wbs

    e1 = make_est("e1", "Кладка стен")
    row_keys = {"R001": e1}
    raw_groups = [
        {
            "title": "Каменные работы",
            "items": [
                {"name": "Кладка стен", "origin": "from_estimate", "row_key": "R001"},
                {
                    "name": "Вывоз мусора",
                    "origin": "ai_added",
                    "ai_reason": "обязательный этап",
                },
            ],
        }
    ]

    groups, items, warnings = _materialize_wbs(make_session(), raw_groups, row_keys)

    added = [it for it in items if it.origin == "ai_added"][0]
    assert added.review_status == "pending"
    assert added.ai_reason == "обязательный этап"
    # все позиции сметы покрыты — лишних предупреждений нет
    assert not any("не распределены" in w for w in warnings)


# ── промпт ───────────────────────────────────────────────────────────────────

def test_build_stage1_prompt_contains_row_keys_and_gap_instruction():
    from app.services.ktp_estimate_service import _build_stage1_prompt

    rows = [("R001", make_est("e1", "Кладка стен"))]
    wt_palette = [{"wt_code": "WT-01", "wt_name": "Каменные работы", "examples": []}]

    with_gap = _build_stage1_prompt(rows, wt_palette, "Жилое здание", gap_fill=True)
    assert "R001" in with_gap
    assert "Кладка стен" in with_gap
    assert "WT-01" in with_gap
    assert "ОТСУТСТВУЮТ" in with_gap

    no_gap = _build_stage1_prompt(rows, wt_palette, "Жилое здание", gap_fill=False)
    assert "НЕ добавляй" in no_gap


def test_parse_stage1_response_extracts_groups():
    from app.services.ktp_estimate_service import _parse_stage1_response

    groups = _parse_stage1_response('{"groups": [{"title": "Г1", "items": []}]}')
    assert groups == [{"title": "Г1", "items": []}]


def test_parse_stage1_response_raises_without_groups():
    from app.services.ktp_estimate_service import _parse_stage1_response

    with pytest.raises(ValueError, match="без списка groups"):
        _parse_stage1_response('{"foo": 1}')


def test_parse_json_object_tolerates_trailing_commas():
    from app.services.openrouter_embeddings import parse_json_object

    # типовая ошибка gpt-4o-mini: запятая перед закрывающей скобкой
    result = parse_json_object('{"groups": [{"title": "Г1", "items": [],}],}')
    assert result == {"groups": [{"title": "Г1", "items": []}]}


def test_parse_json_object_strips_line_comments():
    from app.services.openrouter_embeddings import parse_json_object

    result = parse_json_object(
        '{\n  "groups": [\n    // inline comment\n    {"title": "Г1"}\n  ]\n}'
    )
    assert result == {"groups": [{"title": "Г1"}]}
