from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))


def make_session(sid: str = "sess-1", project_id: str = "p1"):
    s = MagicMock()
    s.id = sid
    s.project_id = project_id
    return s


def make_est(
    eid: str,
    work_name: str,
    unit: str = "м2",
    quantity: float = 10.0,
    section: str | None = None,
    row_order: int = 0,
):
    e = MagicMock()
    e.id = eid
    e.work_name = work_name
    e.unit = unit
    e.quantity = quantity
    e.section = section
    e.row_order = row_order
    e.total_price = None
    return e


def _make_diag() -> dict:
    return {
        "chunk_errors": [],
        "raw_samples": [],
        "coverage": [],
        "wt_code_conflicts": [],
        "gap_fill_trimmed": [],
        "repeated_sections": [],
        "unassigned_ai_items": [],
    }


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


def test_stage1_job_stale_detection_uses_started_at():
    from datetime import datetime, timedelta, timezone

    from app.services.ktp_estimate_service import _is_stale_stage1_job

    job = MagicMock()
    job.type = "ktp_estimate_stage1"
    job.status = "processing"
    job.started_at = datetime(2026, 5, 30, 18, 0, tzinfo=timezone.utc)
    job.created_at = job.started_at - timedelta(minutes=1)

    assert _is_stale_stage1_job(
        job,
        now=job.started_at + timedelta(hours=3),
    )


def test_non_stage1_job_is_not_stale_for_ktp_recovery():
    from datetime import datetime, timedelta, timezone

    from app.services.ktp_estimate_service import _is_stale_stage1_job

    job = MagicMock()
    job.type = "estimate_upload"
    job.status = "processing"
    job.started_at = datetime(2026, 5, 30, 18, 0, tzinfo=timezone.utc)
    job.created_at = job.started_at

    assert not _is_stale_stage1_job(
        job,
        now=job.started_at + timedelta(days=1),
    )


# ── section_key и python_groups ─────────────────────────────────────────────

def test_make_section_key_stable_and_versioned():
    from app.services.ktp_estimate_service import (
        _make_section_key,
        _normalize_section_title,
    )

    a = _make_section_key(1, _normalize_section_title("Кровля"))
    b = _make_section_key(1, _normalize_section_title("  кровля  "))
    assert a == b
    assert a.startswith("sec_0001_")


def test_build_python_groups_merges_repeated_sections():
    from app.services.ktp_estimate_service import _build_python_groups

    estimates = [
        make_est("e1", "Снятие отделки", section="Демонтаж", row_order=0),
        make_est("e2", "Монтаж стропил", section="Кровля", row_order=1),
        make_est("e3", "Вывоз мусора", section="демонтаж", row_order=2),
    ]
    diag = _make_diag()
    groups = _build_python_groups(estimates, {est.id: f"R{i}" for i, est in enumerate(estimates, start=1)}, diag)

    titles = sorted(g["display_title"] for g in groups.values())
    assert titles == ["Демонтаж", "Кровля"]

    demo = next(g for g in groups.values() if g["display_title"] == "Демонтаж")
    assert {row_key for row_key, _ in demo["rows"]} == {"R1", "R3"}
    assert demo["sort_order"] == 0
    assert len(diag["repeated_sections"]) == 1


def test_build_python_groups_collects_ungrouped():
    from app.services.ktp_estimate_service import _build_python_groups

    estimates = [
        make_est("e1", "A", section="Кровля", row_order=0),
        make_est("e2", "B", section=None, row_order=1),
        make_est("e3", "C", section="   ", row_order=2),
    ]
    diag = _make_diag()
    groups = _build_python_groups(estimates, {est.id: f"R{i}" for i, est in enumerate(estimates, start=1)}, diag)
    assert "__ungrouped__" in groups
    assert {row_key for row_key, _ in groups["__ungrouped__"]["rows"]} == {"R2", "R3"}


# ── валидаторы покрытия ─────────────────────────────────────────────────────

def test_validate_section_coverage_drops_unknown_and_duplicates_fills_missing():
    from app.services.ktp_estimate_service import _validate_section_coverage

    e1, e2, e3 = (
        make_est("e1", "Кладка"),
        make_est("e2", "Штукатурка"),
        make_est("e3", "Покраска"),
    )
    section_rows = [("R001", e1), ("R002", e2), ("R003", e3)]
    items = [
        {"row_key": "R001", "name": "Кладка стен"},
        {"row_key": "R001", "name": "Дубль"},   # duplicate
        {"row_key": "R999", "name": "Призрак"},  # unknown
        # R002, R003 — missing
    ]
    diag = _make_diag()
    cleaned = _validate_section_coverage(
        items=items,
        section_rows=section_rows,
        section_key="sec_0001_abc",
        chunk_label="sec_test",
        diagnostics=diag,
    )

    by_key = {it["row_key"]: it for it in cleaned}
    assert set(by_key.keys()) == {"R001", "R002", "R003"}
    assert by_key["R001"]["name"] == "Кладка стен"
    # missing восстановлены из Estimate.work_name
    assert by_key["R002"]["name"] == "Штукатурка"
    assert by_key["R003"]["name"] == "Покраска"

    cov = diag["coverage"][0]
    assert "R999" in cov["unknown"]
    assert "R001" in cov["duplicated"]
    assert set(cov["missing"]) == {"R002", "R003"}


