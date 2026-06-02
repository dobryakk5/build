from pathlib import Path
import sys
from collections import Counter

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.parser_factory import detect_format, parse_estimate, FORMAT_MATERIALS_LABOR

SEWERA_PDF = Path.home() / "Downloads" / "Ильинские сады 02.04.2026.pdf"
pytestmark = pytest.mark.skipif(not SEWERA_PDF.exists(), reason="Sewera sample PDF not present")


def test_format_detected_as_materials_labor():
    assert detect_format(str(SEWERA_PDF)) == FORMAT_MATERIALS_LABOR


def test_rows_typed_and_sections_filled():
    rows, meta = parse_estimate(str(SEWERA_PDF))
    assert meta["strategy"] == "pdf_materials_labor"
    assert len(rows) > 100

    counts = Counter(r.raw_data["item_type"] for r in rows)
    assert counts["work"] > 0
    assert counts["material"] > 0
    assert counts["mechanism"] > 0
    assert counts["overhead"] > 0

    # Every row got a section (the page-text fallback fix).
    assert all(r.section for r in rows)


def test_declared_grand_total_captured():
    _rows, meta = parse_estimate(str(SEWERA_PDF))
    kinds = {d["kind"] for d in meta.get("declared_totals", [])}
    assert "grand_total" in kinds


def test_known_rows_have_expected_types():
    rows, _ = parse_estimate(str(SEWERA_PDF))
    by_name = {}
    for r in rows:
        by_name.setdefault(r.work_name, r.raw_data["item_type"])
    # spot-check a few representative rows
    assert by_name.get("Песок речной, карьерный") == "material"
    assert by_name.get("Формирование корыта") == "work"
