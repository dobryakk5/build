"""
Узкий ФЕР matcher для confirmed карточек плана работ (шаг 4).

Идея: вместо поиска одной строки сметы среди 5000 ФЕР таблиц (как раньше),
мы знаем NW карточки → знаем кандидатов из nw_fer_table_mapping (5-30 таблиц).
Среди них LLM выбирает лучшую — точность кратно выше.

Алгоритм:
  1. Получить кандидатов: fer.fer_tables через nw_fer_table_mapping для NW карточки
     (с учётом mapping_type ∈ {direct, partial})
  2. Если кандидатов 0 → пометить status='needs_review'
  3. Если кандидатов 1 → автоматически выбрать
  4. Иначе LLM выбирает best (передаём контекст карточки + кандидатов)
  5. Сохранить fer_table_id, fer_match_score, fer_match_source, fer_candidates
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.openrouter_embeddings import (
    create_chat_completion,
    parse_json_object,
)

logger = logging.getLogger(__name__)

LLM_MODEL = "openai/gpt-oss-120b:free"
SYSTEM_PROMPT = (
    "Ты эксперт по ФЕР расценкам. Среди списка кандидатов выбираешь "
    "одну лучшую расценку для заданной работы. Возвращаешь СТРОГО JSON. "
    "ВАЖНО: все текстовые поля (reason и т.п.) — ТОЛЬКО на русском языке."
)


async def get_candidates(
    db: AsyncSession,
    nw_item_code: str,
    estimate_kind: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Кандидаты ФЕР таблиц для данного NW.
    Если задан estimate_kind, дополнительно фильтруем по разделам из work_type_sections.
    """
    sql = """
        SELECT t.id, t.table_title, t.common_work_name, t.row_count,
               c.num AS coll_num, s.title AS section_title,
               m.mapping_type, m.confidence, m.is_primary, m.notes AS mapping_notes
        FROM fer.nw_fer_table_mapping m
        JOIN fer.fer_tables t ON t.id = m.fer_table_id
        JOIN fer.collections c ON c.id = t.collection_id
        JOIN fer.sections s    ON s.id = t.section_id
        WHERE m.nw_item_code = :nw
          AND m.mapping_type IN ('direct','partial')
          AND NOT COALESCE(t.ignored, FALSE)
    """
    params: dict[str, Any] = {"nw": nw_item_code}
    if estimate_kind is not None:
        sql += """
          AND EXISTS (
              SELECT 1 FROM fer.work_type_sections wts
              WHERE wts.id = :kind AND t.section_id = ANY(wts.section_ids)
          )
        """
        params["kind"] = estimate_kind
    sql += """
        ORDER BY m.is_primary DESC,
                 CASE m.confidence WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                 t.row_count DESC NULLS LAST
        LIMIT :lim
    """
    params["lim"] = limit
    rows = await db.execute(text(sql), params)
    return [dict(r) for r in rows.mappings()]


async def llm_pick_best(
    card_label: str,
    card_subtype: str | None,
    card_unit: str | None,
    card_quantity: float | None,
    card_notes: str | None,
    candidates: list[dict[str, Any]],
) -> tuple[int | None, float, str | None]:
    """
    LLM выбирает лучшего кандидата.
    Возвращает (fer_table_id, score 0..1, reasoning).
    """
    if not candidates:
        return None, 0.0, "no candidates"

    cand_lines: list[str] = []
    for i, c in enumerate(candidates, 1):
        common = f" — {c['common_work_name']}" if c.get("common_work_name") else ""
        cand_lines.append(
            f"{i}. id={c['id']} (Сб.{c['coll_num']}) [{c['mapping_type']}/{c['confidence']}] "
            f"{c['table_title']}{common}"
        )
    candidates_text = "\n".join(cand_lines)

    context = f"Вид работ: {card_label}"
    if card_subtype:
        context += f" ({card_subtype})"
    if card_quantity is not None and card_unit:
        context += f"\nОбъём: {card_quantity} {card_unit}"
    if card_notes:
        context += f"\nЗаметка: {card_notes}"

    prompt = f"""КОНТЕКСТ КАРТОЧКИ ПЛАНА РАБОТ:
{context}

КАНДИДАТЫ ФЕР:
{candidates_text}

ЗАДАЧА: выбери ОДНОГО лучшего кандидата по совпадению с описанием работы.
Учитывай контекст: единицу измерения, объём, заметку.

Верни СТРОГО JSON:
{{
  "id": <число — id выбранного кандидата>,
  "confidence": <число 0..1 — твоя уверенность>,
  "reason": "<краткое обоснование на РУССКОМ языке, 1 предложение>"
}}
Если ни один кандидат не подходит уверенно — верни confidence < 0.3.
Поле "reason" обязательно на русском языке."""

    try:
        raw = await create_chat_completion(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=300,
        )
        parsed = parse_json_object(raw)
    except Exception as e:
        logger.warning("FER LLM pick failed: %s", e)
        return candidates[0]["id"], 0.4, "LLM failure → first candidate (fallback)"

    pid = parsed.get("id")
    if not isinstance(pid, int):
        try:
            pid = int(pid) if pid else None
        except (TypeError, ValueError):
            pid = None
    if pid is None or pid not in {c["id"] for c in candidates}:
        return candidates[0]["id"], 0.3, "LLM returned invalid id → first candidate"

    score = parsed.get("confidence", 0.5)
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.5
    score = max(0.0, min(1.0, score))

    reason = parsed.get("reason") or None
    return pid, score, reason


