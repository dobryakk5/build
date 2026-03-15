# backend/app/services/excel_parser.py
"""
Гибкий парсер Excel-смет.

Поддерживает два формата:
  1. СТРОЧНЫЙ  — классическая таблица с заголовком сверху (ГрандСмета, CourtDoc, Excel вручную)
  2. СТОЛБЦОВЫЙ — каждая работа = столбец, строки = атрибуты (редко, но встречается)

Алгоритм выбора стратегии:
  DetectorEngine сначала сканирует файл и выбирает стратегию,
  затем соответствующий Parser разбирает данные.
"""

from __future__ import annotations
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

import openpyxl
import pandas as pd
from openpyxl.worksheet.worksheet import Worksheet


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ParsedRow:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    section: Optional[str] = None
    work_name: str = ""
    unit: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    total_price: Optional[float] = None
    row_order: int = 0
    raw_data: dict = field(default_factory=dict)
    source_strategy: str = "unknown"   # для отладки: "row" | "column"


# ─────────────────────────────────────────────────────────────────────────────
# ALIAS DICTIONARY  (расширяемый, регистронезависимый)
# ─────────────────────────────────────────────────────────────────────────────

ALIASES: dict[str, list[str]] = {
    # ── Наименование работы ──────────────────────────────────────────────────
    "work_name": [
        # Русский
        "наименование", "наименование работ", "наименование работ и затрат",
        "наименование позиции", "описание работ", "вид работ",
        "вид работ и затрат", "работы", "работа", "содержание работ",
        "состав работ", "операция", "позиция", "статья затрат",
        "номенклатура", "наим.", "работы/материалы",
        # English
        "name", "work name", "description", "task", "activity",
        "item", "work item", "scope of work",
    ],

    # ── Единица измерения ────────────────────────────────────────────────────
    "unit": [
        # Русский
        "ед.изм", "ед. изм", "ед. изм.", "единица", "единица измерения",
        "единицы измерения", "ед", "ед.", "изм.", "измерение",
        "ед.изм.", "е.и.", "е. и.",
        # English
        "unit", "units", "uom", "u/m", "measure",
    ],

    # ── Количество / объём ───────────────────────────────────────────────────
    "quantity": [
        # Русский
        "кол-во", "кол.", "кол", "количество", "объем", "объём",
        "объем работ", "объём работ", "кол-во работ", "количество работ",
        "кол-во ед", "кол. ед.", "кол-во единиц", "итого объем",
        "всего объем", "объем по проекту", "проектный объем",
        "факт", "факт.кол", "фактическое количество",
        # English
        "qty", "quantity", "amount", "vol", "volume", "count",
    ],

    # ── Цена за единицу ──────────────────────────────────────────────────────
    "unit_price": [
        # Русский
        "цена", "цена за ед", "цена за ед.", "цена за единицу",
        "расценка", "стоимость ед", "стоимость ед.", "стоимость единицы",
        "цена ед.изм", "цена за ед.изм", "ед. стоимость",
        "стоим. ед.", "норм. цена", "базовая цена",
        "цена с ндс", "цена без ндс", "цена (без ндс)",
        # English
        "unit price", "price", "rate", "unit cost", "unit rate",
        "cost per unit", "price per unit",
    ],

    # ── Итоговая стоимость ───────────────────────────────────────────────────
    "total_price": [
        # Русский
        "сумма", "сумма всего", "итого", "итого стоимость",
        "общая стоимость", "стоимость", "стоимость работ",
        "стоимость всего", "стоимость итого", "итоговая стоимость",
        "всего", "всего сумма", "всего стоимость",
        "итог", "итог сумма", "итоговая сумма",
        "сумма с ндс", "сумма без ндс", "итого с ндс", "итого без ндс",
        "стоимость с ндс", "стоимость без ндс",
        "общая сумма", "общ. стоимость",
        # English
        "total", "total price", "total cost", "amount",
        "sum", "subtotal", "ext price", "extended price",
    ],

    # ── Трудоёмкость ─────────────────────────────────────────────────────────
    "labor_hours": [
        "трудоёмкость", "трудоемкость", "чел.-час", "чел.час", "чел/час",
        "чел-час", "норма времени", "затраты труда", "трудозатраты",
        "человеко-часы", "нормо-часы", "н/час", "н.час",
        "labor hours", "man hours", "manhours", "hours",
    ],

    # ── Код позиции (ЕНиР / ГЭСН) ────────────────────────────────────────────
    "enir_code": [
        "шифр", "код", "код расценки", "расценка", "норм. шифр",
        "шифр расценки", "ценник", "гэсн", "фер", "тер", "enir",
        "обоснование", "основание", "ссылка", "норматив",
        "code", "item code", "ref", "reference",
    ],

    # ── Материалы ─────────────────────────────────────────────────────────────
    "material_cost": [
        "материалы", "стоимость материалов", "мат.", "мат-лы",
        "материальные затраты", "стоимость матер",
        "materials", "material cost",
    ],
}


