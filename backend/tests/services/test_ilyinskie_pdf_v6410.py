from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.services.materials_labor_pdf_parser import MaterialsLaborPdfParser
from app.services.upload_service import (
    _enrich_work_stages_sync,
    _enrich_work_subtypes_sync,
)


PDF_ENV = "ILYINSKIE_PDF"


@pytest.mark.integration
def test_ilyinskie_pdf_regression():
    file_path = Path(os.environ.get(PDF_ENV, ""))
    if not file_path.is_file():
        pytest.skip(f"Set {PDF_ENV} to Ильинские сады 02.04.2026.pdf")

    rows, meta = MaterialsLaborPdfParser().parse(file_path)
    reconciliation = meta["summary_reconciliation"]
    assert reconciliation["declared_total"] == pytest.approx(12_725_959.27)
    assert reconciliation["detail_rows_total"] == pytest.approx(12_225_959.27)
    assert reconciliation["summary_only_total"] == pytest.approx(500_000.00)
    assert reconciliation["computed_import_total"] == pytest.approx(12_725_959.27)
    assert reconciliation["difference"] == pytest.approx(0.00)
    assert reconciliation["summary_only_count"] == 1

    selection = {
        "estimate_type_id": "landscape_hardscape",
        "estimate_type_number": "9",
        "project_variant_id": "9.4",
        "project_variant_number": "9.4",
        "estimate_profile_id": "landscape_hardscape",
    }
    preclassified = _enrich_work_subtypes_sync(rows, selection)
    _enrich_work_stages_sync(rows, selection, preclassified)

    def matches(name: str, section: str | None = None):
        return [
            row for row in rows
            if name.casefold() in (row.work_name or "").casefold()
            and (section is None or section.casefold() in (row.section or "").casefold())
        ]

    disposal = matches("Утилизация грунта за пределы участка")
    assert len(disposal) == 1
    assert disposal[0].raw_data["summary_only"] is True
    assert disposal[0].raw_data["work_stage_number"] == "9.4.2"
    assert disposal[0].raw_data["work_subtype_code"] == "earthworks/soil_disposal"

    art_masonry = matches("Выполнение кладки", "АРТ-объекта")
    assert len(art_masonry) == 1
    assert art_masonry[0].raw_data["work_stage_number"] == "9.4.6"
    assert art_masonry[0].raw_data["work_subtype_code"] == "landscape/decorative_block_walls"

    grading = matches("Планировка участка спецтехникой")
    assert grading
    assert grading[0].raw_data["synthetic_parent"] is True
    assert grading[0].raw_data["work_stage_number"] == "9.4.11"

    assert not [
        row for row in rows
        if row.raw_data.get("row_role") == "work"
        and not row.raw_data.get("work_subtype_code")
    ]
    assert not [
        row for row in rows
        if row.raw_data.get("row_role") != "work"
        and row.raw_data.get("work_subtype_code")
    ]
