# backend/app/services/ktp_service.py
"""
Сервис генерации КТП (Карт Технологического Процесса).

Шаги:
1. build_ktp_groups_for_batch  — разбивает строки сметы на группы работ
   Приоритет: Estimate.section → fer_group_title → fer_group_collection_name → «Прочие работы»
   Идемпотентно: если группы уже есть и force=False — возвращает их без изменений.

2. generate_ktp_for_group — по group_id запрашивает LLM (OpenRouter chat completion)
   и сохраняет результат в ktp_cards:
   • данных не хватает → status questions_required, сохраняет questions_json
   • данных хватает    → status generated, сохраняет steps_json / recommendations_json
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Estimate, EstimateBatch
from app.models.ktp import KtpCard, KtpGroup
from app.services.openrouter_embeddings import create_chat_completion

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    """ASCII-slug для group_key (идемпотентный ключ группы)."""
    text = unicodedata.normalize("NFKC", text).lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:200]


def _clean_json(raw: str) -> str:
    """Убирает ```json ... ``` если LLM обернул ответ в markdown."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _nonempty(val: str | None) -> str | None:
    return val.strip() if val and val.strip() else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Access guards
# ─────────────────────────────────────────────────────────────────────────────

async def _assert_batch_belongs_to_project(
    db: AsyncSession,
    project_id: str,
    estimate_batch_id: str,
) -> EstimateBatch:
    """Проверяет что батч принадлежит проекту (IDOR guard)."""
    batch = await db.scalar(
        select(EstimateBatch)
        .where(EstimateBatch.id == estimate_batch_id)
        .where(EstimateBatch.project_id == project_id)
        .where(EstimateBatch.deleted_at.is_(None))
    )
    if not batch:
        raise ValueError(
            f"Блок сметы {estimate_batch_id} не найден в проекте {project_id}"
        )
    return batch


async def _assert_group_belongs_to_project(
    db: AsyncSession,
    project_id: str,
    group_id: str,
) -> KtpGroup:
    """Проверяет что группа принадлежит проекту (IDOR guard)."""
    group = await db.scalar(
        select(KtpGroup)
        .where(KtpGroup.id == group_id)
        .where(KtpGroup.project_id == project_id)
    )
    if not group:
        raise ValueError(
            f"Группа КТП {group_id} не найдена в проекте {project_id}"
        )
    return group


# ─────────────────────────────────────────────────────────────────────────────
# Grouping logic (pure, testable without DB)
# ─────────────────────────────────────────────────────────────────────────────

def _group_estimates(
    estimates: list[Estimate],
) -> list[tuple[str, str, list[Estimate]]]:
    """
    Группирует строки сметы по приоритету:
      section → fer_group_title → fer_group_collection_name → «Прочие работы»

    Возвращает список (group_key, display_title, [Estimate]) в порядке появления.
    """
    # ordered dict чтобы сохранить порядок первого появления группы
    buckets: dict[str, tuple[str, list[Estimate]]] = {}

    for e in estimates:
        raw_title = (
            _nonempty(e.section)
            or _nonempty(e.fer_group_title)
            or _nonempty(e.fer_group_collection_name)
            or "Прочие работы"
        )
        key = _slugify(raw_title)
        if key not in buckets:
            buckets[key] = (raw_title, [])
        buckets[key][1].append(e)

    return [(key, title, items) for key, (title, items) in buckets.items()]


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Build groups
# ─────────────────────────────────────────────────────────────────────────────

async def get_ktp_groups(
    db: AsyncSession,
    project_id: str,
    estimate_batch_id: str,
) -> list[KtpGroup]:
    """Возвращает сохранённые группы для батча, отсортированные по sort_order."""
    rows = await db.scalars(
        select(KtpGroup)
        .where(KtpGroup.project_id == project_id)
        .where(KtpGroup.estimate_batch_id == estimate_batch_id)
        .order_by(KtpGroup.sort_order, KtpGroup.created_at)
    )
    return list(rows)


