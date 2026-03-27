#!/usr/bin/env python3
"""
ЕНиР E3 — скрапер сайта meganorm.ru
=====================================
Собирает структуру документа и все таблицы с сайта,
сохраняет в канонический JSON и cross_references.json.

Использование:
    python enir_scraper.py --out ./output
    python enir_scraper.py --url https://... --out ./output
"""

import re, json, argparse, logging
import requests
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin, urlparse
from pathlib import Path
from typing import Optional, List, Dict, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

BASE_URL      = "https://meganorm.ru/Data2/1/4294854/4294854146.htm"
MEGANORM_HOST = "meganorm.ru"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 – FETCH HTML
# ══════════════════════════════════════════════════════════════════════════════

def fetch_html(url: str, cache_path: Optional[Path] = None) -> BeautifulSoup:
    if cache_path and cache_path.exists():
        log.info("Читаю из кэша: %s", cache_path)
        raw = cache_path.read_bytes()
    else:
        log.info("Загружаю %s ...", url)
        resp = requests.get(url, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        raw = resp.content
        if cache_path:
            cache_path.write_bytes(raw)
            log.info("Кэш сохранён -> %s", cache_path)
    return BeautifulSoup(raw, "html.parser")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 – CROSS-REFERENCES
# ══════════════════════════════════════════════════════════════════════════════

def extract_links(soup: BeautifulSoup, page_url: str) -> Dict:
    """
    Два вида ссылок:
      internal_links - #fragment внутри того же документа
      external_links - все остальные URL (ГОСТ, СНиП и пр. на meganorm.ru)
    """
    internal, external = [], []
    parsed_base = urlparse(page_url)

    for a in soup.find_all("a", href=True):
        href: str = a["href"].strip()
        text: str = _clean(a.get_text(" ", strip=True))
        if not href or href == "#":
            continue

        abs_url = urljoin(page_url, href)
        parsed  = urlparse(abs_url)

        record = {
            "text":    text,
            "href":    href,
            "abs_url": abs_url,
            "context": _clean(_parent_text(a)),
        }

        if href.startswith("#"):
            record["fragment"] = href[1:]
            internal.append(record)
        elif (parsed.scheme == parsed_base.scheme
              and parsed.netloc == parsed_base.netloc
              and parsed.path   == parsed_base.path):
            record["fragment"] = parsed.fragment
            internal.append(record)
        else:
            record["is_meganorm"] = MEGANORM_HOST in (parsed.netloc or "")
            external.append(record)

    # Якоря-мишени
    anchors: List[Dict] = []
    seen_names = set()
    for tag in soup.find_all(attrs={"name": True}):
        n = tag["name"]
        if n not in seen_names:
            seen_names.add(n)
            anchors.append({"name": n, "tag": tag.name, "context": _parent_text(tag)})
    for tag in soup.find_all(attrs={"id": True}):
        n = tag["id"]
        if n not in seen_names:
            seen_names.add(n)
            anchors.append({"name": n, "tag": tag.name, "context": _parent_text(tag)})

    log.info("Ссылки: %d внутренних, %d внешних, %d якорей",
             len(internal), len(external), len(anchors))
    return {
        "source_url":     page_url,
        "internal_links": internal,
        "external_links": external,
        "anchor_targets": anchors,
    }


def _parent_text(tag: Tag, chars: int = 120) -> str:
    p = tag.parent
    return p.get_text(" ", strip=True)[:chars] if p else ""


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 – TABLE PARSING (с поддержкой colspan / rowspan)
# ══════════════════════════════════════════════════════════════════════════════

def parse_html_table(table_el: Tag) -> Dict:
    """
    Разворачивает HTML-таблицу с colspan/rowspan в плоскую сетку.
    Возвращает:
      {
        "raw_grid":  [[str, ...], ...],   # все строки
        "headers":   [str, ...],          # заголовочная строка (объединённая)
        "rows":      [[str, ...], ...],   # строки данных
      }
    """
    all_trs = table_el.find_all("tr")
    if not all_trs:
        return {"raw_grid": [], "headers": [], "rows": []}

    # Максимальное число колонок
    max_cols = 0
    for tr in all_trs:
        cols = sum(int(td.get("colspan", 1)) for td in tr.find_all(["td", "th"]))
        max_cols = max(max_cols, cols)
    if max_cols == 0:
        return {"raw_grid": [], "headers": [], "rows": []}

    # Сетка с учётом rowspan/colspan
    grid: List[List[str]] = []
    # rowspan_carry[col] = (rows_remaining, text)
    rowspan_carry: Dict[int, Tuple[int, str]] = {}

    for tr in all_trs:
        row: List[Optional[str]] = [None] * max_cols

        # Переносим rowspan из предыдущих строк
        for col_idx in list(rowspan_carry.keys()):
            rem, txt = rowspan_carry[col_idx]
            row[col_idx] = txt
            if rem <= 1:
                del rowspan_carry[col_idx]
            else:
                rowspan_carry[col_idx] = (rem - 1, txt)

        # Заполняем ячейки текущей строки
        cursor = 0
        for cell in tr.find_all(["td", "th"]):
            while cursor < max_cols and row[cursor] is not None:
                cursor += 1
            if cursor >= max_cols:
                break

            text    = cell.get_text(" ", strip=True)
            colspan = int(cell.get("colspan", 1))
            rowspan = int(cell.get("rowspan", 1))

            for dc in range(colspan):
                pos = cursor + dc
                if pos < max_cols:
                    row[pos] = text
                    if rowspan > 1:
                        rowspan_carry[pos] = (rowspan - 1, text)
            cursor += colspan

        grid.append([c if c is not None else "" for c in row])

    if not grid:
        return {"raw_grid": [], "headers": [], "rows": []}

    # Определяем количество заголовочных строк
    header_row_count = 0
    for tr in all_trs:
        if tr.find("th"):
            header_row_count += 1
        else:
            break
    header_row_count = max(1, header_row_count)

    header_grid = grid[:header_row_count]
    data_rows   = grid[header_row_count:]

    # Объединяем многострочный заголовок в одну строку на колонку
    flat_header: List[str] = []
    for col_i in range(max_cols):
        parts = []
        for h_row in header_grid:
            val = h_row[col_i] if col_i < len(h_row) else ""
            if val and val not in parts:
                parts.append(val)
        flat_header.append(" / ".join(parts))

    return {
        "raw_grid": grid,
        "headers":  flat_header,
        "rows":     data_rows,
    }


# Маппинг заголовков -> ключи колонок
_KEY_MAP = [
    (re.compile(r"н\.вр|норм.*вр",        re.I), "norm_time"),
    (re.compile(r"расц",                   re.I), "price_rub"),
    (re.compile(r"толщин",                 re.I), "thickness"),
    (re.compile(r"^вид\b|вид\s+кла",      re.I), "work_type"),
    (re.compile(r"сложн",                  re.I), "complexity"),
    (re.compile(r"профессия|разряд",       re.I), "profession"),
    (re.compile(r"ед.*изм",                re.I), "unit_col"),
    (re.compile(r"наименован",             re.I), "name"),
    (re.compile(r"^№$|номер\s+строки",    re.I), "row_num"),
    (re.compile(r"отклонен",               re.I), "deviation"),
    (re.compile(r"допуск",                 re.I), "tolerance"),
]

def _header_to_key(h: str, idx: int) -> str:
    for pat, key in _KEY_MAP:
        if pat.search(h):
            return key
    return f"c{idx}"

def _value_type(key: str, val: str, header: str = "") -> str:
    """Определяет тип ячейки без опоры на семантический column_key."""
    v = val.strip()
    h = (header or "").strip()
    if re.match(r"^\d+[-]\d+$", v):
        return "price_cell"
    if re.match(r"^\d+(?:[\.,]\d+)?$", v):
        if re.search(r"н\.?\s*вр|норм.*вр", h, re.I):
            return "norm_cell"
        if re.search(r"расц", h, re.I):
            return "price_num_cell"
        if re.fullmatch(r"№|номер\s+строки", h, re.I):
            return "row_num_cell"
        return "numeric_cell"
    return "cell"


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 – DOCUMENT STRUCTURE PARSER
# ══════════════════════════════════════════════════════════════════════════════

RE_SECTION   = re.compile(r"^Раздел\s+([IVXivx\d]+)[.\s]*(.*)",    re.I)
RE_CHAPTER   = re.compile(r"^Глава\s+(\d+)[.\s]*(.*)",              re.I)
RE_PARA_CODE = re.compile(r"§\s*([ЕEЁё][Зз3]\s*[-]\s*\d+[а-яa-z]?)\b", re.I | re.U)
RE_TECH      = re.compile(r"техническая\s+часть|указания\s+по\s+(качеству|применению)", re.I)
RE_WORK_ITEM = re.compile(r"^\s*(\d+)\.\s+(.+)$", re.S)
# Полная строка звена: "Каменщик 4 разр. - 1"
RE_CREW_FULL = re.compile(
    r"([\u0410-\u044f\u0451\u0401][\u0410-\u044f\u0451\u0401\w\s\-/()\u0401\u0451]{2,55}?)"
    r"\s+(\d)\s*\u0440\u0430\u0437\u0440[.:\s]+[-\u2013\u2014]\s*(\d+)",
    re.I | re.U,
)
# Продолжение-ditto: "« 3 » - 1" или '" 3 " - 1'
RE_CREW_CONT = re.compile(
    r"[\u00ab\u00bb\"]\s*(\d)\s*[\u00ab\u00bb\"\s]+[-\u2013\u2014\-]\s*(\d+)",
    re.U,
)

RE_NOTE_CODE = re.compile(r"\b(ПР|ТЧ)-(\d+)\b", re.I)
RE_COEFF     = re.compile(r"(?:умножать\s+на|коэффициент)\s+([\d,\.]+)", re.I)
RE_UNIT_LINE = re.compile(
    r"Норм[аы]\s+времени\s+и\s+расценк[аи]\s+на\s+(.+?)(?:\n|$)",
    re.I,
)

RE_APPLICATION_HEADING = re.compile(
    r"^(?:состав\s+работ|состав\s+звена|состав\s+бригады|"
    r"норм[аы]\s+времени\s+и\s+расценк[аи].*|табл(?:ица)?\.?\s*\d+.*|"
    r"продолжение\s+табл.*|окончание\s+табл.*)$",
    re.I,
)
RE_CREW_ONLY_HEADING = re.compile(r"^состав\s+(?:звена|бригады)$", re.I)
RE_WORK_ONLY_HEADING = re.compile(r"^состав\s+работ$", re.I)


class EniRParser:
    def __init__(self, soup: BeautifulSoup, source_url: str):
        self.soup       = soup
        self.source_url = source_url
        self.doc        = _empty_doc()

        self._s_cnt  = 0
        self._ch_cnt = 0
        self._p_cnt  = 0
        self._t_cnt  = 0   # глобальный счётчик таблиц (для уникальных ID)

        self._cur_section_id: Optional[str] = None
        self._cur_chapter_id: Optional[str] = None
        self._cur_para_id:    Optional[str] = None
        self._last_crew_prof: Optional[str] = None  # для ditto «3» - 1

    def parse(self) -> Dict:
        self._parse_metadata()
        body = self.soup.find("body") or self.soup
        self._walk(body)
        return self.doc

    def _parse_metadata(self):
        txt = self.soup.get_text(" ", strip=True)
        m = re.search(r"(\d{1,2})\s+декабр[яь]\s+(\d{4})", txt, re.I)
        if m:
            self.doc["approval_date"] = f"{m.group(2)}-12-{int(m.group(1)):02d}"
        m = re.search(r"№\s*([\d/\-]+)", txt)
        if m:
            self.doc["approval_number"] = m.group(1)

    def _walk(self, root: Tag):
        for el in root.children:
            if not isinstance(el, Tag):
                continue
            tag = el.name
            if tag in ("h1","h2","h3","h4","h5","h6"):
                self._on_heading(el)
            elif tag == "table":
                self._on_table(el)
            elif tag in ("p","li"):
                self._on_block(el)
            elif tag in ("ul","ol"):
                for li in el.find_all("li", recursive=False):
                    self._on_block(li)
            elif tag in ("div","section","article","main","td","th","blockquote"):
                self._walk(el)

    # ── заголовки ────────────────────────────────────────────────
    def _on_heading(self, el: Tag):
        text = el.get_text(" ", strip=True)
        if not text:
            return

        m = RE_SECTION.match(text)
        if m:
            self._s_cnt += 1
            sid = f"S{self._s_cnt}"
            self._cur_section_id = sid
            self._cur_chapter_id = None
            self._cur_para_id    = None
            self.doc["has_sections"] = True
            self.doc["sections"].append({
                "section_id":    sid,
                "section_order": self._s_cnt,
                "title":         text,
                "has_tech":      False,
            })
            return

        m = RE_CHAPTER.match(text)
        if m:
            self._ch_cnt += 1
            cid = f"CH{self._ch_cnt}"
            self._cur_chapter_id = cid
            self._cur_para_id    = None
            self.doc["chapters"].append({
                "chapter_id":    cid,
                "section_id":    self._cur_section_id,
                "chapter_order": self._ch_cnt,
                "title":         text,
                "has_tech":      False,
            })
            return

        m = RE_PARA_CODE.search(text)
        if m:
            raw  = m.group(1)
            code = re.sub(r"\s+", "", raw).upper()
            # Нормализация: ЕЗ -> Е3, EЗ -> Е3, латинская E -> кириллическая Е
            code = code.replace("ЕЗ", "Е3").replace("EЗ", "Е3")
            code = re.sub(r"^E", "Е", code)   # латинская E в начале
            pid  = code

            self._p_cnt += 1
            self._cur_para_id = pid
            self._last_crew_prof = None  # сброс при новом параграфе
            title = _clean(text[m.end():].strip(" .–—-") or text)

            # Если нет главы — параграф привязываем к разделу напрямую
            if self._cur_chapter_id is not None:
                p_sec_id = None
                p_ch_id  = self._cur_chapter_id
            else:
                p_sec_id = self._cur_section_id
                p_ch_id  = None

            self.doc["paragraphs"].append({
                "paragraph_id":              pid,
                "section_id":                p_sec_id,
                "chapter_id":                p_ch_id,
                "paragraph_order":           self._p_cnt,
                "code":                      code,
                "title":                     title,
                "unit":                      None,
                "technical_characteristics": [],
                "application_notes":         [],
            })
            log.debug("  Para %s: %s", pid, title[:50])
            return

        if RE_TECH.search(text):
            if self._cur_chapter_id and not self._cur_para_id:
                tech_id = f"TECH_{self._cur_chapter_id}"
                self._cur_para_id = tech_id
                self._p_cnt += 1
                self._add_tech(tech_id, None, self._cur_chapter_id, text)
                for ch in self.doc["chapters"]:
                    if ch["chapter_id"] == self._cur_chapter_id:
                        ch["has_tech"] = True
            elif self._cur_section_id and not self._cur_chapter_id:
                tech_id = f"TECH_{self._cur_section_id}"
                self._cur_para_id = tech_id
                self._p_cnt += 1
                self._add_tech(tech_id, self._cur_section_id, None, text)
                for s in self.doc["sections"]:
                    if s["section_id"] == self._cur_section_id:
                        s["has_tech"] = True

    def _add_tech(self, pid, sec_id, ch_id, title):
        self.doc["paragraphs"].append({
            "paragraph_id":              pid,
            "section_id":                sec_id,
            "chapter_id":                ch_id,
            "paragraph_order":           self._p_cnt - 0.5,
            "code":                      pid,
            "title":                     _clean(title),
            "unit":                      None,
            "technical_characteristics": [],
            "application_notes":         [],
        })

    # ── текстовые блоки ──────────────────────────────────────────
    def _on_block(self, el: Tag):
        text = el.get_text(" ", strip=True)
        if not text or len(text) < 4:
            return
        pid = self._cur_para_id
        if not pid:
            return
        para = self._find_para(pid)
        if not para:
            return

        # Единица измерения
        m = RE_UNIT_LINE.search(text)
        if m and para["unit"] is None:
            para["unit"] = _normalize_unit(m.group(1))
            return

        # Примечания — явный блок "Примечание/Примечания"
        if re.match(r"^\s*Примечани", text, re.I):
            self._parse_notes(pid, text)
            return

        # Примечания встроенные: пронумерованная строка с кодом ТЧ-N/ПР-N
        # Важно проверять ДО состава работ — иначе ТЧ-строки уходят в work_items
        m_item = RE_WORK_ITEM.match(text)
        if m_item and RE_NOTE_CODE.search(text):
            note_text = _clean(m_item.group(2))
            code_m  = RE_NOTE_CODE.search(note_text)
            coeff_m = RE_COEFF.search(note_text)
            order   = len([n for n in self.doc["paragraph_notes"]
                            if n["paragraph_id"] == pid]) + 1
            self.doc["paragraph_notes"].append({
                "paragraph_id": pid,
                "item_order":   order,
                "code":         f"{code_m.group(1).upper()}-{code_m.group(2)}" if code_m else None,
                "text":         note_text,
                "coefficient":  float(coeff_m.group(1).replace(",", ".")) if coeff_m else None,
            })
            return

        # Состав работ
        if m_item:
            order = len([w for w in self.doc["paragraph_work_items"] if w["paragraph_id"] == pid]) + 1
            self.doc["paragraph_work_items"].append({
                "paragraph_id": pid,
                "item_order":   order,
                "text":         _clean(m_item.group(2)),
            })
            return

        # Состав звена — полные строки + ditto-продолжения «grade» - count
        crew_found = []
        for cm in RE_CREW_FULL.finditer(text):
            self._last_crew_prof = _clean(cm.group(1))
            crew_found.append((self._last_crew_prof, int(cm.group(2)), int(cm.group(3))))
        for cm in RE_CREW_CONT.finditer(text):
            if self._last_crew_prof:
                crew_found.append((self._last_crew_prof, int(cm.group(1)), int(cm.group(2))))
        if crew_found:
            for prof, grade, count in crew_found:
                if len(prof) < 65:
                    order = len([c for c in self.doc["paragraph_crew_items"]
                                  if c["paragraph_id"] == pid]) + 1
                    self.doc["paragraph_crew_items"].append({
                        "paragraph_id": pid,
                        "item_order":   order,
                        "profession":   prof,
                        "grade":        grade,
                        "count":        count,
                        "raw":          text[:200],
                    })
            return

        # Общие указания / application_notes
        cleaned_text = _clean(text)
        if len(cleaned_text) > 10 and _should_keep_as_application_note(cleaned_text):
            if cleaned_text not in para["application_notes"]:
                para["application_notes"].append(cleaned_text)

    def _parse_notes(self, pid: str, text: str):
        body = re.sub(r"^Примечани[яе][:\.]?\s*", "", text, flags=re.I).strip()
        parts = re.split(r"(?<!\d)(\d+)\.\s+", body)
        idx = 1
        i = 1
        while i + 1 <= len(parts) - 1:
            note_text = parts[i + 1].strip() if i + 1 < len(parts) else ""
            if note_text:
                code_m  = RE_NOTE_CODE.search(note_text)
                coeff_m = RE_COEFF.search(note_text)
                self.doc["paragraph_notes"].append({
                    "paragraph_id": pid,
                    "item_order":   idx,
                    "code":         f"{code_m.group(1).upper()}-{code_m.group(2)}" if code_m else None,
                    "text":         note_text,
                    "coefficient":  float(coeff_m.group(1).replace(",", ".")) if coeff_m else None,
                })
                idx += 1
            i += 2

    # ── таблицы ──────────────────────────────────────────────────
    def _on_table(self, el: Tag):
        pid = self._cur_para_id
        if not pid:
            return

        self._t_cnt += 1
        tid = f"{pid}_t{self._t_cnt}"

        # Заголовок таблицы
        caption = el.find("caption")
        if caption:
            title = _clean(caption.get_text(" ", strip=True))
        else:
            title = ""
            # Ищем ближайший предшествующий тег с текстом
            for tag_name in ["p","h3","h4","h5","b","strong","div"]:
                prev = el.find_previous_sibling(tag_name)
                if prev:
                    t = _clean(prev.get_text(" ", strip=True))
                    if t:
                        title = t[:200]
                        break
            # Если не нашли явного заголовка — генерируем
            if not title:
                para_title = ""
                if pid in {p["paragraph_id"] for p in self.doc["paragraphs"]}:
                    para_title = next(
                        (p["title"] for p in self.doc["paragraphs"]
                         if p["paragraph_id"] == pid), ""
                    )
                # +1 потому что текущая таблица ещё не добавлена в список
                table_local_order = len([t for t in self.doc["norm_tables"]
                                         if t["paragraph_id"] == pid]) + 1
                title = f"Таблица {table_local_order}. {para_title[:60]}" if para_title else f"Таблица {table_local_order}"

        parsed    = parse_html_table(el)
        headers   = parsed["headers"]
        data_rows = parsed["rows"]

        if not headers and not data_rows:
            return

        # row_count обновим после фильтрации — placeholder 0
        table_local_order = len([t for t in self.doc["norm_tables"] if t["paragraph_id"] == pid]) + 1
        self.doc["norm_tables"].append({
            "table_id":     tid,
            "paragraph_id": pid,
            "table_order":  table_local_order,
            "title":        title,
            "row_count":    0,   # будет обновлено ниже
        })

        # Колонки: используем только стабильные позиционные ключи c1/c2/c3...
        # Семантику сохраняем в header/label, а не в column_key.
        col_keys = []
        clean_headers = []
        for i, h in enumerate(headers, 1):
            if not h.strip() and i == len(headers):
                h = "№"
            h_clean = _clean(h)
            key = f"c{i}"
            col_keys.append(key)
            clean_headers.append(h_clean)

            self.doc["norm_columns"].append({
                "table_id":     tid,
                "column_order": i,
                "column_key":   key,
                "header":       h_clean,
                "label":        h_clean,
            })

        # Единица измерения из заголовка
        para = self._find_para(pid)
        if para and para["unit"] is None:
            m = RE_UNIT_LINE.search(title)
            if m:
                para["unit"] = _normalize_unit(m.group(1))

        # Строки и значения
        accepted_row_order = 0
        for r_i, row in enumerate(data_rows, 1):
            if not any(c.strip() for c in row):
                continue

            # Убираем дублирование текста из colspan:
            # если несколько соседних ячеек несут один и тот же текст —
            # оставляем его только в первой, остальные обнуляем
            row = _deduplicate_colspan_row(row)

            # Пропускаем строки без реальных данных нормы:
            # строка считается значимой если есть хотя бы одно число
            # (Н.вр. / № / любое числовое поле) или непустой уникальный текст
            if not _row_has_norm_data(row, clean_headers):
                continue

            accepted_row_order += 1
            rid = f"{tid}_r{accepted_row_order}"
            self.doc["norm_rows"].append({
                "row_id":         rid,
                "table_id":       tid,
                "row_order":      accepted_row_order,
                "source_row_num": r_i,
            })
            for c_i, key in enumerate(col_keys):
                val = row[c_i].strip() if c_i < len(row) else ""
                self.doc["norm_values"].append({
                    "row_id":     rid,
                    "column_key": key,
                    "value_type": _value_type(key, val, clean_headers[c_i] if c_i < len(clean_headers) else ""),
                    "value_text": val,
                })

        # Обновляем row_count реальным числом принятых строк
        self._update_row_count(tid, len([r for r in self.doc["norm_rows"]
                                         if r["table_id"] == tid]))

    def _update_row_count(self, tid: str, count: int):
        for t in self.doc["norm_tables"]:
            if t["table_id"] == tid:
                t["row_count"] = count
                return

    def _find_para(self, pid: str) -> Optional[Dict]:
        for p in self.doc["paragraphs"]:
            if p["paragraph_id"] == pid:
                return p
        return None


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════


def _deduplicate_colspan_row(row):
    """
    В строках с colspan несколько соседних ячеек несут одинаковый текст.
    Оставляем текст только в первой из группы дублей, остальные обнуляем.
    ["A","A","A","B"] -> ["A","","","B"]
    """
    result = list(row)
    i = 0
    while i < len(result):
        val = result[i].strip()
        if not val:
            i += 1
            continue
        j = i + 1
        while j < len(result) and result[j].strip() == val:
            result[j] = ""
            j += 1
        i = j
    return result


_RE_NUM = re.compile(r"\d")

def _clean(s: str) -> str:
    """Нормализует пробелы: убирает \r\n, двойные пробелы, trim."""
    if not s:
        return s
    return re.sub(r"\s+", " ", s).strip()

def _normalize_unit(s: str) -> str:
    """Приводит типовые единицы измерения к компактному виду: м 2 -> м2, м 3 -> м3."""
    s = _clean(s)
    s = re.sub(r"\bм\s+2\b", "м2", s, flags=re.I)
    s = re.sub(r"\bм\s+3\b", "м3", s, flags=re.I)
    s = re.sub(r"\bм\s*п\b", "м.п.", s, flags=re.I)
    s = re.sub(r"\bт\s+", "т ", s, flags=re.I)
    return s

def _row_has_norm_data(row, headers):
    """
    Определяет, является ли строка реальной строкой нормы, не опираясь на column_key.

    Логика:
      1. Если в строке есть числовые значения в колонках с заголовками вроде
         "Н.вр.", "Расц.", "№" — принимаем строку.
      2. Если в таблице вообще нет явно числовых служебных колонок, принимаем
         непустую строку, где есть содержательный текст вне первой колонки.
    """
    normish_positions = []
    for idx, h in enumerate(headers):
        hh = (h or "").strip()
        if not hh:
            continue
        if re.search(r"н\.?\s*вр|норм.*вр|расц|^№$|номер\s+строки", hh, re.I):
            normish_positions.append(idx)

    if normish_positions:
        for idx in normish_positions:
            val = row[idx].strip() if idx < len(row) else ""
            if val and _RE_NUM.search(val):
                return True
        return False

    # Описательная таблица без явных числовых колонок
    for c_i, cell in enumerate(row):
        val = cell.strip()
        if not val:
            continue
        if c_i > 0:
            return True
    return False


def _should_keep_as_application_note(text: str) -> bool:
    """
    Отсекает служебные заголовки и строки, которые должны жить
    в work_items / crew_items / notes / table titles, а не в application_notes.
    """
    t = _clean(text)
    if not t:
        return False

    if RE_APPLICATION_HEADING.match(t):
        return False

    # Чистые заголовки составов не должны попадать в application_notes
    if RE_CREW_ONLY_HEADING.match(t) or RE_WORK_ONLY_HEADING.match(t):
        return False

    # Если строка содержит явное описание рабочего состава, это не application note
    if RE_CREW_FULL.search(t) or RE_CREW_CONT.search(t):
        return False

    # Явные одиночные пункты состава работ тоже не храним как application note
    if RE_WORK_ITEM.match(t):
        return False

    # Голые заголовки таблиц / продолжений таблиц / фразы про нормы времени — мимо
    if t.lower().startswith(("таблица ", "табл. ", "продолжение табл", "окончание табл")):
        return False

    return True


def _empty_doc() -> Dict:
    return {
        "schema_version":   1,
        "source_file":      BASE_URL,
        "description":      "ЕНиР Сборник Е3 - Каменные работы",
        "collection_name":  "Е3",
        "collection_title": "КАМЕННЫЕ РАБОТЫ",
        "issue":            "",
        "issue_title":      "",
        "issuing_bodies": [
            "Государственный строительный комитет СССР",
            "Государственный комитет СССР по труду и социальным вопросам",
            "Секретариат ВЦСПС",
        ],
        "approval_date":    "1986-12-05",
        "approval_number":  "43/512/29-50",
        "developer":        "ПТИ Министерства строительства в северных и западных районах СССР",
        "coordination":     "ЦНИИСК им. Кучеренко Госстроя СССР",
        "amendments":       [],
        "has_intro":        False,
        "has_sections":     False,
        "sections":         [],
        "chapters":         [],
        "paragraphs":       [],
        "paragraph_work_items":  [],
        "paragraph_crew_items":  [],
        "paragraph_notes":       [],
        "norm_tables":      [],
        "norm_columns":     [],
        "norm_rows":        [],
        "norm_values":      [],
    }


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def parse_args():
    p = argparse.ArgumentParser(description="ЕНиР E3 - скрапер meganorm.ru")
    p.add_argument("--url",   default=BASE_URL,          help="URL страницы")
    p.add_argument("--out",   default="./output",        help="Папка вывода")
    p.add_argument("--cache", default="./cache_e3.html", help="Файл HTML-кэша")
    return p.parse_args()


def main():
    args    = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    soup = fetch_html(args.url, cache_path=Path(args.cache))

    log.info("Извлекаю ссылки ...")
    xrefs = extract_links(soup, args.url)
    xrefs_path = out_dir / "cross_references.json"
    xrefs_path.write_text(json.dumps(xrefs, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Ссылки -> %s  (внутр=%d  внешн=%d  якоря=%d)",
             xrefs_path,
             len(xrefs["internal_links"]),
             len(xrefs["external_links"]),
             len(xrefs["anchor_targets"]))

    log.info("Парсю документ ...")
    parser = EniRParser(soup, args.url)
    doc    = parser.parse()

    log.info("Результат: %d разд, %d глав, %d параграфов, %d таблиц, %d значений",
             len(doc["sections"]),
             len(doc["chapters"]),
             len(doc["paragraphs"]),
             len(doc["norm_tables"]),
             len(doc["norm_values"]))

    doc_path = out_dir / "enir_e3_canonical.json"
    doc_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("JSON -> %s", doc_path)

    _print_summary(doc, xrefs)
    log.info("Готово  Папка: %s", out_dir.resolve())


def _print_summary(doc: Dict, xrefs: Dict):
    print("\n" + "=" * 62)
    print(f"  ЕНиР {doc['collection_name']}  -  {doc['collection_title']}")
    print("=" * 62)
    print(f"  Разделы            : {len(doc['sections'])}")
    print(f"  Главы              : {len(doc['chapters'])}")
    print(f"  Параграфы          : {len(doc['paragraphs'])}")
    print(f"  Составы работ      : {len(doc['paragraph_work_items'])}")
    print(f"  Составы звеньев    : {len(doc['paragraph_crew_items'])}")
    print(f"  Примечания         : {len(doc['paragraph_notes'])}")
    print(f"  Таблиц норм        : {len(doc['norm_tables'])}")
    print(f"  Строк в таблицах   : {len(doc['norm_rows'])}")
    print(f"  Значений ячеек     : {len(doc['norm_values'])}")
    print()
    print(f"  Внутренние ссылки  : {len(xrefs['internal_links'])}")
    print(f"  Внешние ссылки     : {len(xrefs['external_links'])}")
    meganorm_ext = sum(1 for x in xrefs["external_links"] if x.get("is_meganorm"))
    print(f"    из них meganorm  : {meganorm_ext}")
    print(f"  Якоря (#targets)   : {len(xrefs['anchor_targets'])}")
    print("=" * 62 + "\n")


if __name__ == "__main__":
    main()
