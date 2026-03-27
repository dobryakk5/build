"""
validate_enir.py — структурная + числовая валидация ЕНиР Е3.

Два прохода:
  1. Автоматические проверки (без API): сравниваем JSON с XML, числовые аномалии.
     Параграфы без флагов считаются ОК.
  2. Параграфы с флагами отправляем в Qwen 2.5 VL — кроп страницы + JSON-данные.
     Qwen проверяет и возвращает исправленный JSON.

Использование:
  # Только авто-проверка (без Qwen):
  python3 validate_enir.py

  # Полный прогон с Qwen для флагнутых:
  python3 validate_enir.py --api-key KEY --pdf 22_ЕНиР_Сборник_Е_3.pdf

  # Один параграф:
  python3 validate_enir.py --api-key KEY --pdf ... --para Е3-4

  # Сохранить кропы для ручной проверки:
  python3 validate_enir.py --api-key KEY --pdf ... --save-crops

Опции:
  --json FILE         enir_e3.json (default: enir_e3.json)
  --docx FILE         word/document.xml распакованного docx
  --pdf  FILE         PDF для кропов (нужен для Qwen)
  --api-key KEY       OpenRouter API-ключ (или OPENROUTER_API_KEY в env)
  --para Е3-N         обработать один параграф
  --dpi  150          DPI рендера
  --out  FILE         куда писать результат (enir_e3_validated.json)
  --save-crops        сохранить PNG-кропы рядом со скриптом
  --no-qwen           только авто-проверка, без отправки в Qwen
"""

import argparse
import base64
import io
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# ─── Зависимости ──────────────────────────────────────────────────────────────

try:
    import requests
except ImportError:
    sys.exit("pip install requests --break-system-packages")

try:
    import xml.etree.ElementTree as ET
except ImportError:
    sys.exit("xml.etree.ElementTree не найден (стандартная библиотека)")

# ─── Константы ────────────────────────────────────────────────────────────────

OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'
MODEL          = 'qwen/qwen2.5-vl-72b-instruct:free'
PAGE_H_PT      = 841.9

XML_NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

PARA_RE = re.compile(r'^§\s*[ЕE][3З]-(\d+[а-яa-z]?)')
NORM_RE = re.compile(r'[Нн]орм[аы] времени')
CREW_RE = re.compile(r'[Сс]остав звена')
WORK_RE = re.compile(r'[Сс]остав работ')
PROF_RE = re.compile(r'([А-Яа-яёЁ][А-Яа-яёЁ\s\-]+?)\s+(\d)\s+разр')

# ─── Загрузка функций парсера (без запуска основного кода) ────────────────────

def load_parser_fns(docx_xml: str) -> dict:
    """Загружает parse_table и вспомогательные функции из parse_enir_v3.py."""
    script = Path(__file__).parent / 'parse_enir_v3.py'
    if not script.exists():
        sys.exit(f"Не найден {script}")
    src_lines = script.read_text(encoding='utf-8').split('\n')
    cutoff = next(
        i for i, l in enumerate(src_lines)
        if l.startswith('elements = []')
    )
    ns = {}
    exec(compile('\n'.join(src_lines[:cutoff]), str(script), 'exec'), ns)
    return ns


def get_text(el) -> str:
    return ''.join(t.text or '' for t in el.findall('.//w:t', XML_NS)).strip()


def build_elements(body, parse_table_fn) -> list:
    elements = []
    for el in body:
        tag = el.tag.split('}')[1] if '}' in el.tag else el.tag
        if tag == 'p':
            elements.append(('p', get_text(el).strip()))
        elif tag == 'tbl':
            elements.append(('tbl', parse_table_fn(el)))
    return elements


# ─── Авто-проверки ────────────────────────────────────────────────────────────

# Числовые аномалии (как в review_suspicious)
PRICE_MIN  = 0.001   # в ЕНиР реальны расценки 1–3 коп/м³
NORM_MAX   = 35.0
RATIO_MIN  = 0.01


