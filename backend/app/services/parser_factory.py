from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .pdf_parser import PdfEstimateParser, ParsedRow
from .nocode_table_parser import NoCodeTableParser
from .nocode_text_parser import NoCodeTextParser
from .foundation_parser import FoundationTableParser
from .materials_labor_pdf_parser import MaterialsLaborPdfParser
from .excel_typed_journal_parser import ExcelTypedJournalParser
from .excel_parser import ExcelEstimateParser

# Supported format identifiers — PDF
FORMAT_MOSMONTAG  = "mosmontag"    # PDF with item codes (6.10, 7.35…)
FORMAT_MATERIALS_LABOR = "materials_labor_pdf"  # Sewera "Материалы/Трудозатраты"
FORMAT_NOCODE_TBL = "nocode_table" # PDF, no codes, pdfplumber finds tables
FORMAT_FOUNDATION = "foundation"   # PDF, no codes, 6-col sectioned tables
FORMAT_NOCODE_TXT = "nocode_text"  # PDF, no codes, text-only
FORMAT_SCAN       = "scan"         # image-only PDF, no extractable text
# Excel (all variants handled by ExcelEstimateParser internally)
FORMAT_EXCEL      = "excel"
FORMAT_UNKNOWN    = "unknown"

_EXCEL_EXTENSIONS = (".xlsx", ".xls")

# ── Parser profiles ───────────────────────────────────────────────────────────
# The import format the operator explicitly selects (separate from estimate_kind,
# which is the construction-object type). New behaviour activates ONLY for an
# explicitly chosen profile — `auto` keeps the legacy detection so existing Excel
# imports never change silently.
PROFILE_AUTO                       = "auto"
PROFILE_EXCEL_WORK_LIST            = "excel_work_list"
PROFILE_EXCEL_TYPED_JOURNAL        = "excel_typed_journal"
PROFILE_EXCEL_WORK_MATERIAL_MATRIX = "excel_work_material_matrix"
PROFILE_EXCEL_SECTIONED_COST_SPLIT = "excel_sectioned_cost_split"
PROFILE_PDF_MATERIALS_LABOR        = "pdf_materials_labor"
PROFILE_PDF_MOSMONTAG              = "pdf_mosmontag"
PROFILE_MANUAL_MAPPING             = "manual_mapping"

VALID_PARSER_PROFILES = {
    PROFILE_AUTO, PROFILE_EXCEL_WORK_LIST, PROFILE_EXCEL_TYPED_JOURNAL,
    PROFILE_EXCEL_WORK_MATERIAL_MATRIX, PROFILE_EXCEL_SECTIONED_COST_SPLIT,
    PROFILE_PDF_MATERIALS_LABOR, PROFILE_PDF_MOSMONTAG, PROFILE_MANUAL_MAPPING,
}
# Profiles with a real implementation right now.
IMPLEMENTED_PROFILES = {
    PROFILE_AUTO, PROFILE_PDF_MATERIALS_LABOR, PROFILE_EXCEL_TYPED_JOURNAL,
    PROFILE_MANUAL_MAPPING,
}
# Profiles to show in the UI dropdown (only the ready ones), with labels.
UI_PROFILES = [
    {"value": PROFILE_AUTO,                "label": "Автоопределение"},
    {"value": PROFILE_PDF_MATERIALS_LABOR, "label": "PDF: Материалы / Трудозатраты"},
    {"value": PROFILE_EXCEL_TYPED_JOURNAL, "label": "Excel: колонка «Тип»"},
    {"value": PROFILE_MANUAL_MAPPING,      "label": "Ручное сопоставление колонок"},
]


class ParserProfileNotImplemented(Exception):
    """Raised when a known-but-unimplemented profile is requested (→ HTTP 400)."""

    def __init__(self, parser_profile: str):
        self.parser_profile = parser_profile
        super().__init__(f"Parser profile is not implemented yet: {parser_profile}")


_CODE_RE     = re.compile(r'^\d+\.\d+\s', re.MULTILINE)
_SMETA_SHEET_RE = re.compile(r'смет', re.IGNORECASE)