def normalize(s: str) -> str:
    """Нижний регистр, убрать лишние пробелы и спецсимволы для сравнения."""
    return re.sub(r"\s+", " ", str(s).lower().strip().replace("\n", " "))


def match_alias(cell_value: str, field_name: str) -> bool:
    """Проверяем, соответствует ли значение ячейки полю field_name."""
    val = normalize(cell_value)
    return any(alias in val or val in alias for alias in ALIASES[field_name])


def match_any_field(cell_value: str) -> Optional[str]:
    """Определяем поле по значению ячейки."""
    for field_name in ALIASES:
        if match_alias(cell_value, field_name):
            return field_name
    return None


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY PROTOCOL
# ─────────────────────────────────────────────────────────────────────────────

class ParserStrategy(Protocol):
    def can_parse(self, ws: Worksheet) -> float:
        """Возвращает уверенность [0.0 – 1.0], что этот формат подходит."""
        ...

    def parse(self, ws: Worksheet) -> list[ParsedRow]:
        ...


# ─────────────────────────────────────────────────────────────────────────────
# СТРАТЕГИЯ 1: СТРОЧНАЯ (классическая таблица)
# ─────────────────────────────────────────────────────────────────────────────

class RowOrientedParser:
    """
    Формат:
        Строка 1: ... (возможно пустая / шапка)
        Строка N: [Наименование] [Ед.] [Кол-во] [Цена] [Сумма]   ← заголовки
        Строка N+1...: данные
    """

    name = "row"

    def can_parse(self, ws: Worksheet) -> float:
        header_row = self._find_header_row(ws)
        if header_row is None:
            return 0.0
        col_map = self._map_columns(ws, header_row)
        # Уверенность растёт с количеством найденных колонок
        found = len([v for v in col_map.values() if v is not None])
        return min(1.0, found / 3)   # нашли ≥3 колонок → уверенность 1.0

    def parse(self, ws: Worksheet) -> list[ParsedRow]:
        header_row = self._find_header_row(ws)
        if header_row is None:
            return []

        col_map = self._map_columns(ws, header_row)
        rows = self._extract_rows(ws, header_row, col_map)
        return rows

    # ── internals ─────────────────────────────────────────────────────────────

    def _find_header_row(self, ws: Worksheet) -> Optional[int]:
        """
        Ищем строку, в которой ≥2 ячеек совпадают с нашими алиасами.
        Сканируем первые 40 строк.
        """
        for row_idx in range(1, min(41, ws.max_row + 1)):
            hits = 0
            for col_idx in range(1, min(ws.max_column + 1, 30)):
                cell = ws.cell(row_idx, col_idx).value
                if cell and match_any_field(str(cell)):
                    hits += 1
            if hits >= 2:
                return row_idx
        return None

    def _map_columns(self, ws: Worksheet, header_row: int) -> dict[str, Optional[int]]:
        """
        Возвращает {field_name: col_index (1-based)} для всех полей.
        Если колонка не найдена — None.
        """
        col_map: dict[str, Optional[int]] = {f: None for f in ALIASES}
        for col_idx in range(1, ws.max_column + 1):
            cell_val = ws.cell(header_row, col_idx).value
            if not cell_val:
                continue
            field = match_any_field(str(cell_val))
            if field and col_map[field] is None:  # первое совпадение побеждает
                col_map[field] = col_idx
        return col_map

    def _extract_rows(
        self, ws: Worksheet, header_row: int, col_map: dict
    ) -> list[ParsedRow]:
        results: list[ParsedRow] = []
        current_section: Optional[str] = None
        order = 0

        for row_idx in range(header_row + 1, ws.max_row + 1):
            row_values = {
                field: ws.cell(row_idx, col).value
                for field, col in col_map.items()
                if col is not None
            }

            # Пропускаем полностью пустые строки
            if not any(v for v in row_values.values() if v is not None):
                continue

            work_name = row_values.get("work_name")

            # Определяем: это раздел или строка данных?
            if self._is_section(row_values, col_map):
                current_section = str(work_name).strip() if work_name else current_section
                continue

            if not work_name:
                continue

            results.append(ParsedRow(
                section=current_section,
                work_name=str(work_name).strip(),
                unit=_to_str(row_values.get("unit")),
                quantity=_to_float(row_values.get("quantity")),
                unit_price=_to_float(row_values.get("unit_price")),
                total_price=_to_float(row_values.get("total_price")),
                row_order=order,
                raw_data={f: str(v) for f, v in row_values.items() if v is not None},
                source_strategy="row",
            ))
            order += 1

        return results

    def _is_section(self, row_values: dict, col_map: dict) -> bool:
        """
        Раздел = есть work_name, но нет числовых значений.
        Дополнительно: текст не слишком длинный (< 120 символов).
        """
        work_name = row_values.get("work_name")
        if not work_name:
            return False
        has_numbers = any(
            _to_float(row_values.get(f)) is not None
            for f in ("quantity", "unit_price", "total_price")
        )
        return not has_numbers and len(str(work_name)) < 120


