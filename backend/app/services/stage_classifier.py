"""Rule-based work_stage classifier for project_hierarchy v6.4."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.services.work_taxonomy_service import (
    PROMPT_VERSION,
    UNKNOWN_SUBTYPE_CODE,
    ClassificationResult,
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

EARLY_INHERIT_ROLES = {"material", "mechanism", "labor", "logistics", "overhead"}
CONDITIONAL_INHERIT_ROLES = {"unknown"}
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

_DEMOLITION_ACTION_TOKENS = {
    "демонтаж", "демотаж", "демонтажные", "демонтировать", "демонтируем",
    "демонтируется", "разборка", "разобрать", "снятие", "снять",
    "удаление", "удалить",
}
_GENERIC_STAGE_OPTION_TERMS = {
    "армирование",
    "демонтаж",
    "изготовление",
    "монтаж",
    "окраска",
    "опалубка",
    "подготовка",
    "разборка",
    "снятие",
    "установка",
    "усиление",
    "устройство",
    "шпаклевка",
    "шпатлевка",
}
_FINISHING_STAGE_GENERIC_SUBTYPES = {"surface_preparation"}
_FINISHING_STAGE_COMPATIBLE_SUBTYPES = {
    "commercial_wall_floor_finishes",
    "floor_coverings",
    "painting",
    "plastering",
    "putty_primer",
    "surface_preparation",
    "tile_laying",
    "wallpaper",
}
_WINDOW_COVERING_STAGE_COMPATIBLE_SUBTYPES = {"window_coverings_blinds_curtains"}
_ROOFING_ROLL_MATERIAL_TERMS = {"рулонная"}

_PREPARATION_ACTION_RE = re.compile(
    r"\b(?:подметан\w*|обеспылив\w*|грунтов\w*|подготов\w*|"
    r"выравнив\w*|очист\w*|ремонт\w*)\b",
    re.IGNORECASE,
)
_ELECTRICAL_ACTION_RE = re.compile(
    r"\b(?:подключ\w*|монтаж\w*|установ\w*|проклад\w*|затяж\w*|"
    r"прозвон\w*|устройств\w*)\b",
    re.IGNORECASE,
)
_CONSTRUCTIVE_OPENING_ACTION_RE = re.compile(
    r"\b(?:усилен\w*|устройств\w*|монтаж\w*|установ\w*|закладн\w*|"
    r"обрамлен\w*|оформлен\w*|откос\w*)\b",
    re.IGNORECASE,
)


def _has_demolition_action(text: str) -> bool:
    normalized = normalize_text(text)
    tokens = set(normalized.split())
    return bool(tokens & _DEMOLITION_ACTION_TOKENS)


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _row_object_intents(text: str) -> set[str]:
    """Return high-confidence physical object/action intents for hard gates.

    Intents are deliberately physical/action based. They are used only when
    the row itself contains enough evidence; generic subtype compatibility is
    not treated as an object intent.
    """
    normalized = normalize_text(text)
    intents: set[str] = set()

    demolition = _has_demolition_action(normalized)
    if demolition:
        intents.add("demolition")

    has_floor = bool(re.search(r"\bпол(?:а|у|ом|е|ы)?\b", normalized)) or _has_any(normalized, (
        "напольн", "стяжк", "линоле", "ламинат", "паркет", "инженерн дос",
        "инжинерн дос", "массивн дос", "фанер", "плинтус", "порож",
        "шумоизоляц пола", "звукоизоляц пола", "зипс на пол",
    )) or bool(re.search(r"\b(?:osb|осп)\b", normalized))
    has_wall = _has_any(normalized, ("стен", "перегород"))
    has_ceiling = "потол" in normalized
    has_door = bool(_match_terms(
        ["дверь", "наличник", "добор"], normalized, normalized.split()
    ))
    has_window = bool(_match_terms(
        ["окно", "оконный блок", "остекление", "стеклопакет", "подоконник", "оконный откос", "оконный отлив"],
        normalized,
        normalized.split(),
    ))
    has_hatch = bool(_match_terms(
        ["люк-невидимка", "люк-неведимка", "ревизионный люк", "технический люк"],
        normalized,
        normalized.split(),
    ))
    has_opening = has_door or has_window or has_hatch or _has_any(normalized, ("проем", "проём"))

    if has_floor:
        intents.add("floor")
        if _has_any(normalized, ("наливн", "самовыравнив", "стяжк", "основани пола")):
            intents.add("floor_base")
        if _has_any(normalized, (
            "линоле", "ламинат", "ковролин", "паркет", "инженерн дос", "инжинерн дос",
            "массивн дос", "напольн покрыт", "плинтус", "порож", "фанер", "резинов плит",
            "напольн плит",
        )) or bool(re.search(r"\b(?:osb|осп)\b", normalized)):
            intents.add("floor_finish")
        if _PREPARATION_ACTION_RE.search(normalized):
            intents.add("floor_base")

    if has_wall:
        intents.add("wall")
        if not demolition and _has_any(normalized, (
            "теплоизоляц", "пароизоляц", "утеплен", "минеральн ват",
        )):
            intents.add("wall_insulation")
        if not demolition and _has_any(normalized, (
            "штукатур", "шпаклев", "шпатлев", "грунтов", "выравнив", "подготовк стен",
        )):
            intents.add("wall_preparation")
        if not demolition and _has_any(normalized, (
            "окраск", "покраск", "обои", "настенн плит", "облицовк стен", "керамическ плит", "панел", "декоративн отделк",
        )):
            intents.add("wall_finishing")
    if has_ceiling:
        intents.add("ceiling")
        if not demolition and _has_any(normalized, (
            "армстронг", "грильято", "реечн", "натяжн", "подвесн", "гкл", "вгкл",
            "каркас потол", "обшивк потол",
        )) and _has_any(normalized, ("монтаж", "устройств", "обшивк", "установ")):
            intents.add("ceiling_system")
        if not demolition and _has_any(normalized, (
            "штукатур", "шпаклев", "шпатлев", "грунтов", "выравнив", "окраск", "покраск",
        )):
            intents.add("ceiling_preparation")
    if has_opening:
        intents.add("opening")
        if _CONSTRUCTIVE_OPENING_ACTION_RE.search(normalized) and not demolition:
            intents.add("constructive_opening")
    if has_door and not demolition and _has_any(normalized, ("монтаж", "установ", "добор", "наличник")):
        intents.add("door_installation")
    if has_window and not demolition:
        intents.add("window_installation")
    if has_hatch and not demolition:
        intents.add("technical_hatch")

    tile_match = bool(re.search(r"\b(?:плитк|плиточн)\w*", normalized))
    if not demolition and tile_match:
        intents.add("tile_work")
        if has_wall:
            intents.add("wall_finishing")
        if has_floor or "напольн" in normalized:
            intents.add("floor_finish")

    if not demolition and _match_terms(["швы ГКЛ"], normalized, normalized.split()) and _has_any(
        normalized, ("заделк", "шпаклев", "армирован", "грунтов", "шлифов")
    ):
        intents.add("gkl_surface_finish")

    if not demolition and "перегород" in normalized and _has_any(normalized, (
        "возведен", "кладк", "устройств", "монтаж", "обшивк", "каркас",
    )):
        intents.add("new_partition")
    if not demolition and _has_any(normalized, (
        "короб из гкл", "короба из гкл", "гкл короб", "вгкл короб",
    )):
        intents.add("gkl_box")
        intents.add("ceiling_system")

    if _has_any(normalized, ("шумоизоляц", "звукоизоляц", "зипс")):
        intents.add("sound_insulation")
        if has_floor:
            intents.add("sound_floor")
        elif has_ceiling:
            intents.add("sound_ceiling")
        elif "нов" in normalized and "перегород" in normalized:
            intents.add("sound_new_partition")
        elif has_wall:
            intents.add("sound_wall")

    low_voltage_terms = (
        "интернет", "кабеля интернет", "кабеля tv", "tv", "телевид", "скс", "слаботоч", "витая пара", "utp", "ftp",
        "видеонаблюден", "камера", "пожарн сигнал", "оповещен", "скуд", "контрол доступ",
        "домофон", "звонков связ", "охранн сигнал",
    )
    if _has_any(normalized, low_voltage_terms):
        intents.add("low_voltage")

    electrical_objects = (
        "светильник", "люстр", "трек", "шинопровод", "led", "выключател",
        "розет", "подрозет", "кабел", "провод", "гофр", "щит", "автомат",
        "узо", "электроточ", "лотк", "контактор", "электрощит",
        "распределительн панел", "регулятор теплого пола",
    )
    if _match_terms(list(electrical_objects), normalized, normalized.split()) and _ELECTRICAL_ACTION_RE.search(normalized):
        intents.add("electrical_installation")
    if _has_any(normalized, ("светильник", "люстр", "трек", "шинопровод", "led", "бра", "прожектор", "софит")):
        intents.add("lighting_equipment")
    if _has_any(normalized, ("кабел", "провод", "гофр", "кабельн канал", "лоток", "лотк")) or (
        "труб" in normalized and _has_any(normalized, ("электр", "кабел", "провод", "гофр"))
    ):
        intents.add("electrical_distribution")

    if _match_terms([
        "электрический теплый пол", "электрический тёплый пол", "нагревательный мат",
        "регулятор теплого пола", "терморегулятор теплого пола",
    ], normalized, normalized.split()):
        intents.add("electric_heated_floor")

    appliance_objects = (
        "стиральн машин", "посудомоечн", "электроплит", "электрическ плит",
        "водонагревател", "бойлер", "кухонн вытяж", "оборудован", "инвентар",
    )
    if _match_terms(list(appliance_objects), normalized, normalized.split()):
        intents.add("equipment")

    plumbing_objects = (
        "водопровод", "труб ppr", "трубы ppr", "хвс", "гвс", "канализац",
        "смесител", "раковин", "душев", "унитаз", "трап", "гидролок", "ванн",
        "полотенцесушител", "санитарн прибор", "биде", "умывальник",
        "гребенка", "гребёнка", "узел воды", "расчеканка труб",
    )
    plumbing_match = bool(_match_terms(list(plumbing_objects), normalized, normalized.split()))
    generic_pipe_match = bool(_match_terms(["труба"], normalized, normalized.split())) and not _has_any(
        normalized, ("кабель", "провод", "электр", "гофр")
    )
    if plumbing_match or generic_pipe_match or (
        _match_terms(["кран"], normalized, normalized.split())
        and _match_terms(["шаровой"], normalized, normalized.split())
    ):
        intents.add("plumbing_installation")
    if "гидролок" in normalized:
        if _has_any(normalized, ("подключ", "расключ")):
            intents.add("hydrolock_electrical")
        elif _has_any(normalized, ("монтаж", "установ")):
            intents.add("hydrolock_water")
    if "трап" in normalized or "канализац" in normalized:
        intents.add("floor_drainage")

    if _has_any(normalized, ("воздуховод", "вентиляц", "вентилятор", "кондиционер", "сплит систем")):
        intents.add("hvac_installation")
    if _has_any(normalized, ("радиатор", "конвектор", "стояк отоплен", "терморегулятор", "отоплен", "полотенцесушител")):
        intents.add("heating_installation")

    if _has_any(normalized, (
        "жалюзи", "рулонн штор", "римск штор", "светофильтр",
        "солнцезащитн", "карниз штор",
    )):
        intents.add("blinds_curtains")
        if _has_any(normalized, ("электропривод", "подключ", "автоматик")):
            intents.add("blinds_electrical")

    if _has_any(normalized, (
        "монтаж откосов пвх", "оконн откос", "дверн откос", "подоконник",
        "оконн отлив", "отлив окон",
    )):
        intents.add("window_slopes")

    if _has_any(normalized, (
        "разгрузк материал", "разгрузк и погрузк", "разгрузк инструмент", "доставк материал",
        "погрузк материал", "вынос мусор", "вывоз мусор", "контейнер для мусор",
        "контейнер для вывоз", "финальн уборк", "финишн уборк", "дезинфекц",
    )):
        intents.add("logistics_cleanup")
    if _has_any(normalized, (
        "укрытие пленк", "укрытие плёнк", "защита существующ отделк",
        "укрытие мебел", "защита мебел", "перекрытие доступа",
    )):
        intents.add("site_protection")

    if _has_any(normalized, (
        "штроблен", "устройство штроб", "штроба в", "бурение сквозн отверст",
        "отверстие для электроточ", "отверсти для электроточ", "устройство ниш", "ниша в бетон",
        "ниша в кирпич", "ниша в газоблок",
    )) and not _has_any(normalized, ("без штроб", "готовой штроб", "готовую штроб")):
        intents.add("chasing_drilling")

    if _has_any(normalized, ("защитн угол", "поручн", "антивандальн", "отбойн дос", "защитн экран")):
        intents.add("protective_elements")
    if _has_any(normalized, ("пусконалад", "пнр", "испытан", "наладк систем")):
        intents.add("commissioning")

    # Generic ceiling intent is kept for branch 6.2 compatibility. More
    # specific ceiling_system/ceiling_preparation intents take precedence in 6.4.
    if has_ceiling and not ({"lighting_equipment", "blinds_curtains", "demolition"} & intents):
        intents.add("ceiling_finishing")
    return intents


def _stage_object_intents(stage: dict[str, Any]) -> set[str]:
    title = normalize_text(stage.get("title"))
    number = str(stage.get("number") or "")
    intents: set[str] = set()
    if "демонтаж" in title:
        intents.add("demolition")

    # Commercial renovation 6.2.
    if number == "6.2.2":
        intents.add("structural_demolition")
    if number == "6.2.3":
        intents.add("engineering_demolition")
    if number in {"6.2.6", "6.2.13"}:
        intents.add("floor_finish" if number == "6.2.13" else "floor_base")
    if number in {"6.2.4", "6.2.5", "6.2.14"}:
        intents.add("wall")
    if number == "6.2.7":
        intents.add("ceiling")
    if number == "6.2.8":
        intents.add("electrical_installation")
    if number == "6.2.16":
        intents.add("lighting_equipment")
    if number == "6.2.12":
        intents.add("plumbing_installation")
    if number == "6.2.17":
        intents.add("blinds_curtains")
    if number == "6.2.19":
        intents.add("logistics_cleanup")
    if number == "6.2.1":
        intents.add("site_protection")
    if number == "6.2.21":
        intents.add("chasing_drilling")

    # Public/social commercial renovation 6.4.
    stage_64_intents = {
        "6.4.1": {"site_protection"},
        "6.4.2": {"structural_demolition"},
        "6.4.3": {"wall_demolition"},
        "6.4.4": {"engineering_demolition"},
        "6.4.6": {"new_partition"},
        "6.4.7": {"wall_preparation", "ceiling_preparation"},
        "6.4.8": {"floor_base"},
        "6.4.10": {"ceiling_system", "ceiling", "gkl_box"},
        "6.4.11": {"electrical_installation", "chasing_drilling"},
        "6.4.12": {"lighting_equipment"},
        "6.4.13": {"low_voltage"},
        "6.4.14": {"hvac_installation"},
        "6.4.15": {"heating_installation"},
        "6.4.16": {"plumbing_installation"},
        "6.4.17": {"floor_finish"},
        "6.4.18": {"wall_finishing", "wall_insulation", "gkl_surface_finish"},
        "6.4.19": {"protective_elements"},
        "6.4.20": {"door_installation", "technical_hatch"},
        "6.4.21": {"window_installation", "window_slopes", "blinds_curtains"},
        "6.4.23": {"equipment"},
        "6.4.24": {"commissioning"},
        "6.4.25": {"logistics_cleanup"},
    }
    intents.update(stage_64_intents.get(number, set()))

    # Title-based fallback for other variants.
    if _has_any(title, ("стяж", "основани")) and _has_any(title, ("пол", "пола")):
        intents.add("floor_base")
    if _has_any(title, ("напольн покрыт", "плинтус", "порожк")):
        intents.add("floor_finish")
    if _has_any(title, ("стен", "перегород", "мокрых зон")):
        intents.add("wall")
    if "потол" in title:
        intents.add("ceiling")
    if _has_any(title, ("двер", "окон", "проем", "проём", "люк", "стеклян")):
        intents.add("opening")
    if "электромонтаж" in title:
        intents.add("electrical_installation")
    if "осветительн оборудован" in title or "монтаж освещен" in title:
        intents.add("lighting_equipment")
    if _has_any(title, ("мебел", "бытов", "технологическ оборудован")):
        intents.add("equipment")
    if _has_any(title, ("сантехническ", "водоснабжен", "канализац")):
        intents.add("plumbing_installation")
    return intents


def _object_priority_adjustment(stage: dict[str, Any], text: str) -> tuple[int, list[str]]:
    row_intents = _row_object_intents(text)
    if not row_intents:
        return 0, []
    stage_intents = _stage_object_intents(stage)
    score = 0
    reasons: list[str] = []

    def add(value: int, reason: str) -> None:
        nonlocal score
        score += value
        reasons.append(reason)

    for intent, boost in (
        ("floor_base", 14), ("floor_finish", 14), ("wall", 8),
        ("wall_preparation", 14), ("wall_finishing", 14), ("wall_insulation", 16),
        ("tile_work", 14), ("gkl_surface_finish", 16),
        ("ceiling", 10), ("ceiling_system", 18), ("ceiling_preparation", 16), ("gkl_box", 20),
        ("opening", 12), ("door_installation", 18), ("window_installation", 18),
        ("window_slopes", 18), ("technical_hatch", 18), ("new_partition", 18),
        ("electrical_installation", 16), ("lighting_equipment", 18),
        ("low_voltage", 20), ("equipment", 12), ("plumbing_installation", 16),
        ("hvac_installation", 16), ("heating_installation", 16),
        ("blinds_curtains", 18), ("logistics_cleanup", 20),
        ("site_protection", 18), ("chasing_drilling", 20),
        ("protective_elements", 16), ("commissioning", 18),
    ):
        if intent in row_intents and intent in stage_intents:
            add(boost, f"{intent}_object_match")
    return score, reasons


def _stage_object_gate(
    stage: dict[str, Any],
    text: str,
    global_section: str | None,
    global_subtype: str | None,
) -> tuple[bool, list[str]]:
    """Hard-exclude a stage whose physical object/action contradicts the row."""
    intents = _row_object_intents(text)
    number = str(stage.get("number") or "")
    reasons: list[str] = []

    def reject(reason: str) -> tuple[bool, list[str]]:
        return False, [reason]

    demolition_subtype = str(global_subtype or "")
    structural_demolition = demolition_subtype in {
        "ceiling_demolition", "wall_demolition", "floor_demolition",
        "general_structural_demolition", "openings_diamond_cutting",
    }
    engineering_demolition = demolition_subtype in {
        "plumbing_demolition", "electrical_demolition", "hvac_demolition",
    }

    if number.startswith("6.2."):
        # Explicit logistics/protection intent wins over quoted descriptions of
        # the source work (for example «вынос мусора после демонтажа стен»).
        if "logistics_cleanup" in intents:
            if number != "6.2.19":
                return reject("logistics_cleanup_requires_stage_6_2_19")
            return True, reasons
        if "site_protection" in intents:
            if number != "6.2.1":
                return reject("site_protection_requires_stage_6_2_1")
            return True, reasons

        if "demolition" in intents:
            if number not in {"6.2.2", "6.2.3"}:
                return reject("demolition_action_excludes_new_work_stage")
            if number == "6.2.2" and engineering_demolition:
                return reject("engineering_demolition_excludes_structural_demolition_stage")
            if number == "6.2.3" and structural_demolition:
                return reject("structural_demolition_excludes_engineering_demolition_stage")
        elif number in {"6.2.2", "6.2.3"}:
            return reject("non_demolition_row_excludes_demolition_stage")

        if "chasing_drilling" in intents and number != "6.2.21":
            return reject("chasing_drilling_requires_stage_6_2_21")
        if "lighting_equipment" in intents:
            target = "6.2.8" if "electrical_distribution" in intents else "6.2.16"
            if number != target:
                return reject(f"lighting_equipment_requires_stage_{target.replace('.', '_')}")
        if "hydrolock_electrical" in intents and number != "6.2.8":
            return reject("hydrolock_electrical_requires_stage_6_2_8")
        if "hydrolock_water" in intents and number != "6.2.12":
            return reject("hydrolock_water_requires_stage_6_2_12")
        if "window_slopes" in intents and number != "6.2.15":
            return reject("window_slopes_require_stage_6_2_15")
        if "blinds_curtains" in intents:
            allowed = {"6.2.17"}
            if "blinds_electrical" in intents:
                allowed.add("6.2.8")
            if number not in allowed:
                return reject("blinds_curtains_stage_conflict")
        if "sound_floor" in intents and number != "6.2.6":
            return reject("floor_sound_insulation_requires_stage_6_2_6")
        if "sound_ceiling" in intents and number != "6.2.7":
            return reject("ceiling_sound_insulation_requires_stage_6_2_7")
        if "sound_wall" in intents and number != "6.2.5":
            return reject("wall_sound_insulation_requires_stage_6_2_5")
        if "sound_new_partition" in intents and number != "6.2.4":
            return reject("partition_sound_insulation_requires_stage_6_2_4")
        if "ceiling_finishing" in intents and "demolition" not in intents and number != "6.2.7":
            return reject("ceiling_finishing_requires_stage_6_2_7")

        if "floor" in intents:
            if number in {"6.2.15", "6.2.10", "6.2.17"}:
                return reject("floor_object_excludes_unrelated_stage")
            if number in {"6.2.8", "6.2.16"} and "electric_heated_floor" not in intents:
                return reject("floor_object_excludes_electrical_stage")
            if number == "6.2.12" and "floor_drainage" not in intents:
                return reject("floor_object_excludes_plumbing_stage")

        if global_section == "windows_doors" and global_subtype == "window_slopes_sills" and number != "6.2.15":
            return reject("window_slopes_subtype_stage_conflict")
        if global_section == "mobilization" and global_subtype == "logistics_cleanup" and number != "6.2.19":
            return reject("logistics_subtype_stage_conflict")
        if global_section == "mobilization" and global_subtype == "site_setup" and "site_protection" in intents and number != "6.2.1":
            return reject("site_setup_protection_stage_conflict")
        if global_section == "reconstruction_works" and global_subtype == "chasing_drilling_niches" and number != "6.2.21":
            return reject("chasing_subtype_stage_conflict")
        return True, reasons

    if number.startswith("6.4."):
        # Logistics and protection override object words quoted in the row.
        if "logistics_cleanup" in intents:
            return (True, reasons) if number == "6.4.25" else reject("logistics_cleanup_requires_stage_6_4_25")
        if "site_protection" in intents:
            return (True, reasons) if number == "6.4.1" else reject("site_protection_requires_stage_6_4_1")

        demolition_types = {
            "ceiling_demolition", "wall_demolition", "floor_demolition",
            "general_structural_demolition", "openings_diamond_cutting",
            "plumbing_demolition", "electrical_demolition", "hvac_demolition",
        }
        if "demolition" in intents or demolition_subtype in demolition_types:
            old_wall_covering = _has_any(text, (
                "старых обоев", "старые обои", "краск со стен", "краски со стен",
                "побелк со стен", "настенн плит", "штукатурк со стен",
            ))
            if engineering_demolition:
                target = "6.4.4"
            elif demolition_subtype in {"wall_demolition", "openings_diamond_cutting"} and not old_wall_covering:
                target = "6.4.3"
            else:
                target = "6.4.2"
            return (True, reasons) if number == target else reject(
                f"demolition_object_requires_stage_{target.replace('.', '_')}"
            )
        if number in {"6.4.2", "6.4.3", "6.4.4"}:
            return reject("non_demolition_row_excludes_demolition_stage_6_4")

        if (
            "tile_work" in intents
            and not ({"floor_finish", "wall_finishing"} & intents)
            and not ({"technical_hatch", "door_installation", "window_installation", "window_slopes"} & intents)
        ):
            if number not in {"6.4.17", "6.4.18"}:
                return reject("generic_tile_work_requires_floor_or_wall_finish_stage")

        # Explicit action/object routes. Ordering is intentional: a light or
        # low-voltage row is also electrical, and a window slope is also a wall.
        target_by_intent: tuple[tuple[str, str], ...] = (
            ("low_voltage", "6.4.13"),
            ("lighting_equipment", "6.4.12"),
            ("hydrolock_electrical", "6.4.11"),
            ("hydrolock_water", "6.4.16"),
            ("window_slopes", "6.4.21"),
            ("window_installation", "6.4.21"),
            ("blinds_curtains", "6.4.21"),
            ("door_installation", "6.4.20"),
            ("technical_hatch", "6.4.20"),
            ("new_partition", "6.4.6"),
            ("gkl_box", "6.4.10"),
            ("ceiling_system", "6.4.10"),
            ("ceiling_preparation", "6.4.7"),
            ("sound_floor", "6.4.8"),
            ("sound_ceiling", "6.4.10"),
            ("sound_new_partition", "6.4.6"),
            ("sound_wall", "6.4.18"),
            ("chasing_drilling", "6.4.11"),
            ("hvac_installation", "6.4.14"),
            ("heating_installation", "6.4.15"),
            ("plumbing_installation", "6.4.16"),
            ("floor_finish", "6.4.17"),
            ("floor_base", "6.4.8"),
            ("gkl_surface_finish", "6.4.18"),
            ("wall_finishing", "6.4.18"),
            ("wall_insulation", "6.4.18"),
            ("wall_preparation", "6.4.7"),
            ("protective_elements", "6.4.19"),
            ("commissioning", "6.4.24"),
            ("electrical_installation", "6.4.11"),
            ("equipment", "6.4.23"),
        )
        for intent, target in target_by_intent:
            if intent in intents:
                return (True, reasons) if number == target else reject(
                    f"{intent}_requires_stage_{target.replace('.', '_')}"
                )

        # Accepted subtype also constrains the stage when the row text itself
        # is less explicit.
        subtype_targets = {
            ("reconstruction_works", "ceiling_demolition"): "6.4.2",
            ("reconstruction_works", "floor_demolition"): "6.4.2",
            ("reconstruction_works", "general_structural_demolition"): "6.4.2",
            ("reconstruction_works", "wall_demolition"): "6.4.3",
            ("reconstruction_works", "openings_diamond_cutting"): "6.4.3",
            ("reconstruction_works", "plumbing_demolition"): "6.4.4",
            ("reconstruction_works", "electrical_demolition"): "6.4.4",
            ("reconstruction_works", "hvac_demolition"): "6.4.4",
            ("reconstruction_works", "chasing_drilling_niches"): "6.4.11",
            ("insulation", "sound_acoustic_insulation"): "6.4.18",
            ("insulation", "internal_wall_insulation"): "6.4.18",
            ("mobilization", "logistics_cleanup"): "6.4.25",
            ("partitions", "drywall_partitions"): "6.4.6",
            ("partitions", "brick_partitions"): "6.4.6",
            ("partitions", "block_partitions"): "6.4.6",
            ("interior_finishing", "suspended_ceilings"): "6.4.10",
            ("interior_finishing", "gkl_ceilings"): "6.4.10",
            ("interior_finishing", "stretch_ceilings"): "6.4.10",
            ("interior_finishing", "floor_coverings"): "6.4.17",
            ("interior_finishing", "sports_floor_finishes"): "6.4.17",
            ("interior_finishing", "gkl_surface_finishing"): "6.4.18",
            ("windows_doors", "window_slopes_sills"): "6.4.21",
            ("windows_doors", "windows"): "6.4.21",
            ("windows_doors", "interior_doors"): "6.4.20",
            ("windows_doors", "exterior_doors"): "6.4.20",
            ("windows_doors", "fire_doors"): "6.4.20",
            ("windows_doors", "technical_doors_hatches"): "6.4.20",
            ("mep_internal", "structured_cabling"): "6.4.13",
            ("mep_internal", "cctv"): "6.4.13",
            ("mep_internal", "fire_alarm_ops"): "6.4.13",
            ("mep_internal", "access_control"): "6.4.13",
            ("mep_internal", "tv_radio"): "6.4.13",
            ("mep_internal", "sanitary_fixtures"): "6.4.16",
            ("mep_internal", "water_supply"): "6.4.16",
            ("mep_internal", "sewage"): "6.4.16",
            ("mep_internal", "hvac"): "6.4.14",
            ("mep_internal", "heating"): "6.4.15",
            ("mep_internal", "commissioning"): "6.4.24",
        }
        target = subtype_targets.get((str(global_section or ""), str(global_subtype or "")))
        if target and number != target:
            return reject(f"accepted_subtype_requires_stage_{target.replace('.', '_')}")
        return True, reasons

    return True, reasons


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
        context_inherited = self.inherited_from_row_order is not None
        inheritance_reason = None
        if context_inherited:
            inheritance_reason = (
                "overhead_inherits_stage_only"
                if normalized_role == "overhead"
                else f"{normalized_role}_inherits_previous_context"
            )
        data = {
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
            "context_inherited": context_inherited,
            "context_inheritance_reason": inheritance_reason,
            "stage_classification_source": "context_inheritance" if context_inherited else "stage_classifier",
            "work_type_applicable": normalized_role != "overhead",
        }
        if context_inherited:
            data["classification_source"] = "context_inheritance"
            data["operator_review_required"] = False
        return data


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
        global_result: ClassificationResult | None = None,
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
            explicit_stage_context = int(
                stage_match.score_breakdown.get("explicit_stage_evidence_score") or 0
            )
            candidates.append(
                self._candidate_from_ref(
                    primary,
                    "primary_work_type",
                    text,
                    tokens,
                    base_score=1,
                    title=stage.get("title"),
                    stage_context_boost=6 if explicit_stage_context > 0 else 2,
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

        global_result = global_result or classify_work(row_text, row_role="work")
        locked = self._locked_global_work_type(stage, stage_match, global_result)
        if locked is not None:
            return locked
        if global_result.subtype_code and global_result.subtype_code != UNKNOWN_SUBTYPE_CODE:
            section_id, subtype_id = self._split_subtype_code(global_result.subtype_code)
            score = max(0, min(int(global_result.score or 0), 7))
            score += self._estimate_profile_adjustment(estimate_profile_id, section_id, text, tokens)
            candidates.append(
                {
                    "section_id": section_id,
                    "subtype_id": subtype_id,
                    "source": global_result.source or "preclassified",
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
            if previous is None:
                collapsed[key] = candidate
                continue

            previous_score = int(previous.get("score") or 0)
            candidate_score = int(candidate.get("score") or 0)
            if candidate_score > previous_score:
                candidate.setdefault("also_matched_sources", []).append(previous.get("source"))
                if previous.get("source") == "stage_option":
                    candidate["source"] = "stage_option"
                    candidate["stage_option_id"] = previous.get("stage_option_id")
                    candidate["stage_option_title"] = previous.get("stage_option_title")
                    candidate.setdefault("matched_terms", {}).update(previous.get("matched_terms") or {})
                collapsed[key] = candidate
                previous = candidate
            else:
                previous.setdefault("also_matched_sources", []).append(candidate.get("source"))

            # A grouped stage must retain its option identity even when a related
            # or preclassified candidate for the same pair has a slightly higher
            # textual score. The score stays the maximum; only the source/gate
            # metadata is upgraded to stage_option.
            if candidate.get("source") == "stage_option":
                previous["source"] = "stage_option"
                previous["stage_option_id"] = candidate.get("stage_option_id")
                previous["stage_option_title"] = candidate.get("stage_option_title")
                previous.setdefault("matched_terms", {}).update(candidate.get("matched_terms") or {})
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
            section_id=top.get("section_id") if top else None,
            subtype_id=top.get("subtype_id") if top else None,
            confidence=confidence,
            needs_review=needs_review,
            reason=reason,
            source=top.get("source") if top else None,
            stage_option=option,
            score_breakdown=score_json,
        )

    def _locked_global_work_type(
        self,
        stage: dict[str, Any],
        stage_match: StageMatch,
        global_result: ClassificationResult,
    ) -> WorkTypeMatch | None:
        """Keep an accepted subtype when the selected stage explicitly allows it.

        Stage-context candidates may refine ambiguous results, but they must not
        replace a confident subtype with another child of the same grouped stage.
        This was the source of unstable results when a generic option title had a
        slightly higher local score than the already accepted taxonomy result.
        """
        if (
            not global_result
            or global_result.needs_review
            or global_result.subtype_code == UNKNOWN_SUBTYPE_CODE
            or int(global_result.score or 0) < self.thresholds["auto_accept_min_score"]
        ):
            return None

        section_id, subtype_id = self._split_subtype_code(global_result.subtype_code)
        if not section_id or not subtype_id:
            return None

        matching_ref: dict[str, Any] | None = None
        matching_source: str | None = None
        primary = stage.get("primary_work_type") if isinstance(stage.get("primary_work_type"), dict) else {}
        if str(primary.get("section_id") or "") == section_id and str(primary.get("subtype_id") or "") == subtype_id:
            matching_ref = primary
            matching_source = "primary_work_type"

        if matching_ref is None:
            for option in stage.get("stage_options") or []:
                if not isinstance(option, dict):
                    continue
                if str(option.get("section_id") or "") == section_id and str(option.get("subtype_id") or "") == subtype_id:
                    matching_ref = option
                    matching_source = "stage_option"
                    break

        if matching_ref is None:
            for related in stage.get("related_work_types") or []:
                if not isinstance(related, dict):
                    continue
                if str(related.get("section_id") or "") == section_id and str(related.get("subtype_id") or "") == subtype_id:
                    matching_ref = related
                    matching_source = "related_work_type"
                    break

        if (
            matching_source == "related_work_type"
            and int(stage_match.score_breakdown.get("explicit_stage_evidence_score") or 0) > 0
            and subtype_id in {"electrical"}
        ):
            # Only a generic shared subtype may be refined by a more explicit
            # stage (the main example is electrical -> commissioning/PNR).
            # Specific accepted object subtypes such as hvac_demolition,
            # window_slopes_sills or stretch_ceilings must stay locked even
            # when they are listed as related_work_type for the target stage.
            return None

        if matching_ref is None:
            return None

        option = matching_ref if matching_source == "stage_option" else None
        score = int(global_result.score or 0)
        return WorkTypeMatch(
            section_id=section_id,
            subtype_id=subtype_id,
            confidence=global_result.confidence or "high",
            needs_review=False,
            reason=None,
            source="preclassified_locked",
            stage_option=option,
            score_breakdown={
                "candidate_scores": [
                    {
                        "section_id": section_id,
                        "subtype_id": subtype_id,
                        "source": "preclassified_locked",
                        "score": score,
                        "original_source": global_result.source,
                        "stage_reference_source": matching_source,
                    }
                ],
                "winner": {
                    "section_id": section_id,
                    "subtype_id": subtype_id,
                    "source": "preclassified_locked",
                    "score": score,
                },
                "thresholds": self.thresholds,
                "delta_top_1_top_2": score,
                "stage_context": {
                    "work_stage_number": stage.get("number"),
                    "stage_options_mode": stage.get("stage_options_mode") or "none",
                    "stage_role": str(stage.get("stage_role") or "work"),
                },
                "needs_review": False,
                "reason": "confident_preclassified_subtype_preserved",
            },
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
        global_result: ClassificationResult | None = None,
    ) -> StageMatch:
        text = normalize_text(row_text)
        normalized_role = normalize_row_role(row_role)
        row_intents = _row_object_intents(text)
        explicit_stage_intents = {
            "logistics_cleanup",
            "site_protection",
            "chasing_drilling",
            "window_slopes",
            "blinds_curtains",
        }
        if row_intents & explicit_stage_intents and normalized_role in (
            EARLY_INHERIT_ROLES | CONDITIONAL_INHERIT_ROLES
        ):
            # Explicit physical objects classify themselves; they must not
            # inherit an unrelated previous stage merely because row-role
            # detection called them logistics/unknown.
            normalized_role = "work"
        if not text or not allowed_stages:
            return self._unmatched("empty_or_no_allowed_stages", normalized_role)
        if normalized_role in SERVICE_ROLES:
            return self._unmatched(f"row_role_{normalized_role}_skipped", normalized_role, needs_review=False)

        # A grout-only tile row does not identify floor vs wall by itself.
        # In catalogue estimates it immediately follows the corresponding tile
        # installation, so preserve only a confident floor/wall finish context.
        if (
            normalized_role == "work"
            and "tile_work" in row_intents
            and not ({"floor_finish", "wall_finishing"} & row_intents)
            and previous_context
            and str(previous_context.get("work_stage_number") or "") in {"6.4.17", "6.4.18"}
        ):
            inherited = self._inherit_from_context(
                allowed_stages,
                normalized_role,
                previous_context,
                row_order=row_order,
            )
            if inherited is not None:
                return inherited

        # Flat resource rows inherit before any taxonomy or stage scoring. This
        # is the critical fast path for PDF material/labour estimates.
        if normalized_role in EARLY_INHERIT_ROLES:
            inherited = self._inherit_from_context(
                allowed_stages,
                normalized_role,
                previous_context,
                row_order=row_order,
            )
            if inherited is not None:
                return inherited
            return self._unmatched(
                "resource_row_without_parent_context",
                normalized_role,
                needs_review=True,
            )

        if global_result is None:
            global_result = classify_work(row_text, row_role="work")

        # A weak unknown is not allowed to manufacture a new stage. It either
        # inherits the nearest confident work or remains explicitly unmatched.
        if normalized_role in CONDITIONAL_INHERIT_ROLES and (
            global_result.needs_review
            or global_result.subtype_code == UNKNOWN_SUBTYPE_CODE
        ):
            inherited = self._inherit_from_context(
                allowed_stages,
                normalized_role,
                previous_context,
                row_order=row_order,
            )
            if inherited is not None:
                return inherited
            return self._unmatched(
                "unknown_row_without_confident_match_or_parent",
                normalized_role,
                needs_review=True,
            )

        global_section, global_subtype = self.work_type_classifier._split_subtype_code(global_result.subtype_code)
        primary_type_counts = Counter(
            (
                str((stage.get("primary_work_type") or {}).get("section_id") or ""),
                str((stage.get("primary_work_type") or {}).get("subtype_id") or ""),
            )
            for stage in allowed_stages
            if isinstance(stage.get("primary_work_type"), dict)
            and (stage.get("primary_work_type") or {}).get("section_id")
            and (stage.get("primary_work_type") or {}).get("subtype_id")
        )
        scored: list[StageMatch] = []
        hard_excluded_stages: list[dict[str, Any]] = []
        for stage in allowed_stages:
            eligible, gate_reasons = _stage_object_gate(
                stage,
                text,
                global_section,
                global_subtype,
            )
            if not eligible:
                hard_excluded_stages.append(
                    {
                        "work_stage_number": stage.get("number"),
                        "work_stage_title": stage.get("title"),
                        "reasons": gate_reasons,
                    }
                )
                continue
            scored.append(
                self._score_stage(
                    stage,
                    text,
                    normalized_role,
                    previous_context,
                    global_section,
                    global_subtype,
                    primary_type_counts,
                )
            )
        if not scored:
            unmatched = self._unmatched(
                "no_eligible_stage_after_object_gates",
                normalized_role,
                needs_review=True,
            )
            unmatched.score_breakdown["hard_excluded_stages"] = hard_excluded_stages
            unmatched.score_breakdown["row_object_intents"] = sorted(row_intents)
            return unmatched
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

        explicit_score = int(best.score_breakdown.get("explicit_stage_evidence_score") or 0)
        primary_unique = bool(best.score_breakdown.get("primary_work_type_unique_in_variant"))
        confident_global_gate = bool(
            len(scored) == 1
            and hard_excluded_stages
            and global_result is not None
            and not global_result.needs_review
            and global_result.subtype_code != UNKNOWN_SUBTYPE_CODE
        )
        hard_gate_explicit = bool(
            confident_global_gate
            or (
                len(scored) == 1
                and hard_excluded_stages
                and row_intents
                & {
                "logistics_cleanup",
                "site_protection",
                "chasing_drilling",
                "window_slopes",
                "blinds_curtains",
                "hydrolock_electrical",
                "hydrolock_water",
                "sound_floor",
                "sound_ceiling",
                "sound_wall",
                "sound_new_partition",
                "lighting_equipment",
                "low_voltage",
                "new_partition",
                "ceiling_system",
                "gkl_box",
                "ceiling_preparation",
                "wall_preparation",
                "wall_finishing",
                "wall_insulation",
                "gkl_surface_finish",
                "tile_work",
                "floor_finish",
                "floor_base",
                "door_installation",
                "window_installation",
                "technical_hatch",
                "hvac_installation",
                "heating_installation",
                "plumbing_installation",
                "protective_elements",
                "equipment",
                "commissioning",
                "electrical_installation",
                }
            )
        )
        auto_accept_gate_passed = explicit_score > 0 or primary_unique or hard_gate_explicit
        auto_accept_gate_reason = None
        if not auto_accept_gate_passed:
            needs_review = True
            auto_accept_gate_reason = "shared_primary_work_type_without_explicit_stage_evidence"
            reason = reason or auto_accept_gate_reason
        elif hard_gate_explicit and explicit_score <= 0 and not primary_unique:
            auto_accept_gate_reason = (
                "unique_stage_after_confident_subtype_gate"
                if confident_global_gate
                else "unique_stage_after_explicit_object_gate"
            )

        if hard_gate_explicit:
            needs_review = False
            reason = None

        stage_role = str((best.stage or {}).get("stage_role") or "work")
        if stage_role in ALWAYS_REVIEW_STAGE_ROLES:
            needs_review = True
            reason = f"stage_role_{stage_role}_requires_review"
        weak_reason = None if hard_gate_explicit else self._weak_stage_signal_reason(best)
        if weak_reason:
            needs_review = True
            reason = reason or weak_reason
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
            score_breakdown=self._stage_score_json(
                scored,
                best,
                second_score,
                delta,
                reason,
                needs_review,
                auto_accept_gate_passed=auto_accept_gate_passed,
                auto_accept_gate_reason=auto_accept_gate_reason,
                hard_excluded_stages=hard_excluded_stages,
                row_object_intents=sorted(row_intents),
            ),
            normalized_row_role=normalized_role,
        )
        work_type = self.work_type_classifier.classify_row_with_stage_context(
            row_text,
            best.stage or {},
            preliminary,
            estimate_profile_id=estimate_profile_id,
            global_result=global_result,
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
            score_breakdown=self._stage_score_json(
                scored,
                best,
                second_score,
                delta,
                reason,
                needs_review,
                auto_accept_gate_passed=auto_accept_gate_passed,
                auto_accept_gate_reason=auto_accept_gate_reason,
                hard_excluded_stages=hard_excluded_stages,
                row_object_intents=sorted(row_intents),
            ),
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
        if row_role not in CONDITIONAL_INHERIT_ROLES or not previous_context or not previous_context.get("work_stage_number"):
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
        reason = "overhead_inherits_stage_only" if row_role == "overhead" else f"{row_role}_inherits_previous_context"
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
            "reason": reason,
            "classify_work_called": False,
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

        if row_role == "overhead":
            work_type = WorkTypeMatch(
                section_id=None,
                subtype_id=None,
                confidence="low",
                needs_review=False,
                reason="overhead_stage_inherited_without_work_subtype",
                source="context_inheritance",
                stage_option=None,
                score_breakdown={
                    "candidate_scores": [],
                    "winner": None,
                    "thresholds": self.work_type_classifier.thresholds,
                    "delta_top_1_top_2": 0,
                    "needs_review": False,
                    "reason": "work_type_not_applicable_for_overhead",
                },
            )
        else:
            section_id = previous_context.get("section_id") or previous_context.get("work_section_code")
            subtype_id = previous_context.get("subtype_id")
            subtype_code = previous_context.get("work_subtype_code") or previous_context.get("subtype_code")
            if not subtype_id and subtype_code and "/" in str(subtype_code):
                code_section, code_subtype = str(subtype_code).split("/", 1)
                section_id = section_id or code_section
                subtype_id = code_subtype
            work_type = WorkTypeMatch(
                section_id=str(section_id) if section_id else None,
                subtype_id=str(subtype_id) if subtype_id else None,
                confidence="high" if section_id and subtype_id else "low",
                needs_review=False,
                reason="work_type_inherited_from_parent",
                source="context_inheritance",
                stage_option=option,
                score_breakdown={
                    "candidate_scores": [],
                    "winner": {
                        "source": "parent_context",
                        "parent_row_order": previous_context.get("row_order"),
                        "work_subtype_code": subtype_code,
                    },
                    "thresholds": self.work_type_classifier.thresholds,
                    "delta_top_1_top_2": 0,
                    "needs_review": False,
                    "reason": "work_type_inherited_from_parent",
                },
            )
        return StageMatch(**{**inherited.__dict__, "work_type_match": work_type})

    def _score_stage(
        self,
        stage: dict[str, Any],
        text: str,
        row_role: str,
        previous_context: dict[str, Any] | None,
        global_section: str | None,
        global_subtype: str | None,
        primary_type_counts: Counter[tuple[str, str]],
    ) -> StageMatch:
        score = 0
        matched: dict[str, list[str]] = {}
        component_scores: dict[str, int] = {}
        match_type = StageMatchType.UNMATCHED.value
        option_match: tuple[dict[str, Any], int, list[str]] | None = None

        title = normalize_text(stage.get("title"))
        title_terms = _important_terms(stage.get("title"))
        title_matches = _match_terms(title_terms, text, text.split())
        if title_matches and _spurious_roofing_roll_title_match(title, title_matches, text):
            title_matches = []
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

        detail_terms: list[str] = []
        exact_detail_matches: list[str] = []
        for detail_line in stage.get("detail_lines") or []:
            normalized_detail = normalize_text(detail_line)
            if not normalized_detail:
                continue
            if normalized_detail in text:
                exact_detail_matches.append(str(detail_line))
            detail_terms.extend(_important_terms(detail_line))
        detail_matches = _match_terms(detail_terms, text, text.split())
        if exact_detail_matches or detail_matches:
            matched["detail_lines"] = list(dict.fromkeys([*exact_detail_matches, *detail_matches]))
            detail_score = 40 if exact_detail_matches else min(14, len(detail_matches) * 4)
            component_scores["detail_line_match"] = detail_score
            score += detail_score
            if match_type == StageMatchType.UNMATCHED.value:
                match_type = StageMatchType.NEAR_STAGE_TITLE_MATCH.value

        stage_is_demolition = "демонтаж" in title or "демонтаж" in normalize_text(canonical_title)
        if stage_is_demolition and not _has_demolition_action(text):
            component_scores["missing_demolition_action_penalty"] = -15
            score -= 15
        elif not stage_is_demolition and _has_demolition_action(text):
            component_scores["demolition_action_mismatch_penalty"] = -6
            score -= 6

        object_priority_score, object_priority_reasons = _object_priority_adjustment(stage, text)
        if object_priority_score:
            component_scores["object_priority_score"] = object_priority_score
            score += object_priority_score
            matched["object_priority"] = object_priority_reasons

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
        primary_key = (
            str(primary.get("section_id") or ""),
            str(primary.get("subtype_id") or ""),
        )
        primary_unique = bool(primary_key[0] and primary_key[1] and primary_type_counts[primary_key] == 1)
        if self._work_type_matches(primary, global_section, global_subtype):
            matched["primary_work_type"] = [_work_type_code(primary)]
            component_scores["primary_work_type_match"] = 15
            score += 15
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
        if explicit_signal_score >= self.thresholds["stage_auto_accept_min_score"]:
            # Strong row/stage evidence must not be displaced by the previous row.
            sequential_score = 0
        elif sequential_score < 0 and explicit_signal_score >= 8:
            sequential_score = 0
        if sequential_score:
            component_scores["sequential_score"] = sequential_score
            score += sequential_score
            if match_type == StageMatchType.UNMATCHED.value and sequential_score > 0:
                match_type = StageMatchType.SEQUENTIAL_CONTEXT_BOOST.value

        explicit_component_names = {
            "title_match",
            "canonical_stage_match",
            "detail_line_match",
            "occurrence_label",
            "stage_option_match",
        }
        explicit_score = sum(
            max(0, int(value or 0))
            for key, value in component_scores.items()
            if key in explicit_component_names
        )
        # Object-priority evidence is explicit only when it distinguishes a
        # physical object, not when it is a generic electrical compatibility
        # signal shared by many stages.
        object_reasons = matched.get("object_priority") or []
        if object_priority_score > 0 and not set(object_reasons).issubset(
            {"electrical_installation_match", "lighting_equipment_secondary_match"}
        ):
            explicit_score += object_priority_score
        compatibility_score = int(component_scores.get("primary_work_type_match") or 0) + int(
            component_scores.get("related_work_type_match") or 0
        )
        component_scores["explicit_stage_evidence_score"] = explicit_score
        component_scores["work_type_compatibility_score"] = compatibility_score
        component_scores["sequential_context_score"] = int(component_scores.get("sequential_score") or 0)
        component_scores["primary_work_type_unique_in_variant"] = primary_unique

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

    def _weak_stage_signal_reason(self, match: StageMatch) -> str | None:
        matched = match.matched_terms or {}
        if (
            matched.get("primary_work_type")
            or matched.get("related_work_types")
            or matched.get("occurrence_label")
            or matched.get("stage_title_exact")
        ):
            return None
        object_reasons = set(matched.get("object_priority") or [])
        if object_reasons & {
            "ceiling_object_match",
            "ceiling_system_object_match",
            "gkl_box_object_match",
            "ceiling_preparation_object_match",
            "lighting_equipment_object_match",
            "low_voltage_object_match",
            "floor_base_object_match",
            "floor_finish_object_match",
            "wall_preparation_object_match",
            "wall_finishing_object_match",
            "wall_insulation_object_match",
            "new_partition_object_match",
            "door_installation_object_match",
            "window_installation_object_match",
            "window_slopes_object_match",
            "technical_hatch_object_match",
            "plumbing_installation_object_match",
            "hvac_installation_object_match",
            "heating_installation_object_match",
            "logistics_cleanup_object_match",
            "site_protection_object_match",
            "chasing_drilling_object_match",
            "protective_elements_object_match",
            "equipment_object_match",
            "commissioning_object_match",
            "electrical_installation_object_match",
            "tile_work_object_match",
            "gkl_surface_finish_object_match",
        }:
            return None
        if _has_explicit_phrase(matched.get("stage_option") or []):
            return None
        if _has_explicit_phrase(matched.get("stage_title") or []):
            return None
        if _has_explicit_phrase(matched.get("canonical_stage") or []):
            return None
        if _has_explicit_phrase(matched.get("detail_lines") or []):
            return None
        signal_terms = (
            len(matched.get("stage_option") or [])
            + len(matched.get("stage_title") or [])
            + len(matched.get("canonical_stage") or [])
        )
        if signal_terms and match.match_type in {
            StageMatchType.STAGE_OPTION_MATCH.value,
            StageMatchType.NEAR_STAGE_TITLE_MATCH.value,
            StageMatchType.CANONICAL_TITLE_MATCH.value,
        }:
            return "stage_weak_partial_text_match"
        return None

    def _stage_score_json(
        self,
        scored: list[StageMatch],
        best: StageMatch,
        second_score: int,
        delta: int,
        reason: str | None,
        needs_review: bool,
        *,
        auto_accept_gate_passed: bool,
        auto_accept_gate_reason: str | None,
        hard_excluded_stages: list[dict[str, Any]] | None = None,
        row_object_intents: list[str] | None = None,
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
            "explicit_stage_evidence_score": int(
                best.score_breakdown.get("explicit_stage_evidence_score") or 0
            ),
            "work_type_compatibility_score": int(
                best.score_breakdown.get("work_type_compatibility_score") or 0
            ),
            "sequential_context_score": int(
                best.score_breakdown.get("sequential_context_score") or 0
            ),
            "primary_work_type_unique_in_variant": bool(
                best.score_breakdown.get("primary_work_type_unique_in_variant")
            ),
            "auto_accept_gate_passed": auto_accept_gate_passed,
            "auto_accept_gate_reason": auto_accept_gate_reason,
            "hard_excluded_stages": hard_excluded_stages or [],
            "row_object_intents": row_object_intents or [],
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
            title = normalize_text(option.get("title"))
            exact_title_match = bool(title and title in text)
            work_type_matches = self._work_type_matches(option, global_section, global_subtype)
            if (
                matches
                and not exact_title_match
                and not work_type_matches
                and _generic_only_stage_option_match(matches)
            ):
                continue
            score = 0
            if exact_title_match:
                score += 8
            elif matches:
                score += len(matches) * 5
            if work_type_matches:
                # Exact scoped subtype is decisive when the option title also
                # matches the row. Without title/object evidence it is only a
                # supporting signal, because generic subtypes such as electrical
                # can legitimately appear in several stages.
                score += 22 if matches else 10
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
        ref_section = ref.get("section_id")
        ref_subtype = ref.get("subtype_id")
        if ref_section != section_id:
            return (
                ref_section == "interior_finishing"
                and ref_subtype in _FINISHING_STAGE_GENERIC_SUBTYPES
                and section_id == "windows_doors"
                and subtype_id in _WINDOW_COVERING_STAGE_COMPATIBLE_SUBTYPES
            )
        if not ref_subtype or ref_subtype == subtype_id:
            return True
        return (
            section_id == "interior_finishing"
            and ref_subtype in _FINISHING_STAGE_GENERIC_SUBTYPES
            and subtype_id in _FINISHING_STAGE_COMPATIBLE_SUBTYPES
        )


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


def _has_explicit_phrase(terms: list[str]) -> bool:
    return any(len(normalize_text(term).split()) > 1 for term in terms)


def _generic_only_stage_option_match(terms: list[str]) -> bool:
    normalized = {normalize_text(term) for term in terms if normalize_text(term)}
    return bool(normalized) and normalized.issubset(_GENERIC_STAGE_OPTION_TERMS)


def _spurious_roofing_roll_title_match(stage_title: str, terms: list[str], text: str) -> bool:
    normalized = {normalize_text(term) for term in terms if normalize_text(term)}
    return (
        bool(normalized)
        and normalized.issubset(_ROOFING_ROLL_MATERIAL_TERMS)
        and "кров" in stage_title
        and "кров" not in text
    )


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
