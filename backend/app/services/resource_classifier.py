"""Classify a single extracted estimate row into work/material/mechanism/overhead.

Independent of any PDF/Excel parser: it takes an already-extracted row plus the
structural ``current_mode`` (the "Материалы" / "Трудозатраты" block the row sits
in, when the source has one) and returns a typed result.

Design note: for the Sewera "Материалы / Трудозатраты" layout the structural mode
is a *much* stronger signal than a keyword dictionary. Many works there are
measured in куб.м / кв.м ("Формирование корыта", "Засыпка песка"), so a naive
"м³ ⇒ material" rule would be wrong. Therefore mode wins over volume-based units,
and the keyword fallbacks only kick in when there is no mode (e.g. other formats
or a summary page).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.estimate_types import (
    ESTIMATE_ITEM_TYPE_MATERIAL,
    ESTIMATE_ITEM_TYPE_MECHANISM,
    ESTIMATE_ITEM_TYPE_OVERHEAD,
    ESTIMATE_ITEM_TYPE_UNKNOWN,
    ESTIMATE_ITEM_TYPE_WORK,
)

MODE_MATERIALS = "materials"
MODE_LABOR = "labor"
MODE_UNKNOWN = "unknown"

# Units that always mean an overhead percentage line.
_PERCENT_UNITS = {"%", "проц", "процент", "%%"}

# Machine-time units → mechanism (e.g. "маш.-ч", "машино-смена"). NOTE: a bare
# "смена" is intentionally NOT here — a shift can belong to a mechanism, a crew
# or a supervisor, so it must be decided by the text, not the unit alone.
_MECHANISM_UNIT_RE = re.compile(r"маш\.?\s*-?\s*ч|маш\.?час|машино-?смен|\bмех\b", re.IGNORECASE)

# Labour-time units → work.
_LABOR_UNIT_RE = re.compile(r"чел\.?\s*-?\s*ч|чел\.?час|чел\s*/\s*час", re.IGNORECASE)

# Накладные / транспортные / ИТР / снабжение / надзор — overhead regardless of mode.
_OVERHEAD_RE = re.compile(
    r"наклад|транспортн|логистическ|\bитр\b|снабжен|надзор|"
    r"командиров|амортизац|сопровожден|прочие\s+расход|непредвиден",
    re.IGNORECASE,
)

# Техника / механизмы — a mechanism even when listed inside a "Материалы" block.
_MECHANISM_RE = re.compile(
    r"бетононасос|погрузчик|спецтехник|\bтрал\b|самосвал|экскаватор|"
    r"автокран|\bкран\b|каток|виброплит|бульдозер|манипулятор|"
    r"аренда\s+техник|машино-?смен",
    re.IGNORECASE,
)

# Work verbs — used only when there is no structural mode.
_WORK_RE = re.compile(
    r"устройств|укладк|засыпк|формирован|трамбов|бурени|монтаж|демонтаж|"
    r"разработк|перемещен|планировк|разметк|облицовк|мощени|армирован|"
    r"заливк|утилизац|бетонные\s+работы|копк|рыть",
    re.IGNORECASE,
)

# Material nouns — used only when there is no structural mode.
_MATERIAL_RE = re.compile(
    r"\bбетон\b|песок|щебень|геотекстиль|арматур|саморез|доск|"
    r"пл[её]нк|профиль|проволок|\bгрунт\b|пенопл|опор|брусчат|"
    r"\bплит|бордюр|\bкамен|мембран|щебеноч|кирпич|раствор",
    re.IGNORECASE,
)


@dataclass
class ClassificationResult:
    item_type: str
    confidence: float
    reason: str
    normalized_name: str


def _normalize_mode(current_mode: str | None) -> str:
    if current_mode in {MODE_MATERIALS, MODE_LABOR}:
        return current_mode
    return MODE_UNKNOWN


def classify_estimate_row(
    name: str,
    spec: str | None = None,
    unit: str | None = None,
    section: str | None = None,
    current_mode: str | None = None,
) -> ClassificationResult:
    """Classify an extracted estimate row. ``current_mode`` is the structural
    block (``materials`` / ``labor``) when the source exposes one, else ``None``."""
    name = (name or "").strip()
    spec = (spec or "").strip()
    full = " ".join(p for p in (name, spec) if p)
    normalized = " ".join(name.split())
    unit_norm = (unit or "").strip().lower()
    mode = _normalize_mode(current_mode)

    # 1. Overhead — percentage rows or overhead keywords (regardless of mode).
    if unit_norm in _PERCENT_UNITS:
        return ClassificationResult(ESTIMATE_ITEM_TYPE_OVERHEAD, 0.95, "unit_percent", normalized)
    if _OVERHEAD_RE.search(full):
        return ClassificationResult(ESTIMATE_ITEM_TYPE_OVERHEAD, 0.9, "overhead_keyword", normalized)

    # 2. Strong unit signals: machine-time → mechanism, labour-time → work.
    #    A bare "смена" deliberately matches neither and falls through to the
    #    keyword/mode logic below.
    if _MECHANISM_UNIT_RE.search(unit_norm):
        return ClassificationResult(ESTIMATE_ITEM_TYPE_MECHANISM, 0.95, "unit_machine", normalized)
    if _LABOR_UNIT_RE.search(unit_norm):
        return ClassificationResult(ESTIMATE_ITEM_TYPE_WORK, 0.9, "unit_labor", normalized)

    # 3. Mechanism keywords (regardless of mode — a loader inside a materials
    #    block is still a mechanism, not a material).
    if _MECHANISM_RE.search(full):
        return ClassificationResult(ESTIMATE_ITEM_TYPE_MECHANISM, 0.85, "mechanism_keyword", normalized)

    # 4. Structural mode is the strongest remaining signal.
    if mode == MODE_LABOR:
        return ClassificationResult(ESTIMATE_ITEM_TYPE_WORK, 0.9, "mode_labor", normalized)
    if mode == MODE_MATERIALS:
        return ClassificationResult(ESTIMATE_ITEM_TYPE_MATERIAL, 0.9, "mode_materials", normalized)

    # 5. No mode (other formats / summary pages) — fall back to keywords.
    if _WORK_RE.search(full):
        return ClassificationResult(ESTIMATE_ITEM_TYPE_WORK, 0.7, "work_keyword", normalized)
    if _MATERIAL_RE.search(full):
        return ClassificationResult(ESTIMATE_ITEM_TYPE_MATERIAL, 0.6, "material_keyword", normalized)

    # 6. Nothing matched — leave it for manual review.
    return ClassificationResult(ESTIMATE_ITEM_TYPE_UNKNOWN, 0.3, "no_signal", normalized)


def normalize_explicit_type(value: str | None) -> tuple[str, str | None]:
    """Map an explicit "Тип" column value (excel_typed_journal) to (item_type,
    resource_subtype). "Люди" stays a ``work`` (it can drive duration) but is
    tagged ``resource_subtype="labor"`` for future resource-aware scheduling."""
    text = (value or "").strip().lower()
    if not text:
        return ESTIMATE_ITEM_TYPE_UNKNOWN, None
    if "матер" in text:
        return ESTIMATE_ITEM_TYPE_MATERIAL, None
    if "механ" in text or "техник" in text or "маш" in text:
        return ESTIMATE_ITEM_TYPE_MECHANISM, None
    if "наклад" in text or "достав" in text:
        return ESTIMATE_ITEM_TYPE_OVERHEAD, None
    if "люди" in text or "чел" in text:
        return ESTIMATE_ITEM_TYPE_WORK, "labor"
    if "работ" in text:
        return ESTIMATE_ITEM_TYPE_WORK, None
    return ESTIMATE_ITEM_TYPE_UNKNOWN, None