# ─────────────────────────────────────────────────────────────────────────────
# СТРАТЕГИЯ 2: СТОЛБЦОВАЯ
# ─────────────────────────────────────────────────────────────────────────────

class ColumnOrientedParser:
    """
    Формат (встречается в Excel-сметах подрядчиков):

        Строка 1: Наименование  | Монтаж кровли | Устройство стяжки | ...
        Строка 2: Ед.изм        | м2            | м2                | ...
        Строка 3: Количество    | 450           | 320               | ...
        Строка 4: Цена за ед.   | 850           | 400               | ...
        Строка 5: Сумма         | 382500        | 128000            | ...

    Т.е. первая колонка = метки строк, остальные = отдельные работы.
    """

    name = "column"
    LABEL_COL = 1       # колонка с метками (1-based)
    DATA_START_COL = 2  # с какой колонки начинаются данные

    def can_parse(self, ws: Worksheet) -> float:
        label_fields = self._detect_label_rows(ws)
        # Если в первой колонке нашли ≥3 алиаса → скорее всего столбцовый формат
        return min(1.0, len(label_fields) / 3)

    def parse(self, ws: Worksheet) -> list[ParsedRow]:
        label_map = self._detect_label_rows(ws)
        if not label_map:
            return []

        results: list[ParsedRow] = []
        order = 0

        for col_idx in range(self.DATA_START_COL, ws.max_column + 1):
            work_name_row = label_map.get("work_name")
            work_name_val = ws.cell(work_name_row, col_idx).value if work_name_row else None

            if not work_name_val:
                continue

            def get(field: str):
                row = label_map.get(field)
                return ws.cell(row, col_idx).value if row else None

            results.append(ParsedRow(
                section=None,          # в столбцовом формате разделы обычно отсутствуют
                work_name=str(work_name_val).strip(),
                unit=_to_str(get("unit")),
                quantity=_to_float(get("quantity")),
                unit_price=_to_float(get("unit_price")),
                total_price=_to_float(get("total_price")),
                row_order=order,
                raw_data={
                    field: str(ws.cell(row, col_idx).value)
                    for field, row in label_map.items()
                    if ws.cell(row, col_idx).value is not None
                },
                source_strategy="column",
            ))
            order += 1

        return results

    # ── internals ─────────────────────────────────────────────────────────────

    def _detect_label_rows(self, ws: Worksheet) -> dict[str, int]:
        """
        Сканируем первую колонку — ищем строки, значения которых
        соответствуют нашим алиасам.
        Возвращает {field_name: row_index}.
        """
        label_map: dict[str, int] = {}
        for row_idx in range(1, min(ws.max_row + 1, 50)):
            cell_val = ws.cell(row_idx, self.LABEL_COL).value
            if not cell_val:
                continue
            field = match_any_field(str(cell_val))
            if field and field not in label_map:
                label_map[field] = row_idx
        return label_map


