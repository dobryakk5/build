"""Rule-based work_stage classifier for project_hierarchy v6.4."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.services.work_taxonomy_service import (
    PROMPT_VERSION,
    UNKNOWN_SUBTYPE_CODE,
    classify_work,
    dictionary_version,
    normalize_text,
    _load_dictionary,
    _match_terms,
)


STAGE_AUTO_ACCEPT_MIN_SCORE = 10
STAGE_REVIEW_MIN_SCORE = 5
STAGE_MIN_DELTA_BETWEEN_TOP_TWO = 3
WORK_TYPE_AUTO_ACCEPT_MIN_SCORE = 9
WORK_TYPE_REVIEW_MIN_SCORE = 5
WORK_TYPE_MIN_DELTA_BETWEEN_TOP_TWO = 3

CANONICAL_ROW_ROLES = {
    "work",
    "material",
    "mechanism",
    "labor",
    "logistics",
    "overhead",
    "header",
    "total",
    "placeholder",
    "unknown",
}

LEGACY_ROW_ROLE_MAP = {
    "equipment": "mechanism",
    "delivery": "logistics",
    "cleanup": "logistics",
    "documentation": "overhead",
}

INHERIT_ROLES = {"material", "mechanism", "labor", "logistics", "overhead", "unknown"}
SERVICE_ROLES = {"total", "placeholder"}

PARENT_STAGE_ROLES = {"selectable_group", "grouped_stage", "group_header"}
ALWAYS_REVIEW_STAGE_ROLES = {"needs_mapping_review", "needs_foreman_review", "unknown", "other"}
EXPLICIT_ONLY_STAGE_ROLES = {"handover_instruction", "design_documentation", "design_survey"}
CAUTIOUS_STAGE_ROLES = {
    "logistics_cleanup",
    "cleanup",
    "preparation",
    "demolition",
    "testing_commissioning",
    "configuration_commissioning",
    "commissioning",
    "optional_work",
}

OCCURRENCE_PATTERNS = [
    (re.compile(r"\b(\d+)\s*(этаж|эт\.?|этажа)\b", re.IGNORECASE), "{N} этаж"),
    (re.compile(r"\b(цоколь|цокольный)\b", re.IGNORECASE), "цоколь"),
    (re.compile(r"\b(подвал|подвальный)\b", re.IGNORECASE), "подвал"),
    (re.compile(r"\b(мансард\w*|мансарда|мансардный)\b", re.IGNORECASE), "мансарда"),
    (re.compile(r"\b(чердак|чердачный)\b", re.IGNORECASE), "чердак"),
]


class StageMatchType(StrEnum):
    EXACT_STAGE_TITLE_MATCH = "exact_stage_title_match"
    NEAR_STAGE_TITLE_MATCH = "near_stage_title_match"
    CANONICAL_TITLE_MATCH = "canonical_title_match"
    STAGE_OPTION_MATCH = "stage_option_match"
    PRIMARY_WORK_TYPE_MATCH = "primary_work_type_match"
    RELATED_WORK_TYPE_MATCH = "related_work_type_match"
    SEQUENTIAL_CONTEXT_BOOST = "sequential_context_boost"
    CONTEXT_INHERIT = "context_inherit"
    MATERIAL_INHERIT = "material_inherit"
    LOGISTICS_INHERIT = "logistics_inherit"
    MECHANISM_INHERIT = "mechanism_inherit"
    FALLBACK_GLOBAL_CLASSIFIER = "fallback_global_classifier"
    LLM_REVIEW_SUGGESTED = "llm_review_suggested"
    MANUAL_OPERATOR_OVERRIDE = "manual_operator_override"
    UNMATCHED = "unmatched"


@dataclass(frozen=True)
class WorkTypeMatch:
    section_id: str | None
    subtype_id: str | None
    confidence: str
    needs_review: bool
    reason: str | None
    source: str | None
    stage_option: dict[str, Any] | None = None
    score_breakdown: dict[str, Any] = field(default_factory=dict)

    @property
    def work_subtype_code(self) -> str | None:
        if self.section_id and self.subtype_id:
            return f"{self.section_id}/{self.subtype_id}"
        return None


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
    occurrence_label: str | None = None
    score_breakdown: dict[str, Any] = field(default_factory=dict)
    work_type_match: WorkTypeMatch | None = None
    inherited_from_row_order: int | None = None
    parent_row_order: int | None = None
    normalized_row_role: str = "unknown"

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
        work_type = self.work_type_match
        section_id = work_type.section_id if work_type else None
        subtype_id = work_type.subtype_id if work_type else None
        stage_number = stage.get("number")
        work_subtype_code = f"{section_id}/{subtype_id}" if section_id and subtype_id else None
        normalized_role = normalize_row_role(row_role or self.normalized_row_role)
        stage_needs_review = bool(self.needs_review or (work_type.needs_review if work_type else False))
        review_reason = self.review_reason or (work_type.reason if work_type and work_type.needs_review else None)
        return {
            "estimate_type_id": estimate_type_id,
            "estimate_type_number": estimate_type_number,
            "project_variant_id": project_variant_id,
            "project_variant_number": project_variant_number,
            "canonical_stage_id": stage.get("canonical_stage_id"),
            "work_stage_number": stage_number,
            "work_stage_title": stage.get("title"),
            "stage_occurrence_index": stage.get("occurrence_index"),
            "stage_occurrence_label": self.occurrence_label or stage.get("occurrence_label"),
            "stage_options_mode": stage.get("stage_options_mode") or "none",
            "stage_option_id": option.get("id") or option.get("number"),
            "stage_option_title": option.get("title"),
            "section_id": section_id,
            "subtype_id": subtype_id,
            "row_role": normalized_role,
            "parent_row_id": None,
            "inherited_from_row_id": None,
            "parent_row_order": self.parent_row_order,
            "inherited_from_row_order": self.inherited_from_row_order,
            "stage_confidence": self.confidence,
            "work_type_confidence": work_type.confidence if work_type else "low",
            "autofill_enabled": bool(work_subtype_code and not stage_needs_review),
            "needs_review": stage_needs_review,
            "review_reason": review_reason,
            "stage_match_type": self.match_type,
            "stage_match_score_json": self.score_breakdown or {
                "score": self.score,
                "matched_terms": self.matched_terms,
            },
            "work_type_match_score_json": (work_type.score_breakdown if work_type else {}),
            "dictionary_version": dictionary_version(),
            "prompt_version": PROMPT_VERSION,
            "work_section_code": section_id,
            "work_subtype_code": work_subtype_code,
        }


def normalize_row_role(row_role: str | None) -> str:
    value = normalize_text(row_role or "unknown").replace(" ", "_")
    value = LEGACY_ROW_ROLE_MAP.get(value, value)
    return value if value in CANONICAL_ROW_ROLES else "unknown"


class WorkTypeClassifier:
    def __init__(self) -> None:
        self.payload = _load_dictionary()
        scoring = self.payload.get("scoring") or {}
        thresholds = scoring.get("decision_thresholds") or {}
        self.thresholds = {
            "auto_accept_min_score": int(thresholds.get("auto_accept_min_score", WORK_TYPE_AUTO_ACCEPT_MIN_SCORE)),
            "review_min_score": int(thresholds.get("review_min_score", WORK_TYPE_REVIEW_MIN_SCORE)),
            "min_delta_between_top_two": int(
                thresholds.get("min_delta_between_top_two", WORK_TYPE_MIN_DELTA_BETWEEN_TOP_TWO)
            ),
        }
        self.sections_by_id = {
            str(section.get("id") or ""): section
            for section in self.payload.get("sections") or []
            if isinstance(section, dict)
        }

    def classify_row_with_stage_context(
        self,
        row_text: str,
        stage: dict[str, Any],
        stage_match: StageMatch,
        estimate_profile_id: str | None = None,
    ) -> WorkTypeMatch:
        text = normalize_text(row_text)
        tokens = text.split()
        mode = stage.get("stage_options_mode") or "none"
        stage_role = str(stage.get("stage_role") or "work")
        candidates: list[dict[str, Any]] = []

        for option in stage.get("stage_options") or []:
            if not isinstance(option, dict):
                continue
            candidates.append(
                self._candidate_from_ref(
                    option,
                    "stage_option",
                    text,
                    tokens,
                    base_score=2,
                    title=option.get("title"),
                    stage_context_boost=2,
                )
            )

        primary = stage.get("primary_work_type") if isinstance(stage.get("primary_work_type"), dict) else {}
        if primary:
            candidates.append(
                self._candidate_from_ref(
                    primary,
                    "primary_work_type",
                    text,
                    tokens,
                    base_score=1,
                    title=stage.get("title"),
                    stage_context_boost=2,
                )
            )

        for related in stage.get("related_work_types") or []:
            if not isinstance(related, dict):
                continue
            candidates.append(
                self._candidate_from_ref(
                    related,
                    "related_work_type",
                    text,
                    tokens,
                    base_score=0,
                    title=stage.get("title"),
                    stage_context_boost=1,
                )
            )

        global_result = classify_work(row_text, row_role="work")
        if global_result.subtype_code and global_result.subtype_code != UNKNOWN_SUBTYPE_CODE:
            section_id, subtype_id = self._split_subtype_code(global_result.subtype_code)
            score = max(0, min(int(global_result.score or 0), 7))
            score += self._estimate_profile_adjustment(estimate_profile_id, section_id, text, tokens)
            candidates.append(
                {
                    "section_id": section_id,
                    "subtype_id": subtype_id,
                    "source": "global_classifier",
                    "score": score,
                    "matched_terms": global_result.matched_terms,
                    "stage_option_id": None,
                    "stage_option_title": None,
                    "global_score": global_result.score,
                    "global_confidence": global_result.confidence,
                    "global_needs_review": global_result.needs_review,
                }
            )

        candidates = [c for c in candidates if c.get("section_id") and c.get("subtype_id")]
        collapsed: dict[tuple[str, str], dict[str, Any]] = {}
        for candidate in candidates:
            key = (str(candidate.get("section_id")), str(candidate.get("subtype_id")))
            previous = collapsed.get(key)
            if previous is None or int(candidate.get("score") or 0) > int(previous.get("score") or 0):
                collapsed[key] = candidate
            elif previous is not None:
                previous.setdefault("also_matched_sources", []).append(candidate.get("source"))
        candidates = list(collapsed.values())
        candidates.sort(key=lambda item: int(item.get("score") or 0), reverse=True)
        top = candidates[0] if candidates else None
        second_score = int(candidates[1].get("score") or 0) if len(candidates) > 1 else 0
        top_score = int(top.get("score") or 0) if top else 0
        delta = top_score - second_score

        needs_review = (
            top is None
            or top_score < self.thresholds["auto_accept_min_score"]
            or delta < self.thresholds["min_delta_between_top_two"]
        )
        reason = None
        if top is None:
            reason = "no_work_type_candidate"
        elif top_score < self.thresholds["auto_accept_min_score"]:
            reason = "work_type_score_below_auto_accept"
        elif delta < self.thresholds["min_delta_between_top_two"]:
            reason = "work_type_candidates_ambiguous"

        gate_reason = self._autofill_gate_reason(stage, stage_match, top)
        if gate_reason:
            needs_review = True
            reason = gate_reason

        confidence = "low" if needs_review else "high" if top_score >= self.thresholds["auto_accept_min_score"] else "medium"
        option = None
        if top and top.get("source") == "stage_option":
            option = self._find_option(stage, top.get("stage_option_id"), top.get("stage_option_title"))

        score_json = {
            "candidate_scores": candidates[:10],
            "winner": {
                "section_id": top.get("section_id") if top else None,
                "subtype_id": top.get("subtype_id") if top else None,
                "source": top.get("source") if top else None,
                "score": top_score,
            },
            "thresholds": self.thresholds,
            "delta_top_1_top_2": delta,
            "stage_context": {
                "work_stage_number": stage.get("number"),
                "stage_options_mode": mode,
                "stage_role": stage_role,
                "estimate_profile_id": estimate_profile_id,
            },
            "needs_review": needs_review,
            "reason": reason,
        }
        return WorkTypeMatch(
            section_id=top.get("section_id") if top and not needs_review else None,
            subtype_id=top.get("subtype_id") if top and not needs_review else None,
            confidence=confidence,
            needs_review=needs_review,
            reason=reason,
            source=top.get("source") if top else None,
            stage_option=option if not needs_review else None,
            score_breakdown=score_json,
        )

    def _candidate_from_ref(
        self,
        ref: dict[str, Any],
        source: str,
        text: str,
        tokens: list[str],
        *,
        base_score: int,
        title: Any,
        stage_context_boost: int,
    ) -> dict[str, Any]:
        section_id = ref.get("section_id")
        subtype_id = ref.get("subtype_id")
        matched: dict[str, list[str]] = {}
        score = base_score
        title_terms = _important_terms(title)
        title_matches = _match_terms(title_terms, text, tokens)
        if title_matches:
            matched["title_terms"] = title_matches
            score += 8 if normalize_text(title) and normalize_text(title) in text else 5
        if section_id and subtype_id:
            subtype_score, subtype_matches = self._subtype_score(str(section_id), str(subtype_id), text, tokens)
            if subtype_score:
                score += subtype_score
                matched.update(subtype_matches)
            score += stage_context_boost
        if source == "primary_work_type":
            score += 5
        elif source == "related_work_type":
            score += 3
        elif source == "stage_option" and title_matches:
            score += 5
        return {
            "section_id": section_id,
            "subtype_id": subtype_id,
            "source": source,
            "score": score,
            "matched_terms": matched,
            "stage_option_id": ref.get("id") or ref.get("number") if source == "stage_option" else None,
            "stage_option_title": ref.get("title") if source == "stage_option" else None,
        }

    def _subtype_score(
        self,
        section_id: str,
        subtype_id: str,
        text: str,
        tokens: list[str],
    ) -> tuple[int, dict[str, list[str]]]:
        section = self.sections_by_id.get(section_id) or {}
        subtype = next(
            (
                item
                for item in section.get("subtypes") or []
                if str(item.get("id") or "") == subtype_id or str(item.get("code") or "") == subtype_id
            ),
            None,
        )
        if not subtype:
            return 0, {}
        matched: dict[str, list[str]] = {}
        score = 0
        strong = _match_terms(subtype.get("strong_terms") or [], text, tokens)
        if strong:
            matched["subtype_strong_terms"] = strong
            score += len(strong) * 5
        pairs = []
        for pair in subtype.get("action_object_pairs") or []:
            if not isinstance(pair, list) or len(pair) < 2:
                continue
            if _match_terms([pair[0]], text, tokens) and _match_terms([pair[1]], text, tokens):
                pairs.append(f"{pair[0]} + {pair[1]}")
        if pairs:
            matched["action_object_pairs"] = pairs
            score += len(pairs) * 3
        negative = _match_terms(subtype.get("negative_terms") or [], text, tokens)
        if negative:
            matched["subtype_negative_terms"] = negative
            score -= len(negative) * 6
        return score, matched

    def _estimate_profile_adjustment(
        self,
        estimate_profile_id: str | None,
        section_id: str | None,
        text: str,
        tokens: list[str],
    ) -> int:
        if not estimate_profile_id or not section_id:
            return 0
        for profile in self.payload.get("estimate_profiles") or []:
            if str(profile.get("id") or "") != str(estimate_profile_id):
                continue
            terms = _match_terms(profile.get("strong_terms") or [], text, tokens)
            if not terms:
                return 0
            if section_id in set(profile.get("prefer_sections") or []):
                return 4
            if section_id in set(profile.get("penalize_sections") or []):
                return -4
        return 0

    def _autofill_gate_reason(
        self,
        stage: dict[str, Any],
        stage_match: StageMatch,
        winner: dict[str, Any] | None,
    ) -> str | None:
        if not winner:
            return "no_resolved_work_type"
        stage_role = str(stage.get("stage_role") or "work")
        mode = stage.get("stage_options_mode") or "none"
        if stage_role in ALWAYS_REVIEW_STAGE_ROLES:
            return f"stage_role_{stage_role}_requires_review"
        if stage_role in PARENT_STAGE_ROLES and winner.get("source") != "stage_option":
            return f"stage_role_{stage_role}_is_parent"
        if mode != "none" and winner.get("source") != "stage_option":
            return "stage_option_required_for_autofill"
        if mode == "none" and not bool(stage.get("autofill_enabled", False)):
            return "stage_autofill_disabled"
        if stage_role in EXPLICIT_ONLY_STAGE_ROLES and int(winner.get("score") or 0) < self.thresholds["auto_accept_min_score"] + 3:
            return f"stage_role_{stage_role}_requires_explicit_match"
        if stage_role in CAUTIOUS_STAGE_ROLES and int(winner.get("score") or 0) < self.thresholds["auto_accept_min_score"]:
            return f"stage_role_{stage_role}_requires_strong_match"
        if stage_match.needs_review:
            return "stage_match_requires_review"
        return None

    def _find_option(self, stage: dict[str, Any], option_id: Any, option_title: Any) -> dict[str, Any] | None:
        for option in stage.get("stage_options") or []:
            if not isinstance(option, dict):
                continue
            if option_id and str(option.get("id") or option.get("number") or "") == str(option_id):
                return option
            if option_title and str(option.get("title") or "") == str(option_title):
                return option
        return None

    def _split_subtype_code(self, subtype_code: str | None) -> tuple[str | None, str | None]:
        if not subtype_code or "/" not in subtype_code:
            return None, subtype_code
        section_id, subtype_id = subtype_code.split("/", 1)
        return section_id or None, subtype_id or None


class StageClassifier:
    def __init__(self, sequential_policy: dict[str, Any] | None = None) -> None:
        self.sequential_policy = sequential_policy or {}
        self.payload = _load_dictionary()
        scoring = self.payload.get("stage_scoring") or {}
        self.thresholds = {
            "stage_auto_accept_min_score": int(scoring.get("stage_auto_accept_min_score", STAGE_AUTO_ACCEPT_MIN_SCORE)),
            "stage_review_min_score": int(scoring.get("stage_review_min_score", STAGE_REVIEW_MIN_SCORE)),
            "stage_min_delta_between_top_two": int(
                scoring.get("stage_min_delta_between_top_two", STAGE_MIN_DELTA_BETWEEN_TOP_TWO)
            ),
            "source": "json" if scoring else "backend_default_pending_calibration",
        }
        self.work_type_classifier = WorkTypeClassifier()

    def classify_row_to_stage(
        self,
        row_text: str,
        row_role: str,
        allowed_stages: list[dict[str, Any]],
        previous_context: dict[str, Any] | None = None,
        *,
        estimate_profile_id: str | None = None,
        row_order: int | None = None,
    ) -> StageMatch:
        text = normalize_text(row_text)
        normalized_role = normalize_row_role(row_role)
        if not text or not allowed_stages:
            return self._unmatched("empty_or_no_allowed_stages", normalized_role)
        if normalized_role in SERVICE_ROLES:
            return self._unmatched(f"row_role_{normalized_role}_skipped", normalized_role, needs_review=False)

        global_result = classify_work(row_text, row_role="work")
        global_section, global_subtype = self.work_type_classifier._split_subtype_code(global_result.subtype_code)
        scored = [
            self._score_stage(stage, text, normalized_role, previous_context, global_section, global_subtype)
            for stage in allowed_stages
        ]
        scored.sort(key=lambda item: item.score, reverse=True)
        best = scored[0]
        second_score = scored[1].score if len(scored) > 1 else 0
        delta = best.score - second_score

        if self._should_inherit(normalized_role, previous_context, best, delta):
            inherited = self._inherit_from_context(
                allowed_stages,
                normalized_role,
                previous_context,
                row_order=row_order,
            )
            if inherited:
                return inherited

        needs_review = (
            best.score < self.thresholds["stage_auto_accept_min_score"]
            or delta < self.thresholds["stage_min_delta_between_top_two"]
        )
        reason = None
        if best.score < self.thresholds["stage_review_min_score"]:
            reason = "stage_score_below_review_min"
        elif best.score < self.thresholds["stage_auto_accept_min_score"]:
            reason = "stage_score_below_auto_accept"
        elif delta < self.thresholds["stage_min_delta_between_top_two"]:
            reason = "stage_candidates_ambiguous"

        stage_role = str((best.stage or {}).get("stage_role") or "work")
        if stage_role in ALWAYS_REVIEW_STAGE_ROLES:
            needs_review = True
            reason = f"stage_role_{stage_role}_requires_review"

        confidence = "low" if needs_review else "high" if best.score >= 14 else "medium"
        occurrence_label = self._resolve_occurrence_label(best.stage, text, previous_context)
        preliminary = StageMatch(
            best.stage,
            best.score,
            confidence,
            needs_review,
            best.match_type,
            best.matched_terms,
            best.stage_option,
            None,
            reason,
            occurrence_label=occurrence_label,
            score_breakdown=self._stage_score_json(scored, best, second_score, delta, reason, needs_review),
            normalized_row_role=normalized_role,
        )
        work_type = self.work_type_classifier.classify_row_with_stage_context(
            row_text,
            best.stage or {},
            preliminary,
            estimate_profile_id=estimate_profile_id,
        )
        option = work_type.stage_option or best.stage_option
        return StageMatch(
            best.stage,
            best.score,
            confidence,
            bool(needs_review or work_type.needs_review),
            best.match_type,
            best.matched_terms,
            option,
            None,
            reason or (work_type.reason if work_type.needs_review else None),
            occurrence_label=occurrence_label,
            score_breakdown=self._stage_score_json(scored, best, second_score, delta, reason, bool(needs_review or work_type.needs_review)),
            work_type_match=work_type,
            normalized_row_role=normalized_role,
        )

    def _unmatched(self, reason: str, row_role: str, needs_review: bool = True) -> StageMatch:
        return StageMatch(
            None,
            0,
            "low",
            needs_review,
            StageMatchType.UNMATCHED.value,
            review_reason=reason,
            score_breakdown={
                "candidate_scores": [],
                "winner": None,
                "thresholds": self.thresholds,
                "delta_top_1_top_2": 0,
                "needs_review": needs_review,
                "reason": reason,
            },
            normalized_row_role=row_role,
        )

    def _should_inherit(
        self,
        row_role: str,
        previous_context: dict[str, Any] | None,
        best: StageMatch,
        delta: int,
    ) -> bool:
        if row_role not in INHERIT_ROLES or not previous_context or not previous_context.get("work_stage_number"):
            return False
        if best.score >= self.thresholds["stage_auto_accept_min_score"] and delta >= self.thresholds["stage_min_delta_between_top_two"]:
            return False
        return True

    def _inherit_from_context(
        self,
        allowed_stages: list[dict[str, Any]],
        row_role: str,
        previous_context: dict[str, Any] | None,
        *,
        row_order: int | None,
    ) -> StageMatch | None:
        if not previous_context:
            return None
        stage = self._stage_by_number(allowed_stages, str(previous_context.get("work_stage_number") or ""))
        if not stage:
            return None
        option = self._option_by_id(stage, previous_context.get("stage_option_id"))
        match_type = {
            "material": StageMatchType.MATERIAL_INHERIT.value,
            "mechanism": StageMatchType.MECHANISM_INHERIT.value,
            "logistics": StageMatchType.LOGISTICS_INHERIT.value,
        }.get(row_role, StageMatchType.CONTEXT_INHERIT.value)
        score = int(self.sequential_policy.get("same_stage_context_boost", 4))
        occurrence_label = previous_context.get("stage_occurrence_label") or stage.get("occurrence_label")
        stage_json = {
            "candidate_scores": [
                {
                    "work_stage_number": stage.get("number"),
                    "work_stage_title": stage.get("title"),
                    "score": score,
                    "source": "context_inheritance",
                    "matched_terms": {"row_role": [row_role]},
                }
            ],
            "winner": {
                "work_stage_number": stage.get("number"),
                "score": score,
                "match_type": match_type,
            },
            "thresholds": self.thresholds,
            "delta_top_1_top_2": score,
            "needs_review": False,
            "reason": f"{row_role}_inherits_previous_context",
        }
        inherited = StageMatch(
            stage,
            score,
            "high",
            False,
            match_type,
            matched_terms={"context": [row_role]},
            stage_option=option,
            occurrence_label=occurrence_label,
            score_breakdown=stage_json,
            inherited_from_row_order=previous_context.get("row_order"),
            parent_row_order=previous_context.get("row_order"),
            normalized_row_role=row_role,
        )
        work_type = WorkTypeMatch(
            section_id=None,
            subtype_id=None,
            confidence="low",
            needs_review=False,
            reason="context_inherited_without_subtype_autofill",
            source="context_inheritance",
            stage_option=option,
            score_breakdown={
                "candidate_scores": [],
                "winner": None,
                "thresholds": self.work_type_classifier.thresholds,
                "delta_top_1_top_2": 0,
                "needs_review": False,
                "reason": "context_inherited_without_subtype_autofill",
            },
        )
        return StageMatch(
            **{**inherited.__dict__, "work_type_match": work_type}
        )

    def _score_stage(
        self,
        stage: dict[str, Any],
        text: str,
        row_role: str,
        previous_context: dict[str, Any] | None,
        global_section: str | None,
        global_subtype: str | None,
    ) -> StageMatch:
        score = 0
        matched: dict[str, list[str]] = {}
        component_scores: dict[str, int] = {}
        match_type = StageMatchType.UNMATCHED.value
        option_match: tuple[dict[str, Any], int, list[str]] | None = None

        title = normalize_text(stage.get("title"))
        title_terms = _important_terms(stage.get("title"))
        title_matches = _match_terms(title_terms, text, text.split())
        if title and title in text:
            matched["stage_title_exact"] = [title]
            component_scores["title_match"] = 8
            score += 8
            match_type = StageMatchType.EXACT_STAGE_TITLE_MATCH.value
        elif title_matches:
            matched["stage_title"] = title_matches
            component_scores["title_match"] = min(7, len(title_matches) * 3)
            score += component_scores["title_match"]
            match_type = StageMatchType.NEAR_STAGE_TITLE_MATCH.value

        canonical_title = self._canonical_title(stage.get("canonical_stage_id"))
        canonical_matches = _match_terms(_important_terms(canonical_title), text, text.split())
        if canonical_matches:
            matched["canonical_stage"] = canonical_matches
            component_scores["canonical_stage_match"] = min(5, len(canonical_matches) * 2)
            score += component_scores["canonical_stage_match"]
            if match_type == StageMatchType.UNMATCHED.value:
                match_type = StageMatchType.CANONICAL_TITLE_MATCH.value

        occurrence_label = self._resolve_occurrence_label(stage, text, previous_context)
        if occurrence_label and _match_terms([occurrence_label], text, text.split()):
            matched["occurrence_label"] = [occurrence_label]
            component_scores["occurrence_label"] = 4
            score += 4
        else:
            try:
                occurrence_index = int(stage.get("occurrence_index") or 0)
            except (TypeError, ValueError):
                occurrence_index = 0
            if occurrence_index > 1:
                component_scores["occurrence_missing_penalty"] = -3
                score -= 3

        primary = stage.get("primary_work_type") if isinstance(stage.get("primary_work_type"), dict) else {}
        if self._work_type_matches(primary, global_section, global_subtype):
            matched["primary_work_type"] = [_work_type_code(primary)]
            component_scores["primary_work_type_match"] = 5
            score += 5
            if match_type == StageMatchType.UNMATCHED.value:
                match_type = StageMatchType.PRIMARY_WORK_TYPE_MATCH.value

        related_score = 0
        for related in stage.get("related_work_types") or []:
            if self._work_type_matches(related, global_section, global_subtype):
                matched.setdefault("related_work_types", []).append(_work_type_code(related))
                related_score += 3
        if related_score:
            component_scores["related_work_type_match"] = related_score
            score += related_score
            if match_type == StageMatchType.UNMATCHED.value:
                match_type = StageMatchType.RELATED_WORK_TYPE_MATCH.value

        option_match = self._best_option(stage, text, global_section, global_subtype)
        if option_match:
            option, option_score, option_terms = option_match
            matched["stage_option"] = option_terms
            component_scores["stage_option_match"] = option_score
            score += option_score
            match_type = StageMatchType.STAGE_OPTION_MATCH.value

        if row_role == "work":
            component_scores["row_role_score"] = 2
            score += 2
        elif row_role == "header" and match_type in {
            StageMatchType.EXACT_STAGE_TITLE_MATCH.value,
            StageMatchType.NEAR_STAGE_TITLE_MATCH.value,
        }:
            component_scores["row_role_score"] = 1
            score += 1
        elif row_role in SERVICE_ROLES:
            component_scores["row_role_score"] = -8
            score -= 8

        explicit_signal_score = score
        sequential_score = self._sequential_score(stage, previous_context)
        if sequential_score < 0 and explicit_signal_score >= 8:
            sequential_score = 0
        if sequential_score:
            component_scores["sequential_score"] = sequential_score
            score += sequential_score
            if match_type == StageMatchType.UNMATCHED.value and sequential_score > 0:
                match_type = StageMatchType.SEQUENTIAL_CONTEXT_BOOST.value

        return StageMatch(
            stage,
            score,
            "low",
            True,
            match_type,
            matched,
            option_match[0] if option_match else None,
            review_reason=None,
            occurrence_label=occurrence_label,
            score_breakdown=component_scores,
            normalized_row_role=row_role,
        )

    def _stage_score_json(
        self,
        scored: list[StageMatch],
        best: StageMatch,
        second_score: int,
        delta: int,
        reason: str | None,
        needs_review: bool,
    ) -> dict[str, Any]:
        return {
            "candidate_scores": [
                {
                    "work_stage_number": item.stage.get("number") if item.stage else None,
                    "work_stage_title": item.stage.get("title") if item.stage else None,
                    "canonical_stage_id": item.stage.get("canonical_stage_id") if item.stage else None,
                    "stage_role": item.stage.get("stage_role") if item.stage else None,
                    "score": item.score,
                    "match_type": item.match_type,
                    "matched_terms": item.matched_terms,
                    "score_components": item.score_breakdown,
                }
                for item in scored[:10]
            ],
            "winner": {
                "work_stage_number": best.stage.get("number") if best.stage else None,
                "work_stage_title": best.stage.get("title") if best.stage else None,
                "score": best.score,
                "second_score": second_score,
                "match_type": best.match_type,
            },
            "thresholds": self.thresholds,
            "delta_top_1_top_2": delta,
            "needs_review": needs_review,
            "reason": reason,
        }

    def _canonical_title(self, canonical_stage_id: Any) -> str:
        if not canonical_stage_id:
            return ""
        canonical = ((self.payload.get("project_hierarchy") or {}).get("canonical_stages") or {}).get(str(canonical_stage_id))
        if isinstance(canonical, dict):
            return str(canonical.get("title") or "")
        return ""

    def _resolve_occurrence_label(
        self,
        stage: dict[str, Any] | None,
        text: str,
        previous_context: dict[str, Any] | None,
    ) -> str | None:
        if stage and stage.get("occurrence_label"):
            return str(stage.get("occurrence_label"))
        for source in (stage.get("title") if stage else "", text):
            label = _occurrence_from_text(str(source or ""))
            if label:
                return label
        if previous_context and previous_context.get("stage_occurrence_label"):
            return str(previous_context.get("stage_occurrence_label"))
        return None

    def _best_option(
        self,
        stage: dict[str, Any],
        text: str,
        global_section: str | None,
        global_subtype: str | None,
    ) -> tuple[dict[str, Any], int, list[str]] | None:
        best: tuple[dict[str, Any], int, list[str]] | None = None
        tokens = text.split()
        for option in stage.get("stage_options") or []:
            if not isinstance(option, dict):
                continue
            terms = _important_terms(option.get("title"))
            matches = _match_terms(terms, text, tokens)
            score = 0
            if normalize_text(option.get("title")) and normalize_text(option.get("title")) in text:
                score += 8
            elif matches:
                score += len(matches) * 5
            if self._work_type_matches(option, global_section, global_subtype):
                score += 12
                matches.append(_work_type_code(option))
            if score > 0 and (best is None or score > best[1]):
                best = (option, score, matches)
        return best

    def _sequential_score(self, stage: dict[str, Any], previous_context: dict[str, Any] | None) -> int:
        if not previous_context or not previous_context.get("work_stage_number"):
            return 0
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
        penalty = int(self.sequential_policy.get("far_stage_penalty", -2))
        if current > previous + 3:
            penalty += int(self.sequential_policy.get("stage_order_jump_penalty", -3))
        return penalty

    def _stage_order(self, number: Any) -> int | None:
        try:
            return int(str(number).split(".")[-1])
        except (TypeError, ValueError):
            return None

    def _stage_by_number(self, stages: list[dict[str, Any]], number: str) -> dict[str, Any] | None:
        return next((stage for stage in stages if str(stage.get("number") or "") == number), None)

    def _option_by_id(self, stage: dict[str, Any], option_id: Any) -> dict[str, Any] | None:
        if not option_id:
            return None
        for option in stage.get("stage_options") or []:
            if str(option.get("id") or option.get("number") or "") == str(option_id):
                return option
        return None

    def _work_type_matches(self, ref: dict[str, Any], section_id: str | None, subtype_id: str | None) -> bool:
        if not ref or not section_id:
            return False
        if ref.get("section_id") != section_id:
            return False
        return not ref.get("subtype_id") or ref.get("subtype_id") == subtype_id


def _important_terms(value: Any) -> list[str]:
    tokens = [
        token
        for token in normalize_text(value).split()
        if len(token) > 3
        and token
        not in {
            "работы",
            "работ",
            "устройство",
            "монтаж",
            "если",
            "есть",
            "при",
            "наличии",
            "необходимости",
        }
    ]
    terms = list(dict.fromkeys(tokens))
    normalized = normalize_text(value)
    if normalized:
        terms.append(normalized)
    return terms


def _work_type_code(ref: dict[str, Any]) -> str:
    return f"{ref.get('section_id')}/{ref.get('subtype_id')}"


def _occurrence_from_text(value: str) -> str | None:
    source = normalize_text(value)
    if not source:
        return None
    for pattern, template in OCCURRENCE_PATTERNS:
        match = pattern.search(source)
        if not match:
            continue
        if "{N}" in template:
            return template.replace("{N}", match.group(1))
        return template
    return None
