"""Parser for the Sewera "Материалы / Трудозатраты" landscape estimate format.

Each detail page has a section title block ("СМЕТА\\n<section>\\n<subtitle>")
followed by a 6-column table:

    [Материалы/Трудозатраты | Спецификации/Примечания | Ед.изм | Кол-во | Цена | Сумма]

Inside the table, single-cell rows "Материалы" / "Трудозатраты" switch the
current mode. Both the section and the mode persist across page breaks (a
section's "Трудозатраты" block often continues on the next page, which has no
"СМЕТА" header of its own).

The first page is a "СВОДНАЯ СМЕТА" summary whose rows duplicate the detail
pages — we skip it for row creation (to avoid double-counting) but keep its
total for the sum reconciliation in ``meta["declared_totals"]``.
"""
from __future__ import annotations

import re
from pathlib import Path

from .pdf_parser import ParsedRow, _f
from .resource_classifier import (
    MODE_LABOR,
    MODE_MATERIALS,
    classify_estimate_row,
)

SOURCE_STRATEGY = "pdf_materials_labor"

# Single-cell rows that switch the current block mode.
_MODE_MARKERS = {
    "материалы": MODE_MATERIALS,
    "трудозатраты": MODE_LABOR,
}

# Table column header — skip it.
_HEADER_RE = re.compile(r"материалы\s*/\s*трудозатраты", re.IGNORECASE)

# Informational parameter rows (no priceable quantity) — skip, don't store.
_INFO_RE = re.compile(
    r"^(площадь|средн|уровень|объ[её]м|глубина|длина|ширина|высота|периметр)\b",
    re.IGNORECASE,
)

# Subtotal / total rows — captured into declared_totals, not stored as rows.
_TOTAL_RES = (
    (re.compile(r"^итого\s*\(материалы\s+и\s+трудозатраты\)", re.IGNORECASE), "section_subtotal"),
    (re.compile(r"^всего\s*\(материалы\)", re.IGNORECASE), "materials_total"),
    (re.compile(r"^всего\s*\(трудозатраты\)", re.IGNORECASE), "labor_total"),
    (re.compile(r"^всего\b", re.IGNORECASE), "section_total"),
    (re.compile(r"^итого\b", re.IGNORECASE), "block_subtotal"),
)


def _clean(cell) -> str:
    return (cell or "").strip()


def _section_from_cell(cell: str) -> str | None:
    """Turn 'СМЕТА\\nОснование отмостки...\\nАрмированный бетон 10 см' into a
    single section title."""
    lines = [ln.strip() for ln in (cell or "").split("\n") if ln.strip()]
    lines = [ln for ln in lines if ln.upper() != "СМЕТА"]
    return " ".join(lines) if lines else None


def _match_total(name: str):
    for regex, kind in _TOTAL_RES:
        if regex.search(name):
            return kind
    return None


# Header lines that mark the end of a section title in the page text.
_SECTION_STOP_RE = re.compile(
    r"материалы\s*/\s*трудозатраты|цена\.?\s*за\s*ед|ед\.\s*изм|спецификации\s*/\s*примечания",
    re.IGNORECASE,
)


def _section_from_page_text(page_text: str) -> str | None:
    """Read the section title from a detail page's text when it is printed above
    the table (e.g. page «чистовая планировка») rather than inside a table cell.

    The page text starts with "СМЕТА" followed by the section title line(s),
    then the column header. Continuation pages have no "СМЕТА" line → None, so
    the current section persists."""
    lines = [ln.strip() for ln in (page_text or "").split("\n") if ln.strip()]
    if not lines or lines[0].upper() != "СМЕТА":
        return None
    title_lines: list[str] = []
    for ln in lines[1:]:
        if _SECTION_STOP_RE.search(ln):
            break
        title_lines.append(ln)
    return " ".join(title_lines) if title_lines else None


