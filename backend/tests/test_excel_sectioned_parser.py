from pathlib import Path
import sys
from collections import Counter

import pytest
from openpyxl import Workbook

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.parser_factory import parse_estimate, PROFILE_EXCEL_SECTIONED_COST_SPLIT

GRUNT_XLSX = Path.home() / "Downloads" / "грунтовые работы.xlsx"


def _sectioned(tmp_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.append(["№ п/п", "Наименование работ, материалов", "Ед. изм.", "Кол-во",
               "Стоимость единицы, руб", "", "Всего"])
    ws.append(["", "", "", "", "Стоимость работ", "Стоимость материала", ""])
    ws.append(["", "РАБОТЫ котлован", "", "", "", "", ""])
    ws.append([1, "разработка грунта экскаватором", "м3", 500, 300, "-", 150000])
    ws.append([2, "засыпка котлована вручную", "м3", 300, 500, "-", 150000])
    ws.append(["", "НАКЛАДНЫЕ РАСХОДЫ", "", "", "", "", ""])
    ws.append([3, "Расходные материалы", "компл.", 1, 14500, "", 14500])
    ws.append([4, "Накладные, командировочные и транспортные расходы", "компл.", 1, 95000, "", 95000])
    ws.append([5, "Аренда спецтехники (Кран) - Заказчик", "смен", 2, "", "", 0])
    ws.append([6, "Вывоз мусора - Заказчик", "компл.", 1, "", "", 0])
    ws.append(["", "", "", "", "Итого работы :", 300000, ""])
    ws.append(["", "", "", "", "Всего по смете :", 409500, ""])
    ws.append(["", "Составил: ООО Ромашка", "", "", "", "", ""])
    path = tmp_path / "sectioned.xlsx"
    wb.save(path)
    wb.close()
    return path


def test_auto_detects_sectioned(tmp_path):
    rows, meta = parse_estimate(_sectioned(tmp_path))
    assert meta["strategy"] == "excel_sectioned_cost_split"
    assert meta["parser_profile"] == PROFILE_EXCEL_SECTIONED_COST_SPLIT


def test_blocks_drive_types_with_keyword_overrides(tmp_path):
    rows, meta = parse_estimate(_sectioned(tmp_path))
    by_name = {r.work_name: r.raw_data["item_type"] for r in rows}

    # РАБОТЫ block → work
    assert by_name["разработка грунта экскаватором"] == "work"
    assert by_name["засыпка котлована вручную"] == "work"
    # work row mentioning a machine → derived mechanism
    assert by_name.get("Экскаватором") == "mechanism"
    # НАКЛАДНЫЕ block with keyword overrides
    assert by_name["Расходные материалы"] == "material"
    assert by_name["Накладные, командировочные и транспортные расходы"] == "overhead"
    assert by_name["Аренда спецтехники (Кран) - Заказчик"] == "mechanism"
    assert by_name["Вывоз мусора - Заказчик"] == "overhead"
    # subtotals captured, footer excluded
    assert any("Итого работы" in d["label"] for d in meta["declared_totals"])
    assert "Составил: ООО Ромашка" not in by_name


@pytest.mark.skipif(not GRUNT_XLSX.exists(), reason="sample file not present")
def test_real_grunt_file_classifies_materials_and_mechanisms():
    rows, meta = parse_estimate(str(GRUNT_XLSX))
    assert meta["strategy"] == "excel_sectioned_cost_split"
    counts = Counter(r.raw_data["item_type"] for r in rows)
    assert counts["work"] > 0 and counts["overhead"] > 0
    assert counts["mechanism"] > 0  # Кран + derived from work rows
    assert counts["material"] > 0   # Расходные материалы
    by_name = {r.work_name: r.raw_data["item_type"] for r in rows}
    assert by_name.get("Аренда спецтехники (Кран) - Заказчик") == "mechanism"
