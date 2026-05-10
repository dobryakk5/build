"""
Сервис плана работ (КТП проекта).

Основные операции:
  • auto_create_from_estimate(batch_id) — построить черновик плана из загруженной сметы
  • get_plan(batch_id)                  — текущее состояние плана (с дочерними)
  • update_card / delete_card / add_custom_card — правки прораба
  • confirm_card / confirm_all          — подтверждение

Последовательность auto_create:
  1. Подгружаем строки сметы
  2. Для каждой строки → keyword-match на NW (estimate_nw_matcher)
  3. Группируем (nw_code, unit) → общий объём, список estimate_id
  4. Создаём ProjectWorkPlan карточки + linkи в project_work_plan_estimate_link
  5. Если NW агрегатный (NW-021 и т.п.) — создаём родителя + декомпозиция
  6. Добавляем "expected" NW из палитры estimate_kind, которых нет в смете
     (status='auto_proposed', quantity=NULL, прораб уточнит)
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.estimate_nw_matcher import EstimateNwMatch, match_estimate_row
from app.services.nw_palette_service import (
    NW_DECOMPOSITION,
    decompose,
    get_palette,
    is_aggregate,
)


async def auto_create_from_estimate(
    db: AsyncSession,
    estimate_batch_id: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    Построить черновик плана работ из сметы.

    Возвращает summary:
      {
        "batch_id": "...",
        "estimate_kind": 2,
        "matched_rows": 47,    # сколько строк сметы засматчилось
        "unmatched_rows": 5,   # сколько строк не нашли NW (нужен LLM/ручной)
        "cards_created": 23,   # сколько карточек ProjectWorkPlan создано
        "expected_added": 4,   # сколько NW добавлены из палитры с пустым объёмом
        "aggregate_decomposed": [{"parent_id": ..., "children": [...]}, ...]
      }
    """
    # ── Получаем смету ──
    batch_row = (await db.execute(
        text("SELECT estimate_kind FROM estimate_batches WHERE id = :id"),
        {"id": estimate_batch_id},
    )).mappings().first()
    if not batch_row:
        raise ValueError(f"EstimateBatch {estimate_batch_id} not found")
    estimate_kind = int(batch_row["estimate_kind"])

    estimate_rows = (await db.execute(
        text(
            """
            SELECT id, section, work_name, unit, quantity
            FROM estimates
            WHERE estimate_batch_id = :id AND deleted_at IS NULL
            """
        ),
        {"id": estimate_batch_id},
    )).mappings().all()

    # ── Палитра ──
    palette = await get_palette(db, estimate_kind)
    palette_codes = {p["nw_item_code"] for p in palette}

    # ── 1. Match каждой строки сметы → NW ──
    # БЕЗ агрегации: 1 строка сметы = 1 карточка плана
    cards_created = 0
    aggregate_decomposed: list[dict[str, Any]] = []
    matched_nw_codes: set[str] = set()
    unmatched_rows: list[dict[str, Any]] = []

    for er in estimate_rows:
        match = match_estimate_row(
            work_name=er["work_name"],
            section=er["section"],
            allowed_nw_codes=palette_codes if palette_codes else None,
        )
        if match.nw_code is None:
            unmatched_rows.append(dict(er))
            continue

        # Создаём карточку для этой строки
        card_id = await _create_card(
            db,
            estimate_batch_id=estimate_batch_id,
            nw_item_code=match.nw_code,
            unit=er["unit"],
            quantity=float(er["quantity"]) if er["quantity"] is not None else None,
            status="auto_proposed",
            user_id=user_id,
            notes=match.note,
            source_label=er["work_name"],
            source_section=er["section"],
        )
        cards_created += 1
        matched_nw_codes.add(match.nw_code)

        # Привязка строки сметы 1:1
        await db.execute(
            text(
                """
                INSERT INTO fer.project_work_plan_estimate_link (plan_id, estimate_id, share)
                VALUES (:pid, :eid, 1.0)
                ON CONFLICT DO NOTHING
                """
            ),
            {"pid": card_id, "eid": er["id"]},
        )

        # Декомпозиция агрегатных NW (например «Дом под ключ»)
        if is_aggregate(match.nw_code):
            child_ids: list[int] = []
            for child_nw in decompose(match.nw_code):
                cid = await _create_card(
                    db,
                    estimate_batch_id=estimate_batch_id,
                    nw_item_code=child_nw,
                    unit=None,
                    quantity=None,
                    parent_id=card_id,
                    status="needs_volume",
                    user_id=user_id,
                    notes=f"декомпозиция {match.nw_code}",
                )
                child_ids.append(cid)
                cards_created += 1
                matched_nw_codes.add(child_nw)
            aggregate_decomposed.append({"parent_id": card_id, "children": child_ids})

    # ── 3. Expected NW не покрыты сметой → пустые карточки ──
    expected_added = 0
    for p in palette:
        if p["nw_item_code"] in matched_nw_codes:
            continue
        await _create_card(
            db,
            estimate_batch_id=estimate_batch_id,
            nw_item_code=p["nw_item_code"],
            unit=None,
            quantity=None,
            status="needs_volume",
            user_id=user_id,
            notes="Добавлено по типу проекта; объём не задан",
        )
        expected_added += 1
        cards_created += 1

    await db.commit()
    return {
        "batch_id": estimate_batch_id,
        "estimate_kind": estimate_kind,
        "estimate_rows_total": len(estimate_rows),
        "matched_rows": len(estimate_rows) - len(unmatched_rows),
        "unmatched_rows": len(unmatched_rows),
        "unmatched_examples": [
            {"id": r["id"], "work_name": r["work_name"], "section": r["section"]}
            for r in unmatched_rows[:5]
        ],
        "cards_created": cards_created,
        "expected_added": expected_added,
        "aggregate_decomposed": aggregate_decomposed,
        "palette_size": len(palette),
    }


