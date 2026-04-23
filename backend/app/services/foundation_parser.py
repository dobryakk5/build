from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .pdf_parser import ParsedRow, _f

# Column layout: [section_num, name, unit, qty, price, sum]
# First row of each table: [section_num, section_name, '', '', '', '']
# Data rows:               [None,        name,          unit, qty, price, sum]

_SKIP_ROW_RE = re.compile(r'^(ИТОГО|ВСЕГО|ед\.?изм|кол-во|наименование)', re.IGNORECASE)


class FoundationTableParser:
    """
    Парсит сметы с секционными таблицами (без кодов позиций).
    Каждая таблица начинается со строки-заголовка: [№, Название раздела, '', ...]
    Остальные строки: [None, название работы, ед., кол-во, цена, сумма]

    Числа чистые — pdfplumber извлекает их корректно.

    Пример: Смета_Рождествено_фундаменты.pdf
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
            for page in pdf.pages:
                tables = page.extract_tables()
                for tbl in tables:
                    if not tbl:
                        continue
                    section = self._extract_section(tbl)
                    for row in tbl:
                        if not row or len(row) < 6:
                            continue
                        # First column: section number or None
                        col0 = (row[0] or '').strip()
                        name  = (row[1] or '').strip()
                        unit  = (row[2] or '').strip()
                        qty_s   = (row[3] or '').strip()
                        price_s = (row[4] or '').strip()
                        sum_s   = (row[5] or '').strip()

                        # Section header row: col0 is a number, rest are empty
                        if col0 and not name:
                            continue
                        if col0 and not qty_s:
                            # "1 Section Title" style header
                            section = name
                            continue

                        # Global header or ИТОГО row
                        if not name or _SKIP_ROW_RE.match(name):
                            continue

                        qty   = _f(qty_s.replace(' ', ''))
                        price = _f(price_s.replace(' ', ''))
                        total = _f(sum_s.replace(' ', ''))

                        if total is None:
                            continue

                        all_rows.append(ParsedRow(
                            section         = section,
                            work_name       = name,
                            unit            = unit or None,
                            quantity        = qty,
                            unit_price      = price,
                            total_price     = total,
                            row_order       = order,
                            raw_data        = {"row": row},
                            source_strategy = "pdf_foundation",
                        ))
                        order += 1

        return all_rows, {
            "strategy":   "pdf_foundation",
            "confidence": 0.85 if all_rows else 0.0,
            "pages":      pages,
            "rows_found": len(all_rows),
        }

    def _extract_section(self, tbl: list[list]) -> str:
        """Read section name from first row of table."""
        if not tbl or not tbl[0]:
            return "Общие работы"
        first = tbl[0]
        # Typically: [section_num, section_title, '', '', '', '']
        if len(first) >= 2 and first[1]:
            return first[1].strip()
        if first[0]:
            return first[0].strip()
        return "Общие работы"