# ─────────────────────────────────────────────────────────────────────────────
# СТРАТЕГИЯ 3: СМЕШАННАЯ (блочная)
# ─────────────────────────────────────────────────────────────────────────────

class BlockOrientedParser:
    """
    Формат: несколько независимых таблиц на одном листе.
    Каждый «блок» — это мини-таблица со своей шапкой.
    Встречается в сметах, скомпонованных вручную.

    Алгоритм:
      - Ищем все строки, которые могут быть заголовками (≥2 хитов)
      - Для каждого найденного заголовка парсим блок до следующего
    """

    name = "block"

    def can_parse(self, ws: Worksheet) -> float:
        header_rows = self._find_all_header_rows(ws)
        return 0.8 if len(header_rows) > 1 else 0.0

    def parse(self, ws: Worksheet) -> list[ParsedRow]:
        header_rows = self._find_all_header_rows(ws)
        if not header_rows:
            return []

        all_results: list[ParsedRow] = []
        current_section: Optional[str] = None
        row_parser = RowOrientedParser()

        for i, header_row in enumerate(header_rows):
            # Граница блока: до следующего заголовка или конца листа
            end_row = header_rows[i + 1] - 1 if i + 1 < len(header_rows) else ws.max_row

            # Определяем название раздела: ищем непустую строку выше заголовка
            for r in range(header_row - 1, max(0, header_row - 5), -1):
                candidate = ws.cell(r, 1).value
                if candidate and not match_any_field(str(candidate)):
                    current_section = str(candidate).strip()
                    break

            # Парсим блок как обычную строчную таблицу
            col_map = row_parser._map_columns(ws, header_row)
            block_rows = self._extract_block(ws, header_row, end_row, col_map, current_section)
            all_results.extend(block_rows)

        return all_results

    def _find_all_header_rows(self, ws: Worksheet) -> list[int]:
        found = []
        for row_idx in range(1, ws.max_row + 1):
            hits = sum(
                1 for col_idx in range(1, min(ws.max_column + 1, 30))
                if (cell := ws.cell(row_idx, col_idx).value) and match_any_field(str(cell))
            )
            if hits >= 2:
                found.append(row_idx)
        return found

    def _extract_block(
        self,
        ws: Worksheet,
        header_row: int,
        end_row: int,
        col_map: dict,
        section: Optional[str],
    ) -> list[ParsedRow]:
        results = []
        order = 0
        row_parser = RowOrientedParser()

        for row_idx in range(header_row + 1, end_row + 1):
            row_values = {
                field: ws.cell(row_idx, col).value
                for field, col in col_map.items()
                if col is not None
            }
            if not any(v for v in row_values.values() if v is not None):
                continue
            work_name = row_values.get("work_name")
            if not work_name:
                continue
            if row_parser._is_section(row_values, col_map):
                continue

            results.append(ParsedRow(
                section=section,
                work_name=str(work_name).strip(),
                unit=_to_str(row_values.get("unit")),
                quantity=_to_float(row_values.get("quantity")),
                unit_price=_to_float(row_values.get("unit_price")),
                total_price=_to_float(row_values.get("total_price")),
                row_order=order,
                raw_data={f: str(v) for f, v in row_values.items() if v is not None},
                source_strategy="block",
            ))
            order += 1

        return results




