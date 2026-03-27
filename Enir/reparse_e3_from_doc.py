#!/usr/bin/env python3
"""
Rebuild ENIR E3 JSON from a legacy .doc file using OpenRouter.

The local .doc -> .docx path on macOS loses table structure, but plain-text
extraction via textutil keeps enough content to reconstruct each paragraph.
This script:
  1. extracts normalized text from .doc
  2. splits E3 into paragraph snippets
  3. asks a free OpenRouter model to emit structured JSON for each paragraph
  4. optionally imports the rebuilt collection into PostgreSQL
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests


MODEL = "nvidia/nemotron-nano-12b-v2-vl:free"
OPENROUTER_URL = "https://openrouter.ai/api/v1/responses"


def load_env() -> None:
    for p in [
        Path(__file__).resolve().parent.parent / "backend" / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]:
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def extract_text(doc_path: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="enir_doc_") as td:
        txt_path = Path(td) / "source.txt"
        subprocess.run(
            ["textutil", "-convert", "txt", "-output", str(txt_path), str(doc_path)],
            check=True,
        )
        raw = txt_path.read_text(encoding="utf-8", errors="ignore")

    text = raw.encode("latin1", errors="ignore").decode("cp1251", errors="ignore")
    text = re.sub(r"§\s*ЕЗ-", "§ Е3-", text)
    text = re.sub(r"§\s*E3-", "§ Е3-", text)
    text = text.replace("\x07", " ")
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def derive_meta(doc_path: Path) -> tuple[str, str, int]:
    stem = doc_path.stem
    sort_order = 0
    m_order = re.match(r"(\d+)\.", stem)
    if m_order:
        sort_order = int(m_order.group(1))

    m_code = re.search(r"Е\s*([0-9]+[а-яa-z]?)", stem, flags=re.IGNORECASE)
    if not m_code:
        raise SystemExit(f"Cannot derive collection code from {doc_path.name}")
    collection_code = f"Е{m_code.group(1)}"
    return collection_code, stem, sort_order


def load_reference(reference_json: Path) -> list[dict]:
    data = json.loads(reference_json.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"Reference JSON must contain a list: {reference_json}")
    return data


def find_heading_positions(text: str) -> dict[str, int]:
    positions: dict[str, int] = {}
    for m in re.finditer(r"§\s*Е3-(\d+[а-яa-z]?)\.", text):
        code = f"Е3-{m.group(1)}"
        snippet = text[m.start():m.start() + 180]
        if code == "Е3-19" and "нормировать дополнительно" in snippet.lower():
            continue
        if code == "Е3-3" and "Таблица 1" in snippet and "Состав звена" in snippet:
            continue
        positions.setdefault(code, m.start())
    return positions


def build_sections(text: str, codes: list[str]) -> dict[str, str]:
    positions = find_heading_positions(text)
    needed = [c for c in codes if c in positions]
    needed.sort(key=lambda code: positions[code])

    sections: dict[str, str] = {}
    for idx, code in enumerate(needed):
        start = positions[code]
        end = positions[needed[idx + 1]] if idx + 1 < len(needed) else len(text)
        sections[code] = text[start:end].strip()

    # In the source text, E3-7/8/9 lost explicit paragraph headers.
    e6 = sections.get("Е3-6")
    if e6 and "§ Е3-10." in text:
        gap_start = positions["Е3-6"]
        gap_end = positions["Е3-10"]
        gap = text[gap_start:gap_end]

        m7 = re.search(
            r"Указания по применению норм\s+Нормой предусмотрена кладка наружных стен толщиной",
            gap,
            flags=re.DOTALL,
        )
        m8 = re.search(
            r"Нормами предусмотрена кладка наружных стен из керамических камней",
            gap,
            flags=re.DOTALL,
        )
        m9 = re.search(
            r"Состав работы\s+1\. Натягивание причалки\. 2\. Подача и раскладка кирпича\.",
            gap,
            flags=re.DOTALL,
        )
        if m7 and m8 and m9:
            sections["Е3-6"] = gap[:m7.start()].strip()
            sections["Е3-7"] = gap[m7.start():m8.start()].strip()
            sections["Е3-8"] = gap[m8.start():m9.start()].strip()
            sections["Е3-9"] = gap[m9.start():].strip()

    missing = [code for code in codes if code not in sections]
    if missing:
        raise SystemExit(f"Could not locate snippets for codes: {', '.join(missing)}")
    return sections


def make_prompt(code: str, snippet: str, reference: dict) -> list[dict]:
    schema = {
        "code": "Е3-N",
        "title": "string",
        "unit": "string|null",
        "work_compositions": [
            {"condition": "string|null", "operations": ["string", "..."]}
        ],
        "crew": [
            {"profession": "string", "grade": "number|null", "count": "integer"}
        ],
        "norms": [
            {
                "row_num": "integer|null",
                "work_type": "string|null",
                "condition": "string|null",
                "thickness_mm": "integer|null",
                "column_label": "string|null",
                "norm_time": "number|null",
                "price_rub": "number|null",
            }
        ],
        "notes": [
            {
                "num": "integer",
                "text": "string",
                "coefficient": "number|null",
                "code": "string|null",
            }
        ],
    }
    system = (
        "You extract one ENIR paragraph from noisy Russian plain text. "
        "Return only one valid JSON object and nothing else. "
        "Use the raw snippet as the main source of truth. "
        "The reference JSON is only a weak hint because it may be incomplete or wrong. "
        "Keep Russian text. Use dot decimals. Use empty arrays when a block is absent."
    )
    user = {
        "target_code": code,
        "expected_title_hint": reference.get("title"),
        "json_schema": schema,
        "reference_json_may_be_incomplete": reference,
        "raw_document_snippet": snippet,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def parse_model_response(raw: str) -> dict:
    clean = raw.strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s*```$", "", clean)
    obj = json.loads(clean)
    if not isinstance(obj, dict):
        raise ValueError("response is not an object")
    return obj


def extract_output_text(response_json: dict) -> str:
    chunks: list[str] = []
    for item in response_json.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content", []) or []:
            if part.get("type") == "output_text" and part.get("text"):
                chunks.append(part["text"])
    if not chunks:
        raise ValueError(f"No output_text in response: {response_json}")
    return "".join(chunks)


def call_model(api_key: str, messages: list[dict], retries: int = 2) -> dict:
    input_items = []
    for msg in messages:
        input_items.append(
            {
                "type": "message",
                "role": msg["role"],
                "content": [
                    {
                        "type": "input_text",
                        "text": msg["content"],
                    }
                ],
            }
        )
    payload = {
        "model": MODEL,
        "input": input_items,
        "temperature": 0.1,
        "max_output_tokens": 12000,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=180,
            )
            resp.raise_for_status()
            raw = extract_output_text(resp.json())
            return parse_model_response(raw)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                time.sleep(2 + attempt)
            else:
                raise RuntimeError(f"OpenRouter failed: {exc}") from exc
    raise RuntimeError(f"OpenRouter failed: {last_err}")


def normalize_paragraph(obj: dict, code: str, fallback_title: str) -> dict:
    obj["code"] = obj.get("code") or code
    obj["title"] = (obj.get("title") or fallback_title).strip()
    obj["unit"] = obj.get("unit")
    obj["work_compositions"] = obj.get("work_compositions") or []
    obj["crew"] = obj.get("crew") or []
    obj["norms"] = obj.get("norms") or []
    obj["notes"] = obj.get("notes") or []
    return obj


def rebuild_json(
    doc_path: Path,
    reference_json: Path,
    output_json: Path,
    api_key: str,
) -> list[dict]:
    ref_items = load_reference(reference_json)
    ref_by_code = {item["code"]: item for item in ref_items}
    codes = [item["code"] for item in ref_items]

    text = extract_text(doc_path)
    sections = build_sections(text, codes)

    existing: dict[str, dict] = {}
    if output_json.exists():
        try:
            old = json.loads(output_json.read_text(encoding="utf-8"))
            if isinstance(old, list):
                existing = {
                    item["code"]: item
                    for item in old
                    if isinstance(item, dict) and item.get("code")
                }
        except Exception:  # noqa: BLE001
            existing = {}

    rebuilt: list[dict] = []
    for idx, code in enumerate(codes, start=1):
        ref = ref_by_code[code]
        snippet = sections[code]
        if code in existing:
            print(f"[{idx:02d}/{len(codes)}] {code}  resume", flush=True)
            rebuilt.append(existing[code])
            continue
        print(f"[{idx:02d}/{len(codes)}] {code}  snippet={len(snippet)} chars", flush=True)
        obj = call_model(api_key, make_prompt(code, snippet, ref))
        rebuilt.append(normalize_paragraph(obj, code, ref["title"]))
        output_json.write_text(
            json.dumps(rebuilt, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return rebuilt


def import_into_db(
    json_path: Path,
    collection_code: str,
    collection_title: str,
    sort_order: int,
) -> None:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent.parent / "backend" / "import_enir.py"),
        str(json_path),
        "--collection-code",
        collection_code,
        "--collection-title",
        collection_title,
        "--sort-order",
        str(sort_order),
        "--overwrite",
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    load_env()

    ap = argparse.ArgumentParser(description="Rebuild ENIR E3 JSON from .doc via OpenRouter")
    ap.add_argument("doc_file", help="Path to source .doc file")
    ap.add_argument(
        "--reference-json",
        default=str(Path(__file__).resolve().parent / "enir_e3.json"),
        help="Existing JSON used as a weak hint and as the canonical code order",
    )
    ap.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent / "22.ЕНиР Сборник Е 3.qwen.json"),
        help="Where to write rebuilt JSON",
    )
    ap.add_argument("--import-db", action="store_true", help="Import into PostgreSQL after rebuild")
    args = ap.parse_args()

    api_key = os.environ.get("openrouter_API") or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("openrouter_API / OPENROUTER_API_KEY is not set")

    doc_path = Path(args.doc_file).resolve()
    ref_path = Path(args.reference_json).resolve()
    out_path = Path(args.out).resolve()

    collection_code, collection_title, sort_order = derive_meta(doc_path)
    rebuilt = rebuild_json(doc_path, ref_path, out_path, api_key)

    print(
        f"\nRebuilt {len(rebuilt)} paragraphs -> {out_path}\n"
        f"Collection: code={collection_code} title={collection_title!r} sort_order={sort_order}"
    )

    if args.import_db:
        import_into_db(out_path, collection_code, collection_title, sort_order)


if __name__ == "__main__":
    main()
