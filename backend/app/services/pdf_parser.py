"""
backend/app/services/pdf_parser.py

Парсит PDF-сметы вида (ООО «Новые технологии» и аналогичные):

  Заголовок раздела:
    "6. Работы по потолкам (Отделочные работы) 112 997,4"

  Строка работы (однострочная):
    "6.10 Теплоизоляция потолка ... м2 20,79 847 17609,1"

  Строка работы (перенос — длинное название на предыдущей строке):
    "Монтаж 2-х гранного короба из ГКЛ..."
    "7.36 шириной м.пог 3,00 780 2 340,0"

Стратегия:
  1. Извлекаем сырой текст через pdfplumber (построчно)
  2. Фильтруем шапку/подвал
  3. Парсим каждую строку регуляркой справа: сумма -> цена -> кол-во -> ед -> название
  4. Перенесённые строки склеиваем через prev_fragment
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ParsedRow:
    id:           str             = field(default_factory=lambda: str(uuid.uuid4()))
    section:      Optional[str]   = None
    work_name:    str             = ""
    unit:         Optional[str]   = None
    quantity:     Optional[float] = None
    unit_price:   Optional[float] = None
    total_price:  Optional[float] = None
    materials:    list[dict]      = field(default_factory=list)
    row_order:    int             = 0
    raw_data:     dict            = field(default_factory=dict)
    source_strategy: str          = "pdf"


# ── Числа (с пробелом как разделителем тысяч, запятой как десятичным) ─────────
# Число: целое с разделителем тысяч (пробел) или просто цифры, с опциональным дробным
_N = r'\d{1,3}(?:\s\d{3})+(?:[,.]\d+)?|\d+(?:[,.]\d+)?'

# ── Единицы измерения ──────────────────────────────────────────────────────────
_UNITS_LIST = [
    'м\\.пог\\.?', 'м\\.кв\\.?', 'м\\.п\\.?', 'пог\\.м\\.?', 'кв\\.м\\.?',
    'куб\\.м\\.?', 'м2', 'м3', 'м', 'шт\\.?', 'комп\\.?',
    'к-т\\.?', 'тчк\\.?', 'тн\\.?', 'т\\.(?=\\s)', 'кг', 'уп\\.?', 'рул\\.?',
    'л\\.(?=\\s)', 'п\\.м\\.?', 'л\\.м\\.?',
]
_UNIT_PAT = '(?:' + '|'.join(_UNITS_LIST) + ')'

# Полная строка: {код} {название} {ед} {кол} {цена} {сумма}
_ROW_RE = re.compile(
    rf'^(\d+\.\d+)\s+(.+?)\s+({_UNIT_PAT})\s+({_N})\s+({_N})\s+({_N})\s*$',
    re.IGNORECASE,
)

# Хвост переноса: {код} [хвост_названия] {ед} {кол} {цена} {сумма}
_TAIL_RE = re.compile(
    rf'^(\d+\.\d+)\s*(.*?)\s*({_UNIT_PAT})\s+({_N})\s+({_N})\s+({_N})\s*$',
    re.IGNORECASE,
)

# Заголовок раздела: "N. Название [сумма]"
_SECTION_RE = re.compile(r'^(\d+)\.\s+([А-ЯЁа-яёA-Za-z].+?)(?:\s+[\d][\d ]*[,.]?\d*)?\s*$')

# Строки которые нужно пропустить
_SKIP_RE = re.compile(
    r'ООО|ИНН|www\.|e-mail|Электронная почта|Заказчик:|Адрес объекта:|Телефон|'
    r'Подрядчик|ОГРН|КПП|Тел\.|Email|Почта:|Серия паспорта|Стоимость выполненных|'
    r'Приложение №|к договору №|Строительные работы|Раздел |Срок выполнения|'
    r'Звоните нам|Яна Новикова|Сайт:|Наименование работ|Даем Сертификат|'
    r'Оплата поэтапно|Опыт и качество|Офис:',
    re.IGNORECASE,
)

_TOTAL_RE = re.compile(r'^(ИТОГО|ВСЕГО)', re.IGNORECASE)


def _f(s: str) -> Optional[float]:
    try:
        return float(re.sub(r'\s', '', s).replace(',', '.'))
    except Exception:
        return None


class PdfEstimateParser:

    def parse(self, file_path: str | Path) -> tuple[list[ParsedRow], dict]:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Установите pdfplumber: pip install pdfplumber>=0.11")

        raw_lines: list[str] = []
        pages = 0

        with pdfplumber.open(str(file_path)) as pdf:
            pages = len(pdf.pages)
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
                raw_lines.extend(text.split('\n'))

        rows = self._parse_lines(raw_lines)
        success = len(rows) > 0

        return rows, {
            "strategy":    "pdf",
            "confidence":  0.9 if success else 0.0,
            "pages":       pages,
            "rows_found":  len(rows),
        }

    def _parse_lines(self, raw_lines: list[str]) -> list[ParsedRow]:
        rows: list[ParsedRow]  = []
        section: Optional[str] = None
        prev_fragment: Optional[str] = None  # начало перенесённого названия
        order = 0
        # Флаг: таблица уже началась (строка заголовка «№ Наименование...»)
        table_started = False

        for raw in raw_lines:
            line = raw.strip()
            if not line:
                continue

            # Заголовок таблицы — переключаем флаг
            if re.search(r'№\s+Наименование работ', line):
                table_started = True
                continue

            # Шапка/подвал — пропускаем
            if _SKIP_RE.search(line):
                prev_fragment = None
                continue

            # ИТОГО — пропускаем
            if _TOTAL_RE.match(line):
                prev_fragment = None
                continue

            if not table_started:
                continue

            # ── ПРИОРИТЕТ: если есть fragment, сначала пробуем хвост ─────────
            # Пример: prev="Монтаж 2-х гранного короба..."
            #         line="7.36 шириной м.пог 3,00 780 2 340,0"
            if prev_fragment:
                tm = _TAIL_RE.match(line)
                if tm:
                    tail_name = tm.group(2).strip()
                    full_name = (prev_fragment + (' ' + tail_name if tail_name else '')).strip()
                    rows.append(ParsedRow(
                        section      = section,
                        work_name    = full_name,
                        unit         = tm.group(3).strip(),
                        quantity     = _f(tm.group(4)),
                        unit_price   = _f(tm.group(5)),
                        total_price  = _f(tm.group(6)),
                        row_order    = order,
                        raw_data     = {"fragment": prev_fragment, "tail": line},
                        source_strategy = "pdf",
                    ))
                    order += 1
                    prev_fragment = None
                    continue

            # ── Полная строка работы ───────────────────────────────────────
            m = _ROW_RE.match(line)
            if m:
                rows.append(ParsedRow(
                    section      = section,
                    work_name    = m.group(2).strip(),
                    unit         = m.group(3).strip(),
                    quantity     = _f(m.group(4)),
                    unit_price   = _f(m.group(5)),
                    total_price  = _f(m.group(6)),
                    row_order    = order,
                    raw_data     = {"line": line},
                    source_strategy = "pdf",
                ))
                order += 1
                prev_fragment = None
                continue

            # ── Заголовок раздела ──────────────────────────────────────────
            sm = _SECTION_RE.match(line)
            if sm:
                section = sm.group(2).strip()
                section = re.sub(r'\s+[\d][\d ]*[,.]?\d*\s*$', '', section).strip()
                prev_fragment = None
                continue

            # ── Строка без кода — возможно начало переноса названия ────────
            if not re.match(r'^\d+\.\d+\s', line):
                prev_fragment = line
            else:
                prev_fragment = None

        return rows