# ─────────────────────────────────────────────────────────────────────────────
# СТРАТЕГИЯ: ШАБЛОННЫЙ ЛИСТ (Смета / Estimate sheet)
# ─────────────────────────────────────────────────────────────────────────────

_SMETA_SHEET_RE = re.compile(r'смет|estimate|smeta', re.IGNORECASE)
_ITEM_CODE_RE   = re.compile(r'^\d+\.\d+$')      # «1.1», «2.10», «15.3»
_SECTION_HDR_RE = re.compile(r'^\d+\.\s+.+')     # «6. Работы по потолкам»
_SKIP_NAME_RE   = re.compile(
    r'^(ИТОГО|ОБЩАЯ СТОИМОСТЬ|СКИДКА|можно вписать|наименование работ)',
    re.IGNORECASE,
)

# Фиксированные колонки шаблона (0-based): A=0 пустая, B=1 код, C=2 название, D=3 ед.изм.
# Колонки qty/price/total определяются динамически из строки заголовка.
_TC_CODE = 1
_TC_NAME = 2
_TC_UNIT = 3

# Алиасы заголовков для динамического поиска qty / price / total
_HDR_QTY   = re.compile(r'^кол', re.IGNORECASE)
_HDR_PRICE = re.compile(r'^цена$', re.IGNORECASE)
_HDR_TOTAL = re.compile(r'^сумма$', re.IGNORECASE)


def _detect_template_cols(ws, max_scan: int = 10) -> tuple:
    """
    Ищет строку-заголовок в первых max_scan строках листа.
    Возвращает (idx_qty, idx_price, idx_total) — 0-based индексы в строке.
    Если заголовок не найден — возвращает дефолтные значения (4, 5, 6).
    """
    default = (4, 5, 6)   # E, F, G — исходный шаблон без «Базовой Цены»

    for raw_row in ws.iter_rows(min_col=1, max_col=10, max_row=max_scan, values_only=True):
        row = [str(v).strip() if v is not None else "" for v in raw_row]
        qty_idx = price_idx = total_idx = None
        for i, cell in enumerate(row):
            if _HDR_QTY.match(cell):
                qty_idx = i
            elif _HDR_PRICE.match(cell):
                price_idx = i
            elif _HDR_TOTAL.match(cell):
                total_idx = i
        if qty_idx is not None and total_idx is not None:
            if price_idx is None:
                price_idx = total_idx - 1
            return (qty_idx, price_idx, total_idx)

    return default


class TemplateSheetStrategy:
    """
    Парсит Excel-сметы на основе именованного листа (Смета / Estimate).

    Признаки формата:
    - Есть лист с именем, содержащим «смет» / «estimate»
    - Фиксированные колонки: B=код, C=название, D=ед.изм.
    - Колонки qty / price / total определяются из строки заголовка —
      корректно разбирает шаблоны с дополнительными колонками
      (например «Базовая Цена» между ед.изм. и кол-вом)
    - max_column может быть огромным из-за merged cells — читаем только
      нужное количество колонок (read_only=True)
    - Позиции с total=0 и qty=0/None — незаполненные строки прайс-листа,
      пропускаем
    """

    name = "smeta_template"

    def can_parse(self, ws) -> float:
        return 0.95 if _SMETA_SHEET_RE.search(ws.title or "") else 0.0

    def parse(self, ws) -> list[ParsedRow]:
        result: list[ParsedRow] = []
        section: Optional[str] = None
        order = 0

        idx_qty, idx_price, idx_total = _detect_template_cols(ws)
        max_col = max(idx_qty, idx_price, idx_total) + 2

        for raw_row in ws.iter_rows(min_col=1, max_col=max_col, values_only=True):
            row = list(raw_row) + [None] * (max_col - len(raw_row))

            code  = row[_TC_CODE]
            name  = row[_TC_NAME]
            unit  = row[_TC_UNIT]
            qty   = _to_float(row[idx_qty])
            price = _to_float(row[idx_price])
            total = _to_float(row[idx_total])

            name_str = str(name).strip() if name else ""
            if not name_str:
                continue
            if _SKIP_NAME_RE.match(name_str):
                continue

            code_str = str(code).strip() if code else ""

            # Заголовок раздела: нет кода, имя вида «N. Название»
            if not code_str and _SECTION_HDR_RE.match(name_str):
                section = re.sub(r'^\d+\.\s*', '', name_str).strip()
                continue

            # Строка данных — обязателен числовой код
            if not _ITEM_CODE_RE.match(code_str):
                continue

            # Незаполненная позиция прайс-листа — пропускаем
            if (total is None or total == 0) and (qty is None or qty == 0):
                continue

            result.append(ParsedRow(
                section         = section,
                work_name       = name_str,
                unit            = _to_str(unit),
                quantity        = qty,
                unit_price      = price,
                total_price     = total if total else None,
                row_order       = order,
                raw_data        = {"code": code_str},
                source_strategy = "smeta_template",
            ))
            order += 1

        return result

