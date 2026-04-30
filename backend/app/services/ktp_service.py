from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Estimate, EstimateBatch
from app.models.ktp import KtpCard, KtpGroup
from app.services.openrouter_embeddings import create_chat_completion

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"
ESTIMATE_ITEM_TYPE_WORK = "work"
ESTIMATE_ITEM_TYPE_MECHANISM = "mechanism"


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:200]


def _clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _nonempty(val: str | None) -> str | None:
    return val.strip() if val and val.strip() else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _estimate_item_type(estimate: Estimate) -> str:
    item_type = getattr(estimate, "item_type", None)
    if item_type in {ESTIMATE_ITEM_TYPE_WORK, ESTIMATE_ITEM_TYPE_MECHANISM}:
        return item_type

    raw_data = getattr(estimate, "raw_data", None)
    if isinstance(raw_data, dict):
        item_type = raw_data.get("item_type")
        if item_type in {ESTIMATE_ITEM_TYPE_WORK, ESTIMATE_ITEM_TYPE_MECHANISM}:
            return item_type
    return ESTIMATE_ITEM_TYPE_WORK


async def _assert_batch_belongs_to_project(
    db: AsyncSession,
    project_id: str,
    estimate_batch_id: str,
) -> EstimateBatch:
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
    group = await db.scalar(
        select(KtpGroup)
        .where(KtpGroup.id == group_id)
        .where(KtpGroup.project_id == project_id)
    )
    if not group:
        raise ValueError(f"Группа КТП {group_id} не найдена в проекте {project_id}")
    return group


def _group_estimates(
    estimates: list[Estimate],
) -> list[tuple[str, str, list[Estimate]]]:
    buckets: dict[str, tuple[str, list[Estimate]]] = {}

    for estimate in estimates:
        raw_title = (
            _nonempty(estimate.section)
            or _nonempty(estimate.fer_group_title)
            or _nonempty(estimate.fer_group_collection_name)
            or "Прочие работы"
        )
        key = _slugify(raw_title)
        if key not in buckets:
            buckets[key] = (raw_title, [])
        buckets[key][1].append(estimate)

    return [(key, title, items) for key, (title, items) in buckets.items()]


async def get_ktp_groups(
    db: AsyncSession,
    project_id: str,
    estimate_batch_id: str,
) -> list[KtpGroup]:
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
    await _assert_batch_belongs_to_project(db, project_id, estimate_batch_id)

    existing = await get_ktp_groups(db, project_id, estimate_batch_id)
    if existing and not force:
        return existing

    if existing and force:
        for group in existing:
            await db.delete(group)
        await db.flush()

    estimates = list(
        await db.scalars(
            select(Estimate)
            .where(Estimate.project_id == project_id)
            .where(Estimate.estimate_batch_id == estimate_batch_id)
            .where(Estimate.deleted_at.is_(None))
            .order_by(Estimate.row_order, Estimate.id)
        )
    )
    estimates = [estimate for estimate in estimates if _estimate_item_type(estimate) == ESTIMATE_ITEM_TYPE_WORK]
    if not estimates:
        await db.commit()
        return []

    result: list[KtpGroup] = []
    for sort_order, (key, title, items) in enumerate(_group_estimates(estimates)):
        total = sum(float(item.total_price or 0) for item in items)
        group = KtpGroup(
            project_id=project_id,
            estimate_batch_id=estimate_batch_id,
            group_key=key,
            title=title,
            estimate_ids=[item.id for item in items],
            row_count=len(items),
            total_price=total or None,
            sort_order=sort_order,
            status="new",
        )
        db.add(group)
        result.append(group)

    try:
        await db.flush()
        for group in result:
            await db.refresh(group)

        await db.commit()
        return result
    except IntegrityError as exc:
        await db.rollback()
        existing = await get_ktp_groups(db, project_id, estimate_batch_id)
        if existing:
            logger.info(
                "KTP groups already created concurrently for project=%s batch=%s",
                project_id,
                estimate_batch_id,
            )
            return existing
        raise exc


