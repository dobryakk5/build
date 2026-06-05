from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))


def make_group(gid: str, items=None, title: str = "", wt_code=None):
    g = MagicMock()
    g.id = gid
    g.duration_days = 1
    g.start_date = None
    g.items = items or []
    g.accepted_items = items or []
    g.title = title or gid
    g.wt_code = wt_code
    g.prod_lag_after = 0
    return g


def make_item(iid: str, *, quantity=100.0, unit="м3", estimate_id=None):
    it = MagicMock()
    it.id = iid
    it.name = "Кладка"
    it.quantity = quantity
    it.unit = unit
    it.estimate_id = estimate_id
    it.session_id = "sess1"
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


def make_spec(code="2.1", unit="м3", output_per_day=25.0, crew_size=2, lag_after_days=0):
    s = MagicMock()
    s.subtype_code = code
    s.unit = unit
    s.output_per_day = output_per_day
    s.crew_size = crew_size
    s.lag_after_days = lag_after_days
    return s


# ── _apply_subtype_norm ──────────────────────────────────────────────────────

def test_apply_subtype_norm_grounds_from_productivity():
    from app.services.ktp_gpr_service import _apply_subtype_norm

    it = make_item("i1", quantity=100.0)
    spec = make_spec(output_per_day=25.0, crew_size=2)
    ok = _apply_subtype_norm(it, spec, hours_per_day=8.0, default_brigade=3)

    assert ok is True
    assert it.norm_source == "manual"
    assert it.norm_kind == "vyrabotka"
    assert it.norm_value == 25.0
    # duration = ceil(100 / 25) = 4; brigade = crew_size = 2
    assert it.duration_days == 4
    assert it.brigade_size == 2
    # labor = 4 * 2 * 8 = 64
    assert it.labor_hours == 64.0
    assert "подтип" in it.norm_ref


def test_apply_subtype_norm_falls_back_to_default_brigade():
    from app.services.ktp_gpr_service import _apply_subtype_norm

    it = make_item("i1", quantity=50.0)
    spec = make_spec(output_per_day=10.0, crew_size=None)
    ok = _apply_subtype_norm(it, spec, hours_per_day=8.0, default_brigade=4)

    assert ok is True
    assert it.brigade_size == 4  # из default_brigade
    assert it.duration_days == 5  # ceil(50/10)


def test_apply_subtype_norm_skips_without_spec():
    from app.services.ktp_gpr_service import _apply_subtype_norm

    it = make_item("i1")
    assert _apply_subtype_norm(it, None, hours_per_day=8.0, default_brigade=2) is False


def test_apply_subtype_norm_skips_without_output():
    from app.services.ktp_gpr_service import _apply_subtype_norm

    it = make_item("i1")
    assert _apply_subtype_norm(it, make_spec(output_per_day=None), 8.0, 2) is False
    assert _apply_subtype_norm(it, make_spec(output_per_day=0), 8.0, 2) is False


def test_apply_subtype_norm_skips_missing_quantity():
    from app.services.ktp_gpr_service import _apply_subtype_norm

    it = make_item("i1", quantity=None)
    assert _apply_subtype_norm(it, make_spec(), 8.0, 2) is False


# ── _compute_durations grounds from subtypes and bypasses AI ─────────────────

@pytest.mark.asyncio
async def test_compute_durations_bypasses_ai_for_subtype_items():
    from app.services.ktp_gpr_service import _compute_durations

    grounded = make_item("g1", quantity=100.0, unit="м3")
    ungrounded = make_item("u1", quantity=100.0, unit="шт")
    g = make_group("grp", items=[grounded, ungrounded])

    specs = {("2.1", "м3"): make_spec(code="2.1", unit="м3", output_per_day=25.0, crew_size=2, lag_after_days=3)}

    def resolve(it, est, taxonomy, by_code):
        return ("2.1", "Кладка", None, "м3") if it.id == "g1" else ("3.5", "Прочее", None, "шт")

    ai_mock = AsyncMock(return_value={})
    with (
        patch("app.services.ktp_gpr_service._load_subtype_specs", AsyncMock(return_value=specs)),
        patch("app.services.work_taxonomy_service.load_taxonomy", AsyncMock(return_value=[])),
        patch("app.services.ktp_estimate_service._resolve_item_subtype", side_effect=resolve),
        patch("app.services.ktp_gpr_service._ground_norms", AsyncMock(return_value={})),
        patch("app.services.ktp_gpr_service._ai_pick_norms", ai_mock),
    ):
        await _compute_durations(
            AsyncMock(), [g], hours_per_day=8.0, warnings=[], default_brigade=3
        )

    # grounded item computed from productivity, not AI
    assert grounded.norm_source == "manual"
    assert grounded.duration_days == 4
    # лаг подтипа предшественника записан на группу
    assert g.prod_lag_after == 3
    # AI picker получил grounded id в skip_ids, ungrounded — нет
    _, kwargs = ai_mock.call_args
    assert "g1" in kwargs["skip_ids"]
    assert "u1" not in kwargs["skip_ids"]
