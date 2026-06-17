from pathlib import Path
import sys
from types import SimpleNamespace
from datetime import date

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.upload_service import (
    _build_preview_groups,
    _split_work_and_subtotal_rows,
    MAX_PREVIEW_GROUP_ROWS,
)
from app.services.excel_parser import ParsedRow

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


@pytest.mark.asyncio
async def test_preview_upload_skips_expensive_subtype_enrichment(monkeypatch, tmp_path: Path):
    from app.services import parser_factory, preview_session, upload_service

    class FakeUpload:
        filename = "large.xlsx"

        async def read(self):
            return b"xlsx"

    async def fail_enrich(*args, **kwargs):
        raise AssertionError("preview must not run full subtype enrichment")

    async def fake_save(payload):
        assert payload["tmp_path"].endswith(".xlsx")
        assert payload["type_breakdown"]["work"]["count"] == 1
        return "preview-id"

    def fake_parse(path, parser_profile="auto"):
        return [
            ParsedRow(
                section="Раздел",
                work_name="Монтаж перегородки",
                unit="м2",
                quantity=10,
                total_price=1000,
                raw_data={"item_type": "work"},
            )
        ], {"format": parser_factory.FORMAT_EXCEL, "strategy": "row", "parser_profile": "auto"}

    monkeypatch.setattr(upload_service, "_save_tmp", lambda data, suffix: str(tmp_path / f"preview{suffix}"))
    monkeypatch.setattr(upload_service, "_enrich_work_subtypes", fail_enrich)
    monkeypatch.setattr(parser_factory, "parse_estimate", fake_parse)
    monkeypatch.setattr(preview_session, "save_preview_session", fake_save)

    result = await upload_service.preview_upload_job(
        file=FakeUpload(),
        project_id="project-id",
        user_id="user-id",
        parser_profile="auto",
        start_date=date(2026, 6, 11),
        workers=3,
        estimate_kind=6,
        complex_mode=False,
        build_gantt=True,
        clarification_answers=None,
        hierarchy_selection=None,
        db=None,
    )

    assert result["preview_id"] == "preview-id"
    assert result["rows"][0]["subtype_code"] is None


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
