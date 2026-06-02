from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.upload_service import (
    _build_preview_groups,
    _split_work_and_subtotal_rows,
    MAX_PREVIEW_GROUP_ROWS,
)

SEWERA_PDF = Path.home() / "Downloads" / "Ильинские сады 02.04.2026.pdf"


def _row(name, item_type, section, total=100.0, order=0, materials=None):
    return SimpleNamespace(
        section=section, work_name=name, unit="шт", quantity=1, unit_price=total,
        total_price=total, row_order=order, materials=materials or [],
        raw_data={"item_type": item_type},
    )


def test_groups_by_section_with_row_order_and_nested_materials():
    rows = [
        _row("Устройство фундамента", "work", "Фундамент", order=0,
             materials=[{"name": "Бетон В25", "unit": "м3", "qty": 40, "total": 200000}]),
        _row("Бетон В25", "material", "Фундамент", order=1),
        _row("Кладка стен", "work", "Стены", order=2),
    ]
    out = _build_preview_groups(rows)
    assert [g["section"] for g in out["groups"]] == ["Фундамент", "Стены"]
    found = out["groups"][0]
    assert len(found["works"]) == 1 and len(found["materials"]) == 1
    assert found["works"][0]["row_order"] == 0
    # nested ParsedRow.materials surfaced under the work
    assert found["works"][0]["materials"][0]["name"] == "Бетон В25"


def test_no_section_bucket_and_count():
    rows = [_row("Прочее", "work", None, order=0), _row("Ещё", "material", None, order=1)]
    out = _build_preview_groups(rows)
    assert out["no_section_count"] == 2
    assert out["groups"][0]["section"] == "Без раздела"


def test_truncation_keeps_totals_full():
    n = MAX_PREVIEW_GROUP_ROWS + 50
    rows = [_row(f"W{i}", "work", "Раздел", total=10.0, order=i) for i in range(n)]
    out = _build_preview_groups(rows)
    assert out["truncated"] is True
    g = out["groups"][0]
    # totals count ALL rows even though the list is capped
    assert g["totals"]["work"]["count"] == n
    assert len(g["works"]) <= MAX_PREVIEW_GROUP_ROWS


@pytest.mark.skipif(not SEWERA_PDF.exists(), reason="Sewera sample PDF not present")
def test_sewera_groups_have_works_and_materials_together():
    from app.services.parser_factory import parse_estimate
    rows, _meta = parse_estimate(str(SEWERA_PDF))
    rows, _ = _split_work_and_subtotal_rows(rows)
    out = _build_preview_groups(rows)
    assert len(out["groups"]) > 1

    otmostka = next(g for g in out["groups"] if "Основание отмостки" in g["section"])
    assert otmostka["works"] and otmostka["materials"]

    # totals across groups == total of all rows
    grand = sum(
        b["total"] for g in out["groups"] for b in g["totals"].values()
    )
    all_rows_total = sum(float(r.total_price or 0) for r in rows)
    assert round(grand, 2) == round(all_rows_total, 2)
