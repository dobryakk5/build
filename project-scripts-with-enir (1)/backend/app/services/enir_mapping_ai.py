"""
app/services/enir_mapping_ai.py

Два вызова к OpenRouter:
  map_group_to_collection  — группа задач → сборник ЕНИР
  map_estimate_to_paragraph — строка сметы → параграф ЕНИР

Модели (пробуем по очереди при ошибке):
  PRIMARY  : openrouter/hunter-alpha          — сильная, русский ок
  FALLBACK : google/gemini-2.0-flash-001      — быстрая, русский отличный
  FALLBACK2: mistralai/mistral-large-2407     — надёжная, русский хороший
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

# ── Модели в порядке приоритета ───────────────────────────────────────────────
_MODELS = [
    settings.OPENROUTER_MODEL,           # из .env, по умолчанию hunter-alpha
    "google/gemini-2.0-flash-001",
    "mistralai/mistral-large-2407",
]

_TIMEOUT = 60.0   # секунд


# ─────────────────────────────────────────────────────────────────────────────
# Базовый HTTP-вызов
# ─────────────────────────────────────────────────────────────────────────────

async def _chat(prompt: str) -> str:
    """
    Отправляет промпт, пробует модели по очереди.
    Возвращает text-ответ или бросает RuntimeError.
    """
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://construction-app.local",
        "X-Title":       "Construction ENIR Mapper",
    }

    last_err: Exception | None = None

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for model in _MODELS:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,    # нужна детерминированность
                "max_tokens": 1024,
            }
            try:
                resp = await client.post(
                    f"{settings.OPENROUTER_BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"].strip()
                    log.info("AI model=%s ok, len=%d", model, len(text))
                    return text
                else:
                    log.warning("AI model=%s status=%d, trying fallback", model, resp.status_code)
                    last_err = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                log.warning("AI model=%s error=%s, trying fallback", model, e)
                last_err = e

    raise RuntimeError(f"Все AI-модели недоступны. Последняя ошибка: {last_err}")


def _extract_json(text: str) -> dict:
    """
    Вытаскивает JSON из ответа модели.
    Модели иногда оборачивают его в ```json ... ```.
    """
    text = text.strip()
    # убираем markdown-блок если есть
    if "```" in text:
        start = text.find("{")
        end   = text.rfind("}") + 1
        if start != -1 and end > start:
            text = text[start:end]
    return json.loads(text)


# ─────────────────────────────────────────────────────────────────────────────
# Этап 1 — группа задач → сборник ЕНИР
# ─────────────────────────────────────────────────────────────────────────────

async def map_group_to_collection(
    group_name: str,
    sample_works: list[str],          # 5-10 дочерних work_name для контекста
    collections: list[dict],          # [{id, code, title, description}]
) -> dict:
    """
    Возвращает:
    {
      "collection_id": int | null,
      "collection_code": str | null,
      "confidence": float,
      "reasoning": str,
      "alternatives": [            # если confidence < 0.85
        {"collection_id": int, "code": str, "title": str, "confidence": float}
      ]
    }
    """
    coll_list = "\n".join(
        f'  - id={c["id"]}, код="{c["code"]}", название="{c["title"]}"'
        + (f', описание="{c["description"]}"' if c.get("description") else "")
        for c in collections
    )
    works_sample = "\n".join(f"  • {w}" for w in sample_works[:10])

    prompt = f"""Ты помощник по нормированию строительных работ.

Задача: определить, к какому сборнику ЕНИР относится группа работ из строительной сметы.

Группа работ: «{group_name}»

Примеры работ внутри этой группы:
{works_sample}

Доступные сборники ЕНИР:
{coll_list}

Выбери ОДИН наиболее подходящий сборник. Если уверенность ниже 0.85 — укажи альтернативы.

Ответь ТОЛЬКО валидным JSON (без пояснений вне JSON):
{{
  "collection_id": <id сборника или null если не подходит ни один>,
  "collection_code": <код сборника или null>,
  "confidence": <число от 0 до 1>,
  "reasoning": "<краткое объяснение на русском языке>",
  "alternatives": [
    {{"collection_id": <id>, "code": "<код>", "title": "<название>", "confidence": <число>}}
  ]
}}