async def generate_ktp_for_group(
    db: AsyncSession,
    project_id: str,
    group_id: str,
    answers: dict[str, str] | None = None,
) -> dict[str, Any]:
    group = await _assert_group_belongs_to_project(db, project_id, group_id)
    card = await _get_or_create_card(db, group)
    estimates = await _load_estimates_for_group(db, group)
    prompt = _build_prompt(group, estimates, answers or {})

    model = settings.KTP_GENERATION_MODEL
    max_tokens = settings.KTP_MAX_TOKENS

    try:
        raw = await create_chat_completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        logger.exception("KTP generation failed for group %s", group_id)
        card.status = "failed"
        card.error_message = str(exc)
        card.updated_at = _now()
        group.status = "failed"
        group.updated_at = _now()
        await db.commit()
        raise

    try:
        parsed = json.loads(_clean_json(raw))
    except json.JSONDecodeError as exc:
        card.status = "failed"
        card.error_message = f"JSON parse error: {exc}\nRaw: {raw[:500]}"
        card.updated_at = _now()
        group.status = "failed"
        group.updated_at = _now()
        await db.commit()
        raise ValueError(f"LLM вернул невалидный JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        card.status = "failed"
        card.error_message = "LLM returned JSON, but not an object"
        card.updated_at = _now()
        group.status = "failed"
        group.updated_at = _now()
        await db.commit()
        raise ValueError("LLM вернул JSON, но не объект")

    card.llm_model = model
    card.prompt_version = PROMPT_VERSION
    card.updated_at = _now()
    group.updated_at = _now()

    if answers:
        card.answers_json = answers

    sufficient = bool(parsed.get("sufficient", True))
    if not sufficient:
        questions = parsed.get("questions", [])
        if not isinstance(questions, list):
            card.status = "failed"
            card.error_message = "LLM вернул questions не в виде списка"
            card.updated_at = _now()
            group.status = "failed"
            group.updated_at = _now()
            await db.commit()
            raise ValueError("LLM вернул questions не в виде списка")
        card.questions_json = questions
        card.steps_json = None
        card.recommendations_json = None
        card.status = "questions_required"
        card.error_message = None
        group.status = "questions_required"
        await db.commit()
        return {"sufficient": False, "questions": questions}

    ktp_data = parsed.get("ktp", {})
    if not isinstance(ktp_data, dict):
        card.status = "failed"
        card.error_message = "LLM не вернул объект ktp"
        card.updated_at = _now()
        group.status = "failed"
        group.updated_at = _now()
        await db.commit()
        raise ValueError("LLM не вернул объект ktp")

    card.title = ktp_data.get("title") or group.title
    card.goal = ktp_data.get("goal") or ""
    card.steps_json = ktp_data.get("steps", [])
    card.recommendations_json = ktp_data.get("recommendations", [])
    card.questions_json = None
    card.status = "generated"
    card.error_message = None
    group.status = "generated"

    await db.commit()
    await db.refresh(card)

    return {
        "sufficient": True,
        "ktp_card_id": card.id,
        "ktp": {
            "id": card.id,
            "title": card.title,
            "goal": card.goal,
            "steps": card.steps_json or [],
            "recommendations": card.recommendations_json or [],
            "status": card.status,
            "questions_json": None,
        },
    }


async def _get_or_create_card(db: AsyncSession, group: KtpGroup) -> KtpCard:
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


async def _load_estimates_for_group(db: AsyncSession, group: KtpGroup) -> list[Estimate]:
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
    lines: list[str] = []
    for estimate in estimates:
        qty = (
            f"{float(estimate.quantity):.2f} {estimate.unit or ''}".strip()
            if estimate.quantity is not None
            else "—"
        )
        price = (
            f"{float(estimate.total_price):.2f} руб."
            if estimate.total_price is not None
            else "—"
        )
        lines.append(f"  • {estimate.work_name} | {qty} | {price}")

    works_block = "\n".join(lines) if lines else "  (нет позиций)"
    answers_block = ""
    if answers:
        answers_block = "\n\nДополнительные данные от пользователя:\n" + "\n".join(
            f"  {key}: {value}" for key, value in answers.items()
        )

    return f"""Ты эксперт-технолог в строительстве. На основе группы работ из строительной сметы создай КТП (Карту Технологического Процесса).

ГРУППА РАБОТ: «{group.title}»
Количество позиций: {group.row_count}

ПОЗИЦИИ СМЕТЫ:
{works_block}
{answers_block}

ИНСТРУКЦИЯ:
1. Если данных достаточно для качественного КТП, сразу создай КТП.
2. Если не хватает ключевых технических данных, верни только уточняющие вопросы.
3. Ответ верни только валидным JSON без markdown.

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
        "work_details": "Разбивка осей, устройство основания, установка опалубки",
        "control_points": "Проверка отметок, акт освидетельствования основания"
      }}
    ],
    "recommendations": [
      "Бетонирование выполнять непрерывно",
      "Соблюдать требования по уходу за бетоном"
    ]
  }}
}}
"""


async def get_ktp_card(
    db: AsyncSession,
    project_id: str,
    group_id: str,
) -> KtpCard | None:
    group = await _assert_group_belongs_to_project(db, project_id, group_id)
    return group.ktp_card
