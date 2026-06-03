"""Классификация work-строк по отраслевому справочнику (макротип + подтип) и
построение зависимостей Ганта по графу предшествования.

Данные живут в БД (work_subtypes / work_precedence, засеяны из CSV миграцией).
Справочник маленький (~62 подтипа, ~40 рёбер) и неизменный в рамках процесса,
поэтому грузим его один раз в module-level кэш (plain-структуры, не ORM —
чтобы не зависеть от сессии).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WorkPrecedence, WorkSubtype


@dataclass(frozen=True)
class SubtypeDef:
    macro_id: int
    code: str
    name: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class PrecedenceEdge:
    predecessor_code: str
    successor_code: str
    lag_days: int


@dataclass(frozen=True)
class SubtypeMatch:
    macro_id: int
    code: str
    name: str
    score: int


_taxonomy_cache: list[SubtypeDef] | None = None
_precedence_cache: list[PrecedenceEdge] | None = None


def clear_cache() -> None:
    """Сбросить кэши (используется в тестах)."""
    global _taxonomy_cache, _precedence_cache
    _taxonomy_cache = None
    _precedence_cache = None


async def load_taxonomy(db: AsyncSession) -> list[SubtypeDef]:
    global _taxonomy_cache
    if _taxonomy_cache is None:
        rows = list(await db.scalars(select(WorkSubtype)))
        _taxonomy_cache = [
            SubtypeDef(
                macro_id=r.macro_id,
                code=r.code,
                name=r.name,
                keywords=tuple(k.lower() for k in (r.keywords or []) if k and k.strip()),
            )
            for r in rows
        ]
    return _taxonomy_cache


async def load_precedence(db: AsyncSession) -> list[PrecedenceEdge]:
    global _precedence_cache
    if _precedence_cache is None:
        rows = list(await db.scalars(select(WorkPrecedence)))
        _precedence_cache = [
            PrecedenceEdge(
                predecessor_code=r.predecessor_code,
                successor_code=r.successor_code,
                lag_days=int(r.lag_days or 0),
            )
            for r in rows
        ]
    return _precedence_cache


def classify_subtype(
    name: str,
    section: str | None,
    taxonomy: list[SubtypeDef],
) -> SubtypeMatch | None:
    """Подобрать подтип по keyword-совпадениям в наименовании (+ раздел).

    Совпадение = keyword-фраза встречается как подстрока. Выигрывает подтип с
    наибольшим числом совпавших ключей; при равенстве — с самым длинным
    совпавшим ключом (более специфичная фраза). None — если ничего не нашли.
    """
    haystack = " ".join(p for p in (name, section) if p).lower()
    if not haystack.strip():
        return None

    best: SubtypeMatch | None = None
    best_longest = 0
    for sub in taxonomy:
        matched = [kw for kw in sub.keywords if kw in haystack]
        if not matched:
            continue
        score = len(matched)
        longest = max(len(kw) for kw in matched)
        if best is None or score > best.score or (score == best.score and longest > best_longest):
            best = SubtypeMatch(macro_id=sub.macro_id, code=sub.code, name=sub.name, score=score)
            best_longest = longest
    return best


def build_precedence_dependencies(
    subtype_to_task_ids: dict[str, list[str]],
    precedence: list[PrecedenceEdge],
) -> list[tuple[str, str, int]]:
    """По графу предшествования и карте ``subtype_code -> [task_id в row_order]``
    вернуть рёбра ``(successor_task_id, predecessor_task_id, lag_days)``.

    v1-упрощение: связь «представитель→представитель» — последняя задача
    подтипа-предшественника соединяется с первой задачей подтипа-последователя.
    Дубли по (successor, predecessor) отбрасываются.
    """
    edges: list[tuple[str, str, int]] = []
    seen: set[tuple[str, str]] = set()
    for edge in precedence:
        preds = subtype_to_task_ids.get(edge.predecessor_code)
        succs = subtype_to_task_ids.get(edge.successor_code)
        if not preds or not succs:
            continue
        predecessor_task_id = preds[-1]   # последняя задача предшествующего подтипа
        successor_task_id = succs[0]      # первая задача последующего подтипа
        if predecessor_task_id == successor_task_id:
            continue
        key = (successor_task_id, predecessor_task_id)
        if key in seen:
            continue
        seen.add(key)
        edges.append((successor_task_id, predecessor_task_id, edge.lag_days))
    return edges
