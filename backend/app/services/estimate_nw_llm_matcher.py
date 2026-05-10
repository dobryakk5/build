"""
LLM-fallback для строк сметы, которые не сматчились keyword'ами на NW.

Алгоритм:
  • Берём строки сметы которые НЕ привязаны к карточкам плана
  • Группируем по 15 — отправляем одним промптом → один JSON-ответ
  • Палитра NW (allowed) задаётся из палитры типа сметы
  • LLM возвращает {row_id: nw_code | null}
  • null = «не подходит ни один» (например мебель / услуги / неинженерные работы)

Стоимость (gpt-4o-mini):
  ~ $0.0002 на batch из 15 строк → $0.002 на смету в 100 строк.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.services.openrouter_embeddings import (
    create_chat_completion,
    parse_json_object,
)

logger = logging.getLogger(__name__)

LLM_MODEL = "openai/gpt-oss-120b:free"
# Альтернативы для тестов:
#   "openai/gpt-oss-120b:free"
#   "nvidia/nemotron-3-super-120b-a12b:free"
BATCH_SIZE = 15

SYSTEM_PROMPT = (
    "Ты эксперт по строительным сметам. Классифицируешь строки сметы по "
    "нормализованным видам работ (NW). Возвращаешь СТРОГО JSON-объект. "
    "Все рассуждения и комментарии — только на русском языке."
)


def _format_palette(palette: list[dict[str, Any]]) -> str:
    """Готовим список NW для промпта."""
    lines: list[str] = []
    for p in palette:
        code = p["nw_item_code"]
        label = p["unique_label"]
        subtype = p.get("subtype")
        if subtype:
            lines.append(f"- {code}: {label} ({subtype})")
        else:
            lines.append(f"- {code}: {label}")
    return "\n".join(lines)


def _format_rows(rows: list[dict[str, Any]]) -> str:
    """Готовим список строк сметы для промпта (1-based индекс)."""
    lines: list[str] = []
    for i, r in enumerate(rows, 1):
        section = r.get("section") or "—"
        work_name = r.get("work_name") or ""
        lines.append(f"{i}. [{section}] {work_name}")
    return "\n".join(lines)


async def llm_match_batch(
    rows: list[dict[str, Any]],
    palette: list[dict[str, Any]],
) -> dict[str, str | None]:
    """
    Один запрос к LLM для пачки строк сметы.
    rows:    [{"id": uuid, "section": str|None, "work_name": str}, ...]  (≤BATCH_SIZE)
    palette: [{"nw_item_code": "NW-001", "unique_label": "...", "subtype": ...}, ...]

    Возвращает {row_id: nw_code | None}
    """
    if not rows:
        return {}

    palette_text = _format_palette(palette)
    rows_text = _format_rows(rows)

    user_prompt = f"""ПАЛИТРА NW (выбирай только из этих кодов):
{palette_text}

СТРОКИ СМЕТЫ ДЛЯ КЛАССИФИКАЦИИ:
{rows_text}

ЗАДАЧА: для каждой строки выбери ОДИН наиболее подходящий NW код из палитры.
Если строка вообще не относится к строительным работам (мебель, аренда, услуги без выезда, доставка) — верни null.

Верни СТРОГО JSON-объект где ключ — номер строки (как строка), значение — код NW или null:
{{
  "1": "NW-XXX",
  "2": "NW-YYY",
  "3": null,
  ...
}}
Никаких комментариев, только JSON."""

    try:
        raw = await create_chat_completion(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=2000,
        )
    except Exception as e:
        logger.warning("LLM batch failed: %s", e)
        return {str(r["id"]): None for r in rows}

    try:
        parsed = parse_json_object(raw)
    except Exception as e:
        logger.warning("LLM returned invalid JSON: %s | raw=%s", e, raw[:200])
        return {str(r["id"]): None for r in rows}

    palette_codes = {p["nw_item_code"] for p in palette}
    result: dict[str, str | None] = {}
    for i, r in enumerate(rows, 1):
        rid = str(r["id"])
        v = parsed.get(str(i)) or parsed.get(i)
        if not v or not isinstance(v, str):
            result[rid] = None
            continue
        v = v.strip().upper()
        if not re.match(r"^NW-\d{3}$", v):
            result[rid] = None
            continue
        if v not in palette_codes:
            # LLM выдал NW не из палитры — игнорируем (защита от галлюцинаций)
            logger.info("LLM returned out-of-palette NW: %s for row %s", v, rid)
            result[rid] = None
            continue
        result[rid] = v
    return result


async def llm_match_all(
    rows: list[dict[str, Any]],
    palette: list[dict[str, Any]],
) -> dict[str, str | None]:
    """Прогнать все строки batch'ами по BATCH_SIZE и склеить результаты."""
    if not rows:
        return {}
    out: dict[str, str | None] = {}
    for i in range(0, len(rows), BATCH_SIZE):
        chunk = rows[i:i + BATCH_SIZE]
        partial = await llm_match_batch(chunk, palette)
        out.update(partial)
    return out
