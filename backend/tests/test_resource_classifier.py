from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.resource_classifier import (
    classify_estimate_row,
    normalize_explicit_type,
    MODE_LABOR,
    MODE_MATERIALS,
)


def _type(name, **kw):
    return classify_estimate_row(name=name, **kw).item_type


# ── Sewera "Материалы / Трудозатраты" structural cases ─────────────────────────

def test_materials_mode_makes_material():
    assert _type("Песок речной, карьерный", spec="Коэф. усадки 10%",
                 unit="куб.м", current_mode=MODE_MATERIALS) == "material"


def test_mechanism_keyword_beats_materials_mode():
    assert _type("Бетононасос", unit="смена", current_mode=MODE_MATERIALS) == "mechanism"
    assert _type("Мини погрузчик с оператором", unit="смена",
                 current_mode=MODE_MATERIALS) == "mechanism"


def test_labor_mode_makes_work_even_for_volume_units():
    for name in ("Формирование корыта", "Засыпка песка", "Вибротрамбование песка"):
        assert _type(name, unit="куб.м", current_mode=MODE_LABOR) == "work", name


def test_overhead_keywords():
    assert _type("Транспортные расходы", unit="%", current_mode=MODE_LABOR) == "overhead"
    assert _type("Накладные расходы", unit="%", current_mode=MODE_LABOR) == "overhead"
    assert _type("ИТР, снабжение, надзор", unit="%") == "overhead"


def test_percent_unit_is_overhead():
    assert _type("Прочие затраты", unit="%") == "overhead"


# ── Unit signals (маш.-ч / чел.-ч / смена) ─────────────────────────────────────

def test_machine_time_unit_is_mechanism():
    assert _type("Экскаватор одноковшовый", unit="маш.-ч") == "mechanism"


def test_labor_time_unit_is_work():
    assert _type("Затраты труда рабочих", unit="чел.-ч") == "work"


def test_bare_shift_is_not_auto_mechanism():
    # "смена" alone must not force mechanism — decided by text instead.
    assert _type("Укладка плитки", unit="смена") == "work"
    assert _type("Бетононасос", unit="смена") == "mechanism"


# ── normalize_explicit_type (excel_typed_journal "Тип" column) ─────────────────

def test_normalize_explicit_type():
    assert normalize_explicit_type("Работа") == ("work", None)
    assert normalize_explicit_type("Материал") == ("material", None)
    assert normalize_explicit_type("Механизм") == ("mechanism", None)
    assert normalize_explicit_type("Накладные") == ("overhead", None)
    assert normalize_explicit_type("Люди") == ("work", "labor")
    assert normalize_explicit_type("") == ("unknown", None)
    assert normalize_explicit_type(None) == ("unknown", None)