def test_validate_ungrouped_coverage_routes_invalid_to_fallback():
    from app.services.ktp_estimate_service import _validate_ungrouped_coverage

    e1, e2, e3 = (
        make_est("e1", "A"),
        make_est("e2", "B"),
        make_est("e3", "C"),
    )
    orphan_rows = [("R1", e1), ("R2", e2), ("R3", e3)]
    assignments = [
        {"row_key": "R1", "assigned_section_key": "sec_0001_ok", "name": "A norm"},
        {"row_key": "R2", "assigned_section_key": "sec_bogus", "name": "B"},  # invalid
        # R3 — отсутствует
    ]
    diag = _make_diag()
    cleaned, fallback = _validate_ungrouped_coverage(
        assignments=assignments,
        orphan_rows=orphan_rows,
        valid_section_keys={"sec_0001_ok"},
        diagnostics=diag,
    )

    assert [c["row_key"] for c in cleaned] == ["R1"]
    fallback_keys = {row_key for row_key, _ in fallback}
    assert fallback_keys == {"R2", "R3"}
    cov = diag["coverage"][0]
    assert "R2" in cov["invalid_assignment"]
    assert "R3" in cov["missing"]


# ── валидаторы формата ─────────────────────────────────────────────────────

def test_validate_section_response_drops_invalid_items():
    from app.services.ktp_estimate_service import _validate_section_response

    out = _validate_section_response(
        {
            "cleaned_title": "  Кровля  ",
            "wt_code": "wt-12",
            "items": [
                {"row_key": "R007", "name": "Монтаж"},
                {"row_key": "  ", "name": "пусто"},
                {"name": "без row_key"},
                "not a dict",
            ],
        }
    )
    assert out["cleaned_title"] == "Кровля"
    assert out["wt_code"] == "WT-12"
    assert out["items"] == [{"row_key": "R007", "name": "Монтаж"}]


def test_validate_per_group_gap_fill_requires_reason():
    from app.services.ktp_estimate_service import _validate_per_group_gap_fill_response

    out = _validate_per_group_gap_fill_response(
        {
            "added_items": [
                {"name": "Снегозадержатели", "ai_reason": "защита"},
                {"name": "без причины"},
                {"name": "", "ai_reason": "нет имени"},
            ]
        }
    )
    assert out == [{"name": "Снегозадержатели", "ai_reason": "защита"}]


def test_validate_project_gap_fill_drops_records_without_reason_or_group_key():
    from app.services.ktp_estimate_service import _validate_project_gap_fill_response

    out = _validate_project_gap_fill_response(
        {
            "distributed": [
                {"group_key": "sec_0001_a", "name": "Снег.", "ai_reason": "защита"},
                {"group_key": "sec_0001_a", "name": "без причины"},
                {"name": "без group_key", "ai_reason": "x"},
            ],
            "unassigned": [
                {"name": "Пусконаладка", "ai_reason": "запрошено"},
                {"name": "без причины"},
            ],
        }
    )
    assert out["distributed"] == [
        {"group_key": "sec_0001_a", "name": "Снег.", "ai_reason": "защита"}
    ]
    assert out["unassigned"] == [{"name": "Пусконаладка", "ai_reason": "запрошено"}]


# ── canonical assembly ─────────────────────────────────────────────────────

def test_assemble_canonical_adds_fallback_for_global_missing():
    from app.services.ktp_estimate_service import (
        FALLBACK_DISPLAY_TITLE,
        _assemble_canonical_groups,
    )

    e1 = make_est("e1", "A")
    e2 = make_est("e2", "B")
    row_keys = {"R1": e1, "R2": e2}
    python_groups = {
        "sec_0001_a": {
            "section_key": "sec_0001_a",
            "display_title": "Кровля",
            "cleaned_title": "Кровля",
            "rows": [("R1", e1)],
            "sort_order": 0,
            "cleaned_items": [{"name": "A", "origin": "from_estimate", "row_key": "R1"}],
            "wt_code": "WT-12",
            "gap_items": [
                {
                    "name": "Снегозадержатели",
                    "origin": "ai_added",
                    "row_key": None,
                    "review_status": "pending",
                    "ai_reason": "защита",
                }
            ],
        }
    }
    diag = _make_diag()
    out = _assemble_canonical_groups(python_groups, row_keys, diag)
    titles = [g["title"] for g in out]
    assert titles == ["Кровля", FALLBACK_DISPLAY_TITLE]
    fallback = next(g for g in out if g["title"] == FALLBACK_DISPLAY_TITLE)
    assert fallback["items"][0]["row_key"] == "R2"
    cov_kinds = {c["kind"] for c in diag["coverage"]}
    assert "global" in cov_kinds


