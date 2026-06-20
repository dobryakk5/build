from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "app"))

from services.excel_work_material_matrix_parser import ExcelWorkMaterialMatrixParser

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _load_upload_service():
    """Load the isolated services archive without the rest of the backend tree."""
    if "services.upload_service" in sys.modules:
        return sys.modules["services.upload_service"]

    app = sys.modules.setdefault("app", types.ModuleType("app"))
    app.__path__ = []

    core = sys.modules.setdefault("app.core", types.ModuleType("app.core"))
    core.__path__ = []

    date_utils = types.ModuleType("app.core.date_utils")
    date_utils.working_days_between = lambda *args, **kwargs: 1
    date_utils.task_end_date = lambda *args, **kwargs: None
    sys.modules["app.core.date_utils"] = date_utils

    estimate_types = types.ModuleType("app.core.estimate_types")
    valid_types = {"work", "material", "mechanism", "overhead", "unknown"}

    def resolve_item_type(obj):
        raw = getattr(obj, "raw_data", None) or {}
        value = raw.get("item_type") or getattr(obj, "item_type", None) or "unknown"
        return value if value in valid_types else "unknown"

    estimate_types.resolve_item_type = resolve_item_type
    estimate_types.VALID_ESTIMATE_ITEM_TYPES = valid_types
    sys.modules["app.core.estimate_types"] = estimate_types

    models = types.ModuleType("app.models")
    for name in ("Job", "GanttTask", "Estimate", "EstimateBatch", "TaskDependency"):
        setattr(models, name, type(name, (), {}))
    sys.modules["app.models"] = models

    app_services = sys.modules.setdefault("app.services", types.ModuleType("app.services"))
    app_services.__path__ = []

    excel_parser = importlib.import_module("services.excel_parser")
    sys.modules["app.services.excel_parser"] = excel_parser

    gantt_calculations = types.ModuleType("app.services.gantt_calculations")
    gantt_calculations.DEFAULT_HOURS_PER_DAY = 8.0
    sys.modules["app.services.gantt_calculations"] = gantt_calculations

    gantt_builder = types.ModuleType("app.services.gantt_builder")
    gantt_builder.GanttBuilder = type("GanttBuilder", (), {})
    gantt_builder.GanttTaskDTO = type("GanttTaskDTO", (), {})
    sys.modules["app.services.gantt_builder"] = gantt_builder

    return importlib.import_module("services.upload_service")


@pytest.mark.parametrize(
    ("filename", "work_total", "material_total", "total", "vat", "grand_total"),
    [
        (
            "estimate_building_1.xlsx",
            8_097_673.26,
            5_803_718.51,
            13_901_391.77,
            3_058_306.19,
            16_959_697.96,
        ),
        (
            "estimate_building_2.xlsx",
            8_121_138.88,
            5_304_862.62,
            13_426_001.50,
            2_953_720.33,
            16_379_721.83,
        ),
    ],
)
def test_matrix_preview_includes_nested_materials_and_declared_totals(
    filename: str,
    work_total: float,
    material_total: float,
    total: float,
    vat: float,
    grand_total: float,
) -> None:
    upload = _load_upload_service()
    rows, meta = ExcelWorkMaterialMatrixParser().parse(FIXTURES / filename)

    # Totals are metadata only; matrix totals do not create ParsedRow subtotals.
    rows, subtotal_rows = upload._split_work_and_subtotal_rows(rows)
    assert subtotal_rows == []

    preview = upload._compute_preview(rows, subtotal_rows, meta)
    assert preview["type_breakdown"]["work"] == {"count": 36, "total": work_total}
    assert preview["type_breakdown"]["material"]["total"] == material_total
    assert preview["type_breakdown"]["material"]["count"] == sum(
        len(row.materials) for row in rows
    )
    assert preview["computed_work_total"] == work_total
    assert preview["computed_material_total"] == material_total
    assert preview["computed_total_without_vat"] == total
    assert preview["computed_total_all_rows"] == total
    assert preview["computed_vat_total"] == vat
    assert preview["computed_total_with_vat"] == grand_total
    assert preview["declared_total"] == total
    assert preview["declared_vat"] == vat
    assert preview["declared_vat_rate"] == 22.0
    assert preview["declared_total_with_vat"] == grand_total
    assert preview["difference"] == 0.0
    assert preview["difference_with_vat"] == 0.0


