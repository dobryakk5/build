"""Parser for the Sewera ``Материалы / Трудозатраты`` PDF format.

The parser keeps detail-block title and description separately, assigns a
stable ``section_block_id`` across continuation pages, extracts the summary
page, reconciles summary rows against detail-block totals, and emits only
unmatched priceable summary rows. This avoids both double counting and the
legacy loss of summary-only work such as soil disposal.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .pdf_parser import ParsedRow, _f
from .resource_classifier import (
    MODE_LABOR,
    MODE_MATERIALS,
    classify_estimate_row,
    extract_mechanism_token,
)

SOURCE_STRATEGY = "pdf_materials_labor"

_MODE_MARKERS = {
    "материалы": MODE_MATERIALS,
    "трудозатраты": MODE_LABOR,
}
_HEADER_RE = re.compile(r"материалы\s*/\s*трудозатраты", re.IGNORECASE)
_INFO_RE = re.compile(
    r"^(площадь|средн|уровень|объ[её]м|глубина|длина|ширина|высота|периметр)",
    re.IGNORECASE,
)
_SUMMARY_INFO_RE = re.compile(r"^общее\s+количество\b", re.IGNORECASE)
_TOTAL_RES = (
    (re.compile(r"^итого\s*\(материалы\s+и\s+трудозатраты\)", re.IGNORECASE), "section_subtotal"),
    (re.compile(r"^всего\s*\(материалы\)", re.IGNORECASE), "materials_total"),
    (re.compile(r"^всего\s*\(трудозатраты\)", re.IGNORECASE), "labor_total"),
    (re.compile(r"^всего\b", re.IGNORECASE), "section_total"),
    (re.compile(r"^итого\b", re.IGNORECASE), "block_subtotal"),
)
_SECTION_STOP_RE = re.compile(
    r"материалы\s*/\s*трудозатраты|цена\.?\s*за\s*ед|ед\.\s*изм|спецификации\s*/\s*примечания",
    re.IGNORECASE,
)


def _clean(cell: Any) -> str:
    return (cell or "").strip()


def _section_parts_from_lines(lines: list[str]) -> tuple[str | None, str | None]:
    cleaned = [line.strip() for line in lines if line and line.strip()]
    cleaned = [line for line in cleaned if line.upper() != "СМЕТА"]
    if not cleaned:
        return None, None
    title = cleaned[0]
    description = " ".join(cleaned[1:]) or None
    return title, description


def _section_parts_from_cell(cell: str) -> tuple[str | None, str | None]:
    return _section_parts_from_lines((cell or "").split("\n"))


def _section_parts_from_page_text(page_text: str) -> tuple[str | None, str | None]:
    lines = [line.strip() for line in (page_text or "").split("\n") if line.strip()]
    if not lines or lines[0].upper() != "СМЕТА":
        return None, None
    title_lines: list[str] = []
    for line in lines[1:]:
        if _SECTION_STOP_RE.search(line):
            break
        title_lines.append(line)
    return _section_parts_from_lines(title_lines)


def _section_text(title: str | None, description: str | None) -> str | None:
    text = " ".join(part for part in (title, description) if part).strip()
    return text or None


def _match_total(name: str) -> str | None:
    for regex, kind in _TOTAL_RES:
        if regex.search(name):
            return kind
    return None


def _norm_match_text(value: str | None) -> str:
    text = (value or "").casefold().replace("ё", "е")
    text = re.sub(r"[^0-9a-zа-я]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _text_similarity(left: str, right: str) -> float:
    a = _norm_match_text(left)
    b = _norm_match_text(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    jaccard = len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens))
    sequence = SequenceMatcher(None, a, b).ratio()
    containment = 0.95 if a in b or b in a else 0.0
    return max(jaccard, sequence, containment)


class MaterialsLaborPdfParser:
    SUMMARY_MATCH_MIN_SIMILARITY = 0.55

    def parse(self, file_path: str | Path) -> tuple[list[ParsedRow], dict]:
        try:
            import pdfplumber
        except ImportError as exc:
            raise ImportError("Установите pdfplumber: pip install pdfplumber>=0.11") from exc

        rows: list[ParsedRow] = []
        declared_totals: list[dict[str, Any]] = []
        summary_rows: list[dict[str, Any]] = []
        detail_blocks: dict[str, dict[str, Any]] = {}
        pages = 0
        order = 0
        block_counter = 0
        current_title: str | None = None
        current_description: str | None = None
        current_section: str | None = None
        current_block_id: str | None = None
        current_mode: str | None = None

        def set_section(title: str | None, description: str | None, page_number: int) -> None:
            nonlocal block_counter, current_title, current_description
            nonlocal current_section, current_block_id, current_mode
            if not title:
                return
            combined = _section_text(title, description)
            if combined == current_section and current_block_id:
                if description and not current_description:
                    current_description = description
                    current_section = combined
                    detail_blocks[current_block_id]["section_description"] = description
                    detail_blocks[current_block_id]["section_text"] = combined
                return
            block_counter += 1
            current_title = title
            current_description = description
            current_section = combined
            current_block_id = f"pdf-page-{page_number}-block-{block_counter}"
            current_mode = None
            detail_blocks[current_block_id] = {
                "section_block_id": current_block_id,
                "section_title": title,
                "section_description": description,
                "section_text": combined,
                "section_total": None,
                "row_orders": [],
            }

        with pdfplumber.open(str(file_path)) as pdf:
            pages = len(pdf.pages)
            for page_number, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                tables = page.extract_tables()

                if "СВОДНАЯ СМЕТА" in page_text:
                    self._record_summary_total(page_text, declared_totals)
                    summary_rows.extend(self._extract_summary_rows(tables, page_number))
                    continue

                page_title, page_description = _section_parts_from_page_text(page_text)
                if page_title:
                    set_section(page_title, page_description, page_number)

                for table in tables:
                    if not table:
                        continue
                    for raw_row in table:
                        if not raw_row:
                            continue
                        cells = [_clean(cell) for cell in raw_row]
                        cells += [""] * (6 - len(cells))
                        name, spec, unit, qty_s, price_s, sum_s = cells[:6]

                        if not name and not sum_s:
                            continue

                        if name.upper().startswith("СМЕТА"):
                            title, description = _section_parts_from_cell(raw_row[0])
                            set_section(title, description, page_number)
                            continue

                        if _HEADER_RE.search(name):
                            continue

                        marker = _MODE_MARKERS.get(name.casefold())
                        if marker and not unit and not sum_s:
                            current_mode = marker
                            continue

                        total_kind = _match_total(name) or _match_total(price_s)
                        if total_kind:
                            value = _f(sum_s) if sum_s else _f(price_s)
                            if value is not None:
                                declared_totals.append(
                                    {
                                        "section": current_section,
                                        "section_block_id": current_block_id,
                                        "kind": total_kind,
                                        "total": value,
                                    }
                                )
                                if current_block_id and total_kind == "section_total":
                                    detail_blocks[current_block_id]["section_total"] = value
                            continue

                        if _INFO_RE.match(name):
                            continue

                        total = _f(sum_s)
                        if total is None:
                            if (
                                current_block_id
                                and current_mode is None
                                and "планировка участка спецтехникой" in _norm_match_text(name)
                            ):
                                if not current_description:
                                    current_description = name
                                    current_section = _section_text(current_title, current_description)
                                    detail_blocks[current_block_id]["section_description"] = current_description
                                    detail_blocks[current_block_id]["section_text"] = current_section
                                rows.append(
                                    ParsedRow(
                                        section=current_section,
                                        work_name=name,
                                        unit=None,
                                        quantity=None,
                                        unit_price=None,
                                        total_price=None,
                                        row_order=order,
                                        raw_data={
                                            "spec": None,
                                            "full_name": name,
                                            "item_text": name,
                                            "item_type": "work",
                                            "classification_confidence": 1.0,
                                            "classification_reason": "synthetic_from_section_header",
                                            "row_role_hint": "work",
                                            "source_mode": "synthetic_parent",
                                            "source_strategy": SOURCE_STRATEGY,
                                            "section_block_id": current_block_id,
                                            "section_title": current_title,
                                            "section_description": current_description,
                                            "section_parent_context": current_section,
                                            "synthetic_parent": True,
                                            "financial_total_applicable": False,
                                            "gpr_included": True,
                                        },
                                        source_strategy=SOURCE_STRATEGY,
                                    )
                                )
                                detail_blocks[current_block_id]["row_orders"].append(order)
                                order += 1
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
                        item_text = " ".join(part for part in (name, spec) if part).strip()
                        raw_data = {
                            "spec": spec or None,
                            "full_name": item_text,
                            "item_text": item_text,
                            "item_type": result.item_type,
                            "classification_confidence": result.confidence,
                            "classification_reason": result.reason,
                            "row_role_hint": result.row_role_hint,
                            "source_mode": current_mode,
                            "source_strategy": SOURCE_STRATEGY,
                            "section_block_id": current_block_id,
                            "section_title": current_title,
                            "section_description": current_description,
                            "section_parent_context": current_section,
                        }
                        rows.append(
                            ParsedRow(
                                section=current_section,
                                work_name=name,
                                unit=unit or None,
                                quantity=qty,
                                unit_price=price,
                                total_price=total,
                                row_order=order,
                                raw_data=raw_data,
                                source_strategy=SOURCE_STRATEGY,
                            )
                        )
                        if current_block_id:
                            detail_blocks[current_block_id]["row_orders"].append(order)
                        order += 1

                        if result.item_type == "work":
                            mech_name = extract_mechanism_token(item_text)
                            if mech_name:
                                rows.append(
                                    ParsedRow(
                                        section=current_section,
                                        work_name=mech_name,
                                        unit=None,
                                        quantity=None,
                                        unit_price=None,
                                        total_price=None,
                                        row_order=order,
                                        raw_data={
                                            "item_type": "mechanism",
                                            "row_role_hint": "mechanism",
                                            "source": "derived_from_work",
                                            "linked_work": name,
                                            "full_name": item_text,
                                            "item_text": mech_name,
                                            "source_mode": current_mode,
                                            "source_strategy": SOURCE_STRATEGY,
                                            "section_block_id": current_block_id,
                                            "section_title": current_title,
                                            "section_description": current_description,
                                            "section_parent_context": current_section,
                                        },
                                        source_strategy=SOURCE_STRATEGY,
                                    )
                                )
                                if current_block_id:
                                    detail_blocks[current_block_id]["row_orders"].append(order)
                                order += 1

        unmatched_summary, reconciliation = self._reconcile_summary(summary_rows, detail_blocks)
        for summary in unmatched_summary:
            result = classify_estimate_row(
                name=summary["name"],
                spec=summary.get("spec"),
                unit=summary.get("unit"),
                section=summary.get("item_text"),
                current_mode=None,
            )
            rows.append(
                ParsedRow(
                    section=summary.get("item_text"),
                    work_name=summary["name"],
                    unit=summary.get("unit") or None,
                    quantity=summary.get("quantity"),
                    unit_price=None,
                    total_price=summary.get("total_price"),
                    row_order=order,
                    raw_data={
                        "spec": summary.get("spec"),
                        "full_name": summary.get("item_text"),
                        "item_text": summary.get("item_text"),
                        "item_type": result.item_type,
                        "classification_confidence": result.confidence,
                        "classification_reason": "summary_only_unmatched_detail",
                        "row_role_hint": result.row_role_hint or "work",
                        "source_mode": "summary_only",
                        "source_strategy": SOURCE_STRATEGY,
                        "summary_only": True,
                        "summary_page_number": summary.get("page_number"),
                        "section_block_id": f"summary-page-{summary.get('page_number')}-row-{summary.get('summary_index')}",
                        "section_title": summary.get("name"),
                        "section_description": summary.get("spec"),
                        "section_parent_context": summary.get("item_text"),
                        "gpr_included": True,
                    },
                    source_strategy=SOURCE_STRATEGY,
                )
            )
            order += 1

        grand_total = next(
            (item["total"] for item in declared_totals if item.get("kind") == "grand_total"),
            None,
        )
        reconciliation["declared_total"] = grand_total
        if grand_total is not None:
            reconciliation["difference"] = round(
                grand_total - reconciliation["computed_import_total"], 2
            )

        meta = {
            "strategy": SOURCE_STRATEGY,
            "confidence": 0.9 if rows else 0.0,
            "pages": pages,
            "rows_found": len(rows),
            "declared_totals": declared_totals,
            "summary_reconciliation": reconciliation,
        }
        return rows, meta

    @staticmethod
    def _record_summary_total(page_text: str, declared_totals: list[dict[str, Any]]) -> None:
        match = re.search(r"всего[:\s]+([\d\s]+[,.]\d{2})", page_text, re.IGNORECASE)
        if match:
            value = _f(match.group(1))
            if value is not None:
                declared_totals.append({"section": None, "kind": "grand_total", "total": value})

    @staticmethod
    def _extract_summary_rows(tables: list[list[list[Any]]], page_number: int) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        raw_index = 0
        for table in tables:
            for raw_row in table or []:
                if not raw_row:
                    continue
                cells = [_clean(cell) for cell in raw_row]
                cells += [""] * (5 - len(cells))
                name, spec, unit, qty_s, total_s = cells[:5]
                if not name:
                    continue
                normalized = _norm_match_text(name)
                if (
                    "наименование" in normalized
                    or normalized == "благоустройство"
                    or normalized.startswith("всего")
                ):
                    continue
                raw_index += 1
                total = _f(total_s)
                if total is None:
                    result.append(
                        {
                            "summary_index": raw_index,
                            "page_number": page_number,
                            "name": name,
                            "spec": spec or None,
                            "item_text": _section_text(name, spec),
                            "priceable": False,
                            "information_only": bool(_SUMMARY_INFO_RE.match(name)),
                        }
                    )
                    continue
                result.append(
                    {
                        "summary_index": raw_index,
                        "page_number": page_number,
                        "name": name,
                        "spec": spec or None,
                        "item_text": _section_text(name, spec),
                        "unit": unit or None,
                        "quantity": _f(qty_s),
                        "total_price": total,
                        "priceable": True,
                        "information_only": False,
                    }
                )
        return result

    def _reconcile_summary(
        self,
        summary_rows: list[dict[str, Any]],
        detail_blocks: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        available = {
            block_id: block
            for block_id, block in detail_blocks.items()
            if block.get("section_total") is not None
        }
        matched: list[dict[str, Any]] = []
        unmatched: list[dict[str, Any]] = []
        ignored_info = 0

        for summary in summary_rows:
            if not summary.get("priceable"):
                if summary.get("information_only"):
                    ignored_info += 1
                continue
            amount = float(summary["total_price"])
            candidates: list[tuple[float, str, dict[str, Any]]] = []
            for block_id, block in available.items():
                if abs(float(block["section_total"]) - amount) > 0.01:
                    continue
                similarity = _text_similarity(
                    str(summary.get("item_text") or ""),
                    str(block.get("section_text") or ""),
                )
                candidates.append((similarity, block_id, block))
            candidates.sort(key=lambda item: item[0], reverse=True)
            if candidates and candidates[0][0] >= self.SUMMARY_MATCH_MIN_SIMILARITY:
                similarity, block_id, block = candidates[0]
                matched.append(
                    {
                        "summary_index": summary["summary_index"],
                        "section_block_id": block_id,
                        "text_similarity": round(similarity, 4),
                        "total_price": amount,
                    }
                )
                available.pop(block_id, None)
            else:
                unmatched.append(summary)

        detail_total = round(sum(item["total_price"] for item in matched), 2)
        summary_only_total = round(
            sum(float(item.get("total_price") or 0) for item in unmatched), 2
        )
        reconciliation = {
            "summary_raw_rows_count": len(summary_rows),
            "summary_priceable_rows_count": sum(1 for item in summary_rows if item.get("priceable")),
            "summary_matched_count": len(matched),
            "summary_only_count": len(unmatched),
            "summary_ignored_info_count": ignored_info,
            "detail_rows_total": detail_total,
            "summary_only_total": summary_only_total,
            "computed_import_total": round(detail_total + summary_only_total, 2),
            "matches": matched,
            "unmatched_summary_rows": [
                {
                    "summary_index": item.get("summary_index"),
                    "item_text": item.get("item_text"),
                    "total_price": item.get("total_price"),
                }
                for item in unmatched
            ],
        }
        return unmatched, reconciliation