def detect_format(file_path: str | Path) -> str:
    """
    Inspect PDF content and return the format identifier.

    Detection order:
      1. All pages image-only              → FORMAT_SCAN
      2. Has item codes (\\d+.\\d+ ...)    → FORMAT_MOSMONTAG
      3. "Материалы/Трудозатраты" layout   → FORMAT_MATERIALS_LABOR
      4. Has 6-col tables (section headers)→ FORMAT_FOUNDATION
      5. Has 5-col tables                  → FORMAT_NOCODE_TBL
      6. Has text but no tables            → FORMAT_NOCODE_TXT
      7. Fallback                          → FORMAT_UNKNOWN
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
        has_mat_labor = False

        for page in pdf.pages:
            text = page.extract_text() or ""
            lines = [l for l in text.split('\n') if l.strip()]
            total_lines += len(lines)

            if _CODE_RE.search(text):
                has_code_rows = True
            if "Материалы / Трудозатраты" in text and "Спецификации / Примечания" in text:
                has_mat_labor = True

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

    # 3. Materials/Labor (Sewera) — must precede FOUNDATION: it also has 6-col
    #    tables but needs section-title + mode-aware parsing.
    if has_mat_labor:
        return FORMAT_MATERIALS_LABOR

    # 4. Foundation (6-col tables with section header rows)
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
        FORMAT_MATERIALS_LABOR: MaterialsLaborPdfParser,
        FORMAT_NOCODE_TBL: NoCodeTableParser,
        FORMAT_FOUNDATION: FoundationTableParser,
        FORMAT_NOCODE_TXT: NoCodeTextParser,
    }.get(fmt, PdfEstimateParser)()


def parse_pdf(file_path: str | Path) -> tuple[list[ParsedRow], dict]:
    """Backward-compatible alias for parse_estimate (PDF only)."""
    return parse_estimate(file_path)


def _tag_profile(rows: list[ParsedRow], parser_profile: str) -> None:
    """Stamp parser_profile onto every row's raw_data (helps debug imports)."""
    for row in rows:
        if isinstance(getattr(row, "raw_data", None), dict):
            row.raw_data.setdefault("parser_profile", parser_profile)
        else:
            row.raw_data = {"parser_profile": parser_profile}


def _excel_is_typed_journal(file_path: str | Path) -> bool:
    """True if the workbook has an explicit «Тип» column (type1 header) — then
    auto routes to ExcelTypedJournalParser instead of the legacy fold."""
    import openpyxl
    from .excel_parser import StructuredSmetaParser

    try:
        wb = openpyxl.load_workbook(file_path, data_only=True)
    except Exception:
        return False
    try:
        smeta = StructuredSmetaParser()
        return any(smeta._find_type1_header(wb[name]) for name in wb.sheetnames)
    except Exception:
        return False
    finally:
        wb.close()


def parse_estimate(
    file_path: str | Path,
    parser_profile: str = PROFILE_AUTO,
    allow_fallback: bool = False,
) -> tuple[list[ParsedRow], dict]:
    """
    Unified entry point: parse an estimate file (PDF or Excel) under a profile.

    - ``auto`` keeps the legacy detection (existing Excel/PDF behaviour unchanged).
    - An explicit profile forces its parser and never runs silently on the wrong
      file type / on other formats.
    - A known-but-unimplemented profile raises ``ParserProfileNotImplemented``
      (→ 400), unless ``allow_fallback`` is set, in which case it falls to ``auto``.

    Returns ``(rows, meta)`` — meta includes 'format', 'strategy', 'parser_profile'.
    """
    path = Path(file_path)
    profile = parser_profile or PROFILE_AUTO

    if profile not in VALID_PARSER_PROFILES:
        raise ValueError(f"Неизвестный профиль импорта: {profile}")
    if profile not in IMPLEMENTED_PROFILES:
        if allow_fallback:
            profile = PROFILE_AUTO
        else:
            raise ParserProfileNotImplemented(profile)

    is_excel = path.suffix.lower() in _EXCEL_EXTENSIONS

    # ── Explicit profiles ──────────────────────────────────────────────────────
    if profile == PROFILE_PDF_MATERIALS_LABOR:
        if is_excel:
            raise ValueError("Профиль «PDF: Материалы / Трудозатраты» применим только к PDF")
        rows, meta = MaterialsLaborPdfParser().parse(path)
        meta["format"] = FORMAT_MATERIALS_LABOR
        meta["parser_profile"] = profile
        _tag_profile(rows, profile)
        return rows, meta

    if profile == PROFILE_EXCEL_TYPED_JOURNAL:
        if not is_excel:
            raise ValueError("Профиль «Excel: колонка Тип» применим только к Excel")
        rows, meta = ExcelTypedJournalParser().parse(path)
        meta["format"] = FORMAT_EXCEL
        meta["parser_profile"] = profile
        _tag_profile(rows, profile)
        return rows, meta

    # ── auto / manual_mapping → legacy detection ───────────────────────────────
    if is_excel:
        # Auto-detect the "Тип" column journal and parse it with full typing
        # (separate material/mechanism/overhead rows). Operators don't pick a
        # profile — the file type is detected here.
        if _excel_is_typed_journal(path):
            rows, meta = ExcelTypedJournalParser().parse(path)
            meta["format"] = FORMAT_EXCEL
            meta["parser_profile"] = PROFILE_EXCEL_TYPED_JOURNAL
            _tag_profile(rows, PROFILE_EXCEL_TYPED_JOURNAL)
            return rows, meta
        rows, meta = ExcelEstimateParser().parse(path)
        meta["format"] = FORMAT_EXCEL
    else:
        fmt = detect_format(path)
        if fmt in (FORMAT_SCAN, FORMAT_UNKNOWN):
            return [], {"format": fmt, "strategy": fmt, "rows_found": 0,
                        "confidence": 0.0, "parser_profile": PROFILE_AUTO}
        rows, meta = get_parser(fmt).parse(path)
        meta["format"] = fmt

    meta["parser_profile"] = PROFILE_AUTO
    _tag_profile(rows, PROFILE_AUTO)
    return rows, meta