class MaterialsLaborPdfParser:
    def parse(self, file_path: str | Path) -> tuple[list[ParsedRow], dict]:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Установите pdfplumber: pip install pdfplumber>=0.11")

        rows: list[ParsedRow] = []
        declared_totals: list[dict] = []
        pages = 0
        order = 0
        current_section: str | None = None
        current_mode: str | None = None

        with pdfplumber.open(str(file_path)) as pdf:
            pages = len(pdf.pages)
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                # Skip the summary page — its rows duplicate the detail pages.
                if "СВОДНАЯ СМЕТА" in page_text:
                    self._record_summary_total(page_text, declared_totals)
                    continue

                # Section title is sometimes printed above the table (not in a
                # "СМЕТА" cell) — pick it up from the page text. Found → new
                # section + reset mode; not found → keep the current section
                # (the labour block often continues on the next page).
                page_section = _section_from_page_text(page_text)
                if page_section:
                    current_section = page_section
                    current_mode = None

                for tbl in page.extract_tables():
                    if not tbl:
                        continue
                    for raw in tbl:
                        if not raw:
                            continue
                        row = [_clean(c) for c in raw]
                        # Pad to 6 columns so indexing is safe.
                        row += [""] * (6 - len(row))
                        name, spec, unit, qty_s, price_s, sum_s = row[:6]

                        if not name and not sum_s:
                            continue

                        # Section title block: "СМЕТА ..." in the first cell.
                        if name.upper().startswith("СМЕТА"):
                            section = _section_from_cell(raw[0])
                            if section:
                                current_section = section
                                current_mode = None
                            continue

                        # Column header row.
                        if _HEADER_RE.search(name):
                            continue

                        # Mode switch.
                        marker = _MODE_MARKERS.get(name.lower())
                        if marker and not unit and not sum_s:
                            current_mode = marker
                            continue

                        # Subtotal / total rows — capture the number, skip the row.
                        total_kind = _match_total(name) or _match_total(price_s)
                        if total_kind:
                            value = _f(sum_s) if sum_s else _f(price_s)
                            if value is not None:
                                declared_totals.append({
                                    "section": current_section,
                                    "kind": total_kind,
                                    "total": value,
                                })
                            continue

                        # Informational parameter rows.
                        if _INFO_RE.match(name):
                            continue

                        total = _f(sum_s)
                        if total is None:
                            continue

                        qty = _f(qty_s)
                        price = _f(price_s)
                        result = classify_estimate_row(
                            name=name,
                            spec=spec,
                            unit=unit,
                            section=current_section,
                            current_mode=current_mode,
                        )
                        full_name = " ".join(p for p in (name, spec) if p)

                        rows.append(ParsedRow(
                            section         = current_section,
                            work_name       = name,
                            unit            = unit or None,
                            quantity        = qty,
                            unit_price      = price,
                            total_price     = total,
                            row_order       = order,
                            raw_data        = {
                                "spec": spec or None,
                                "full_name": full_name,
                                "item_type": result.item_type,
                                "classification_confidence": result.confidence,
                                "classification_reason": result.reason,
                                "source_mode": current_mode,
                                "source_strategy": SOURCE_STRATEGY,
                            },
                            source_strategy = SOURCE_STRATEGY,
                        ))
                        order += 1

        meta = {
            "strategy": SOURCE_STRATEGY,
            "confidence": 0.85 if rows else 0.0,
            "pages": pages,
            "rows_found": len(rows),
            "declared_totals": declared_totals,
        }
        return rows, meta

    @staticmethod
    def _record_summary_total(page_text: str, declared_totals: list[dict]) -> None:
        """Capture the grand total ('Всего: 12 725 959,27') from the summary page."""
        match = re.search(r"всего[:\s]+([\d\s]+[,.]\d{2})", page_text, re.IGNORECASE)
        if match:
            value = _f(match.group(1))
            if value is not None:
                declared_totals.append({
                    "section": None,
                    "kind": "grand_total",
                    "total": value,
                })
