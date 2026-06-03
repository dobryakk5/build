from pathlib import Path
import sys

import pytest
from openpyxl import Workbook

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.parser_factory import parse_estimate, PROFILE_EXCEL_TYPED_JOURNAL


def _journal(tmp_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Смета"
    ws.append(["№", "Позиция", "Тип", "Ед.изм", "Кол-во", "Цена за ед.", "Стоимость"])
    ws.append(["1", "Фундамент", "", "", "", "", ""])               # group
    ws.append(["1.1", "Устройство фундамента", "Работа", "м3", 40, 6000, 240000])
    ws.append(["1.2", "Бетон В25", "Материал", "м3", 40, 5000, 200000])
    ws.append(["1.3", "Экскаватор", "Механизм", "смена", 2, 30000, 60000])
    ws.append(["1.4", "Транспортные", "Накладные", "%", 5, None, 15000])
    ws.append(["1.5", "Бригада монтажников", "Люди", "чел.-ч", 100, 500, 50000])
    ws.append(["", "ИТОГО", "", "", "", "", 565000])
    path = tmp_path / "journal.xlsx"
    wb.save(path)
    wb.close()
    return path


def test_typed_journal_trusts_type_column(tmp_path):
    rows, meta = parse_estimate(_journal(tmp_path), parser_profile=PROFILE_EXCEL_TYPED_JOURNAL)
    assert meta["strategy"] == "excel_typed_journal"
    by_type = {r.work_name: r.raw_data["item_type"] for r in rows}

    assert by_type["Устройство фундамента"] == "work"
    assert by_type["Бетон В25"] == "material"
    assert by_type["Экскаватор"] == "mechanism"
    assert by_type["Транспортные"] == "overhead"
    assert by_type["Бригада монтажников"] == "work"
    # ИТОГО is a subtotal and must not be emitted as a row.
    assert "ИТОГО" not in by_type


def test_auto_detects_typed_journal(tmp_path):
    # No explicit profile — auto must detect the «Тип» column and use the typed parser.
    rows, meta = parse_estimate(_journal(tmp_path))
    assert meta["strategy"] == "excel_typed_journal"
    assert meta["parser_profile"] == "excel_typed_journal"


def test_typed_journal_tags_labor_subtype_and_profile(tmp_path):
    rows, _ = parse_estimate(_journal(tmp_path), parser_profile=PROFILE_EXCEL_TYPED_JOURNAL)
    people = next(r for r in rows if r.work_name == "Бригада монтажников")
    assert people.raw_data["resource_subtype"] == "labor"
    assert all(r.raw_data["parser_profile"] == "excel_typed_journal" for r in rows)
    assert all(r.section == "Фундамент" for r in rows)