async def _create_card(
    db: AsyncSession,
    *,
    estimate_batch_id: str,
    nw_item_code: str,
    unit: str | None,
    quantity: float | None,
    status: str,
    parent_id: int | None = None,
    user_id: str | None = None,
    notes: str | None = None,
    source_label: str | None = None,
    source_section: str | None = None,
) -> int:
    """Создать одну карточку ProjectWorkPlan, вернуть id."""
    row = (await db.execute(
        text(
            """
            INSERT INTO fer.project_work_plan (
              estimate_batch_id, parent_id, nw_item_code,
              unit, quantity, status, created_by, notes,
              source_label, source_section
            )
            VALUES (
              :batch, :parent, :nw,
              :unit, :qty, :status, :user_id, :notes,
              :src_label, :src_section
            )
            RETURNING id
            """
        ),
        {
            "batch":   estimate_batch_id,
            "parent":  parent_id,
            "nw":      nw_item_code,
            "unit":    unit,
            "qty":     quantity,
            "status":  status,
            "user_id": user_id,
            "notes":   notes,
            "src_label":   source_label,
            "src_section": source_section,
        },
    )).scalar()
    return int(row)


# ─────────────────────────────────────────────────────────────────────────────
# Чтение / правки
# ─────────────────────────────────────────────────────────────────────────────

async def get_plan(db: AsyncSession, estimate_batch_id: str) -> list[dict[str, Any]]:
    """Получить план работ для batch'а — все карточки с подкарточками."""
    rows = await db.execute(
        text(
            """
            SELECT
              p.id, p.parent_id, p.nw_item_code, p.unit, p.quantity, p.status,
              p.object_type_code, p.building_technology_code,
              p.location_scope_code, p.stage_code, p.is_capital_repair,
              p.fer_table_id, p.fer_match_score, p.fer_match_source,
              p.fer_candidates,
              p.fer_row_id,
              fr.clarification AS fer_row_clarification,
              fr.h_hour        AS fer_row_h_hour,
              t.table_title    AS fer_table_title,
              COALESCE(
                substring(t.table_title from '(\\d{2}-\\d{2}-\\d{3})'),
                substring(t.table_url   from '(\\d{2}-\\d{2}-\\d{3})')
              ) AS fer_table_code,
              p.human_hours_per_unit, p.workers_count, p.duration_days,
              p.notes, p.source_label, p.source_section,
              p.created_at, p.confirmed_at,
              i.unique_label AS nw_label,
              i.work_type_code,
              wt.name AS work_type_name,
              (SELECT COUNT(*) FROM fer.project_work_plan_estimate_link l
                 WHERE l.plan_id = p.id) AS estimate_links_count
            FROM fer.project_work_plan p
            JOIN fer.nw_item i      ON i.code = p.nw_item_code
            JOIN fer.nw_work_type wt ON wt.code = i.work_type_code
            LEFT JOIN fer.fer_tables t ON t.id = p.fer_table_id
            LEFT JOIN fer.fer_rows fr  ON fr.id = p.fer_row_id
            WHERE p.estimate_batch_id = :id
            ORDER BY wt.sort_order, i.sort_order, p.id
            """
        ),
        {"id": estimate_batch_id},
    )
    return [dict(r) for r in rows.mappings()]