# ─────────────────────────────────────────────────────────────────────────────
# ГЛАВНЫЙ ПАРСЕР — выбирает стратегию автоматически
# ─────────────────────────────────────────────────────────────────────────────

class ExcelEstimateParser:
    """
    Использование:
        parser = ExcelEstimateParser()
        rows, meta = parser.parse("smeta.xlsx")

    meta содержит:
        {
            "strategy": "row" | "column" | "block",
            "sheet": "Sheet1",
            "confidence": 0.95,
            "rows_found": 47,
        }
    """

    STRATEGIES: list = [
        RowOrientedParser(),
        ColumnOrientedParser(),
        BlockOrientedParser(),
    ]

    def parse(self, file_path: str | Path) -> tuple[list[ParsedRow], dict]:
        file_path = Path(file_path)

        # ── Быстрая проверка: есть ли лист типа «Смета»? ──────────────────
        # Используем read_only чтобы не грузить merged cells (max_col=16376)
        wb_ro = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
        smeta_sheet = next(
            (s for s in wb_ro.sheetnames if _SMETA_SHEET_RE.search(s)), None
        )
        wb_ro.close()

        if smeta_sheet:
            # Открываем только нужный лист, ограничиваем колонки
            wb_ro = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
            ws = wb_ro[smeta_sheet]
            strategy = TemplateSheetStrategy()
            rows = strategy.parse(ws)
            wb_ro.close()
            if rows:
                return rows, {
                    "strategy":   strategy.name,
                    "sheet":      smeta_sheet,
                    "confidence": 0.95,
                    "rows_found": len(rows),
                }

        # ── Стандартный путь для остальных форматов ───────────────────────
        wb = openpyxl.load_workbook(file_path, data_only=True)
        best_rows: list[ParsedRow] = []
        best_meta = {"strategy": "none", "confidence": 0.0}

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            if ws.max_row < 3 or ws.max_column < 2:
                continue

            for strategy in self.STRATEGIES:
                confidence = strategy.can_parse(ws)
                if confidence > best_meta["confidence"]:
                    try:
                        rows = strategy.parse(ws)
                        if rows:
                            best_rows = rows
                            best_meta = {
                                "strategy": strategy.name,
                                "sheet": sheet_name,
                                "confidence": confidence,
                                "rows_found": len(rows),
                            }
                    except Exception:
                        continue

        if not best_rows:
            raise ValueError(
                "Не удалось распознать формат сметы. "
                "Убедитесь, что файл содержит колонки: "
                "наименование, количество, единица измерения, сумма."
            )

        return best_rows, best_meta


# ─────────────────────────────────────────────────────────────────────────────
# УТИЛИТЫ
# ─────────────────────────────────────────────────────────────────────────────

def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d,.\-]", "", str(value)).replace(",", ".")
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _to_str(value) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None