Поле "alternatives" — пустой массив [] если уверенность >= 0.85.
"""
    raw = await _chat(prompt)

    try:
        result = _extract_json(raw)
    except Exception as e:
        log.error("Failed to parse AI response for group mapping: %s\nRaw: %s", e, raw[:300])
        return {
            "collection_id": None,
            "collection_code": None,
            "confidence": 0.0,
            "reasoning": f"Ошибка разбора ответа ИИ: {e}",
            "alternatives": [],
        }

    # валидация collection_id
    valid_ids = {c["id"] for c in collections}
    if result.get("collection_id") not in valid_ids:
        result["collection_id"] = None
        result["collection_code"] = None
        result["confidence"] = min(result.get("confidence", 0.0), 0.4)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Этап 2 — строка сметы → параграф + подсказка строки нормы
# ─────────────────────────────────────────────────────────────────────────────

async def map_estimate_to_paragraph(
    work_name: str,
    unit: str | None,
    collection_code: str,
    collection_title: str,
    paragraphs: list[dict],    # [{id, code, title, unit}]
) -> dict:
    """
    Возвращает:
    {
      "paragraph_id": int | null,
      "paragraph_code": str | null,
      "confidence": float,
      "reasoning": str,
      "norm_row_id": str | null,      # слабая ссылка (Вариант В)
      "norm_row_hint": str,           # текстовое описание строки нормы
      "alternatives": [
        {"paragraph_id": int, "code": str, "title": str, "confidence": float}
      ]
    }
    """
    para_list = "\n".join(
        f'  - id={p["id"]}, код="{p["code"]}", название="{p["title"]}"'
        + (f', ед="{p["unit"]}"' if p.get("unit") else "")
        for p in paragraphs
    )
    unit_str = f", единица измерения: {unit}" if unit else ""

    prompt = f"""Ты помощник по нормированию строительных работ.

Задача: найти параграф ЕНИР, соответствующий строке строительной сметы.

Сборник ЕНИР: {collection_code} — «{collection_title}»

Строка сметы: «{work_name}»{unit_str}

Параграфы сборника:
{para_list}

Найди ОДИН наиболее подходящий параграф.
Также укажи текстовую подсказку: какая именно строка таблицы норм подходит
(условие применения, толщина, тип, разряд грунта и т.п.) — одной фразой.

Ответь ТОЛЬКО валидным JSON (без пояснений вне JSON):
{{
  "paragraph_id": <id параграфа или null>,
  "paragraph_code": <код параграфа или null>,
  "confidence": <число от 0 до 1>,
  "reasoning": "<краткое объяснение на русском языке>",
  "norm_row_hint": "<подсказка какая строка нормы подходит, одна фраза>",
  "alternatives": [
    {{"paragraph_id": <id>, "code": "<код>", "title": "<название>", "confidence": <число>}}
  ]
}}

Поле "alternatives" — пустой массив [] если уверенность >= 0.85.
Если подходящего параграфа нет — paragraph_id: null, confidence: 0.
"""
    raw = await _chat(prompt)

    try:
        result = _extract_json(raw)
    except Exception as e:
        log.error("Failed to parse AI response for estimate mapping: %s\nRaw: %s", e, raw[:300])
        return {
            "paragraph_id":   None,
            "paragraph_code": None,
            "confidence":     0.0,
            "reasoning":      f"Ошибка разбора ответа ИИ: {e}",
            "norm_row_id":    None,
            "norm_row_hint":  "",
            "alternatives":   [],
        }

    # ИИ не знает norm_row_id — это поле заполняется отдельно или пользователем
    result.setdefault("norm_row_id", None)
    result.setdefault("norm_row_hint", "")

    # валидация paragraph_id
    valid_ids = {p["id"] for p in paragraphs}
    if result.get("paragraph_id") not in valid_ids:
        result["paragraph_id"] = None
        result["paragraph_code"] = None
        result["confidence"] = min(result.get("confidence", 0.0), 0.4)

    return result
