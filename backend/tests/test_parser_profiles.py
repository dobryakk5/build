from pathlib import Path
import sys

import pytest
from openpyxl import Workbook

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.parser_factory import (
    parse_estimate,
    ParserProfileNotImplemented,
    PROFILE_AUTO,
    PROFILE_PDF_MATERIALS_LABOR,
)

SEWERA_PDF = Path.home() / "Downloads" / "Ильинские сады 02.04.2026.pdf"
_has_pdf = SEWERA_PDF.exists()


def _simple_xlsx(tmp_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.append(["Наименование работ", "Ед. изм.", "Кол-во", "Цена", "Сумма"])
    ws.append(["Кладка стен из кирпича", "м3", 10, 5000, 50000])
    ws.append(["Устройство стяжки пола", "м2", 120, 800, 96000])
    ws.append(["Штукатурка стен", "м2", 200, 600, 120000])
    ws.append(["Окраска потолков", "м2", 150, 400, 60000])
    ws.append(["Монтаж перегородок ГКЛ", "м2", 80, 1200, 96000])
    path = tmp_path / "simple.xlsx"
    wb.save(path)
    wb.close()
    return path


def test_unknown_profile_raises_value_error(tmp_path):
    with pytest.raises(ValueError):
        parse_estimate(_simple_xlsx(tmp_path), parser_profile="bogus")


def test_unimplemented_profile_raises(tmp_path):
    with pytest.raises(ParserProfileNotImplemented) as ei:
        parse_estimate(_simple_xlsx(tmp_path), parser_profile="excel_work_list")
    assert ei.value.parser_profile == "excel_work_list"


def test_unimplemented_profile_allow_fallback(tmp_path):
    rows, meta = parse_estimate(_simple_xlsx(tmp_path), parser_profile="excel_work_list",
                                allow_fallback=True)
    assert meta["parser_profile"] == PROFILE_AUTO


def test_pdf_profile_on_excel_raises(tmp_path):
    with pytest.raises(ValueError):
        parse_estimate(_simple_xlsx(tmp_path), parser_profile=PROFILE_PDF_MATERIALS_LABOR)


def test_auto_tags_rows_with_profile(tmp_path):
    rows, meta = parse_estimate(_simple_xlsx(tmp_path))
    assert meta["parser_profile"] == PROFILE_AUTO
    assert rows and rows[0].raw_data.get("parser_profile") == PROFILE_AUTO


@pytest.mark.skipif(not _has_pdf, reason="Sewera sample PDF not present")
def test_pdf_materials_labor_profile_routes_to_parser():
    rows, meta = parse_estimate(str(SEWERA_PDF), parser_profile=PROFILE_PDF_MATERIALS_LABOR)
    assert meta["strategy"] == "pdf_materials_labor"
    assert meta["parser_profile"] == PROFILE_PDF_MATERIALS_LABOR
    assert rows