async def match_card_to_fer(
    db: AsyncSession,
    plan_id: int,
    use_llm: bool = True,
) -> dict[str, Any]:
    """
    Подобрать ФЕР для одной карточки плана. Сохраняет результат.
    Возвращает summary {plan_id, fer_table_id, score, candidates_count, reason}.
    """
    # Загружаем карточку
    card = (await db.execute(
        text(
            """
            SELECT p.id, p.estimate_batch_id, p.nw_item_code, p.unit, p.quantity,
                   p.notes, i.unique_label, i.subtype, eb.estimate_kind
            FROM fer.project_work_plan p
            JOIN fer.nw_item i      ON i.code = p.nw_item_code
            JOIN estimate_batches eb ON eb.id = p.estimate_batch_id
            WHERE p.id = :id
            """
        ),
        {"id": plan_id},
    )).mappings().first()
    if not card:
        raise ValueError(f"plan card {plan_id} not found")

    # Кандидаты
    candidates = await get_candidates(
        db, card["nw_item_code"], int(card["estimate_kind"])
    )
    if not candidates:
        # Расширим без фильтра по типу сметы
        candidates = await get_candidates(db, card["nw_item_code"], None)

    if not candidates:
        await db.execute(
            text(
                """
                UPDATE fer.project_work_plan
                SET fer_match_source = 'no_candidates',
                    status = 'needs_review',
                    updated_at = NOW()
                WHERE id = :id
                """
            ),
            {"id": plan_id},
        )
        await db.commit()
        return {
            "plan_id": plan_id, "fer_table_id": None, "score": 0.0,
            "candidates_count": 0, "reason": "нет кандидатов в nw_fer_table_mapping",
        }

    # Топ-N кандидатов в JSON для UI
    candidates_json = [
        {
            "id": c["id"], "title": c["table_title"], "coll_num": c["coll_num"],
            "section_title": c["section_title"], "mapping_type": c["mapping_type"],
            "confidence": c["confidence"], "is_primary": c["is_primary"],
        }
        for c in candidates[:10]
    ]

    # Авто или LLM
    if len(candidates) == 1 or not use_llm:
        chosen_id = candidates[0]["id"]
        score = 0.9 if len(candidates) == 1 else 0.5
        reason = "единственный кандидат" if len(candidates) == 1 else "auto first"
        source = "auto"
    else:
        chosen_id, score, reason = await llm_pick_best(
            card["unique_label"],
            card["subtype"],
            card["unit"],
            float(card["quantity"]) if card["quantity"] is not None else None,
            card["notes"],
            candidates,
        )
        source = "llm"

    new_status = "fer_mapped" if score >= 0.5 else "needs_review"

    await db.execute(
        text(
            """
            UPDATE fer.project_work_plan
            SET fer_table_id     = :tid,
                fer_match_score  = :score,
                fer_match_source = :source,
                fer_candidates   = CAST(:cands AS JSONB),
                fer_matched_at   = NOW(),
                status           = :status,
                updated_at       = NOW(),
                notes            = COALESCE(notes, '') ||
                                   CASE WHEN CAST(:reason AS TEXT) IS NOT NULL
                                        THEN E'\nFER: ' || CAST(:reason AS TEXT) ELSE '' END
            WHERE id = :id
            """
        ),
        {
            "tid": chosen_id, "score": score, "source": source,
            "cands": json.dumps(candidates_json, ensure_ascii=False),
            "status": new_status, "reason": reason, "id": plan_id,
        },
    )
    await db.commit()

    return {
        "plan_id": plan_id, "fer_table_id": chosen_id, "score": score,
        "candidates_count": len(candidates), "reason": reason, "source": source,
    }


async def get_fer_rows_for_card(
    db: AsyncSession,
    plan_id: int,
) -> list[dict[str, Any]]:
    """Все строки fer_rows для FER-таблицы карточки (для UI выбора)."""
    rows = await db.execute(
        text(
            """
            SELECT
                r.id,
                row_number() OVER (ORDER BY r.id)::int AS position,
                r.clarification,
                r.h_hour,
                r.m_hour,
                r.row_slug
            FROM fer.fer_rows r
            JOIN fer.project_work_plan p ON p.fer_table_id = r.table_id
            WHERE p.id = :id
            ORDER BY r.id
            """
        ),
        {"id": plan_id},
    )
    return [dict(r) for r in rows.mappings()]


