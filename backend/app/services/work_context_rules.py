"""Shared text-context rules used by taxonomy classification and rate selection."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.work_rate_import_service import normalize_name


@dataclass(slots=True)
class MasonryContextResult:
    context_code: str | None
    needs_review: bool = False
    review_reason: str | None = None


def has_any(text: str, fragments: tuple[str, ...]) -> bool:
    return any(fragment in text for fragment in fragments)


def build_rate_context_text(
    *,
    work_name: str | None = None,
    item_text: str | None = None,
    spec: str | None = None,
    section_title: str | None = None,
    section_description: str | None = None,
    section_parent_context: str | None = None,
) -> tuple[str, str, str]:
    """Build the canonical work, section and combined context text."""
    work_text = normalize_name(" ".join(
        value for value in (work_name, item_text, spec) if value
    ))
    section_context_text = normalize_name(" ".join(
        value for value in (
            section_title,
            section_description,
            section_parent_context,
        ) if value
    ))
    source_context_text = normalize_name(" ".join(
        value for value in (work_text, section_context_text) if value
    ))
    return work_text, section_context_text, source_context_text


def has_internal_wall_insulation_exception(text: str) -> bool:
    return has_any(
        normalize_name(text),
        (
            "утепление стен изнутри",
            "утепление изнутри",
            "внутреннее утепление стен",
            "утепление внутренней поверхности стен",
            "теплоизоляция стен со стороны помещения",
        ),
    )


def resolve_special_masonry_operation(
    work_text: str,
    section_context_text: str,
) -> str | None:
    """Resolve special masonry before the generic brick_masonry operation."""
    if (
        has_any(work_text, ("облицовочн", "лицев"))
        and has_any(work_text, ("фасад",))
        and has_any(work_text, ("кирпич", "кладк"))
    ):
        return "facade_cladding"
    if (
        has_any(work_text, ("облицовочн", "лицев"))
        and has_any(work_text, ("кирпич", "кладк"))
        and has_any(section_context_text, ("фасад",))
    ):
        return "facade_cladding"
    if (
        has_any(work_text, ("столб", "колонн"))
        and has_any(work_text, ("кирпич", "кладк"))
    ):
        return "brick_pillar_masonry"
    if has_any(work_text, ("армопояс", "армированн пояс")):
        return "arm_belt_masonry"
    if has_any(
        work_text,
        ("вентканал", "вентиляционн канал", "вентиляционн шахт"),
    ):
        return "vent_shaft_masonry"
    return None


def resolve_masonry_context(text: str) -> MasonryContextResult:
    """Resolve wall-rate context; frame infill intentionally precedes conflict."""
    normalized = normalize_name(text)
    has_frame_infill = "заполнен" in normalized and "каркас" in normalized
    has_exterior = "наружн" in normalized
    has_interior = "внутренн" in normalized

    if has_frame_infill:
        return MasonryContextResult("frame_infill")
    if has_exterior and has_interior:
        return MasonryContextResult(None, True, "masonry_location_conflict")
    if has_exterior:
        return MasonryContextResult("exterior_wall")
    if has_interior:
        return MasonryContextResult("interior_wall")
    return MasonryContextResult(None, True, "masonry_location_not_resolved")
