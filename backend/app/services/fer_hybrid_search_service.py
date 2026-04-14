from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import Integer, bindparam, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.openrouter_embeddings import create_chat_completion, parse_json_object


_FTS_CONFIG_CACHE: str | None = None
_FTS_CONFIG_CANDIDATES = ("russian", "pg_catalog.russian", "simple")

_NORMALIZE_PROMPT = """Ты эксперт по строительным сметам России и ФЕР.
Переформулируй строку сметы в стандартную форму для поиска по ФЕР.

Правила:
- раскрывай строительные сокращения
- сохраняй исходный смысл и не выдумывай отсутствующие данные
- приводи текст к формулировкам, близким к ФЕР
- укажи вид работы, материал, конструкцию, условие и единицу измерения, если они есть во входе
- ответь одной строкой без пояснений
"""

_RERANK_PROMPT = """Ты эксперт по строительным сметам России и ФЕР.
Нужно выбрать лучший вариант ФЕР для строки сметы.

Критерии по убыванию важности:
1. Вид работы
2. Материал и конструкция
3. Условия выполнения и характеристики
4. Единица измерения

Ответь строго JSON-объектом:
{
  "selected_index": <номер кандидата, начиная с 1>,
  "confidence": <число 0..1>,
  "reason": "<краткое объяснение>"
}
"""


@dataclass(slots=True)
class HybridCandidate:
    vector_index_id: int
    table_id: int | None
    work_type: str
    source_text: str
    search_text: str
    vec_score: float
    fts_score: float
    final_score: float


@dataclass(slots=True)
class HybridScoreSummary:
    top1_score: float
    top2_score: float | None
    score_gap: float | None


@dataclass(slots=True)
class RerankDecision:
    selected_candidate: HybridCandidate
    confidence: float
    reason: str
    corrected: bool


def build_normalization_input(
    *,
    section: str | None,
    work_name: str,
    unit: str | None,
) -> str:
    parts: list[str] = []
    if section and str(section).strip():
        parts.append(f"Раздел: {str(section).strip()}")
    parts.append(f"Строка сметы: {str(work_name).strip()}")
    if unit and str(unit).strip():
        parts.append(f"Единица измерения: {str(unit).strip()}")
    return "\n".join(parts)


async def normalize_smeta_item(
    *,
    section: str | None,
    work_name: str,
    unit: str | None,
) -> str:
    content = await create_chat_completion(
        model=settings.NORMALIZATION_MODEL,
        messages=[
            {"role": "system", "content": _NORMALIZE_PROMPT},
            {
                "role": "user",
                "content": build_normalization_input(
                    section=section,
                    work_name=work_name,
                    unit=unit,
                ),
            },
        ],
        temperature=0.0,
        max_tokens=220,
    )
    normalized = " ".join(content.split())
    return normalized or str(work_name).strip()


async def resolve_fts_config(db: AsyncSession) -> str:
    global _FTS_CONFIG_CACHE
    if _FTS_CONFIG_CACHE:
        return _FTS_CONFIG_CACHE

    for candidate in _FTS_CONFIG_CANDIDATES:
        try:
            await db.execute(
                text(f"SELECT to_tsvector('{candidate}', 'кладка наружных стен')")
            )
            _FTS_CONFIG_CACHE = candidate
            return candidate
        except Exception:
            await db.rollback()
            continue

    _FTS_CONFIG_CACHE = "simple"
    return _FTS_CONFIG_CACHE


def build_fts_document_text(search_text: str, source_text: str | None = None) -> str:
    parts = [search_text.replace("\n", " ").strip()]
    if source_text and source_text.strip():
        parts.append(source_text.strip())
    return " ".join(part for part in parts if part)