async def llm_pick_fer_row(
    db: AsyncSession,
    plan_id: int,
) -> dict[str, Any]:
    """
    LLM выбирает лучшую строку fer_rows для карточки (учитывая её unit/quantity/notes).
    Сохраняет fer_row_id в карточку и пересчитывает duration.
    """
    card = (await db.execute(
        text(
            """
            SELECT p.id, p.fer_table_id, p.unit, p.quantity, p.notes,
                   i.unique_label, i.subtype
            FROM fer.project_work_plan p
            JOIN fer.nw_item i ON i.code = p.nw_item_code
            WHERE p.id = :id
            """
        ),
        {"id": plan_id},
    )).mappings().first()
    if not card or not card["fer_table_id"]:
        return {"plan_id": plan_id, "fer_row_id": None, "skipped": "no fer_table_id"}

    rows = await get_fer_rows_for_card(db, plan_id)
    if not rows:
        return {"plan_id": plan_id, "fer_row_id": None, "skipped": "no fer_rows"}
    if len(rows) == 1:
        chosen = rows[0]
        await db.execute(
            text("UPDATE fer.project_work_plan SET fer_row_id = :rid, updated_at = NOW() WHERE id = :id"),
            {"rid": chosen["id"], "id": plan_id},
        )
        await db.commit()
        return {"plan_id": plan_id, "fer_row_id": chosen["id"], "score": 0.95, "reason": "единственная строка"}

    cand_lines = []
    for i, r in enumerate(rows, 1):
        cand_lines.append(f"{i}. id={r['id']} h={r['h_hour']}ч | {r['clarification']}")
    candidates_text = "\n".join(cand_lines)

    context = f"Вид работ: {card['unique_label']}"
    if card["subtype"]:
        context += f" ({card['subtype']})"
    if card["quantity"] is not None and card["unit"]:
        context += f"\nОбъём: {card['quantity']} {card['unit']}"
    if card["notes"]:
        context += f"\nЗаметка: {card['notes']}"

    prompt = f"""КОНТЕКСТ КАРТОЧКИ ПЛАНА РАБОТ:
{context}

СТРОКИ ВЫБРАННОЙ ФЕР ТАБЛИЦЫ:
{candidates_text}

ЗАДАЧА: выбери ОДНУ строку расценки которая точно соответствует объёму карточки.
Учитывай единицу измерения и числовые параметры в clarification (объём, диаметр, толщина и т.п.).

Верни СТРОГО JSON:
{{
  "id": <число — id выбранной строки>,
  "confidence": <число 0..1>,
  "reason": "<краткое обоснование на РУССКОМ языке>"
}}
Поле "reason" обязательно на русском языке."""

    try:
        raw = await create_chat_completion(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "Ты эксперт по ФЕР. Выбираешь конкретную строку расценки. Возвращаешь СТРОГО JSON. ВАЖНО: все текстовые поля только на русском языке."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=300,
        )
        parsed = parse_json_object(raw)
    except Exception as e:
        logger.warning("FER row LLM pick failed: %s", e)
        return {"plan_id": plan_id, "fer_row_id": None, "skipped": f"LLM error: {e}"}

    rid = parsed.get("id")
    try:
        rid = int(rid) if rid else None
    except (TypeError, ValueError):
        rid = None
    valid_ids = {r["id"] for r in rows}
    if rid not in valid_ids:
        return {"plan_id": plan_id, "fer_row_id": None, "skipped": "LLM returned invalid id"}

    score = float(parsed.get("confidence", 0.5) or 0.5)
    reason = parsed.get("reason") or None

    await db.execute(
        text("UPDATE fer.project_work_plan SET fer_row_id = :rid, updated_at = NOW() WHERE id = :id"),
        {"rid": rid, "id": plan_id},
    )
    await db.commit()
    return {"plan_id": plan_id, "fer_row_id": rid, "score": score, "reason": reason}


async def match_all_confirmed_cards(
    db: AsyncSession,
    estimate_batch_id: str,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Прогнать narrow FER matcher для всех confirmed/auto_proposed/custom_added карточек."""
    rows = (await db.execute(
        text(
            """
            SELECT id FROM fer.project_work_plan
            WHERE estimate_batch_id = :id
              AND status IN ('confirmed','auto_proposed','custom_added')
              AND fer_table_id IS NULL
              AND parent_id IS NULL
            ORDER BY id
            """
        ),
        {"id": estimate_batch_id},
    )).mappings().all()

    matched = 0
    no_cands = 0
    needs_review = 0
    errors = 0
    for r in rows:
        try:
            res = await match_card_to_fer(db, r["id"], use_llm=use_llm)
            if res["fer_table_id"] is None:
                no_cands += 1
            elif res["score"] < 0.5:
                needs_review += 1
            else:
                matched += 1
        except Exception as e:
            logger.warning("match_card_to_fer failed for %s: %s", r["id"], e)
            errors += 1

    return {
        "total_processed": len(rows),
        "fer_mapped": matched,
        "needs_review": needs_review,
        "no_candidates": no_cands,
        "errors": errors,
    }
