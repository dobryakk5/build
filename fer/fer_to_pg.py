import re
import time
import os
from pathlib import Path
from urllib.parse import urljoin

import psycopg2
import psycopg2.extras
import requests
from bs4 import BeautifulSoup

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


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

DB_SCHEMA = "fer"
DEFAULT_DSN = "postgresql://user:password@localhost:5432/fgisrf"

REQUEST_DELAY = 0.3
TIMEOUT = 30
RETRIES = 3

# Ограничения для теста (None = без лимита)
MAX_COLLECTIONS = None
MAX_TABLES_PER_COLLECTION = None

NAV_PREFIXES = ("Сборник ", "Раздел ", "Подраздел ", "Таблица ")

TABLE_TITLE_RE  = re.compile(r"^Таблица\s+(\d{2}-\d{2}-\d{3})\.\s*(.+)$")
COLLECTION_RE   = re.compile(r"^Сборник\s+(\d{2})\.\s*(.+)$")
TABLE_CODE_RE   = re.compile(r"tablitsa-(\d{2}-\d{2}-\d{3})", re.IGNORECASE)

session = requests.Session()
session.headers.update(HEADERS)


# =========================
# УТИЛИТЫ
# =========================
def clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def fetch_soup(url: str) -> BeautifulSoup:
    last_error = None
    for attempt in range(1, RETRIES + 1):
        try:
            r = session.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            r.encoding = "utf-8"
            return BeautifulSoup(r.text, "html.parser")
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
        if not href.startswith(ROOT_URL) or href in seen:
            continue
        seen.add(href)
        yield text, href


def table_code_from_url(url: str) -> str | None:
    m = TABLE_CODE_RE.search(url)
    return m.group(1) if m else None


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


def longest_common_prefix(strings):
    strings = [s for s in strings if s]
    if not strings:
        return ""
    s1, s2 = min(strings), max(strings)
    i = 0
    while i < min(len(s1), len(s2)) and s1[i] == s2[i]:
        i += 1
    return s1[:i]


def find_description_header(headers):
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
        if "наименование" in h.lower():
            return h
    return None


def normalize_common_work_name(raw: str) -> str:
    return raw.rstrip(" ,;").strip() if raw else ""


