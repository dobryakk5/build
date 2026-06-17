"""Rule-based work_stage classifier for project_hierarchy v6.4."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.work_taxonomy_service import (
    PROMPT_VERSION,
    classify_work,
    dictionary_version,
    normalize_text,
    _match_terms,
)


@dataclass(frozen=True)
class StageMatch:
    stage: dict[str, Any] | None
    score: int
    confidence: str
    needs_review: bool
    match_type: str
    matched_terms: dict[str, list[str]] = field(default_factory=dict)
    stage_option: dict[str, Any] | None = None
    work_type_ref: dict[str, Any] | None = None
    review_reason: str | None = None

    def as_raw_data(
        self,
        *,
        estimate_type_id: str | None,
        estimate_type_number: str | None,
        project_variant_id: str | None,
        project_variant_number: str | None,
        row_role: str | None,
    ) -> dict[str, Any]:
        stage = self.stage or {}
        option = self.stage_option or {}
        work_type = self.work_type_ref or {}
        section_id = work_type.get("section_id")
        subtype_id = work_type.get("subtype_id")
        stage_number = stage.get("number")
        work_subtype_code = f"{section_id}/{subtype_id}" if section_id and subtype_id else None
        return {
            "estimate_type_id": estimate_type_id,
            "estimate_type_number": estimate_type_number,
            "project_variant_id": project_variant_id,
            "project_variant_number": project_variant_number,
            "canonical_stage_id": stage.get("canonical_stage_id"),
            "work_stage_number": stage_number,
            "work_stage_title": stage.get("title"),
            "stage_occurrence_index": stage.get("occurrence_index"),
            "stage_occurrence_label": stage.get("occurrence_label"),
            "stage_options_mode": stage.get("stage_options_mode") or "none",
            "stage_option_id": option.get("id") or option.get("number"),
            "stage_option_title": option.get("title"),
            "section_id": section_id,
            "subtype_id": subtype_id,
            "row_role": row_role,
            "parent_row_id": None,
            "inherited_from_row_id": None,
            "stage_confidence": self.confidence,
            "work_type_confidence": self.confidence if section_id and subtype_id else "low",
            "autofill_enabled": bool(
                option.get("autofill_enabled")
                if option
                else stage.get("autofill_enabled") and (stage.get("stage_options_mode") or "none") == "none"
            ),
            "needs_review": self.needs_review,
            "review_reason": self.review_reason,
            "stage_match_type": self.match_type,
            "stage_match_score_json": {
                "score": self.score,
                "matched_terms": self.matched_terms,
            },
            "work_type_match_score_json": {
                "section_id": section_id,
                "subtype_id": subtype_id,
                "source": work_type.get("mapping_source"),
                "mapping_confidence": work_type.get("mapping_confidence"),
            },
            "dictionary_version": dictionary_version(),
            "prompt_version": PROMPT_VERSION,
            "work_section_code": section_id,
            "work_subtype_code": work_subtype_code,
        }


class StageClassifier:
    def __init__(self, sequential_policy: dict[str, Any] | None = None) -> None:
        self.sequential_policy = sequential_policy or {}

    def classify_row_to_stage(
        self,
        row_text: str,
        row_role: str,
        allowed_stages: list[dict[str, Any]],
        previous_context: dict[str, Any] | None = None,
    ) -> StageMatch:
        text = normalize_text(row_text)
        if not text or not allowed_stages:
            return StageMatch(None, 0, "low", True, "no_stage_match", review_reason="empty_or_no_allowed_stages")

        if self._should_inherit(row_role, previous_context):
            stage = self._stage_by_number(allowed_stages, str(previous_context.get("work_stage_number") or ""))
            if stage:
                return StageMatch(
                    stage,
                    int(self.sequential_policy.get("same_stage_context_boost", 4)),
                    "high",
                    False,
                    "inherited_context",
                    matched_terms={"context": [row_role]},
                    work_type_ref=None,
                )

        global_work = classify_work(row_text, row_role="work")
        global_section = global_work.section_code
        global_subtype = None
        if global_work.subtype_code and "/" in global_work.subtype_code:
            global_section, global_subtype = global_work.subtype_code.split("/", 1)

        scored = [
            self._score_stage(stage, text, row_role, global_section, global_subtype, previous_context)
            for stage in allowed_stages
        ]
        scored.sort(key=lambda item: item.score, reverse=True)
        best = scored[0]
        second_score = scored[1].score if len(scored) > 1 else 0
        delta = best.score - second_score
        needs_review = best.score < 6 or delta < 2
        confidence = "high" if not needs_review and best.score >= 12 else "medium" if not needs_review else "low"
        return StageMatch(
            best.stage,
            best.score,
            confidence,
            needs_review,
            best.match_type,
            best.matched_terms,
            best.stage_option,
            best.work_type_ref,
            None if not needs_review else "low_stage_score_or_ambiguous",
        )

    def _should_inherit(self, row_role: str, previous_context: dict[str, Any] | None) -> bool:
        if not previous_context or not previous_context.get("work_stage_number"):
            return False
        if row_role == "material" and self.sequential_policy.get("material_inherits_current_stage", True):
            return True
        if row_role in {"delivery", "logistics", "overhead"} and self.sequential_policy.get("delivery_cleanup_inherits_current_stage", True):
            return True
        return False

    def _stage_by_number(self, stages: list[dict[str, Any]], number: str) -> dict[str, Any] | None:
        return next((stage for stage in stages if str(stage.get("number") or "") == number), None)

    def _score_stage(
        self,
        stage: dict[str, Any],
        text: str,
        row_role: str,
        global_section: str | None,
        global_subtype: str | None,
        previous_context: dict[str, Any] | None,
    ) -> StageMatch:
        score = 0
        matched: dict[str, list[str]] = {}
        stage_terms = self._important_terms(stage.get("title"))
        title_matches = _match_terms(stage_terms, text, text.split())
        if title_matches:
            matched["stage_title"] = title_matches
            score += len(title_matches) * 3

        occurrence_label = stage.get("occurrence_label")
        if occurrence_label and _match_terms([str(occurrence_label)], text, text.split()):
            matched["occurrence_label"] = [str(occurrence_label)]
            score += 5

        primary = stage.get("primary_work_type") if isinstance(stage.get("primary_work_type"), dict) else {}
        work_type_ref = None
        if self._work_type_matches(primary, global_section, global_subtype):
            matched["primary_work_type"] = [self._work_type_code(primary)]
            score += 8
            work_type_ref = primary

        for related in stage.get("related_work_types") or []:
            if self._work_type_matches(related, global_section, global_subtype):
                matched.setdefault("related_work_types", []).append(self._work_type_code(related))
                score += 6
                work_type_ref = work_type_ref or related

        option_match = self._best_option(stage, text, global_section, global_subtype)
        if option_match:
            option, option_score, option_terms = option_match
            matched["stage_option"] = option_terms
            score += option_score
            work_type_ref = {
                "section_id": option.get("section_id"),
                "subtype_id": option.get("subtype_id"),
                "mapping_source": option.get("mapping_source"),
                "mapping_confidence": "stage_option",
            }

        if previous_context and previous_context.get("work_stage_number"):
            score += self._sequential_score(stage, previous_context)

        match_type = "stage_option" if option_match else "work_type_context" if work_type_ref else "stage_title"
        if not work_type_ref and (stage.get("stage_options_mode") or "none") == "none" and stage.get("autofill_enabled"):
            work_type_ref = primary if primary.get("section_id") and primary.get("subtype_id") else None
        return StageMatch(stage, score, "low", True, match_type, matched, option_match[0] if option_match else None, work_type_ref)

    def _best_option(
        self,
        stage: dict[str, Any],
        text: str,
        global_section: str | None,
        global_subtype: str | None,
    ) -> tuple[dict[str, Any], int, list[str]] | None:
        best: tuple[dict[str, Any], int, list[str]] | None = None
        for option in stage.get("stage_options") or []:
            if not isinstance(option, dict):
                continue
            terms = self._important_terms(option.get("title"))
            matches = _match_terms(terms, text, text.split())
            score = len(matches) * 8
            if self._work_type_matches(option, global_section, global_subtype):
                score += 10
                matches.append(self._work_type_code(option))
            if score > 0 and (best is None or score > best[1]):
                best = (option, score, matches)
        return best

    def _sequential_score(self, stage: dict[str, Any], previous_context: dict[str, Any]) -> int:
        current = self._stage_order(stage.get("number"))
        previous = self._stage_order(previous_context.get("work_stage_number"))
        if current is None or previous is None:
            return 0
        if current == previous:
            return int(self.sequential_policy.get("same_stage_context_boost", 4))
        if current == previous + 1:
            return int(self.sequential_policy.get("next_stage_boost", 2))
        if current == previous - 1:
            return int(self.sequential_policy.get("previous_stage_boost", 1))
        return int(self.sequential_policy.get("far_stage_penalty", -2))

    def _stage_order(self, number: Any) -> int | None:
        try:
            return int(str(number).split(".")[-1])
        except (TypeError, ValueError):
            return None

    def _work_type_matches(self, ref: dict[str, Any], section_id: str | None, subtype_id: str | None) -> bool:
        if not ref or not section_id:
            return False
        if ref.get("section_id") != section_id:
            return False
        return not ref.get("subtype_id") or ref.get("subtype_id") == subtype_id

    def _work_type_code(self, ref: dict[str, Any]) -> str:
        return f"{ref.get('section_id')}/{ref.get('subtype_id')}"

    def _important_terms(self, value: Any) -> list[str]:
        tokens = [
            token
            for token in normalize_text(value).split()
            if len(token) > 3
            and token not in {"работы", "работ", "устройство", "монтаж", "если", "есть", "при", "наличии", "необходимости"}
        ]
        terms = list(dict.fromkeys(tokens))
        normalized = normalize_text(value)
        if normalized:
            terms.append(normalized)
        return terms
