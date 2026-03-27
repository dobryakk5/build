import csv
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


# =========================
# НАСТРОЙКИ
# =========================
BASE_URL = "https://fgisrf.ru"
ROOT_URL = f"{BASE_URL}/fer/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

OUT_DIR = Path("fgisrf_fer_dump")
TABLES_DIR = OUT_DIR / "tables"

REQUEST_DELAY = 0.3
TIMEOUT = 30
RETRIES = 3

# Ограничения для теста
MAX_COLLECTIONS = 3
MAX_TABLES_PER_COLLECTION = 1

# Делать ли общий файл по строкам всех таблиц
WRITE_COMBINED_ROWS_FILE = True

NAV_PREFIXES = ("Сборник ", "Раздел ", "Подраздел ", "Таблица ")

TABLE_TITLE_RE = re.compile(r"^Таблица\s+(\d{2}-\d{2}-\d{3})\.\s*(.+)$")
COLLECTION_RE = re.compile(r"^Сборник\s+(\d{2})\.\s*(.+)$")


session = requests.Session()
session.headers.update(HEADERS)


# =========================
# УТИЛИТЫ
# =========================
def clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def safe_name(value: str) -> str:
    value = value.replace("№", "No")
    value = re.sub(r'[\\/*?:"<>|]+', "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:180]


def fetch_soup(url: str) -> BeautifulSoup:
    last_error = None

    for attempt in range(1, RETRIES + 1):
        try:
            response = session.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            response.encoding = "utf-8"
            return BeautifulSoup(response.text, "html.parser")
        except Exception as e:
            last_error = e
            print(f"[WARN] {url} | attempt {attempt}/{RETRIES} | {e}")
            time.sleep(1.5 * attempt)

    raise RuntimeError(f"Не удалось загрузить {url}: {last_error}")


def get_page_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        return clean_text(h1.get_text(" ", strip=True))

    if soup.title:
        return clean_text(soup.title.get_text(" ", strip=True))

    return ""


def iter_nav_links(soup: BeautifulSoup, base_url: str):
    seen = set()

    for a in soup.find_all("a", href=True):
        text = clean_text(a.get_text(" ", strip=True))
        if not text.startswith(NAV_PREFIXES):
            continue

        href = urljoin(base_url, a["href"]).split("#")[0]

        if not href.startswith(ROOT_URL):
            continue

        if href in seen:
            continue

        seen.add(href)
        yield text, href


def split_table_title(title: str):
    m = TABLE_TITLE_RE.match(title)
    if not m:
        return "", title
    return m.group(1), m.group(2)


def split_collection_title(title: str):
    m = COLLECTION_RE.match(title)
    if not m:
        return "", title
    return m.group(1), m.group(2)


def make_unique_headers(headers):
    result = []
    used = {}

    for i, header in enumerate(headers, start=1):
        h = clean_text(header)
        if not h:
            h = f"col_{i}"

        base = h
        if base in used:
            used[base] += 1
            h = f"{base} ({used[base]})"
        else:
            used[base] = 1

        result.append(h)

    return result


def get_collection_links():
    soup = fetch_soup(ROOT_URL)
    collections = []

    for text, href in iter_nav_links(soup, ROOT_URL):
        if text.startswith("Сборник "):
            collections.append((text, href))

    def sort_key(item):
        text = item[0]
        m = re.search(r"Сборник\s+(\d{2})", text)
        return int(m.group(1)) if m else 999

    collections.sort(key=sort_key)

    if MAX_COLLECTIONS is not None:
        collections = collections[:MAX_COLLECTIONS]

    return collections


def longest_common_prefix(strings):
    if not strings:
        return ""

    strings = [s for s in strings if s]
    if not strings:
        return ""

    s1 = min(strings)
    s2 = max(strings)

    i = 0
    max_len = min(len(s1), len(s2))
    while i < max_len and s1[i] == s2[i]:
        i += 1

    return s1[:i]


def find_description_header(headers):
    """
    Пытаемся автоматически найти колонку с описанием работ.
    """
    priorities = [
        "Наименование и характеристика работ и конструкций",
        "Наименование работ",
        "Наименование и характеристика",
        "Наименование",
    ]

    lower_map = {h.lower(): h for h in headers}

    for p in priorities:
        if p.lower() in lower_map:
            return lower_map[p.lower()]

    for h in headers:
        hl = h.lower()
        if "наименование" in hl:
            return h

    return None


def normalize_common_work_name(raw_prefix: str) -> str:
    """
    Нормализация общего повторяющегося названия.
    """
    if not raw_prefix:
        return ""

    text = clean_text(raw_prefix).strip()

    # убираем только хвостовые пробелы/запятые/точки с запятой,
    # двоеточие оставляем, т.к. оно часто смысловое
    text = text.rstrip(" ,;")
    return text


# =========================
# ПАРСИНГ ТАБЛИЦЫ
# =========================
def extract_table_records(soup: BeautifulSoup, page_url: str):
    """
    Возвращает:
    - headers: заголовки таблицы
    - records: список словарей по строкам
    """
    table = soup.find("table")
    if table is None:
        return [], []

    raw_rows = []

    for tr in table.find_all("tr"):
        cell_tags = tr.find_all(["th", "td"])
        if not cell_tags:
            continue

        cells = []
        row_slug = ""

        for idx, cell in enumerate(cell_tags):
            cells.append(clean_text(cell.get_text(" ", strip=True)))

            if idx == 0:
                a = cell.find("a", href=True)
                if a:
                    row_slug = a["href"].strip()

        if any(cells):
            raw_rows.append({
                "cells": cells,
                "row_slug": row_slug,
            })

    if not raw_rows:
        return [], []

    header_row = raw_rows[0]["cells"]
    headers = make_unique_headers(header_row)

    records = []
    for raw in raw_rows[1:]:
        values = raw["cells"][:]

        if len(values) < len(headers):
            values.extend([""] * (len(headers) - len(values)))
        elif len(values) > len(headers):
            values = values[:len(headers)]

        record = {
            "row_slug": raw["row_slug"],
        }

        for header, value in zip(headers, values):
            record[header] = value

        records.append(record)

    return headers, records


def transform_records(headers, records):
    """
    1) Убираем row_url и Номер расценки
    2) Оставляем только row_slug
    3) Автоматически выделяем общий повторяющийся фрагмент описания в common_work_name
    4) В строки кладём только 'Уточнение'
    """
    if not records:
        return [], [], "", ""

    description_header = find_description_header(headers)

    common_work_name = ""
    raw_prefix = ""

    if description_header:
        descriptions = [
            clean_text(r.get(description_header, ""))
            for r in records
            if clean_text(r.get(description_header, ""))
        ]

        unique_descriptions = list(dict.fromkeys(descriptions))

        if len(unique_descriptions) >= 2:
            raw_prefix = longest_common_prefix(unique_descriptions)
            raw_prefix = raw_prefix.rstrip()
            common_work_name = normalize_common_work_name(raw_prefix)

            # защита от слишком короткого/бесполезного префикса
            if len(common_work_name) < 15:
                raw_prefix = ""
                common_work_name = ""

    output_headers = ["row_slug"]

    if description_header:
        output_headers.append("Уточнение")

    for h in headers:
        if h == "Номер расценки":
            continue
        if h == description_header:
            continue
        output_headers.append(h)

    output_records = []

    for r in records:
        out = {
            "row_slug": r.get("row_slug", "")
        }

        if description_header:
            full_desc = clean_text(r.get(description_header, ""))

            if raw_prefix and full_desc.startswith(raw_prefix):
                suffix = full_desc[len(raw_prefix):].strip()
            else:
                suffix = full_desc

            out["Уточнение"] = suffix

        for h in headers:
            if h == "Номер расценки":
                continue
            if h == description_header:
                continue
            out[h] = r.get(h, "")

        output_records.append(out)

    return output_headers, output_records, description_header, common_work_name


# =========================
# СОХРАНЕНИЕ
# =========================
def save_table_csv(meta: dict, output_headers: list[str], output_records: list[dict]) -> str:
    collection_num = meta.get("collection_num") or "XX"
    folder = TABLES_DIR / f"sbornik_{collection_num}"
    folder.mkdir(parents=True, exist_ok=True)

    filename = f"{meta['table_code'] or safe_name(meta['table_title'])}.csv"
    filepath = folder / filename

    with filepath.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=output_headers)
        writer.writeheader()
        for record in output_records:
            writer.writerow(record)

    return str(filepath.relative_to(OUT_DIR))