async def build_ktp_groups_for_batch(
    db: AsyncSession,
    project_id: str,
    estimate_batch_id: str,
    force: bool = False,
) -> list[KtpGroup]:
    """
    Создаёт или обновляет группы работ для батча.

    force=False: если группы уже существуют — просто возвращает их (идемпотентно).
    force=True:  удаляет старые и строит заново (сбрасывает готовые КТП!).
    """
    await _assert_batch_belongs_to_project(db, project_id, estimate_batch_id)

    existing = await get_ktp_groups(db, project_id, estimate_batch_id)
    if existing and not force:
        return existing

    if existing and force:
        for g in existing:
            await db.delete(g)
        await db.flush()

    # Загружаем строки сметы для батча
    estimates: list[Estimate] = list(
        await db.scalars(
            select(Estimate)
            .where(Estimate.project_id == project_id)
            .where(Estimate.estimate_batch_id == estimate_batch_id)
            .where(Estimate.deleted_at.is_(None))
            .order_by(Estimate.row_order, Estimate.id)
        )
    )
    if not estimates:
        return []

    groups_raw = _group_estimates(estimates)
    result: list[KtpGroup] = []

    for sort_order, (key, title, items) in enumerate(groups_raw):
        total = sum(
            float(e.total_price) for e in items if e.total_price is not None
        )
        group = KtpGroup(
            project_id=project_id,
            estimate_batch_id=estimate_batch_id,
            group_key=key,
            title=title,
            estimate_ids=[e.id for e in items],
            row_count=len(items),
            total_price=total or None,
            sort_order=sort_order,
            status="new",
        )
        db.add(group)
        result.append(group)

    await db.flush()
    for g in result:
        await db.refresh(g)

    await db.commit()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Generate KTP
# ─────────────────────────────────────────────────────────────────────────────

