from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .pdf_parser import PdfEstimateParser, ParsedRow
from .nocode_table_parser import NoCodeTableParser
from .nocode_text_parser import NoCodeTextParser
from .foundation_parser import FoundationTableParser
from .excel_parser import ExcelEstimateParser

# Supported format identifiers — PDF
FORMAT_MOSMONTAG  = "mosmontag"    # PDF with item codes (6.10, 7.35…)
FORMAT_NOCODE_TBL = "nocode_table" # PDF, no codes, pdfplumber finds tables
FORMAT_FOUNDATION = "foundation"   # PDF, no codes, 6-col sectioned tables
FORMAT_NOCODE_TXT = "nocode_text"  # PDF, no codes, text-only
FORMAT_SCAN       = "scan"         # image-only PDF, no extractable text
# Excel (all variants handled by ExcelEstimateParser internally)
FORMAT_EXCEL      = "excel"
FORMAT_UNKNOWN    = "unknown"

_EXCEL_EXTENSIONS = (".xlsx", ".xls")


_CODE_RE     = re.compile(r'^\d+\.\d+\s', re.MULTILINE)
_SMETA_SHEET_RE = re.compile(r'смет', re.IGNORECASE)


def detect_format(file_path: str | Path) -> str:
    """
    Inspect PDF content and return the format identifier.

    Detection order:
      1. All pages image-only              → FORMAT_SCAN
      2. Has item codes (\\d+.\\d+ ...)    → FORMAT_MOSMONTAG
      3. Has 6-col tables (section headers)→ FORMAT_FOUNDATION
      4. Has 5-col tables                  → FORMAT_NOCODE_TBL
      5. Has text but no tables            → FORMAT_NOCODE_TXT
      6. Fallback                          → FORMAT_UNKNOWN
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError("Установите pdfplumber: pip install pdfplumber>=0.11")

    with pdfplumber.open(str(file_path)) as pdf:
        total_lines   = 0
        has_code_rows = False
        has_6col_tbl  = False
        has_5col_tbl  = False

        for page in pdf.pages:
            text = page.extract_text() or ""
            lines = [l for l in text.split('\n') if l.strip()]
            total_lines += len(lines)

            if _CODE_RE.search(text):
                has_code_rows = True

            for tbl in page.extract_tables():
                if not tbl:
                    continue
                ncols = max(len(r) for r in tbl if r)
                if ncols >= 6:
                    has_6col_tbl = True
                elif ncols == 5:
                    has_5col_tbl = True

    # 1. Scan
    if total_lines == 0:
        return FORMAT_SCAN

    # 2. MosMontag (coded items)
    if has_code_rows:
        return FORMAT_MOSMONTAG

    # 3. Foundation (6-col tables with section header rows)
    if has_6col_tbl:
        return FORMAT_FOUNDATION

    # 4. NoCode table (5-col tables)
    if has_5col_tbl:
        return FORMAT_NOCODE_TBL

    # 5. NoCode text (text but no tables)
    if total_lines > 0:
        return FORMAT_NOCODE_TXT

    return FORMAT_UNKNOWN


def get_parser(fmt: str):
    """Return the PDF parser instance for a given format identifier."""
    return {
        FORMAT_MOSMONTAG:  PdfEstimateParser,
        FORMAT_NOCODE_TBL: NoCodeTableParser,
        FORMAT_FOUNDATION: FoundationTableParser,
        FORMAT_NOCODE_TXT: NoCodeTextParser,
    }.get(fmt, PdfEstimateParser)()


def parse_pdf(file_path: str | Path) -> tuple[list[ParsedRow], dict]:
    """Backward-compatible alias for parse_estimate (PDF only)."""
    return parse_estimate(file_path)


def parse_estimate(file_path: str | Path) -> tuple[list[ParsedRow], dict]:
    """
    Unified entry point: detect format and parse any estimate file (PDF or Excel).

    Returns:
        (rows, meta)  — meta includes 'format' key with detected format string.
    """
    path = Path(file_path)

    # ── Excel ────────────────────────────────────────────────────────────────
    if path.suffix.lower() in _EXCEL_EXTENSIONS:
        rows, meta = ExcelEstimateParser().parse(path)
        meta["format"] = FORMAT_EXCEL
        return rows, meta

    # ── PDF ──────────────────────────────────────────────────────────────────
    fmt = detect_format(path)
    if fmt in (FORMAT_SCAN, FORMAT_UNKNOWN):
        return [], {"format": fmt, "strategy": fmt, "rows_found": 0, "confidence": 0.0}

    parser = get_parser(fmt)
    rows, meta = parser.parse(path)
    meta["format"] = fmt
    return rows, meta
