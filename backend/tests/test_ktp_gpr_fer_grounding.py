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
    return g


def make_fer_item(
    iid: str,
    *,
    quantity=100.0,
    unit="м2",
    fer_match_source="auto",
    fer_h_hour=0.5,
    fer_unit_multiplier=1.0,
    fer_table_id=10,
    fer_row_id=101,
):
    it = MagicMock()
    it.id = iid
    it.name = "Облицовка"
    it.quantity = quantity
    it.unit = unit
    it.estimate_id = None
    it.duration_days = None
    it.labor_hours = None
    it.norm_kind = None
    it.norm_value = None
    it.norm_unit = None
    it.norm_source = None
    it.norm_ref = None
    it.brigade_size = None
    it.quantity_source = None
    it.fer_match_source = fer_match_source
    it.fer_h_hour = fer_h_hour
    it.fer_unit_multiplier = fer_unit_multiplier
    it.fer_table_id = fer_table_id
    it.fer_row_id = fer_row_id
    it.fer_unit = unit
    return it


# ── _apply_fer_norm ──────────────────────────────────────────────────────────

def test_apply_fer_norm_grounds_with_multiplier_one():
    from app.services.ktp_gpr_service import _apply_fer_norm

    it = make_fer_item("i1", quantity=100.0, fer_h_hour=0.5, fer_unit_multiplier=1.0)
    ok = _apply_fer_norm(it, hours_per_day=8.0, default_brigade=2)

    assert ok is True
    assert it.norm_source == "fer"
    assert it.norm_kind == "norm_time"
    # labor = 100 * (0.5/1) = 50; duration = ceil(50/(2*8)) = 4
    assert it.labor_hours == 50.0
    assert it.duration_days == 4
    assert it.brigade_size == 2
    assert "ФЕР" in it.norm_ref


def test_apply_fer_norm_divides_by_multiplier():
    from app.services.ktp_gpr_service import _apply_fer_norm

    # table stated "на 100 м2", h_hour per 100 m2 = 50 → per m2 = 0.5
    it = make_fer_item("i1", quantity=100.0, fer_h_hour=50.0, fer_unit_multiplier=100.0)
    ok = _apply_fer_norm(it, hours_per_day=8.0, default_brigade=2)

    assert ok is True
    assert it.norm_value == 0.5
    assert it.labor_hours == 50.0
    assert it.duration_days == 4


def test_apply_fer_norm_skips_review_source():
    from app.services.ktp_gpr_service import _apply_fer_norm

    it = make_fer_item("i1", fer_match_source="review")
    assert _apply_fer_norm(it, hours_per_day=8.0, default_brigade=2) is False


def test_apply_fer_norm_skips_unreconciled_unit():
    from app.services.ktp_gpr_service import _apply_fer_norm

    it = make_fer_item("i1", fer_unit_multiplier=None)  # unit not reconciled
    assert _apply_fer_norm(it, hours_per_day=8.0, default_brigade=2) is False


def test_apply_fer_norm_skips_missing_quantity():
    from app.services.ktp_gpr_service import _apply_fer_norm

    it = make_fer_item("i1", quantity=None)
    assert _apply_fer_norm(it, hours_per_day=8.0, default_brigade=2) is False


# ── _compute_durations bypasses AI for grounded items ────────────────────────

@pytest.mark.asyncio
async def test_compute_durations_bypasses_ai_for_fer_items():
    from app.services.ktp_gpr_service import _compute_durations

    grounded = make_fer_item("fer1", quantity=100.0, fer_h_hour=0.5, fer_unit_multiplier=1.0)
    # ungrounded item (no FER match) must still go to the AI picker
    ungrounded = make_fer_item("ai1", fer_match_source="review")
    g = make_group("g1", items=[grounded, ungrounded])

    ai_mock = AsyncMock(return_value={})
    with (
        patch("app.services.ktp_gpr_service._ground_norms", AsyncMock(return_value={})),
        patch("app.services.ktp_gpr_service._ai_pick_norms", ai_mock),
    ):
        await _compute_durations(
            AsyncMock(), [g], hours_per_day=8.0, warnings=[], default_brigade=2
        )

    # grounded item computed from ФЕР, not AI
    assert grounded.norm_source == "fer"
    assert grounded.duration_days == 4
    # AI picker was called with the grounded id in skip_ids
    _, kwargs = ai_mock.call_args
    assert "fer1" in kwargs["skip_ids"]
    assert "ai1" not in kwargs["skip_ids"]


# ── _ai_pick_norms skips fully-grounded groups (no LLM call) ──────────────────

@pytest.mark.asyncio
async def test_ai_pick_norms_skips_when_all_grounded():
    from app.services.ktp_gpr_service import _ai_pick_norms

    it = make_fer_item("i1")
    g = make_group("g1", items=[it])

    chat_mock = AsyncMock()
    with patch("app.services.ktp_gpr_service.create_chat_completion", chat_mock):
        result = await _ai_pick_norms(
            [g], [it], hints={}, warnings=[], skip_ids={"i1"}
        )

    assert result == {}
    chat_mock.assert_not_called()