def numeric_flags(norm: dict) -> list[str]:
    """Только числовые аномалии. work_type пуст и row_num=None — структурные, не числовые."""
    flags = []
    nv, pr = norm['norm_time'], norm['price_rub']
    if pr < PRICE_MIN:
        flags.append(f'price_rub={pr} мала')
    if nv > NORM_MAX:
        flags.append(f'norm_time={nv} велика')
    ratio = pr / nv if nv > 0 else None
    if ratio is not None and ratio < RATIO_MIN and nv > 1.0:
        flags.append(f'price/norm={ratio:.4f} мало')
    return flags


def structural_flags(para: dict, chunk: list) -> list[str]:
    """
    Сравнивает JSON-параграф с XML-чанком.
    Возвращает список флагов-строк.
    """
    flags = []

    # ── Нормы ─────────────────────────────────────────────────────────────────
    xml_norm_rows: set[int] = set()
    in_norm = False
    for typ, val in chunk:
        if typ == 'p' and NORM_RE.search(val):
            in_norm = True
        if in_norm and typ == 'tbl':
            for row in val:
                last = (row[-1] if row else '').strip()
                if re.match(r'^\d+$', last):
                    xml_norm_rows.add(int(last))

    json_row_nums = {n['row_num'] for n in para.get('norms', [])
                     if n['row_num'] is not None}

    if xml_norm_rows and not para.get('norms'):
        flags.append('NO_NORMS')
    elif xml_norm_rows:
        missing = xml_norm_rows - json_row_nums
        if missing:
            flags.append(f'MISSING_ROWS({sorted(missing)})')

    # ── Единица измерения ─────────────────────────────────────────────────────
    if para.get('unit') is None and xml_norm_rows:
        # "на измерители, указанные в таблице" — допустимо
        has_explicit_no_unit = any(
            typ == 'p' and 'измерители' in val and 'таблиц' in val
            for typ, val in chunk
        )
        if not has_explicit_no_unit:
            flags.append('NO_UNIT')

    # ── Состав звена ──────────────────────────────────────────────────────────
    has_crew_header = any(typ == 'p' and CREW_RE.search(val) for typ, val in chunk)
    if has_crew_header:
        xml_crew_lines = 0
        in_crew = False
        for typ, val in chunk:
            if typ == 'p' and CREW_RE.search(val):
                in_crew = True
            if in_crew and typ == 'tbl':
                for row in val:
                    if PROF_RE.search(' '.join(row)):
                        xml_crew_lines += 1
                break
        json_crew = len(para.get('crew', []))
        if xml_crew_lines > json_crew:
            flags.append(f'CREW_SHORT(xml={xml_crew_lines} json={json_crew})')

    # ── Состав работ ──────────────────────────────────────────────────────────
    has_work = any(typ == 'p' and WORK_RE.search(val) for typ, val in chunk)
    if has_work and not para.get('work_compositions'):
        flags.append('NO_WORK_COMP')

    # ── Структурные аномалии в нормах ─────────────────────────────────────────
    # (отдельно от числовых: не отправляются в Qwen, но видны в отчёте)
    no_wt   = sum(1 for n in para.get('norms', []) if not n.get('work_type'))
    no_rnum = sum(1 for n in para.get('norms', []) if n.get('row_num') is None)
    if no_wt:
        flags.append(f'EMPTY_WORK_TYPE({no_wt}норм)')
    if no_rnum:
        flags.append(f'NO_ROW_NUM({no_rnum}норм)')

    # ── Числовые аномалии в нормах ────────────────────────────────────────────
    num_bad = sum(1 for n in para.get('norms', []) if numeric_flags(n))
    if num_bad:
        flags.append(f'NUMERIC_ANOMALY({num_bad}норм)')

    return flags


# ─── Работа с PDF: page map и точечные кропы ─────────────────────────────────

def _get_convert():
    try:
        from pdf2image import convert_from_path
        return convert_from_path
    except ImportError:
        sys.exit("pip install pdf2image --break-system-packages")