async def get_card_detail(
    db: AsyncSession,
    estimate_batch_id: str,
    plan_id: int,
) -> dict[str, Any]:
    """Детали карточки плана: сама карточка и связанные строки сметы."""
    cards = await get_plan(db, estimate_batch_id)
    card = next((c for c in cards if int(c["id"]) == plan_id), None)
    if not card:
        raise ValueError(f"plan card {plan_id} not found")

    estimate_rows = await db.execute(
        text(
            """
            SELECT
              e.id, e.row_order, e.section, e.work_name, e.unit, e.quantity,
              e.unit_price, e.total_price, e.labor_hours, l.share
            FROM fer.project_work_plan_estimate_link l
            JOIN estimates e ON e.id = l.estimate_id
            WHERE l.plan_id = :plan_id
              AND e.deleted_at IS NULL
            ORDER BY e.row_order NULLS LAST, e.section NULLS LAST, e.work_name
            """
        ),
        {"plan_id": plan_id},
    )

    return {
        "card": card,
        "estimate_rows": [dict(r) for r in estimate_rows.mappings()],
    }


async def update_card(
    db: AsyncSession,
    plan_id: int,
    fields: dict[str, Any],
) -> None:
    """Частичное обновление карточки. Разрешённые поля — whitelist."""
    allowed = {
        "object_type_code", "building_technology_code", "location_scope_code",
        "stage_code", "is_capital_repair",
        "unit", "quantity",
        "workers_count", "status", "notes",
    }
    set_parts = []
    params: dict[str, Any] = {"id": plan_id}
    for k, v in fields.items():
        if k not in allowed:
            continue
        set_parts.append(f"{k} = :{k}")
        params[k] = v
    if not set_parts:
        return
    set_parts.append("updated_at = NOW()")
    sql = f"UPDATE fer.project_work_plan SET {', '.join(set_parts)} WHERE id = :id"
    await db.execute(text(sql), params)
    await db.commit()


async def delete_card(db: AsyncSession, plan_id: int, soft: bool = True) -> None:
    """Удалить карточку. soft → status='removed', hard → DELETE."""
    if soft:
        await db.execute(
            text("UPDATE fer.project_work_plan SET status = 'removed', updated_at = NOW() WHERE id = :id"),
            {"id": plan_id},
        )
    else:
        await db.execute(
            text("DELETE FROM fer.project_work_plan WHERE id = :id"),
            {"id": plan_id},
        )
    await db.commit()


async def add_custom_card(
    db: AsyncSession,
    estimate_batch_id: str,
    nw_item_code: str,
    unit: str | None = None,
    quantity: float | None = None,
    user_id: str | None = None,
    notes: str | None = None,
    estimate_ids: list[str] | None = None,
    source_label: str | None = None,
) -> int:
    """Прораб вручную добавляет карточку (NW которого не было в авто-генерации).
    Опционально сразу привязывает строки сметы (объём суммируется если unit совпадают)."""
    # Если строки сметы переданы и source_label не задан — подтянем work_name первой строки
    src_label = source_label
    src_section = None
    if not src_label and estimate_ids:
        row = (await db.execute(
            text(
                "SELECT work_name, section FROM estimates WHERE id = :id LIMIT 1"
            ),
            {"id": estimate_ids[0]},
        )).mappings().first()
        if row:
            src_label = row["work_name"]
            src_section = row["section"]

    pid = await _create_card(
        db,
        estimate_batch_id=estimate_batch_id,
        nw_item_code=nw_item_code,
        unit=unit,
        quantity=quantity,
        status="custom_added",
        user_id=user_id,
        notes=notes,
        source_label=src_label,
        source_section=src_section,
    )
    await db.commit()
    if estimate_ids:
        await link_estimates_to_card(db, pid, estimate_ids, accumulate_quantity=True)
    return pid


