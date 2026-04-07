from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterable

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


async def create_embeddings(texts: Iterable[str]) -> list[list[float]]:
    items = list(texts)
    if not items:
        return []

    payload = {
        "model": settings.EMBEDDING_MODEL,
        "input": items,
    }
    headers = {
        "Authorization": f"Bearer {get_openrouter_api_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.APP_BASE_URL,
        "X-Title": "construction-backend",
    }
    timeout = httpx.Timeout(60.0, connect=15.0)
    last_error: Exception | None = None

    async with httpx.AsyncClient(base_url=settings.EMBEDDING_BASE_URL, timeout=timeout) as client:
        for attempt in range(5):
            try:
                response = await client.post("/embeddings", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                break
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code
                if status not in {429, 500, 502, 503, 504} or attempt == 4:
                    body = exc.response.text[:500]
                    raise RuntimeError(
                        f"OpenRouter embeddings request failed with status {status}: {body}"
                    ) from exc
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt == 4:
                    raise RuntimeError("OpenRouter embeddings request failed.") from exc

            await asyncio.sleep(min(2 ** attempt, 10))
        else:
            raise RuntimeError("OpenRouter embeddings request failed.") from last_error

    embeddings = [item["embedding"] for item in data.get("data", [])]
    if len(embeddings) != len(items):
        raise RuntimeError(
            f"Embeddings response size mismatch: expected {len(items)}, got {len(embeddings)}."
        )
    return embeddings