def test_assemble_canonical_includes_ai_added_with_required_fields():
    from app.services.ktp_estimate_service import _assemble_canonical_groups

    e1 = make_est("e1", "A")
    row_keys = {"R1": e1}
    python_groups = {
        "sec_0001_a": {
            "section_key": "sec_0001_a",
            "display_title": "Кровля",
            "cleaned_title": "Кровля",
            "rows": [("R1", e1)],
            "sort_order": 0,
            "cleaned_items": [{"name": "A", "origin": "from_estimate", "row_key": "R1"}],
            "wt_code": None,
            "gap_items": [
                {
                    "name": "Снегозадержатели",
                    "origin": "ai_added",
                    "row_key": None,
                    "review_status": "pending",
                    "ai_reason": "защита",
                }
            ],
        }
    }
    out = _assemble_canonical_groups(python_groups, row_keys, _make_diag())
    assert len(out) == 1
    items = out[0]["items"]
    ai_added = [it for it in items if it["origin"] == "ai_added"]
    assert len(ai_added) == 1
    assert ai_added[0]["row_key"] is None
    assert ai_added[0]["review_status"] == "pending"


def test_materialize_wbs_handles_ai_added_with_null_row_key():
    from app.services.ktp_estimate_service import _materialize_wbs

    e1 = make_est("e1", "A")
    row_keys = {"R1": e1}
    raw_groups = [
        {
            "title": "Кровля",
            "sort_order": 1,
            "wt_code": "WT-12",
            "items": [
                {"name": "A", "origin": "from_estimate", "row_key": "R1"},
                {
                    "name": "Снегозадержатели",
                    "origin": "ai_added",
                    "row_key": None,
                    "review_status": "pending",
                    "ai_reason": "защита",
                },
            ],
        }
    ]
    groups, items, warnings = _materialize_wbs(make_session(), raw_groups, row_keys)
    by_origin = {it.origin: it for it in items}
    assert by_origin["from_estimate"].estimate_id == "e1"
    assert by_origin["ai_added"].estimate_id is None
    assert by_origin["ai_added"].review_status == "pending"
    assert by_origin["ai_added"].ai_reason == "защита"


# ── последовательность групп (2-й уровень) ───────────────────────────────────

def make_group_row(gid: str, title: str, sort_order: float = 1000.0):
    g = MagicMock()
    g.id = gid
    g.title = title
    g.sort_order = sort_order
    return g


def test_is_fallback_group_title_detects_titles():
    from app.services.ktp_estimate_service import _is_fallback_group_title

    assert _is_fallback_group_title("Прочие позиции сметы")
    assert _is_fallback_group_title("Прочие работы сметы")
    assert not _is_fallback_group_title("Фундамент")


def test_reassign_sequence_sort_order_pins_fallback_last():
    from app.services.ktp_estimate_service import _reassign_sequence_sort_order

    a = make_group_row("a", "Земляные")
    b = make_group_row("b", "Фундамент")
    z = make_group_row("z", "Прочие позиции сметы")
    _reassign_sequence_sort_order([b, a], [z])  # порядок b,a

    assert b.sort_order == 1000.0
    assert a.sort_order == 2000.0
    assert z.sort_order == 3000.0  # fallback после всех обычных


@pytest.mark.asyncio
async def test_propose_group_sequence_orders_and_sets_status():
    import app.services.ktp_estimate_service as svc

    session = MagicMock()
    session.status = "gpr_pending"
    groups = [
        make_group_row("a", "Отделка", 1000.0),
        make_group_row("b", "Земляные", 2000.0),
        make_group_row("z", "Прочие позиции сметы", 3000.0),
    ]
    db = AsyncMock()

    with (
        patch.object(svc, "get_session_by_id", AsyncMock(return_value=session)),
        patch.object(svc, "_load_session_groups", AsyncMock(return_value=groups)),
        patch(
            "app.services.ktp_gpr_service._ai_order_groups",
            AsyncMock(return_value=["b", "a"]),  # ИИ: Земляные → Отделка
        ),
        patch.object(svc, "get_wbs", AsyncMock(return_value={"groups": []})),
    ):
        await svc.propose_group_sequence(db, "p1", "s1")

    by_id = {g.id: g for g in groups}
    assert by_id["b"].sort_order == 1000.0
    assert by_id["a"].sort_order == 2000.0
    assert by_id["z"].sort_order == 3000.0  # fallback в конце
    assert session.status == "gpr_sequence_review"
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_approve_group_sequence_repins_fallback_and_sets_ready():
    import app.services.ktp_estimate_service as svc

    session = MagicMock()
    session.status = "gpr_sequence_review"
    # оператор по ошибке поставил fallback в середину
    groups = [
        make_group_row("a", "Земляные", 1000.0),
        make_group_row("z", "Прочие позиции сметы", 1500.0),
        make_group_row("b", "Отделка", 2000.0),
    ]
    db = AsyncMock()

    with (
        patch.object(svc, "get_session_by_id", AsyncMock(return_value=session)),
        patch.object(svc, "_load_session_groups", AsyncMock(return_value=groups)),
    ):
        result = await svc.approve_group_sequence(db, "p1", "s1")

    by_id = {g.id: g for g in groups}
    # fallback пере-пинится после максимального обычного (2000) → 3000
    assert by_id["z"].sort_order == 3000.0
    assert session.status == "gpr_ready"
    assert result is session