async def generate_ktp_for_group(
    db: AsyncSession,
    project_id: str,
    group_id: str,
    answers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Запускает генерацию КТП для группы через OpenRouter.

    Возвращает одно из двух:
      {"sufficient": False, "questions": [...]}
    или
      {"sufficient": True, "ktp_card_id": str, "ktp": {...}}

    Состояние (вопросы / КТП / ошибки) персистируется в ktp_cards.
    """
    group = await _assert_group_belongs_to_project(db, project_id, group_id)
    card = await _get_or_create_card(db, group)
    estimates = await _load_estimates_for_group(db, group)

    prompt = _build_prompt(group, estimates, answers or {})

    model: str = getattr(settings, "KTP_GENERATION_MODEL", "openai/gpt-4o-mini")
    max_tokens: int = getattr(settings, "KTP_MAX_TOKENS", 3000)

    try:
        raw = await create_chat_completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        card.status = "failed"
        card.error_message = str(exc)
        card.updated_at = _now()
        await db.commit()
        raise

    try:
        parsed = json.loads(_clean_json(raw))
    except json.JSONDecodeError as exc:
        card.status = "failed"
        card.error_message = f"JSON parse error: {exc}\nRaw: {raw[:500]}"
        card.updated_at = _now()
        await db.commit()
        raise ValueError(f"LLM вернул невалидный JSON: {exc}") from exc

    card.llm_model = model
    card.prompt_version = PROMPT_VERSION
    card.updated_at = _now()

    if answers:
        card.answers_json = answers

    sufficient: bool = bool(parsed.get("sufficient", True))

    if not sufficient:
        questions = parsed.get("questions", [])
        card.questions_json = questions
        card.status = "questions_required"
        group.status = "questions_required"
        group.updated_at = _now()
        await db.commit()
        return {"sufficient": False, "questions": questions}

    # Данных хватает — сохраняем КТП
    ktp_data = parsed.get("ktp", {})
    card.title = ktp_data.get("title") or group.title
    card.goal = ktp_data.get("goal", "")
    card.steps_json = ktp_data.get("steps", [])
    card.recommendations_json = ktp_data.get("recommendations", [])
    card.questions_json = None
    card.status = "generated"
    group.status = "generated"
    group.updated_at = _now()

    await db.commit()
    await db.refresh(card)

    return {
        "sufficient": True,
        "ktp_card_id": card.id,
        "ktp": {
            "title": card.title,
            "goal": card.goal,
            "steps": card.steps_json or [],
            "recommendations": card.recommendations_json or [],
        },
    }


async def _get_or_create_card(db: AsyncSession, group: KtpGroup) -> KtpCard:
    """Возвращает существующую ktp_card для группы или создаёт новую."""
    # Если ktp_card уже загружен через selectin — используем его
    if group.ktp_card is not None:
        return group.ktp_card

    card = KtpCard(
        project_id=group.project_id,
        estimate_batch_id=group.estimate_batch_id,
        ktp_group_id=group.id,
        status="draft",
    )
    db.add(card)
    await db.flush()
    await db.refresh(card)
    return card


async def _load_estimates_for_group(
    db: AsyncSession, group: KtpGroup
) -> list[Estimate]:
    """Загружает строки сметы для группы по estimate_ids."""
    if not group.estimate_ids:
        return []
    rows = await db.scalars(
        select(Estimate)
        .where(Estimate.id.in_(group.estimate_ids))
        .where(Estimate.deleted_at.is_(None))
        .order_by(Estimate.row_order, Estimate.id)
    )
    return list(rows)


def _build_prompt(
    group: KtpGroup,
    estimates: list[Estimate],
    answers: dict[str, str],
) -> str:
    """Формирует промпт для генерации КТП."""
    lines = []
    for e in estimates:
        qty = (
            f"{float(e.quantity):.2f} {e.unit or ''}".strip()
            if e.quantity is not None
            else "—"
        )
        price = f"{float(e.total_price):.2f} руб." if e.total_price is not None else "—"
        lines.append(f"  • {e.work_name} | {qty} | {price}")

    works_block = "\n".join(lines) if lines else "  (нет позиций)"

    answers_block = ""
    if answers:
        answers_block = "\n\nДополнительные данные от заказчика:\n" + "\n".join(
            f"  {k}: {v}" for k, v in answers.items()
        )

    return f"""Ты эксперт-технолог в строительстве. На основе группы работ из строительной сметы создай КТП (Карту Технологического Процесса).

ГРУППА РАБОТ: «{group.title}»
Количество позиций: {group.row_count}

ПОЗИЦИИ СМЕТЫ:
{works_block}
{answers_block}

ИНСТРУКЦИЯ:
1. Если данных ДОСТАТОЧНО для создания качественного КТП — сразу создай его.
2. Если каких-то ключевых технических данных НЕ ХВАТАЕТ (марка бетона, класс арматуры, условия грунта, проектные нагрузки и т.п.) — задай уточняющие вопросы.

Верни ТОЛЬКО JSON (без markdown-блоков, без пояснений вне JSON).

Если данных не хватает:
{{
  "sufficient": false,
  "questions": [
    {{
      "key": "concrete_grade",
      "label": "Какой класс бетона предусмотрен проектом?",
      "type": "text",
      "hint": "Например: B25, B30"
    }}
  ]
}}

Если данных достаточно:
{{
  "sufficient": true,
  "questions": [],
  "ktp": {{
    "title": "КТП: Возведение монолитной фундаментной плиты",
    "goal": "Обеспечить качественное выполнение работ в соответствии с проектом и СП",
    "steps": [
      {{
        "no": 1,
        "stage": "Подготовительные работы",
        "work_details": "Разбивка осей, устройство щебёночной подготовки t=100 мм, уплотнение основания, установка опалубки по периметру плиты",
        "control_points": "Нивелировка основания (отклонение ≤ 5 мм/м), акт освидетельствования основания"
      }}
    ],
    "recommendations": [
      "Бетонирование производить непрерывно, не допускать рабочих швов",
      "Уход за бетоном — влажное укрытие не менее 7 суток при t > +5°C"
    ]
  }}
}}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Read card
# ─────────────────────────────────────────────────────────────────────────────

async def get_ktp_card(
    db: AsyncSession,
    project_id: str,
    group_id: str,
) -> KtpCard | None:
    """Возвращает ktp_card для группы (или None если ещё не создана)."""
    group = await _assert_group_belongs_to_project(db, project_id, group_id)
    # ktp_card уже загружен через selectin
    return group.ktp_card