def to_numeric(value: str) -> float | None:
    if not value:
        return None
    try:
        return float(value.replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def load_psycopg2_dsn() -> str:
    database_url = os.getenv("DATABASE_URL")

    if not database_url and load_dotenv is not None:
        backend_env = Path(__file__).resolve().parents[1] / "backend" / ".env"
        if backend_env.exists():
            load_dotenv(backend_env, override=False)
            database_url = os.getenv("DATABASE_URL")

    if not database_url:
        return DEFAULT_DSN

    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    return database_url


def table_limit_reached(collection_state: dict) -> bool:
    return (
        MAX_TABLES_PER_COLLECTION is not None
        and collection_state["tables_found"] >= MAX_TABLES_PER_COLLECTION
    )


# =========================
# ПАРСИНГ ТАБЛИЦЫ
# =========================
def extract_table_records(soup: BeautifulSoup):
    table = soup.find("table")
    if table is None:
        return [], []

    raw_rows = []
    for tr in table.find_all("tr"):
        cells_tags = tr.find_all(["th", "td"])
        if not cells_tags:
            continue
        cells = []
        row_slug = ""
        for idx, cell in enumerate(cells_tags):
            cells.append(clean_text(cell.get_text(" ", strip=True)))
            if idx == 0:
                a = cell.find("a", href=True)
                if a:
                    row_slug = a["href"].strip()
        if any(cells):
            raw_rows.append({"cells": cells, "row_slug": row_slug})

    if not raw_rows:
        return [], []

    headers = make_unique_headers(raw_rows[0]["cells"])
    records = []
    for raw in raw_rows[1:]:
        values = raw["cells"][:]
        if len(values) < len(headers):
            values.extend([""] * (len(headers) - len(values)))
        elif len(values) > len(headers):
            values = values[:len(headers)]
        record = {"row_slug": raw["row_slug"]}
        for h, v in zip(headers, values):
            record[h] = v
        records.append(record)

    return headers, records


def transform_records(headers, records):
    if not records:
        return [], []

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
            raw_prefix = longest_common_prefix(unique_descriptions).rstrip()
            common_work_name = normalize_common_work_name(raw_prefix)
            if len(common_work_name) < 15:
                raw_prefix = ""
                common_work_name = ""

    # последние два столбца — числовые (чел./ч и маш./ч)
    numeric_headers = [h for h in headers if h not in ("Номер расценки", description_header)]

    output_records = []
    for r in records:
        full_desc = clean_text(r.get(description_header, "")) if description_header else ""
        if raw_prefix and full_desc.startswith(raw_prefix):
            clarification = full_desc[len(raw_prefix):].strip()
        else:
            clarification = full_desc

        nums = []
        for h in numeric_headers:
            nums.append(to_numeric(r.get(h, "")))

        h_hour = nums[-2] if len(nums) >= 2 else (nums[0] if len(nums) == 1 else None)
        m_hour = nums[-1] if len(nums) >= 2 else None

        output_records.append({
            "row_slug":     r.get("row_slug", ""),
            "clarification": clarification,
            "h_hour":       h_hour,
            "m_hour":       m_hour,
        })

    return common_work_name, output_records


# =========================
# БД: UPSERT-ХЕЛПЕРЫ
# =========================
def upsert_collection(cur, num: str, name: str) -> int:
    cur.execute("""
        INSERT INTO collections (num, name)
        VALUES (%s, %s)
        ON CONFLICT (num) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
    """, (num, name))
    return cur.fetchone()[0]


def upsert_section(cur, collection_id: int, title: str) -> int:
    cur.execute("""
        INSERT INTO sections (collection_id, title)
        VALUES (%s, %s)
        ON CONFLICT (collection_id, title) DO NOTHING
        RETURNING id
    """, (collection_id, title))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("SELECT id FROM sections WHERE collection_id = %s AND title = %s",
                (collection_id, title))
    return cur.fetchone()[0]


def upsert_subsection(cur, section_id: int, title: str) -> int:
    cur.execute("""
        INSERT INTO subsections (section_id, title)
        VALUES (%s, %s)
        ON CONFLICT (section_id, title) DO NOTHING
        RETURNING id
    """, (section_id, title))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("SELECT id FROM subsections WHERE section_id = %s AND title = %s",
                (section_id, title))
    return cur.fetchone()[0]


def upsert_fer_table(cur, data: dict) -> int | None:
    cur.execute("""
        INSERT INTO fer_tables (
            collection_id, section_id, subsection_id,
            table_title, table_url, row_count, common_work_name
        )
        VALUES (%(collection_id)s, %(section_id)s, %(subsection_id)s,
                %(table_title)s, %(table_url)s, %(row_count)s, %(common_work_name)s)
        ON CONFLICT (table_url) DO UPDATE SET
            row_count        = EXCLUDED.row_count,
            common_work_name = EXCLUDED.common_work_name,
            scraped_at       = NOW()
        RETURNING id
    """, data)
    row = cur.fetchone()
    return row[0] if row else None


def insert_rows(cur, table_id: int, records: list[dict]):
    cur.execute("DELETE FROM fer_rows WHERE table_id = %s", (table_id,))
    psycopg2.extras.execute_values(cur, """
        INSERT INTO fer_rows (table_id, row_slug, clarification, h_hour, m_hour)
        VALUES %s
    """, [
        (table_id, r["row_slug"], r["clarification"], r["h_hour"], r["m_hour"])
        for r in records
    ])


# =========================
# ОБХОД
# =========================
def crawl_collection(url, parent_path, visited, conn, collection_state):
    if table_limit_reached(collection_state):
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
        headers, records = extract_table_records(soup)

        if records:
            common_work_name, output_records = transform_records(headers, records)

            collection_title = next((x for x in current_path if x.startswith("Сборник ")), "")
            section_title    = next((x for x in current_path if x.startswith("Раздел ")), "")
            subsection_title = next((x for x in current_path if x.startswith("Подраздел ")), "")

            col_num, col_name = split_collection_title(collection_title)

            with conn.cursor() as cur:
                col_id = upsert_collection(cur, col_num, col_name)

                sec_id = None
                if section_title:
                    sec_id = upsert_section(cur, col_id, section_title)

                sub_id = None
                if subsection_title and sec_id:
                    sub_id = upsert_subsection(cur, sec_id, subsection_title)

                table_title = re.sub(r"^Таблица\s+[\d\-]+\.\s*", "", title)

                table_id = upsert_fer_table(cur, {
                    "collection_id":    col_id,
                    "section_id":       sec_id,
                    "subsection_id":    sub_id,
                    "table_title":      table_title,
                    "table_url":        url,
                    "row_count":        len(output_records),
                    "common_work_name": common_work_name,
                })

                if table_id:
                    insert_rows(cur, table_id, output_records)

            conn.commit()
            collection_state["tables_found"] += 1
            print(f"[OK] {title} | строк: {len(output_records)}")
        else:
            print(f"[WARN] Пустая таблица: {url}")

        if table_limit_reached(collection_state):
            return

    for _, child_url in iter_nav_links(soup, url):
        if table_limit_reached(collection_state):
            break
        if child_url not in visited:
            crawl_collection(child_url, current_path, visited, conn, collection_state)


def get_collection_links():
    soup = fetch_soup(ROOT_URL)
    collections = []
    for text, href in iter_nav_links(soup, ROOT_URL):
        if text.startswith("Сборник "):
            collections.append((text, href))

    collections.sort(key=lambda x: int(m.group(1)) if (m := re.search(r"Сборник\s+(\d{2})", x[0])) else 999)

    if MAX_COLLECTIONS is not None:
        collections = collections[:MAX_COLLECTIONS]
    return collections


# =========================
# MAIN
# =========================
def main():
    conn = psycopg2.connect(
        load_psycopg2_dsn(),
        options=f"-c search_path={DB_SCHEMA},public",
    )

    try:
        collections = get_collection_links()
        print(f"Найдено сборников: {len(collections)}")

        visited = set()

        for i, (col_title, col_url) in enumerate(collections, start=1):
            print(f"\n=== [{i}/{len(collections)}] {col_title} ===")
            state = {"tables_found": 0}
            crawl_collection(col_url, [], visited, conn, state)
            print(f"[DONE] таблиц загружено: {state['tables_found']}")

    finally:
        conn.close()

    print("\nГотово.")


if __name__ == "__main__":
    main()
