"""
Маппинг строк сметы → NW (нормализованный вид работ).

Гибридный алгоритм:
  1. Точечные keyword-правила (NW_OVERRIDES из nw_classifier — те же что для ФЕР таблиц,
     они построены для технических формулировок, что близко к смете)
  2. Дополнительные правила для смет (более «человечные» формулировки прорабов)
  3. Fallback на LLM — отдельная функция (вызывается только для unmatched, по запросу)

На спринт 1 — только keyword. LLM будет добавлен отдельно.

Возвращает best_match с confidence:
  - high   : чёткое совпадение по правилу
  - medium : только частичное / общая категория
  - None   : не сматчилось — нужен LLM или ручной разбор
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from app.services.nw_classifier import NW_OVERRIDES, _COMPILED


# ─────────────────────────────────────────────────────────────────────────────
# Дополнительные правила специфичные для смет (более «человечные» формулировки)
# ─────────────────────────────────────────────────────────────────────────────
# Правила из nw_classifier работают для FER table_title — они достаточно общие,
# но прорабы часто пишут короче / неформальнее. Тут добавляем.

ESTIMATE_EXTRA_RULES: list[tuple[str, str, str]] = [
    # (regex, nw_code, note)
    (r"земл\w* работ|разработк\w* грунт",  "NW-003", "общие земляные"),
    (r"планировк\w* участк|вертикальн\w* планировк", "NW-005", "планировка"),
    (r"подсыпк|подушк\w* (песчан|щебён)",  "NW-008", "подушка/уплотнение"),
    (r"вывоз\w* (мусор|стройотход)",       "NW-015", "вывоз мусора"),
    (r"монолитн\w* фундамент|ленточн\w* фундамент|плитн\w* фундамент|свайн\w* фундамент",
                                            "NW-018", "фундамент монолит"),
    (r"кладк\w* стен",                      "NW-024", "кладка стен"),
    (r"перекрыт\w* (этаж|первого|второго)", "NW-025", "перекрытия"),
    (r"кровл\w* по|устройств\w* кровл",    "NW-069", "кровля"),
    (r"утеплен\w* (стен|фасад)",            "NW-073", "утепление"),
    (r"монтаж\w* (трубопровод|труб) (отопл|водоснаб|канализ)",
                                            "NW-046", "трубы внутр.инженерии"),
    (r"монтаж\w* отопл|радиатор|конвектор",  "NW-045", "отопление"),
    (r"электрик|электромонтаж|кабель силов|щит распред",
                                            "NW-049", "электрика"),
    (r"вентиляц|кондиционер",                "NW-048", "вентиляция"),
    (r"внутренн\w* (отделк|ремонт)",         "NW-031", "внутр. отделка"),
    (r"наружн\w* отделк|фасадн\w* работ",    "NW-076", "фасадная отделка"),
    (r"мебель|фурнитур",                     None,    "не строительство — мебель"),  # signal-only, не маппит
    (r"отопл\w* приборов|бойлер",            "NW-045", "отопит. оборудование"),
    (r"котельн|теплов\w* пункт",             "NW-045", "котельная"),
    (r"озеленен|посадк\w* (дерев|кустарн|растен)",
                                            "NW-085", "озеленение"),
    (r"газон|травян\w* покрыт",              "NW-086", "газон"),
    (r"забор|огражден\w* участк|штакетн",    "NW-084", "забор/МАФ"),
]

_RULES_COMPILED = [(re.compile(p, re.IGNORECASE), nw, note)
                   for p, nw, note in ESTIMATE_EXTRA_RULES]


# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class EstimateNwMatch:
    nw_code: str | None
    confidence: str        # 'high' | 'medium'
    source: str            # 'keyword_extra' | 'keyword_fer' | 'unmatched'
    note: str | None


def match_estimate_row(
    work_name: str,
    section: str | None = None,
    allowed_nw_codes: Iterable[str] | None = None,
) -> EstimateNwMatch:
    """
    Сматчить строку сметы на NW.

    work_name: название работы из сметы (Estimate.work_name)
    section:   секция в смете (Estimate.section), часто содержит укрупнённую категорию
    allowed_nw_codes: ограничение по палитре (если задано — отфильтровывать вне палитры)
    """
    text = " ".join(filter(None, [section or "", work_name or ""])).strip()
    if not text:
        return EstimateNwMatch(None, "medium", "unmatched", None)

    allowed = set(allowed_nw_codes) if allowed_nw_codes else None

    # 1. Сначала специфичные для смет правила
    for rx, nw, note in _RULES_COMPILED:
        if not rx.search(text):
            continue
        if nw is None:
            continue  # signal-only правило (например «мебель»)
        if allowed and nw not in allowed:
            continue
        return EstimateNwMatch(nw, "high", "keyword_extra", f"по ключевому слову: {note}")

    # 2. Затем переиспользуем NW_OVERRIDES из nw_classifier (правила для ФЕР, но достаточно общие)
    for rule in NW_OVERRIDES:
        # only_in_collections в правилах для ФЕР относится к сборнику ФЕР,
        # для строки сметы это поле не применимо — игнорируем
        rx = _COMPILED.get(rule.pattern) or re.compile(rule.pattern, re.IGNORECASE)
        if not rx.search(text):
            continue
        if allowed and rule.nw_code not in allowed:
            continue
        return EstimateNwMatch(
            rule.nw_code,
            rule.confidence,            # high/medium
            "keyword_fer",
            f"по ключевому слову: {rule.note}",
        )

    return EstimateNwMatch(None, "medium", "unmatched", None)
