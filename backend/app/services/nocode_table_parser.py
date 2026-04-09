from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .pdf_parser import ParsedRow, _f


# Known section header keywords → canonical section name
_SECTION_KEYWORDS = {
    'вид работ':      'Работа',
    'работ':          'Работа',
    'материал':       'Материалы',
    'управлени':      'Управление',
    'раздел':         'Раздел',
    'этап':           'Этап',
}

# Row skip patterns
_SKIP_NAMES = re.compile(
    r'^(вид работ|материалы|управление проектом|наименование)$',
    re.IGNORECASE,
)


def _section_from_header(cell: str) -> Optional[str]:
    low = cell.lower().strip()
    for kw, name in _SECTION_KEYWORDS.items():
        if kw in low:
            return name
    return None


def _normalize_section(cell: str) -> Optional[str]:
    clean = re.sub(r'^\d+[.)]\s*', '', cell).strip()
    if not clean:
      return None
    if len(clean) > 120:
      return None
    if re.search(r'\d', clean) and not re.match(r'^\d+[.)]\s', cell.strip()):
      return None
    return clean


class NoCodeTableParser:
    """
    Парсит сметы без кодов позиций, где pdfplumber находит таблицы.

    Формат колонок: [название, ед.изм., кол-во, цена, сумма]
    Секции определяются по первой строке таблицы или заголовку над ней.

    Пример: смета_ремонт_дома_дек_23.pdf
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
                # Collect section labels from raw text between tables
                text_sections = self._extract_section_labels(page)
                tables = page.extract_tables()

                for t_idx, tbl in enumerate(tables):
                    if not tbl:
                        continue
                    # Determine section: from table header row or text label
                    section = text_sections.get(t_idx, 'Работа')
                    first_row = tbl[0] if tbl else []

                    for row in tbl:
                        if not row or len(row) < 4:
                            continue

                        name = (row[0] or '').strip()
                        unit = (row[1] or '').strip()
                        qty_s   = (row[2] or '').strip()
                        price_s = (row[3] or '').strip()
                        sum_s   = (row[4] or '').strip() if len(row) > 4 else ''

                        # Header row — update section, skip
                        if _SKIP_NAMES.match(name):
                            sec = _section_from_header(name)
                            if sec:
                                section = sec
                            continue

                        normalized_section = _normalize_section(name)
                        if normalized_section and not qty_s and not price_s and not sum_s:
                            section = normalized_section
                            continue

                        # Empty / stub rows
                        if not name:
                            continue
                        if qty_s in ('', '0', '-') and sum_s in ('', '-'):
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
                            source_strategy = "pdf_nocode_table",
                        ))
                        order += 1

        return all_rows, {
            "strategy":   "pdf_nocode_table",
            "confidence": 0.8 if all_rows else 0.0,
            "pages":      pages,
            "rows_found": len(all_rows),
        }

    def _extract_section_labels(self, page) -> dict[int, str]:
        """Map table index → section name, detected from text above each table."""
        text = page.extract_text() or ""
        lines = [l.strip() for l in text.split('\n') if l.strip()]

        # Find ИТОГО lines to split by section
        section_map: dict[int, str] = {}
        current_section = 'Работа'
        table_idx = 0

        for line in lines:
            low = line.lower()
            # Detect known section headers
            for kw, name in _SECTION_KEYWORDS.items():
                if low.startswith(kw) and not any(c.isdigit() for c in line):
                    current_section = name
                    break
            normalized_section = _normalize_section(line)
            if normalized_section:
                current_section = normalized_section
            # ИТОГО → next table gets next section
            if low.startswith('итого') and table_idx not in section_map:
                section_map[table_idx] = current_section
                table_idx += 1

        # Assign remaining tables
        tables = page.extract_tables()
        for i in range(len(tables)):
            if i not in section_map:
                section_map[i] = current_section

        return section_map
