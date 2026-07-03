"""Shared text-context rules used by taxonomy classification and rate selection."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.work_rate_import_service import normalize_name


@dataclass(slots=True)
class MasonryContextResult:
    context_code: str | None
    needs_review: bool = False
    review_reason: str | None = None
    applicability: dict[str, str] | None = None


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


def resolve_roof_covering_context(text: str) -> MasonryContextResult:
    """Resolve roof-covering material context before generic roof installation rates."""
    normalized = normalize_name(text)
    has_metal_tile = has_any(normalized, ("металлочерепиц", "металлическ черепиц"))
    has_flexible_shingles = has_any(
        normalized,
        (
            "гибк черепиц",
            "битумн черепиц",
            "мягк черепиц",
            "мягк кровл",
        ),
    )
    if has_metal_tile and has_flexible_shingles:
        return MasonryContextResult(None, True, "roof_covering_material_conflict")
    if has_metal_tile:
        return MasonryContextResult(
            "metal_tile",
            applicability={
                "roof_covering_material": "metal_tile",
                "base_type": "sparse_batten",
            },
        )
    if has_flexible_shingles:
        return MasonryContextResult(
            "flexible_shingles",
            applicability={
                "roof_covering_material": "flexible_shingles",
                "base_type": "solid_deck",
            },
        )
    return MasonryContextResult(None, True, "roof_covering_material_not_resolved")


def resolve_insulation_context(text: str) -> MasonryContextResult:
    """Resolve insulation location/material dimensions before scoring."""
    normalized = normalize_name(text)
    applicability: dict[str, str] = {}
    if has_any(normalized, ("минват", "минераловат", "каменн ват", "базальтов")):
        applicability["insulation_material"] = "mineral_wool"
    elif has_any(normalized, ("эппс", "xps", "экструдирован")):
        applicability["insulation_material"] = "xps"
    elif has_any(normalized, ("пенополистирол", "ппс", "eps")):
        applicability["insulation_material"] = "eps"
    elif has_any(normalized, ("ппу", "пенополиуретан")):
        applicability["insulation_material"] = "polyurethane_foam"

    if has_any(normalized, ("фасад", "наружн", "кирпичн стен")):
        applicability["insulation_location"] = "facade"
    elif has_any(normalized, ("цокол", "фундамент", "подземн стен")):
        applicability["insulation_location"] = "foundation_wall"
    elif has_any(normalized, ("под плит", "под фундаментн", "под ушп")):
        applicability["insulation_location"] = "under_slab"
    elif has_any(normalized, ("кровл", "стропил", "чердак", "мансард")):
        applicability["insulation_location"] = "roof"
    elif has_any(normalized, ("внутренн стен", "изнутри", "со стороны помещения")):
        applicability["insulation_location"] = "internal_wall"

    return MasonryContextResult(
        "_".join(
            value
            for value in (
                applicability.get("insulation_location"),
                applicability.get("insulation_material"),
            )
            if value
        ) or None,
        applicability=applicability or None,
    )


def resolve_roof_structure_context(text: str) -> MasonryContextResult:
    normalized = normalize_name(text)
    if has_any(normalized, ("лстк", "легк стальн", "тонкостенн")):
        return MasonryContextResult(
            "light_gauge_steel",
            applicability={"roof_structure_material": "light_gauge_steel"},
        )
    if has_any(normalized, ("дерев", "пиломат", "брус", "дос")):
        return MasonryContextResult(
            "timber",
            applicability={"roof_structure_material": "timber"},
        )
    if has_any(normalized, ("клеен", "glulam")):
        return MasonryContextResult(
            "glulam",
            applicability={"roof_structure_material": "glulam"},
        )
    return MasonryContextResult(None, True, "roof_structure_material_not_resolved")


def resolve_membrane_context(text: str) -> MasonryContextResult:
    normalized = normalize_name(text)
    has_vapor = has_any(normalized, ("пароизоляц", "пароизоляцион"))
    has_wind_waterproof = has_any(normalized, ("гидроветр", "ветрозащит", "ветро", "диффузион", "мембран"))
    applicability: dict[str, str] = {}
    if has_vapor and has_wind_waterproof:
        applicability["membrane_type"] = "combined_membrane"
    elif has_vapor:
        applicability["membrane_type"] = "vapor_barrier"
    elif has_wind_waterproof:
        applicability["membrane_type"] = "wind_waterproof_membrane"

    if has_any(normalized, ("со стороны помещения", "внутренн")):
        applicability["installation_position"] = "interior_side"
    elif has_any(normalized, ("кровл", "скатн", "чердак", "мансард", "стропил")):
        applicability["installation_position"] = "roof_assembly"
    elif has_any(normalized, ("наружн", "снаружи")):
        applicability["installation_position"] = "exterior_side"

    context_code = "_".join(
        value
        for value in (
            applicability.get("membrane_type"),
            applicability.get("installation_position"),
        )
        if value
    ) or None
    return MasonryContextResult(
        context_code,
        needs_review=not bool(context_code),
        review_reason=None if context_code else "membrane_context_not_resolved",
        applicability=applicability or None,
    )
