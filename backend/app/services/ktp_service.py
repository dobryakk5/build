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
from app.services.estimate_nw_matcher import match_estimate_row
from app.services.nw_palette_service import get_palette
from app.services.openrouter_embeddings import create_chat_completion, parse_json_object

logger = logging.getLogger(__name__)

from app.core.estimate_types import (
    ESTIMATE_ITEM_TYPE_WORK,
    ESTIMATE_ITEM_TYPE_MECHANISM,
    resolve_item_type,
)

PROMPT_VERSION = "v1"


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
    return resolve_item_type(estimate)


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


def _build_ktp_group_match_text(group: KtpGroup, estimates: list[Estimate]) -> str:
    seen: set[str] = set()
    work_names: list[str] = []
    for estimate in estimates:
        work_name = " ".join(str(estimate.work_name or "").split()).strip()
        if not work_name:
            continue
        lowered = work_name.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        work_names.append(work_name)
        if len(work_names) >= 8:
            break

    if not work_names:
        return group.title

    return f"{group.title}. Работы: {'; '.join(work_names)}"


def _build_wt_palette(nw_palette: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_code: dict[str, dict[str, Any]] = {}
    for item in nw_palette:
        code = str(item.get("work_type_code") or "").strip()
        name = str(item.get("work_type_name") or "").strip()
        if not code or not name:
            continue

        wt = by_code.setdefault(
            code,
            {
                "wt_code": code,
                "wt_name": name,
                "examples": [],
            },
        )

        label = str(item.get("unique_label") or "").strip()
        if label and label not in wt["examples"] and len(wt["examples"]) < 4:
            wt["examples"].append(label)

    return list(by_code.values())


def _format_wt_palette_for_prompt(wt_palette: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for wt in wt_palette:
        examples = wt.get("examples") or []
        examples_suffix = f" | примеры NW: {'; '.join(examples)}" if examples else ""
        lines.append(f"- {wt['wt_code']}: {wt['wt_name']}{examples_suffix}")
    return "\n".join(lines)


def _normalize_wt_confidence(value: Any) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, confidence))


def _extract_wt_candidate_codes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    codes: list[str] = []
    for item in value:
        if isinstance(item, str):
            code = item.strip().upper()
        elif isinstance(item, dict):
            code = str(item.get("wt_code") or item.get("code") or "").strip().upper()
        else:
            continue
        if re.match(r"^WT-\d{2}$", code) and code not in codes:
            codes.append(code)
    return codes


def _clear_ktp_group_wt_match(group: KtpGroup, matched_at: datetime | None = None) -> None:
    group.wt_code = None
    group.wt_name = None
    group.wt_match_reason = None
    group.wt_match_confidence = None
    group.wt_match_candidates = None
    group.wt_matched_at = matched_at


async def _match_wt_by_keywords_for_ktp_group(
    db: AsyncSession,
    group: KtpGroup,
    estimates: list[Estimate],
    estimate_kind: int,
) -> None:
    matched_at = _now()
    nw_palette = await get_palette(db, estimate_kind)
    if not nw_palette:
        _clear_ktp_group_wt_match(group, matched_at)
        return

    nw_by_code = {
        str(item["nw_item_code"]).strip(): item
        for item in nw_palette
        if item.get("nw_item_code") and item.get("work_type_code") and item.get("work_type_name")
    }
    if not nw_by_code:
        _clear_ktp_group_wt_match(group, matched_at)
        return

    stats: dict[str, dict[str, Any]] = {}
    total_score = 0.0
    for estimate in estimates:
        match = match_estimate_row(
            work_name=str(estimate.work_name or ""),
            section=_nonempty(estimate.section),
            allowed_nw_codes=nw_by_code.keys(),
        )
        if not match.nw_code:
            continue

        nw_item = nw_by_code.get(match.nw_code)
        if not nw_item:
            continue

        wt_code = str(nw_item["work_type_code"]).strip()
        wt_name = str(nw_item["work_type_name"]).strip()
        weight = 2.0 if match.confidence == "high" else 1.0
        total_score += weight

        item = stats.setdefault(
            wt_code,
            {
                "wt_code": wt_code,
                "wt_name": wt_name,
                "rows": 0,
                "score": 0.0,
                "notes": [],
            },
        )
        item["rows"] += 1
        item["score"] += weight
        if match.note and match.note not in item["notes"] and len(item["notes"]) < 3:
            item["notes"].append(match.note)

    if not stats:
        group.wt_code = None
        group.wt_name = None
        group.wt_match_reason = "По ключевым словам WT не определён"
        group.wt_match_confidence = 0.0
        group.wt_match_candidates = None
        group.wt_matched_at = matched_at
        return

    ranked = sorted(
        stats.values(),
        key=lambda item: (float(item["score"]), int(item["rows"]), item["wt_code"]),
        reverse=True,
    )
    top = ranked[0]
    confidence = (
        max(0.0, min(1.0, float(top["score"]) / total_score))
        if total_score > 0
        else None
    )

    notes = ", ".join(top["notes"]) if top["notes"] else "по совпадениям в названиях работ"
    group.wt_code = top["wt_code"]
    group.wt_name = top["wt_name"]
    group.wt_match_reason = (
        f"По ключевым словам: {top['rows']} из {len(estimates)} позиций группы "
        f"относятся к {top['wt_name']} ({notes})"
    )
    group.wt_match_confidence = confidence
    group.wt_match_candidates = [
        {"wt_code": item["wt_code"], "wt_name": item["wt_name"]}
        for item in ranked[1:3]
    ] or None
    group.wt_matched_at = matched_at


