#!/usr/bin/env python3
"""
Find meaningful discrepancies between the legacy E3 .doc and current enir_e3.json.

Usage:
  python3 Enir/find_e3_discrepancies.py
  python3 Enir/find_e3_discrepancies.py --issue E3-6:unit_diff
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Enir.reparse_e3_from_doc import build_sections, extract_text, load_reference


def infer_unit(section: str) -> str | None:
    m = re.search(r"Нормы времени(?: и расценки)? на\s+([^\n]+)", section, flags=re.IGNORECASE)
    if not m:
        return None
    unit = re.sub(r"\s+", " ", m.group(1)).strip(" .")
    return unit


def normalize_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    unit = unit.strip()
    unit = re.sub(r"^\d+\s+", "", unit)
    unit = re.sub(r"\s+", " ", unit)
    return unit


def infer_has_crew(section: str) -> bool:
    return "Состав звена" in section or bool(re.search(r"Каменщик\s+\d\s*разр", section))


def infer_has_work(section: str) -> bool:
    return "Состав работ" in section or "Состав работы" in section


def issue_snippet(section: str, issue_type: str) -> str:
    if issue_type == "unit_diff":
        m = re.search(r"(Нормы времени(?: и расценки)? на\s+[^\n]+)", section, flags=re.IGNORECASE)
        return m.group(1) if m else section[:600]
    if issue_type == "crew_present_in_doc_but_empty_in_json":
        idx = section.find("Состав звена")
        if idx == -1:
            idx = max(0, section.find("Каменщик"))
        return section[idx:idx + 1200].strip()
    if issue_type == "work_present_in_doc_but_empty_in_json":
        idx = section.find("Состав работ")
        if idx == -1:
            idx = section.find("Состав работы")
        return section[idx:idx + 1600].strip()
    return section[:1200].strip()


def find_discrepancies(doc_path: Path, json_path: Path) -> list[dict]:
    text = extract_text(doc_path)
    ref = load_reference(json_path)
    sections = build_sections(text, [x["code"] for x in ref])

    issues: list[dict] = []
    for item in ref:
        code = item["code"]
        section = sections[code]

        if code in {"Е3-7", "Е3-8", "Е3-9"}:
            issues.append(
                {
                    "code": code,
                    "issue_type": "missing_explicit_heading_in_doc_text",
                    "details": "Paragraph body exists in document text, but explicit heading was lost during extraction.",
                    "json_value": item["title"],
                    "doc_value": None,
                    "snippet": issue_snippet(section, "missing_explicit_heading_in_doc_text"),
                }
            )

        doc_unit = normalize_unit(infer_unit(section))
        json_unit = normalize_unit(item.get("unit"))
        if doc_unit and json_unit and doc_unit != json_unit:
            issues.append(
                {
                    "code": code,
                    "issue_type": "unit_diff",
                    "details": "Document-derived unit differs from current JSON after normalization.",
                    "json_value": json_unit,
                    "doc_value": doc_unit,
                    "snippet": issue_snippet(section, "unit_diff"),
                }
            )

        if infer_has_crew(section) and len(item.get("crew") or []) == 0:
            issues.append(
                {
                    "code": code,
                    "issue_type": "crew_present_in_doc_but_empty_in_json",
                    "details": "Document contains crew information, but JSON crew array is empty.",
                    "json_value": [],
                    "doc_value": "crew section present",
                    "snippet": issue_snippet(section, "crew_present_in_doc_but_empty_in_json"),
                }
            )

        if infer_has_work(section) and len(item.get("work_compositions") or []) == 0:
            issues.append(
                {
                    "code": code,
                    "issue_type": "work_present_in_doc_but_empty_in_json",
                    "details": "Document contains work-composition text, but JSON has no work compositions.",
                    "json_value": [],
                    "doc_value": "work section present",
                    "snippet": issue_snippet(section, "work_present_in_doc_but_empty_in_json"),
                }
            )

    return issues


def select_issue(issues: list[dict], key: str) -> dict:
    code, issue_type = key.split(":", 1)
    for issue in issues:
        if issue["code"] == code and issue["issue_type"] == issue_type:
            return issue
    raise SystemExit(f"Issue not found: {key}")


def build_single_issue_prompt(issue: dict, item: dict) -> dict:
    return {
        "task": "Analyze exactly one discrepancy in ENIR E3",
        "rules": [
            "Analyze only this one issue.",
            "Do not rewrite the whole paragraph.",
            "If the JSON value is already acceptable for the current schema, say so.",
            "Return only JSON.",
        ],
        "response_schema": {
            "code": "Е3-N",
            "issue_type": issue["issue_type"],
            "verdict": "keep_json | change_json | schema_limitation",
            "recommended_value": "string | array | null",
            "reasoning": "short string",
        },
        "issue": {
            "code": issue["code"],
            "issue_type": issue["issue_type"],
            "details": issue["details"],
            "json_value": issue["json_value"],
            "doc_value": issue["doc_value"],
        },
        "current_json_fragment": {
            "title": item.get("title"),
            "unit": item.get("unit"),
            "crew": item.get("crew"),
            "work_compositions": item.get("work_compositions"),
        },
        "raw_document_snippet": issue["snippet"],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Find ENIR E3 discrepancies before single-issue model analysis")
    ap.add_argument(
        "--doc",
        default="Enir/22.ЕНиР Сборник Е 3.doc",
        help="Source .doc file",
    )
    ap.add_argument(
        "--json",
        default="Enir/enir_e3.json",
        help="Current JSON file",
    )
    ap.add_argument(
        "--issue",
        default=None,
        help="Print a single-issue prompt payload, e.g. E3-6:unit_diff",
    )
    args = ap.parse_args()

    doc_path = Path(args.doc)
    json_path = Path(args.json)

    ref = load_reference(json_path)
    ref_by_code = {item["code"]: item for item in ref}
    issues = find_discrepancies(doc_path, json_path)

    if args.issue:
        issue = select_issue(issues, args.issue)
        prompt = build_single_issue_prompt(issue, ref_by_code[issue["code"]])
        print(json.dumps(prompt, ensure_ascii=False, indent=2))
        return

    print(json.dumps(issues, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