async def get_unmatched_estimate_rows(
    db: AsyncSession,
    estimate_batch_id: str,
) -> list[dict[str, Any]]:
    """Строки сметы, не привязанные ни к одной карточке плана."""
    rows = await db.execute(
        text(
            """
            SELECT e.id, e.section, e.work_name, e.unit, e.quantity, e.total_price
            FROM estimates e
            WHERE e.estimate_batch_id = :id
              AND e.deleted_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM fer.project_work_plan_estimate_link l
                  WHERE l.estimate_id = e.id
              )
            ORDER BY e.section NULLS LAST, e.work_name
            """
        ),
        {"id": estimate_batch_id},
    )
    return [dict(r) for r in rows.mappings()]


async def link_estimates_to_card(
    db: AsyncSession,
    plan_id: int,
    estimate_ids: list[str],
    accumulate_quantity: bool = True,
) -> int:
    """
    Привязать выбранные строки сметы к существующей карточке плана.
    Если accumulate_quantity=True — суммируем quantity к карточке (если совпадают units).
    Возвращает число фактически прилинкованных.
    """
    if not estimate_ids:
        return 0
    # Берём текущую карточку и строки сметы (только ещё не привязанные)
    card = (await db.execute(
        text("SELECT unit, quantity, status FROM fer.project_work_plan WHERE id = :id"),
        {"id": plan_id},
    )).mappings().first()
    if not card:
        raise ValueError(f"plan card {plan_id} not found")

    rows = (await db.execute(
        text(
            """
            SELECT e.id, e.unit, e.quantity
            FROM estimates e
            WHERE e.id = ANY(:ids) AND e.deleted_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM fer.project_work_plan_estimate_link l
                  WHERE l.estimate_id = e.id AND l.plan_id = :pid
              )
            """
        ),
        {"ids": estimate_ids, "pid": plan_id},
    )).mappings().all()

    if not rows:
        return 0

    card_unit = (card["unit"] or "").strip().lower() or None
    delta = 0.0
    for r in rows:
        await db.execute(
            text(
                """
                INSERT INTO fer.project_work_plan_estimate_link (plan_id, estimate_id, share)
                VALUES (:pid, :eid, 1.0)
                ON CONFLICT DO NOTHING
                """
            ),
            {"pid": plan_id, "eid": r["id"]},
        )
        if accumulate_quantity and r["quantity"] is not None:
            row_unit = (r["unit"] or "").strip().lower() or None
            if row_unit == card_unit:
                delta += float(r["quantity"])

    if delta > 0:
        new_status = "auto_proposed" if card["status"] == "needs_volume" else card["status"]
        await db.execute(
            text(
                """
                UPDATE fer.project_work_plan
                SET quantity = COALESCE(quantity, 0) + :delta,
                    status = :status,
                    updated_at = NOW()
                WHERE id = :id
                """
            ),
            {"delta": delta, "status": new_status, "id": plan_id},
        )
    await db.commit()
    return len(rows)


async def confirm_card(db: AsyncSession, plan_id: int) -> None:
    await db.execute(
        text(
            """
            UPDATE fer.project_work_plan
            SET status = 'confirmed', confirmed_at = NOW(), updated_at = NOW()
            WHERE id = :id
            """
        ),
        {"id": plan_id},
    )
    await db.commit()