async def _match_wt_with_ai_for_ktp_group(
    db: AsyncSession,
    group: KtpGroup,
    estimates: list[Estimate],
    estimate_kind: int,
) -> None:
    matched_at = _now()
    raw_group_text = _build_ktp_group_match_text(group, estimates).strip()
    if not raw_group_text:
        _clear_ktp_group_wt_match(group, matched_at)
        return

    nw_palette = await get_palette(db, estimate_kind)
    wt_palette = _build_wt_palette(nw_palette)
    if not wt_palette:
        _clear_ktp_group_wt_match(group, matched_at)
        return

    wt_by_code = {item["wt_code"]: item for item in wt_palette}
    user_prompt = f"""Ты классифицируешь группу строительной сметы по верхнему уровню work type (WT).
Выбери только один WT код из палитры ниже или верни null, если подходящий WT определить нельзя.
Ответ верни строго JSON-объектом без markdown.

ПАЛИТРА ДОПУСТИМЫХ WT:
{_format_wt_palette_for_prompt(wt_palette)}

ГРУППА СМЕТЫ:
{raw_group_text}

Верни JSON такого вида:
{{
  "wt_code": "WT-01",
  "reason": "Краткое объяснение выбора на русском",
  "confidence": 0.84,
  "alternatives": ["WT-02", "WT-05"]
}}

Если выбор сделать нельзя, верни:
{{
  "wt_code": null,
  "reason": "Почему не удалось определить",
  "confidence": 0.0,
  "alternatives": []
}}"""

    try:
        raw = await create_chat_completion(
            model=settings.KTP_GENERATION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты эксперт по строительным сметам. "
                        "Классифицируешь группу работ только по допустимым WT кодам. "
                        "Возвращаешь строго JSON."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=700,
        )
        parsed = parse_json_object(raw)
    except Exception:
        logger.exception("WT match failed for KTP group %s", group.id)
        _clear_ktp_group_wt_match(group)
        return

    reason = _nonempty(
        str(parsed.get("reason") or "") if parsed.get("reason") is not None else None
    )
    confidence = _normalize_wt_confidence(parsed.get("confidence"))
    alternatives = []
    for candidate_code in _extract_wt_candidate_codes(parsed.get("alternatives")):
        candidate = wt_by_code.get(candidate_code)
        if candidate:
            alternatives.append(
                {"wt_code": candidate_code, "wt_name": candidate["wt_name"]}
            )

    wt_code_raw = parsed.get("wt_code")
    wt_code = (
        str(wt_code_raw).strip().upper()
        if isinstance(wt_code_raw, str) and wt_code_raw.strip()
        else None
    )
    if wt_code is None:
        group.wt_code = None
        group.wt_name = None
        group.wt_match_reason = reason
        group.wt_match_confidence = confidence
        group.wt_match_candidates = alternatives or None
        group.wt_matched_at = matched_at
        return

    if wt_code not in wt_by_code:
        _clear_ktp_group_wt_match(group)
        return

    group.wt_code = wt_code
    group.wt_name = wt_by_code[wt_code]["wt_name"]
    group.wt_match_reason = reason
    group.wt_match_confidence = confidence
    group.wt_match_candidates = [
        candidate for candidate in alternatives if candidate["wt_code"] != wt_code
    ] or None
    group.wt_matched_at = matched_at


async def _ensure_ktp_group_wt_matches(
    db: AsyncSession,
    batch: EstimateBatch,
    groups: list[KtpGroup],
) -> list[KtpGroup]:
    changed = False
    for group in groups:
        if group.wt_matched_at is not None:
            continue
        estimates = await _load_estimates_for_group(db, group)
        await _match_wt_by_keywords_for_ktp_group(
            db, group, estimates, batch.estimate_kind
        )
        changed = True

    if changed:
        await db.commit()
        return (
            await get_ktp_groups(db, groups[0].project_id, groups[0].estimate_batch_id)
            if groups
            else groups
        )
    return groups


async def build_ktp_groups_for_batch(
    db: AsyncSession,
    project_id: str,
    estimate_batch_id: str,
    force: bool = False,
) -> list[KtpGroup]:
    batch = await _assert_batch_belongs_to_project(db, project_id, estimate_batch_id)

    existing = await get_ktp_groups(db, project_id, estimate_batch_id)
    if existing and not force:
        return await _ensure_ktp_group_wt_matches(db, batch, existing)

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
        await _match_wt_by_keywords_for_ktp_group(
            db, group, items, batch.estimate_kind
        )

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


async def ai_match_ktp_groups_for_batch(
    db: AsyncSession,
    project_id: str,
    estimate_batch_id: str,
    *,
    only_unmatched: bool = True,
) -> list[KtpGroup]:
    batch = await _assert_batch_belongs_to_project(db, project_id, estimate_batch_id)
    groups = await get_ktp_groups(db, project_id, estimate_batch_id)
    if not groups:
        return []

    changed = False
    for group in groups:
        if only_unmatched and group.wt_code:
            continue
        estimates = await _load_estimates_for_group(db, group)
        await _match_wt_with_ai_for_ktp_group(db, group, estimates, batch.estimate_kind)
        changed = True

    if changed:
        await db.commit()
        return await get_ktp_groups(db, project_id, estimate_batch_id)
    return groups


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