def test_declared_totals_new_and_legacy_formats() -> None:
    upload = _load_upload_service()

    new_meta = {
        "declared_totals": [
            {"kind": "total_without_vat", "total": 100.0},
            {"kind": "vat", "rate": 22, "total": 22.0},
            {"kind": "grand_total", "total": 122.0},
        ]
    }
    normalized = upload._declared_totals_from_meta(new_meta)
    assert normalized == {
        "total_without_vat": 100.0,
        "vat": 22.0,
        "vat_rate": 22.0,
        "total_with_vat": 122.0,
        "legacy_total": 122.0,
    }
    assert upload._declared_total_from_meta(new_meta) == 100.0

    old_grand = {"declared_totals": [{"kind": "grand_total", "total": 122.0}]}
    assert upload._declared_total_from_meta(old_grand) == 122.0

    old_sections = {
        "declared_totals": [
            {"kind": "section_total", "total": 40.004},
            {"kind": "section_total", "total": 59.996},
        ]
    }
    assert upload._declared_total_from_meta(old_sections) == 100.0
    assert upload._declared_total_from_meta({"declared_totals": {}}) is None


def test_material_preview_keeps_extended_fields_and_zero_values() -> None:
    upload = _load_upload_service()
    material = {
        "name": "Материал с нулевой стоимостью",
        "unit": "шт",
        "quantity": 0,
        "unit_price": 0,
        "total_price": 0,
        "source_num": "26.9",
        "parent_work_num": "26",
        "source_excel_row": 123,
        "item_type_confidence": 1.0,
    }

    result = upload._material_dict(material)
    assert result["quantity"] == 0
    assert result["unit_price"] == 0
    assert result["total_price"] == 0
    assert result["source_num"] == "26.9"
    assert result["parent_work_num"] == "26"
    assert result["source_excel_row"] == 123
    assert result["item_type_confidence"] == 1.0
    assert result["confidence"] == 1.0


def test_group_preview_contains_material_fields_and_material_totals() -> None:
    upload = _load_upload_service()
    rows, _meta = ExcelWorkMaterialMatrixParser().parse(FIXTURES / "estimate_building_2.xlsx")
    grouped = upload._build_preview_groups(rows)

    first_group = grouped["groups"][0]
    first_work = first_group["works"][0]
    first_material = first_work["materials"][0]
    flat_work = upload._row_preview_dict(rows[0], index=0)
    flat_material = flat_work["materials"][0]
    for key in (
        "unit_price",
        "source_num",
        "parent_work_num",
        "source_excel_row",
        "item_type_confidence",
    ):
        assert key in first_material
        assert key in flat_material

    assert sum(group["totals"]["material"]["count"] for group in grouped["groups"]) == 95
    assert round(sum(group["totals"]["material"]["total"] for group in grouped["groups"]), 2) == 5_304_862.62


def test_nested_material_is_not_counted_twice_when_also_top_level() -> None:
    upload = _load_upload_service()
    ParsedRow = importlib.import_module("services.excel_parser").ParsedRow
    nested = {
        "name": "Кабель",
        "quantity": 1,
        "total_price": 100,
        "source_num": "1.1",
        "source_excel_row": 11,
        "item_type": "material",
    }
    work = ParsedRow(
        work_name="Монтаж кабеля",
        total_price=50,
        materials=[nested],
        raw_data={"item_type": "work", "source_num": "1"},
    )
    material_row = ParsedRow(
        work_name="Кабель",
        quantity=1,
        total_price=100,
        raw_data={
            "item_type": "material",
            "source_num": "1.1",
            "source_excel_row": 11,
        },
    )

    preview = upload._compute_preview([work, material_row], [], {})
    assert preview["type_breakdown"]["material"] == {"count": 1, "total": 100.0}
    assert preview["computed_total_without_vat"] == 150.0