def build_page_map(pdf_path: Path) -> dict[str, int]:
    r = subprocess.run(
        ['pdftotext', '-layout', str(pdf_path), '-'],
        capture_output=True, text=True
    )
    pages = r.stdout.split('\x0c')
    page_map: dict[str, int] = {}
    for pi, page in enumerate(pages, 1):
        for line in page.splitlines():
            m = re.match(r'^\s*§\s*[ЕE][3З]-(\d+[а-яa-z]?)', line.strip())
            if m:
                code = 'Е3-' + m.group(1)
                if code not in page_map:
                    page_map[code] = pi
    return page_map


def get_para_pages(code: str, page_map: dict, all_codes: list, total_pages: int) -> list[int]:
    start = page_map.get(code)
    if start is None:
        return []
    idx = all_codes.index(code) if code in all_codes else -1
    end = total_pages
    if idx >= 0:
        for nc in all_codes[idx + 1:]:
            if nc in page_map:
                end = page_map[nc]
                break
    end = min(end, start + 4)
    return list(range(start, end + 1))


def _parse_bbox_page(pdf_path: Path, page_num: int) -> dict[int, list[tuple]]:
    """
    Возвращает {y_rounded: [(x1, x2, text), ...]} для одной страницы.
    Использует pdftotext -bbox.
    """
    r = subprocess.run(
        ['pdftotext', '-bbox', '-f', str(page_num), '-l', str(page_num),
         str(pdf_path), '-'],
        capture_output=True, text=True
    )
    words = re.findall(
        r'<word[^>]+xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)"[^>]+>([^<]+)</word>',
        r.stdout
    )
    lines: dict[int, list] = defaultdict(list)
    for x1, y, x2, t in words:
        lines[round(float(y))].append((float(x1), float(x2), t.strip()))
    return lines


def _crop_y(pdf_path, page_num, y_top, y_bot, dpi, pad=15):
    """Вырезает горизонтальную полосу страницы между y_top и y_bot (в pt)."""
    convert = _get_convert()
    imgs = convert(str(pdf_path), dpi=dpi, first_page=page_num, last_page=page_num)
    img = imgs[0]
    w, h = img.size
    scale = h / PAGE_H_PT
    top    = max(0, int((y_top - pad) * scale))
    bottom = min(h, int((y_bot + pad) * scale))
    return img.crop((0, top, w, bottom))


