from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "app"))

from services.excel_work_material_matrix_parser import (
    ExcelWorkMaterialMatrixParser,
    PROFILE_NAME,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.mark.parametrize(
    ("filename", "sheet", "works", "materials", "source_rows"),
    [
        ("estimate_building_1.xlsx", "ЭОМ-1", 36, 97, 134),
        ("estimate_building_2.xlsx", "ЭОМ-2", 36, 95, 132),
    ],
)
def test_real_estimates_are_detected_and_fold_materials(
    filename: str,
    sheet: str,
    works: int,
    materials: int,
    source_rows: int,
) -> None:
    parser = ExcelWorkMaterialMatrixParser()
    path = FIXTURES / filename

    detected = parser.detect(path)
    assert detected["detected"] is True
    assert detected["confidence"] == 1.0
    assert detected["sheet"] == sheet

    rows, meta = parser.parse(path)
    assert len(rows) == works
    assert sum(len(row.materials) for row in rows) == materials
    assert meta["strategy"] == PROFILE_NAME
    assert meta["parser_profile"] == PROFILE_NAME
    assert meta["source_rows_found"] == source_rows
    assert meta["work_rows_found"] == works
    assert meta["material_rows_found"] == materials
    assert meta["skipped_technical_rows"] == 1
    assert meta["orphan_material_rows"] == []
    assert all(row.raw_data["item_type"] == "work" for row in rows)
    assert all(row.raw_data["item_type_confidence"] == 1.0 for row in rows)
    assert all(
        material["item_type"] == "material"
        for row in rows
        for material in row.materials
    )


def test_building_2_uses_material_columns_and_preserves_zero_cost_material() -> None:
    rows, _ = ExcelWorkMaterialMatrixParser().parse(FIXTURES / "estimate_building_2.xlsx")
    materials = {
        material["source_num"]: material
        for row in rows
        for material in row.materials
    }

    # E/H are zero for 5.2, but G/J contain the actual material price.
    assert materials["5.2"]["unit_price"] == pytest.approx(18091.08)
    assert materials["5.2"]["total_price"] == pytest.approx(108546.48)

    # A valid numbered material must survive even when all price columns are zero.
    assert materials["26.9"]["quantity"] == 2.0
    assert materials["26.9"]["unit_price"] == 0.0
    assert materials["26.9"]["total_price"] == 0.0
    assert materials["26.9"]["parent_work_num"] == "26"


def test_material_is_attached_by_parent_number_not_last_physical_work() -> None:
    rows, meta = ExcelWorkMaterialMatrixParser().parse(FIXTURES / "non_adjacent_matrix.xlsx")
    by_num = {row.raw_data["source_num"]: row for row in rows}

    assert len(rows) == 3
    assert meta["material_rows_found"] == 3
    assert [m["source_num"] for m in by_num["1"].materials] == ["1.1"]
    assert [m["source_num"] for m in by_num["2"].materials] == ["2.1"]
    assert [m["source_num"] for m in by_num["3"].materials] == ["3.1"]


def _install_partial_archive_app_stub() -> None:
    """The delivered archive contains services only, not app/core.

    In the full backend these modules already exist.  The stub lets this isolated
    archive exercise parser_factory without changing production imports.
    """
    if "app.core.estimate_types" in sys.modules:
        return
    app = types.ModuleType("app")
    app.__path__ = []
    core = types.ModuleType("app.core")
    core.__path__ = []
    estimate_types = types.ModuleType("app.core.estimate_types")
    constants = {
        "ESTIMATE_ITEM_TYPE_MATERIAL": "material",
        "ESTIMATE_ITEM_TYPE_MECHANISM": "mechanism",
        "ESTIMATE_ITEM_TYPE_OVERHEAD": "overhead",
        "ESTIMATE_ITEM_TYPE_UNKNOWN": "unknown",
        "ESTIMATE_ITEM_TYPE_WORK": "work",
    }
    for name, value in constants.items():
        setattr(estimate_types, name, value)
    sys.modules.update({
        "app": app,
        "app.core": core,
        "app.core.estimate_types": estimate_types,
    })


def test_parser_factory_auto_and_explicit_profile() -> None:
    try:
        from services.parser_factory import (  # type: ignore
            PROFILE_EXCEL_WORK_MATERIAL_MATRIX,
            parse_estimate,
        )
    except ModuleNotFoundError as exc:
        if not exc.name or not exc.name.startswith("app"):
            raise
        _install_partial_archive_app_stub()
        # Clear a partially imported module before retrying.
        sys.modules.pop("services.parser_factory", None)
        from services.parser_factory import (  # type: ignore
            PROFILE_EXCEL_WORK_MATERIAL_MATRIX,
            parse_estimate,
        )

    path = FIXTURES / "estimate_building_1.xlsx"
    auto_rows, auto_meta = parse_estimate(path)
    explicit_rows, explicit_meta = parse_estimate(
        path,
        parser_profile=PROFILE_EXCEL_WORK_MATERIAL_MATRIX,
    )

    assert len(auto_rows) == len(explicit_rows) == 36
    assert auto_meta["parser_profile"] == PROFILE_EXCEL_WORK_MATERIAL_MATRIX
    assert explicit_meta["parser_profile"] == PROFILE_EXCEL_WORK_MATERIAL_MATRIX
    assert sum(len(row.materials) for row in auto_rows) == 97