async def hybrid_search_candidates(
    db: AsyncSession,
    *,
    normalized_text: str,
    embedding_literal: str,
    allowed_section_ids: Sequence[int] | None = None,
    top_k: int | None = None,
    vector_limit: int = 40,
    fts_limit: int = 40,
) -> list[HybridCandidate]:
    if allowed_section_ids is not None and len(allowed_section_ids) == 0:
        return []

    fts_config = await resolve_fts_config(db)
    top_k = top_k or settings.RERANK_CANDIDATE_COUNT

    section_filter = ""
    params: dict[str, object] = {
        "embedding": embedding_literal,
        "query_text": normalized_text,
        "top_k": int(top_k),
        "vector_limit": int(vector_limit),
        "fts_limit": int(fts_limit),
        "vector_weight": float(settings.HYBRID_VECTOR_WEIGHT),
        "fts_weight": float(settings.HYBRID_FTS_WEIGHT),
    }
    if allowed_section_ids:
        section_filter = "AND t.section_id = ANY(:allowed_section_ids)"
        params["allowed_section_ids"] = [int(section_id) for section_id in allowed_section_ids]

    stmt = text(
        f"""
        WITH vector_search AS (
            SELECT
                vi.id,
                GREATEST(
                    0.0,
                    LEAST(
                        1.0,
                        1 - (vi.embedding OPERATOR(fer.<=>) CAST(:embedding AS fer.vector))
                    )
                ) AS vec_score
            FROM fer.vector_index vi
            LEFT JOIN fer.fer_tables t ON t.id = vi.table_id
            LEFT JOIN fer.collections c ON c.id = t.collection_id
            LEFT JOIN fer.sections s ON s.id = t.section_id
            LEFT JOIN fer.subsections ss ON ss.id = t.subsection_id
            WHERE vi.entity_kind = 'row'
              AND NOT (
                  COALESCE(c.ignored, FALSE)
                  OR COALESCE(s.ignored, FALSE)
                  OR COALESCE(ss.ignored, FALSE)
                  OR COALESCE(t.ignored, FALSE)
              )
              {section_filter}
            ORDER BY vi.embedding OPERATOR(fer.<=>) CAST(:embedding AS fer.vector), vi.id
            LIMIT :vector_limit
        ),
        fts_search AS (
            SELECT
                vi.id,
                ts_rank_cd(
                    vi.fts_document,
                    plainto_tsquery('{fts_config}', :query_text)
                ) AS fts_score
            FROM fer.vector_index vi
            LEFT JOIN fer.fer_tables t ON t.id = vi.table_id
            LEFT JOIN fer.collections c ON c.id = t.collection_id
            LEFT JOIN fer.sections s ON s.id = t.section_id
            LEFT JOIN fer.subsections ss ON ss.id = t.subsection_id
            WHERE vi.entity_kind = 'row'
              AND vi.fts_document IS NOT NULL
              AND vi.fts_document @@ plainto_tsquery('{fts_config}', :query_text)
              AND NOT (
                  COALESCE(c.ignored, FALSE)
                  OR COALESCE(s.ignored, FALSE)
                  OR COALESCE(ss.ignored, FALSE)
                  OR COALESCE(t.ignored, FALSE)
              )
              {section_filter}
            ORDER BY fts_score DESC, vi.id
            LIMIT :fts_limit
        ),
        candidate_ids AS (
            SELECT id FROM vector_search
            UNION
            SELECT id FROM fts_search
        )
        SELECT
            vi.id AS vector_index_id,
            vi.table_id,
            COALESCE(NULLIF(t.common_work_name, ''), t.table_title, vi.source_text) AS work_type,
            vi.source_text,
            vi.search_text,
            COALESCE(v.vec_score, 0.0) AS vec_score,
            COALESCE(f.fts_score, 0.0) AS fts_score,
            GREATEST(
                0.0,
                LEAST(
                    1.0,
                    (:vector_weight * COALESCE(v.vec_score, 0.0))
                    + (:fts_weight * COALESCE(f.fts_score, 0.0))
                )
            ) AS final_score
        FROM candidate_ids ids
        JOIN fer.vector_index vi ON vi.id = ids.id
        LEFT JOIN fer.fer_tables t ON t.id = vi.table_id
        LEFT JOIN vector_search v ON v.id = ids.id
        LEFT JOIN fts_search f ON f.id = ids.id
        ORDER BY final_score DESC, vec_score DESC, fts_score DESC, vi.id
        LIMIT :top_k
        """
    )
    if allowed_section_ids:
        stmt = stmt.bindparams(
            bindparam("allowed_section_ids", type_=postgresql.ARRAY(Integer)),
        )

    rows = (await db.execute(stmt, params)).mappings().all()
    return [
        HybridCandidate(
            vector_index_id=int(row["vector_index_id"]),
            table_id=int(row["table_id"]) if row["table_id"] is not None else None,
            work_type=str(row["work_type"]).strip(),
            source_text=str(row["source_text"] or "").strip(),
            search_text=str(row["search_text"] or "").strip(),
            vec_score=float(row["vec_score"] or 0.0),
            fts_score=float(row["fts_score"] or 0.0),
            final_score=float(row["final_score"] or 0.0),
        )
        for row in rows
        if row["work_type"]
    ]


def summarize_candidate_scores(candidates: Sequence[HybridCandidate]) -> HybridScoreSummary | None:
    if not candidates:
        return None
    top1 = float(candidates[0].final_score)
    top2 = float(candidates[1].final_score) if len(candidates) > 1 else None
    gap = top1 - top2 if top2 is not None else None
    return HybridScoreSummary(top1_score=top1, top2_score=top2, score_gap=gap)


def should_rerank(candidates: Sequence[HybridCandidate]) -> bool:
    if not settings.RERANK_ENABLED or not candidates:
        return False

    summary = summarize_candidate_scores(candidates)
    if summary is None:
        return False
    if summary.top1_score < float(settings.RERANK_SCORE_THRESHOLD):
        return True
    if summary.score_gap is not None and summary.score_gap < float(settings.RERANK_GAP_THRESHOLD):
        return True
    return False


async def llm_rerank(
    *,
    original_text: str,
    normalized_text: str,
    candidates: Sequence[HybridCandidate],
) -> RerankDecision:
    candidate_lines = []
    for index, candidate in enumerate(candidates, start=1):
        candidate_lines.append(
            f"{index}. table_id={candidate.table_id} | {candidate.work_type} | "
            f"source={candidate.source_text} | context={candidate.search_text.replace(chr(10), ' / ')} | "
            f"vec={candidate.vec_score:.3f} | fts={candidate.fts_score:.3f} | final={candidate.final_score:.3f}"
        )

    content = await create_chat_completion(
        model=settings.RERANK_MODEL,
        messages=[
            {"role": "system", "content": _RERANK_PROMPT},
            {
                "role": "user",
                "content": "\n".join(
                    [
                        f"Оригинал: {original_text}",
                        f"Нормализованный текст: {normalized_text}",
                        "Кандидаты:",
                        *candidate_lines,
                    ]
                ),
            },
        ],
        temperature=0.0,
        max_tokens=320,
    )
    data = parse_json_object(content)
    selected_index = int(data["selected_index"]) - 1
    if selected_index < 0 or selected_index >= len(candidates):
        raise RuntimeError("Rerank returned candidate index out of range.")

    selected_candidate = candidates[selected_index]
    return RerankDecision(
        selected_candidate=selected_candidate,
        confidence=max(0.0, min(float(data.get("confidence", selected_candidate.final_score)), 1.0)),
        reason=str(data.get("reason") or "").strip(),
        corrected=selected_index != 0,
    )