def targeted_crops(pdf_path: Path, pages: list[int], flags: list[str],
                   para: dict, dpi: int = 150, save_prefix: str = '') -> list:
    """
    Строит минимальный набор кропов в зависимости от флагов.

    Логика по типу флага
    ────────────────────
    NUMERIC_ANOMALY / MISSING_ROWS
        Ищем в PDF строки таблицы по row_num из проблемных норм.
        Кроп = заголовок норм + проблемные строки ± 2 строки.

    CREW_SHORT
        Кроп от «Состав звена» до следующего раздела.

    NO_WORK_COMP
        Кроп от «Состав работ» до следующего раздела.

    NO_UNIT / NO_NORMS / work_type пуст (весь столбец заголовков пуст)
        Кроп от «Нормы времени» до «Примечани» — но только нужная таблица.

    Если bbox-поиск не нашёл нужных y-координат — кроп всей зоны норм страницы.
    """
    # Выясняем какие row_num нас интересуют — используем ту же функцию что и валидатор
    bad_row_nums: set[int] = set()
    for n in para.get('norms', []):
        if numeric_flags(n) and n.get('row_num') is not None:
            bad_row_nums.add(n['row_num'])

    flag_types = {f.split('(')[0] for f in flags}

    # Нужен ли кроп состава звена / работ?
    need_crew = 'CREW_SHORT' in flag_types
    need_work = 'NO_WORK_COMP' in flag_types
    need_norms = bool(flag_types - {'CREW_SHORT', 'NO_WORK_COMP'})

    crops = []

    for page_num in pages:
        lines = _parse_bbox_page(pdf_path, page_num)
        sorted_ys = sorted(lines)

        def line_text(y):
            return ' '.join(t for _, _, t in sorted(lines[y]))

        def find_y(pattern):
            for y in sorted_ys:
                if re.search(pattern, line_text(y)):
                    return y
            return None

        def row_height():
            """Приблизительная высота строки таблицы в pt."""
            gaps = [sorted_ys[i+1] - sorted_ys[i]
                    for i in range(len(sorted_ys)-1)
                    if 8 < sorted_ys[i+1] - sorted_ys[i] < 30]
            return (sum(gaps)/len(gaps)) if gaps else 14.0

        rh = row_height()

        # ── Кроп состава звена ────────────────────────────────────────────────
        if need_crew:
            y_crew = find_y(r'[Сс]остав звена')
            if y_crew:
                # До следующего раздела или начала норм
                y_end_crew = find_y(r'[Нн]ормы\s+времени|[Тт]аблица\s+\d')
                if y_end_crew is None or y_end_crew <= y_crew:
                    y_end_crew = y_crew + rh * 8
                c = _crop_y(pdf_path, page_num, y_crew, y_end_crew, dpi)
                crops.append((c, f'стр {page_num}: звено y={y_crew:.0f}–{y_end_crew:.0f}'))
                if save_prefix:
                    c.save(f'{save_prefix}_p{page_num}_crew.png')

        # ── Кроп состава работ ────────────────────────────────────────────────
        if need_work:
            y_work = find_y(r'[Сс]остав работ')
            if y_work:
                y_end_work = find_y(r'[Сс]остав звена|[Нн]ормы\s+времени|[Тт]аблица\s+\d')
                if y_end_work is None or y_end_work <= y_work:
                    y_end_work = y_work + rh * 10
                c = _crop_y(pdf_path, page_num, y_work, y_end_work, dpi)
                crops.append((c, f'стр {page_num}: работы y={y_work:.0f}–{y_end_work:.0f}'))
                if save_prefix:
                    c.save(f'{save_prefix}_p{page_num}_work.png')

        # ── Кроп таблицы норм (точечный) ─────────────────────────────────────
        if need_norms:
            y_norm_hdr = find_y(r'[Нн]ормы\s+времени')
            if y_norm_hdr is None:
                continue

            # Конец таблицы: «Примечани» или следующий «§»
            y_norm_end = find_y(r'^[Пп]римечани|^§\s*[ЕE]')
            if y_norm_end is None or y_norm_end <= y_norm_hdr:
                y_norm_end = PAGE_H_PT - 10

            if bad_row_nums:
                # Ищем y конкретных строк: числа из bad_row_nums в правой части
                # (колонка «№» обычно правее 400pt)
                row_y: dict[int, float] = {}
                for y in sorted_ys:
                    if not (y_norm_hdr < y < y_norm_end):
                        continue
                    for x1, x2, t in lines[y]:
                        if x1 > 380 and re.match(r'^\d+$', t):
                            rn = int(t)
                            if rn in bad_row_nums and rn not in row_y:
                                row_y[rn] = y

                if row_y:
                    # Кроп: от заголовка норм до последней проблемной строки + контекст
                    ctx = rh * 2          # 2 строки контекста
                    y_bot = max(row_y.values()) + ctx
                    # Но не выходим за конец таблицы
                    y_bot = min(y_bot, y_norm_end)
                    c = _crop_y(pdf_path, page_num, y_norm_hdr, y_bot, dpi)
                    label = f'стр {page_num}: нормы y={y_norm_hdr:.0f}–{y_bot:.0f} rows={sorted(row_y)}'
                    crops.append((c, label))
                    if save_prefix:
                        c.save(f'{save_prefix}_p{page_num}_norms.png')
                    continue  # нашли — не нужен fallback

            # Fallback: вся зона норм страницы
            c = _crop_y(pdf_path, page_num, y_norm_hdr, y_norm_end, dpi)
            crops.append((c, f'стр {page_num}: нормы y={y_norm_hdr:.0f}–{y_norm_end:.0f} (все)'))
            if save_prefix:
                c.save(f'{save_prefix}_p{page_num}_norms_full.png')

    return crops