async def llm_resolve_unmatched(
    db: AsyncSession,
    estimate_batch_id: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    LLM-проход для строк сметы, которые не привязаны к карточкам плана.

    Возвращает summary:
      {
        "unmatched_before": N,
        "matched_by_llm": M,
        "still_unmatched": K,
        "new_cards": L,           # сколько новых карточек создано
        "linked_to_existing": X,  # сколько строк привязали к уже существующим карточкам
      }
    """
    from collections import defaultdict
    from app.services.estimate_nw_llm_matcher import llm_match_all
    from app.services.nw_palette_service import get_palette, is_aggregate, decompose

    # 1. Найти строки сметы которые НЕ привязаны к карточкам плана
    unmatched_rows = (await db.execute(
        text(
            """
            SELECT e.id, e.section, e.work_name, e.unit, e.quantity
            FROM estimates e
            WHERE e.estimate_batch_id = :id
              AND e.deleted_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM fer.project_work_plan_estimate_link l
                  WHERE l.estimate_id = e.id
              )
            """
        ),
        {"id": estimate_batch_id},
    )).mappings().all()

    if not unmatched_rows:
        return {
            "unmatched_before": 0, "matched_by_llm": 0,
            "still_unmatched": 0, "new_cards": 0, "linked_to_existing": 0,
        }

    # 2. Получить палитру (NW коды + лейблы) из типа сметы
    batch_row = (await db.execute(
        text("SELECT estimate_kind FROM estimate_batches WHERE id = :id"),
        {"id": estimate_batch_id},
    )).mappings().first()
    estimate_kind = int(batch_row["estimate_kind"])
    palette = await get_palette(db, estimate_kind)

    # 3. LLM matching пачками
    rows_for_llm = [
        {"id": r["id"], "section": r["section"], "work_name": r["work_name"]}
        for r in unmatched_rows
    ]
    matched_map = await llm_match_all(rows_for_llm, palette)

    # 4. БЕЗ агрегации: каждая сматченная строка → новая карточка
    new_cards = 0
    matched_count = 0
    by_row: dict[str, dict[str, Any]] = {str(r["id"]): dict(r) for r in unmatched_rows}

    for rid, nw in matched_map.items():
        if not nw:
            continue
        r = by_row.get(rid)
        if not r:
            continue
        matched_count += 1

        card_id = await _create_card(
            db,
            estimate_batch_id=estimate_batch_id,
            nw_item_code=nw,
            unit=r["unit"],
            quantity=float(r["quantity"]) if r["quantity"] is not None else None,
            status="auto_proposed",
            user_id=user_id,
            notes="LLM-классификация",
            source_label=r["work_name"],
            source_section=r["section"],
        )
        new_cards += 1

        # Привязка строки сметы 1:1
        await db.execute(
            text(
                """
                INSERT INTO fer.project_work_plan_estimate_link (plan_id, estimate_id, share)
                VALUES (:pid, :eid, 1.0)
                ON CONFLICT DO NOTHING
                """
            ),
            {"pid": card_id, "eid": r["id"]},
        )

        # Декомпозиция агрегатных
        if is_aggregate(nw):
            for child_nw in decompose(nw):
                await _create_card(
                    db,
                    estimate_batch_id=estimate_batch_id,
                    nw_item_code=child_nw,
                    unit=None,
                    quantity=None,
                    parent_id=card_id,
                    status="needs_volume",
                    user_id=user_id,
                    notes=f"декомпозиция {nw} (LLM)",
                )
                new_cards += 1

    await db.commit()
    return {
        "unmatched_before":   len(unmatched_rows),
        "matched_by_llm":     matched_count,
        "still_unmatched":    len(unmatched_rows) - matched_count,
        "new_cards":          new_cards,
        "linked_to_existing": 0,
    }


async def confirm_all(db: AsyncSession, estimate_batch_id: str) -> int:
    """Подтвердить все карточки batch'а кроме removed/needs_volume. Возвращает кол-во."""
    res = await db.execute(
        text(
            """
            UPDATE fer.project_work_plan
            SET status = 'confirmed', confirmed_at = NOW(), updated_at = NOW()
            WHERE estimate_batch_id = :id
              AND status IN ('auto_proposed','custom_added')
            """
        ),
        {"id": estimate_batch_id},
    )
    await db.commit()
    return res.rowcount or 0
