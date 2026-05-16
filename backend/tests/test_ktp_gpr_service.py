from datetime import date
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))


def make_group(gid: str, duration_days: int = 1, items=None):
    g = MagicMock()
    g.id = gid
    g.duration_days = duration_days
    g.start_date = None
    g.items = items or []
    g.accepted_items = items or []
    return g


def make_item(iid: str, name: str, quantity=None, estimate_id=None):
    it = MagicMock()
    it.id = iid
    it.name = name
    it.quantity = quantity
    it.unit = "м3"
    it.estimate_id = estimate_id
    it.duration_days = None
    it.labor_hours = None
    it.norm_kind = None
    it.norm_value = None
    it.norm_unit = None
    it.norm_source = None
    it.norm_ref = None
    it.brigade_size = None
    it.quantity_source = None
    return it


# ── проверка циклов ──────────────────────────────────────────────────────────

def test_drop_cycles_removes_closing_back_edge():
    from app.services.ktp_gpr_service import _drop_cycles

    groups = [make_group("a"), make_group("b"), make_group("c")]
    # b←a, c←b, a←c  → цикл a→c→b→a
    edges = [("b", "a"), ("c", "b"), ("a", "c")]
    warnings: list[str] = []

    result = _drop_cycles(groups, edges, warnings)

    assert ("b", "a") in result
    assert ("c", "b") in result
    assert ("a", "c") not in result  # замыкающее ребро отброшено
    assert any("циклическ" in w.lower() for w in warnings)


def test_drop_cycles_keeps_acyclic_graph_intact():
    from app.services.ktp_gpr_service import _drop_cycles

    groups = [make_group("a"), make_group("b"), make_group("c")]
    edges = [("b", "a"), ("c", "b")]
    warnings: list[str] = []

    result = _drop_cycles(groups, edges, warnings)

    assert set(result) == {("b", "a"), ("c", "b")}
    assert warnings == []


# ── топологическая расстановка дат (без off-by-one) ──────────────────────────

def test_schedule_groups_dependent_starts_day_after_predecessor_finish():
    from app.services.ktp_gpr_service import _schedule_groups

    a = make_group("a", duration_days=3)
    b = make_group("b", duration_days=2)
    # b зависит от a
    _schedule_groups([a, b], [("b", "a")], date(2026, 1, 1))

    assert a.start_date == date(2026, 1, 1)
    # a длится 3 календарных дня: 01-01..01-03; b стартует 01-04 (без off-by-one)
    assert b.start_date == date(2026, 1, 4)


def test_schedule_groups_independent_groups_share_default_start():
    from app.services.ktp_gpr_service import _schedule_groups

    a = make_group("a", duration_days=2)
    b = make_group("b", duration_days=5)
    _schedule_groups([a, b], [], date(2026, 3, 10))

    assert a.start_date == date(2026, 3, 10)
    assert b.start_date == date(2026, 3, 10)


def test_schedule_groups_takes_max_over_multiple_predecessors():
    from app.services.ktp_gpr_service import _schedule_groups

    a = make_group("a", duration_days=2)   # finish 01-02 → next 01-03
    b = make_group("b", duration_days=10)  # finish 01-10 → next 01-11
    c = make_group("c", duration_days=1)
    _schedule_groups([a, b, c], [("c", "a"), ("c", "b")], date(2026, 1, 1))

    assert c.start_date == date(2026, 1, 11)


# ── детерминированный расчёт длительностей ───────────────────────────────────

@pytest.mark.asyncio
async def test_compute_durations_norm_time_branch():
    from app.services.ktp_gpr_service import _compute_durations

    it = make_item("i1", "Кладка", quantity=100.0)
    g = make_group("g1", items=[it])

    norms = {
        "i1": {
            "norm_kind": "norm_time",
            "norm_value": 0.5,  # чел-ч на единицу
            "norm_unit": "чел-ч/м3",
            "brigade_size": 2,
        }
    }
    with (
        patch("app.services.ktp_gpr_service._ground_norms", AsyncMock(return_value={})),
        patch("app.services.ktp_gpr_service._ai_pick_norms", AsyncMock(return_value=norms)),
    ):
        await _compute_durations(AsyncMock(), [g], hours_per_day=8.0, warnings=[])

    # labor = 100 * 0.5 = 50 чел-ч; duration = ceil(50 / (2*8)) = 4
    assert it.norm_kind == "norm_time"
    assert it.duration_days == 4
    assert it.labor_hours == 50.0
    assert g.duration_days == 4


@pytest.mark.asyncio
async def test_compute_durations_vyrabotka_branch():
    from app.services.ktp_gpr_service import _compute_durations

    it = make_item("i1", "Окраска", quantity=100.0)
    g = make_group("g1", items=[it])

    norms = {
        "i1": {
            "norm_kind": "vyrabotka",
            "norm_value": 10.0,  # единиц на 1 рабочего в день
            "brigade_size": 2,
        }
    }
    with (
        patch("app.services.ktp_gpr_service._ground_norms", AsyncMock(return_value={})),
        patch("app.services.ktp_gpr_service._ai_pick_norms", AsyncMock(return_value=norms)),
    ):
        await _compute_durations(AsyncMock(), [g], hours_per_day=8.0, warnings=[])

    # duration = ceil(100 / (10 * 2)) = 5
    assert it.norm_kind == "vyrabotka"
    assert it.duration_days == 5


@pytest.mark.asyncio
async def test_compute_durations_fallback_when_no_norm_or_quantity():
    from app.services.ktp_gpr_service import _compute_durations

    it = make_item("i1", "Неясная работа", quantity=None)
    g = make_group("g1", items=[it])

    with (
        patch("app.services.ktp_gpr_service._ground_norms", AsyncMock(return_value={})),
        patch("app.services.ktp_gpr_service._ai_pick_norms", AsyncMock(return_value={})),
    ):
        warnings: list[str] = []
        await _compute_durations(AsyncMock(), [g], hours_per_day=8.0, warnings=warnings)

    assert it.norm_kind == "fallback"
    assert it.duration_days == 1
    assert any("норму" in w for w in warnings)
