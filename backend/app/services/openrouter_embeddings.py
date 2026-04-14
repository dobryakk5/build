from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import httpx

from app.core.config import settings


def _read_legacy_key_from_env_file() -> str:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return ""

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        normalized = line[1:].strip() if line.startswith("#") else line
        if normalized.startswith("OPENROUTER_API_KEY=") or normalized.startswith("openrouter_API="):
            return normalized.split("=", 1)[1].strip()
    return ""


def get_openrouter_api_key() -> str:
    key = (
        settings.OPENROUTER_API_KEY.strip()
        or settings.openrouter_API.strip()
        or _read_legacy_key_from_env_file()
    )
    if not key:
        raise RuntimeError(
            "OpenRouter API key is not configured. Set OPENROUTER_API_KEY "
            "or legacy openrouter_API in backend/.env."
        )
    return key


def _build_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_openrouter_api_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.APP_BASE_URL,
        "X-Title": "construction-backend",
    }


async def _post_openrouter(
    path: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    headers = _build_headers()
    timeout = httpx.Timeout(60.0, connect=15.0)
    last_error: Exception | None = None

    async with httpx.AsyncClient(base_url=settings.EMBEDDING_BASE_URL, timeout=timeout) as client:
        for attempt in range(5):
            try:
                response = await client.post(path, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code
                if status not in {429, 500, 502, 503, 504} or attempt == 4:
                    body = exc.response.text[:500]
                    raise RuntimeError(
                        f"OpenRouter request failed with status {status}: {body}"
                    ) from exc
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt == 4:
                    raise RuntimeError("OpenRouter request failed.") from exc

            await asyncio.sleep(min(2 ** attempt, 10))

    raise RuntimeError("OpenRouter request failed.") from last_error


async def create_embeddings(texts: Iterable[str]) -> list[list[float]]:
    items = list(texts)
    if not items:
        return []

    data = await _post_openrouter(
        "/embeddings",
        {
            "model": settings.EMBEDDING_MODEL,
            "input": items,
        },
    )

    embeddings = [item["embedding"] for item in data.get("data", [])]
    if len(embeddings) != len(items):
        raise RuntimeError(
            f"Embeddings response size mismatch: expected {len(items)}, got {len(embeddings)}."
        )
    return embeddings


async def create_chat_completion(
    *,
    model: str,
    messages: Sequence[dict[str, Any]],
    temperature: float = 0.0,
    max_tokens: int = 500,
) -> str:
    data = await _post_openrouter(
        "/chat/completions",
        {
            "model": model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
    )
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("OpenRouter chat response did not return choices.")

    content = choices[0].get("message", {}).get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return "".join(parts).strip()
    raise RuntimeError("OpenRouter chat response content is missing.")


def parse_json_object(content: str) -> dict[str, Any]:
    trimmed = content.strip()
    if trimmed.startswith("```"):
        trimmed = trimmed.strip("`")
        if trimmed.startswith("json"):
            trimmed = trimmed[4:].strip()

    try:
        value = json.loads(trimmed)
    except json.JSONDecodeError:
        start = trimmed.find("{")
        end = trimmed.rfind("}")
        if start < 0 or end < 0 or end <= start:
            raise RuntimeError("Model did not return a valid JSON object.")
        value = json.loads(trimmed[start : end + 1])

    if not isinstance(value, dict):
        raise RuntimeError("Model returned JSON, but not an object.")
    return value