def write_tables_index(tables_index: list[dict]):
    out_file = OUT_DIR / "tables_index.csv"
    fieldnames = [
        "collection_num",
        "collection_name",
        "collection",
        "section",
        "subsection",
        "table_code",
        "table_title",
        "table_url",
        "table_file",
        "row_count",
        "description_header",
        "common_work_name",
        "path",
    ]

    with out_file.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(tables_index)


def write_combined_rows(all_records: list[dict]):
    if not all_records:
        return

    out_file = OUT_DIR / "all_rows_combined.csv"

    base_fields = [
        "collection_num",
        "collection_name",
        "collection",
        "section",
        "subsection",
        "table_code",
        "table_title",
        "table_url",
        "table_file",
        "path",
    ]

    extra_fields = []
    seen = set()

    for row in all_records:
        for key in row.keys():
            if key not in base_fields and key not in seen:
                seen.add(key)
                extra_fields.append(key)

    fieldnames = base_fields + extra_fields

    with out_file.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_records)


# =========================
# ОБХОД
# =========================
def crawl_collection(
    url: str,
    parent_path: list[str],
    visited: set,
    tables_index: list,
    combined_rows: list,
    collection_state: dict,
):
    if collection_state["tables_found"] >= MAX_TABLES_PER_COLLECTION:
        return

    if url in visited:
        return

    visited.add(url)
    time.sleep(REQUEST_DELAY)

    soup = fetch_soup(url)
    title = get_page_title(soup) or url
    current_path = parent_path + [title]

    print(f"[PAGE] {title}")

    if title.startswith("Таблица "):
        headers, records = extract_table_records(soup, url)

        if records:
            output_headers, output_records, description_header, common_work_name = transform_records(headers, records)

            table_code, table_title = split_table_title(title)

            collection = next((x for x in current_path if x.startswith("Сборник ")), "")
            section = next((x for x in current_path if x.startswith("Раздел ")), "")
            subsection = next((x for x in current_path if x.startswith("Подраздел ")), "")

            collection_num, collection_name = split_collection_title(collection)

            meta = {
                "collection_num": collection_num,
                "collection_name": collection_name,
                "collection": collection,
                "section": section,
                "subsection": subsection,
                "table_code": table_code,
                "table_title": table_title,
                "table_url": url,
                "row_count": len(output_records),
                "description_header": description_header or "",
                "common_work_name": common_work_name,
                "path": " > ".join(current_path),
            }

            table_file = save_table_csv(meta, output_headers, output_records)
            meta["table_file"] = table_file
            tables_index.append(meta)

            if WRITE_COMBINED_ROWS_FILE:
                for record in output_records:
                    full_record = {
                        "collection_num": collection_num,
                        "collection_name": collection_name,
                        "collection": collection,
                        "section": section,
                        "subsection": subsection,
                        "table_code": table_code,
                        "table_title": table_title,
                        "table_url": url,
                        "table_file": table_file,
                        "path": meta["path"],
                    }

                    for k, v in record.items():
                        full_record[k] = v

                    combined_rows.append(full_record)

            collection_state["tables_found"] += 1
            print(
                f"[OK] Сохранена таблица {table_code or table_title} "
                f"| строк: {len(output_records)} "
                f"| common_work_name: {common_work_name[:80] if common_work_name else '-'}"
            )
        else:
            print(f"[WARN] Таблица не найдена или пустая: {url}")

        if collection_state["tables_found"] >= MAX_TABLES_PER_COLLECTION:
            return

    for _, child_url in iter_nav_links(soup, url):
        if collection_state["tables_found"] >= MAX_TABLES_PER_COLLECTION:
            break

        if child_url not in visited:
            crawl_collection(
                url=child_url,
                parent_path=current_path,
                visited=visited,
                tables_index=tables_index,
                combined_rows=combined_rows,
                collection_state=collection_state,
            )


# =========================
# MAIN
# =========================
def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)

    collections = get_collection_links()

    print(f"Найдено сборников для обхода: {len(collections)}")
    print(f"Лимит таблиц на сборник: {MAX_TABLES_PER_COLLECTION}")

    visited_global = set()
    tables_index = []
    combined_rows = []

    for i, (collection_title, collection_url) in enumerate(collections, start=1):
        print(f"\n=== [{i}/{len(collections)}] {collection_title} ===")

        collection_state = {"tables_found": 0}

        crawl_collection(
            url=collection_url,
            parent_path=[],
            visited=visited_global,
            tables_index=tables_index,
            combined_rows=combined_rows,
            collection_state=collection_state,
        )

        print(
            f"[DONE] {collection_title}: собрано таблиц = "
            f"{collection_state['tables_found']}"
        )

    write_tables_index(tables_index)

    if WRITE_COMBINED_ROWS_FILE:
        write_combined_rows(combined_rows)

    print("\nГотово.")
    print(f"Сборников обработано: {len(collections)}")
    print(f"Таблиц сохранено: {len(tables_index)}")
    if WRITE_COMBINED_ROWS_FILE:
        print(f"Строк в объединённом файле: {len(combined_rows)}")
    print(f"Результат: {OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