def images_to_b64(crops) -> list[str]:
    """Принимает список (PIL.Image, label) или просто PIL.Image."""
    result = []
    for item in crops:
        img = item[0] if isinstance(item, tuple) else item
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        result.append(base64.b64encode(buf.getvalue()).decode())
    return result


# ─── Запрос к Qwen ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Ты — эксперт по советским строительным нормативам ЕНиР.
Тебе дают фрагмент страницы (кроп нужной части) и конкретную проблему для проверки.
Верни ТОЛЬКО JSON без пояснений и markdown. Структура:
{
  "code": "Е3-N",
  "ok": true/false,
  "issues_found": ["описание найденной проблемы или 'всё верно'"],
  "corrections": [
    {
      "field": "norms[row_num=4][column_label=а].price_rub",
      "old": 0.01,
      "new": правильное_значение
    }
  ]
}
Если данные верны — верни ok=true и пустой corrections=[].
Формат цен: "4,33-01" → norm_time=4.33, price_rub=0.01; "5-64" → price_rub=5.64."""


def ask_qwen(api_key: str, code: str, crops: list,
             problem_desc: str, context_json: dict,
             retries: int = 2) -> dict:
    """
    crops      — список (PIL.Image, label) из targeted_crops
    problem_desc — конкретное описание проблемы (не весь список флагов)
    context_json — только релевантные данные (не весь параграф)
    """
    crop_labels = [label for _, label in crops]
    user_text = (
        f"Параграф {code}.\n"
        f"Проблема: {problem_desc}\n\n"
        f"Данные парсера (только релевантная часть):\n"
        f"{json.dumps(context_json, ensure_ascii=False, indent=2)}\n\n"
        f"Кропы: {'; '.join(crop_labels)}\n"
        f"Проверь по изображению и верни corrections JSON."
    )

    content: list = [{'type': 'text', 'text': user_text}]
    for b64 in images_to_b64(crops):
        content.append({'type': 'image_url',
                         'image_url': {'url': f'data:image/png;base64,{b64}'}})

    payload = {
        'model': MODEL,
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user',   'content': content},
        ],
        'max_tokens': 800,
        'temperature': 0.1,
    }

    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                OPENROUTER_URL,
                headers={'Authorization': f'Bearer {api_key}',
                         'Content-Type': 'application/json'},
                json=payload, timeout=90,
            )
            resp.raise_for_status()
            raw = resp.json()['choices'][0]['message']['content']
            clean = re.sub(r'^```(?:json)?\s*', '', raw.strip(), flags=re.MULTILINE)
            clean = re.sub(r'\s*```$', '',          clean.strip(), flags=re.MULTILINE)
            return json.loads(clean)
        except (requests.exceptions.Timeout, requests.HTTPError) as e:
            last_err = e
            print(f'    ⚠ {type(e).__name__} (попытка {attempt+1}/{retries+1}), повтор...')
        except json.JSONDecodeError as e:
            return {'code': code, 'ok': False,
                    'error': f'JSONDecodeError: {e}', 'raw': raw}

    return {'code': code, 'ok': False, 'error': str(last_err)}


# ─── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description='Валидация ЕНиР Е3')
    ap.add_argument('--json',       default='enir_e3.json')
    ap.add_argument('--docx',       default='unpacked_e3/word/document.xml')
    ap.add_argument('--pdf',        default=None,
                    help='PDF файл (нужен для Qwen; без него только авто-проверка)')
    ap.add_argument('--api-key',    default=os.environ.get('OPENROUTER_API_KEY', ''))
    ap.add_argument('--para',       default=None)
    ap.add_argument('--dpi',        type=int, default=150)
    ap.add_argument('--out',        default='enir_e3_validated.json')
    ap.add_argument('--save-crops', action='store_true')
    ap.add_argument('--no-qwen',    action='store_true',
                    help='Только авто-проверка, не отправлять в Qwen')
    args = ap.parse_args()

    use_qwen = (not args.no_qwen and bool(args.api_key) and args.pdf is not None)
    if not use_qwen and not args.no_qwen:
        if not args.api_key:
            print('ℹ  --api-key не задан → только авто-проверка (--no-qwen)')
        if not args.pdf:
            print('ℹ  --pdf не задан    → только авто-проверка')

    # ── Загрузка данных ──────────────────────────────────────────────────────
    data: list[dict] = json.loads(Path(args.json).read_text(encoding='utf-8'))
    para_by_code = {p['code']: p for p in data}

    fns = load_parser_fns(args.docx)
    tree = ET.parse(args.docx)
    body = tree.getroot().find('.//w:body', XML_NS)
    elements = build_elements(body, fns['parse_table'])

    para_starts = [i for i, (t, v) in enumerate(elements)
                   if t == 'p' and PARA_RE.match(v)]
    all_codes = []
    for s in para_starts:
        m = PARA_RE.match(elements[s][1])
        if m:
            all_codes.append('Е3-' + m.group(1))

    # ── Авто-проверка ────────────────────────────────────────────────────────
    flagged: list[tuple[str, list[str]]] = []   # (code, flags)

    target_codes = [args.para] if args.para else all_codes

    print(f"\n{'Параграф':10s} {'Норм':6s} {'Флаги'}")
    print('─' * 60)

    for pi, (start, code) in enumerate(zip(para_starts, all_codes)):
        if code not in target_codes:
            continue
        end = para_starts[pi + 1] if pi + 1 < len(para_starts) else len(elements)
        chunk = elements[start:end]
        para = para_by_code.get(code, {})

        flags = structural_flags(para, chunk)

        n_norms = len(para.get('norms', []))
        flag_str = '  '.join(flags) if flags else '✓'
        marker = '⚠ ' if flags else '  '
        print(f"{marker}{code:10s} {n_norms:6d}  {flag_str}")

        if flags:
            flagged.append((code, flags))

    print()
    print(f'Чистых: {len(target_codes) - len(flagged)}/{len(target_codes)}')
    if flagged:
        print(f'К проверке: {len(flagged)} параграфов — '
              f'{", ".join(c for c,_ in flagged)}')

    if not flagged:
        print('\nВсе параграфы прошли валидацию ✓')
        return

    # ── Qwen-проверка: по одному запросу на каждый флаг ─────────────────────
    if not use_qwen:
        print('\nQwen не используется (задай --api-key и --pdf для допроверки).')
        return

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit(f'PDF не найден: {pdf_path}')

    r = subprocess.run(['pdfinfo', str(pdf_path)], capture_output=True, text=True)
    m = re.search(r'Pages:\s+(\d+)', r.stdout)
    total_pages = int(m.group(1)) if m else 40

    page_map = build_page_map(pdf_path)
    results: dict[str, list] = {}   # code → [correction_obj, ...]


    for code, flags in flagged:
        print(f'\n── {code} ──')
        pages = get_para_pages(code, page_map, all_codes, total_pages)
        if not pages:
            print('  страница не найдена, пропускаем')
            continue

        para = para_by_code.get(code, {'code': code})
        save_pfx = code.replace('-', '_') if args.save_crops else ''
        flag_types = {f.split('(')[0] for f in flags}
        code_results = []

        # ── Запрос 1: числовые аномалии в нормах ─────────────────────────────
        numeric_bad = [
            n for n in para.get('norms', [])
            if numeric_flags(n)
        ]
        if numeric_bad and flag_types & {'NUMERIC_ANOMALY'}:
            bad_rows = {n['row_num'] for n in numeric_bad if n['row_num']}
            problem = (
                f"Аномальные нормы (строки №{sorted(bad_rows)}):\n"
                + '\n'.join(
                    f"  №{n['row_num']}[{n.get('column_label','')}] "
                    f"norm_time={n['norm_time']} price_rub={n['price_rub']} "
                    f"— {numeric_flags(n)}"
                    for n in numeric_bad
                )
            )
            context = {
                'norms': [
                    n for n in para['norms']
                    if n.get('row_num') in bad_rows
                    or (bad_rows and n.get('row_num') and
                        min(abs(n['row_num'] - r) for r in bad_rows) <= 2)
                ]
            }
            crops = targeted_crops(pdf_path, pages, flags, para, args.dpi, save_pfx)
            print(f'  [числовые] {len(numeric_bad)} норм, {len(crops)} кропов → Qwen...')
            res = ask_qwen(args.api_key, code, crops, problem, context)
            code_results.append({'type': 'NUMERIC', 'result': res})
            ok = res.get('ok', False)
            corr = res.get('corrections', [])
            print(f'  {"✓" if ok else "✗"} corrections={len(corr)}  '
                  f'issues={res.get("issues_found", [])}')

        # ── Запрос 2: неполный состав звена ──────────────────────────────────
        if 'CREW_SHORT' in flag_types:
            crew_flags = [f for f in flags if 'CREW' in f]
            problem = f"Неполный состав звена: {', '.join(crew_flags)}"
            context = {'crew': para.get('crew', [])}
            # Кроп только зоны состава звена
            crew_only_flags = ['CREW_SHORT']
            crops = targeted_crops(pdf_path, pages, crew_only_flags, para, args.dpi, save_pfx)
            print(f'  [звено] {len(crops)} кропов → Qwen...')
            res = ask_qwen(args.api_key, code, crops, problem, context)
            code_results.append({'type': 'CREW', 'result': res})
            print(f'  {"✓" if res.get("ok") else "✗"} corrections={len(res.get("corrections",[]))}')

        # ── Запрос 3: отсутствует состав работ ───────────────────────────────
        if 'NO_WORK_COMP' in flag_types:
            problem = 'В JSON нет состава работ, хотя в документе есть раздел «Состав работ»'
            context = {'work_compositions': para.get('work_compositions', [])}
            work_only_flags = ['NO_WORK_COMP']
            crops = targeted_crops(pdf_path, pages, work_only_flags, para, args.dpi, save_pfx)
            print(f'  [работы] {len(crops)} кропов → Qwen...')
            res = ask_qwen(args.api_key, code, crops, problem, context)
            code_results.append({'type': 'WORK_COMP', 'result': res})
            print(f'  {"✓" if res.get("ok") else "✗"} corrections={len(res.get("corrections",[]))}')

        # ── Запрос 4: пропущенные строки / нет норм ───────────────────────────
        if flag_types & {'NO_NORMS', 'MISSING_ROWS', 'NO_UNIT'}:
            other_flags = [f for f in flags
                           if any(t in f for t in ('NO_NORMS', 'MISSING_ROWS', 'NO_UNIT'))]
            problem = f"Структурные проблемы: {', '.join(other_flags)}"
            context = {
                'unit': para.get('unit'),
                'norms_count': len(para.get('norms', [])),
                'norms_sample': para.get('norms', [])[:5],
            }
            struct_flags = ['NO_NORMS'] if 'NO_NORMS' in flag_types else flags
            crops = targeted_crops(pdf_path, pages, struct_flags, para, args.dpi, save_pfx)
            print(f'  [структура] {len(crops)} кропов → Qwen...')
            res = ask_qwen(args.api_key, code, crops, problem, context)
            code_results.append({'type': 'STRUCTURAL', 'result': res})
            print(f'  {"✓" if res.get("ok") else "✗"} corrections={len(res.get("corrections",[]))}')

        results[code] = code_results

    out_path = Path(args.out)
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    total_corrections = sum(
        len(r['result'].get('corrections', []))
        for runs in results.values()
        for r in runs
    )
    print(f'\nСохранено: {out_path}')
    print(f'Параграфов проверено: {len(results)}, всего corrections: {total_corrections}')


if __name__ == '__main__':
    main()
