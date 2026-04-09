from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .pdf_parser import ParsedRow, _f

# Threshold x-coordinates inferred from header positions
# name  : x < X_UNIT
# unit  : X_UNIT  ≤ x < X_QTY
# qty   : X_QTY   ≤ x < X_PRICE
# price : X_PRICE ≤ x < X_SUM
# sum   : x ≥ X_SUM
#
# Calibrated from Смета_потолок_август_23.pdf header words:
#   ед/изм → 283-296, кол-во → 321, цена → 377, сумма → 447
_X_UNIT  = 283
_X_QTY   = 327
_X_PRICE = 365   # slightly left of 'цена' to catch broken price digits
_X_SUM   = 440

# Lines to skip
_SKIP_RE = re.compile(
    r'(ИТОГО|ОБЩАЯ\s*СУММА|ед\.?\s*изм|кол-во|цена|сумма|Расчет|наименование)',
    re.IGNORECASE,
)

# ИТОГО РАБОТА → next section = Материалы
_SECTION_WORK_END_RE = re.compile(r'ИТОГО\s+РАБОТ', re.IGNORECASE)
_SECTION_HEADER_RE = re.compile(
    r'^(?:\d+[.)]\s*)?[А-ЯЁA-Z][А-ЯЁA-ZA-Za-z0-9\s().,\-]{2,120}$'
)


def _detect_section_header(name: str, unit: str, qty_s: str, price_s: str, sum_s: str) -> str | None:
    clean_name = " ".join(name.split()).strip()
    if not clean_name:
        return None
    if unit or qty_s or price_s or sum_s:
        return None
    if _SKIP_RE.search(clean_name):
        return None
    if not _SECTION_HEADER_RE.match(clean_name):
        return None
    if len(clean_name.split()) <= 1 and clean_name.lower() not in {"работа", "материалы"}:
        return None
    return re.sub(r'^\d+[.)]\s*', '', clean_name).strip()


class NoCodeTextParser:
    """
    Парсит сметы без кодов позиций и без таблиц (text-only PDF).
    Использует x-координаты слов для определения колонок.

    Формат: название | ед.изм. | кол-во | цена | сумма
    Числа могут быть «сломаны» pdfplumber'ом (7 00,00 вместо 700,00).
    Объединение без пробелов исправляет это автоматически.

    Пример: Смета_потолок_август_23.pdf
    """

    def parse(self, file_path: str | Path) -> tuple[list[ParsedRow], dict]:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Установите pdfplumber: pip install pdfplumber>=0.11")

        all_rows: list[ParsedRow] = []
        pages = 0
        order = 0

        with pdfplumber.open(str(file_path)) as pdf:
            pages = len(pdf.pages)
            section = 'Работа'
            for page in pdf.pages:
                page_rows, section = self._parse_page(page, section, order)
                for r in page_rows:
                    r.row_order = order
                    order += 1
                all_rows.extend(page_rows)

        return all_rows, {
            "strategy":   "pdf_nocode_text",
            "confidence": 0.75 if all_rows else 0.0,
            "pages":      pages,
            "rows_found": len(all_rows),
        }

    def _parse_page(
        self, page, section: str, start_order: int
    ) -> tuple[list[ParsedRow], str]:
        words = page.extract_words(x_tolerance=3)

        # Group words by their vertical position (exact top value)
        rows_by_top: dict[int, list] = {}
        for w in words:
            top = round(w['top'])
            rows_by_top.setdefault(top, []).append(w)

        result: list[ParsedRow] = []

        for top in sorted(rows_by_top):
            ws = sorted(rows_by_top[top], key=lambda w: w['x0'])

            name_p: list[str] = []
            unit_p: list[str] = []
            qty_p:  list[str] = []
            price_p:list[str] = []
            sum_p:  list[str] = []

            for w in ws:
                x, t = w['x0'], w['text']
                if x < _X_UNIT:
                    name_p.append(t)
                elif x < _X_QTY:
                    unit_p.append(t)
                elif x < _X_PRICE:
                    qty_p.append(t)
                elif x < _X_SUM:
                    price_p.append(t)
                else:
                    sum_p.append(t)

            name    = ' '.join(name_p)
            unit    = ' '.join(unit_p)
            qty_s   = ''.join(qty_p)    # join without spaces → fixes broken digits
            price_s = ''.join(price_p)
            sum_s   = ''.join(sum_p)

            all_text = ' '.join(filter(None, [name, unit, qty_s, price_s, sum_s]))

            # Section transition: after ИТОГО РАБОТА
            if _SECTION_WORK_END_RE.search(all_text):
                section = 'Материалы'
                continue

            section_header = _detect_section_header(name, unit, qty_s, price_s, sum_s)
            if section_header:
                section = section_header
                continue

            # Skip headers / totals / titles
            if _SKIP_RE.search(all_text):
                continue

            qty   = _f(qty_s)
            price = _f(price_s)
            total = _f(sum_s)

            if total is None:
                continue
            if not name and qty is None:
                continue

            result.append(ParsedRow(
                section         = section,
                work_name       = name.strip(),
                unit            = unit.strip() or None,
                quantity        = qty,
                unit_price      = price,
                total_price     = total,
                raw_data        = {"top": top},
                source_strategy = "pdf_nocode_text",
            ))

        return result, section
