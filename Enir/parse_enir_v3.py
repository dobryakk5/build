import argparse
import xml.etree.ElementTree as ET
import re
import json
from pathlib import Path

_ap = argparse.ArgumentParser(description='Парсер ЕНиР Е3 из docx')
_ap.add_argument('--docx', default='unpacked_e3/word/document.xml',
                 help='Путь к word/document.xml распакованного docx')
_ap.add_argument('--out',  default='enir_e3.json',
                 help='Куда писать JSON (default: enir_e3.json рядом со скриптом)')
# parse_known_args чтобы не падать при exec из validate_enir.py
_args, _ = _ap.parse_known_args()

tree = ET.parse(_args.docx)
root = tree.getroot()
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
body = root.find('.//w:body', ns)

def get_text(el):
    return ''.join(t.text or '' for t in el.findall('.//w:t', ns))

def is_vmerge_continue(cell):
    vm = cell.find('.//w:vMerge', ns)
    if vm is None:
        return False
    return vm.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '') != 'restart'

def get_grid_span(cell):
    """Возвращает горизонтальный span ячейки (w:gridSpan), минимум 1."""
    gs = cell.find(
        './/{http://schemas.openxmlformats.org/wordprocessingml/2006/main}gridSpan', ns
    )
    if gs is None:
        return 1
    try:
        return int(gs.get(
            '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '1'
        ))
    except ValueError:
        return 1

def parse_table(tbl):
    """
    Строит прямоугольную сетку с учётом:
      - vMerge (объединение по вертикали) — берём значение из предыдущей строки
      - gridSpan (объединение по горизонтали) — дублируем значение в соседние колонки
    """
    rows = tbl.findall('w:tr', ns)
    grid = []
    prev = {}  # col_idx → value (для vMerge)

    for row in rows:
        cells   = row.findall('w:tc', ns)
        row_map = {}   # col_idx → value (строим через dict, потом в list)
        col_idx = 0

        for cell in cells:
            span = get_grid_span(cell)

            if is_vmerge_continue(cell):
                val = prev.get(col_idx, '')
            else:
                val = get_text(cell).strip()

            for s in range(span):
                row_map[col_idx + s] = val

            col_idx += span

        max_col = max(row_map.keys()) + 1 if row_map else 0
        vals    = [row_map.get(i, '') for i in range(max_col)]
        prev    = dict(enumerate(vals))
        grid.append(vals)

    return grid

# ─── Парсинг значений ─────────────────────────────────────────────────────────

def parse_norm_combined(raw):
    """
    Разбирает объединённое значение "норма + цена" из ячейки таблицы.
    Три формата из-за артефактов XML/OCR:

    STD:    "2,92-16"    → norm=2.92, price=0.16  (16 коп)
    SPACE:  "3 2-24"     → norm=3,    price=2.24  (пробел разделяет норму и цену)
    MERGED: "11,410-03"  → norm=11.4, price=10.03 (цифры слиплись: "11,4" + "10-03")
    """
    if not raw or raw == '-':
        return None

    # SPACE: "3 2-24" или "2,6 1-94" → пробел разделяет норму и цену (руб-коп)
    sp = re.match(r'^(\d+[,\.]?\d*)\s+(\d+-\d+)$', raw.strip())
    if sp:
        try:
            norm  = float(sp.group(1).replace(',', '.'))
            price = parse_price_separate(sp.group(2))
            if price is not None:
                return {'norm_time': norm, 'price_rub': price}
        except ValueError:
            pass

    raw = re.sub(r'\s+', '', raw).replace(',', '.')

    # MERGED: "11.410-03" → 3+ цифр в дробной части → ищем N откушенных цифр справа
    mm = re.match(r'^(\d+\.\d{3,})-(\d+(?:\.\d+)?)$', raw)
    if mm:
        full_dec = mm.group(1)  # "11.410"
        rest     = mm.group(2)  # "03"
        int_part = full_dec.split('.')[0]
        dec_part = full_dec.split('.')[1]
        for n in range(1, len(dec_part)):
            norm_dec  = dec_part[:-n]
            stolen    = dec_part[-n:]
            price_str = stolen + '-' + rest
            price     = parse_price_separate(price_str)
            norm_str  = int_part + ('.' + norm_dec if norm_dec else '')
            try:
                norm = float(norm_str)
            except ValueError:
                continue
            if price is not None and norm > 0 and price / norm > 0.05:
                return {'norm_time': norm, 'price_rub': price}

    # STD: "2.92-16" → последние 2 цифры = копейки
    # Пробуем раньше SPLITDIGIT: если норма ≤ 20 — она реалистична сама по себе.
    m = re.match(r'^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)$', raw)
    if not m:
        return None
    norm    = float(m.group(1))
    kopecks = float(m.group(2))
    if kopecks > 99.9:      # "380-460" — диапазон, не норма
        return None
    if norm <= 20:
        return {'norm_time': norm, 'price_rub': round(kopecks / 100.0, 4)}

    # SPLITDIGIT: норма > 20 → скорее всего две цифры слиплись с ценой ("42-80").
    # Паттерн XY-ZZ: первая цифра = норма, XY без X = начало цены.
    sd = re.match(r'^(\d)(\d)-(\d{2})$', raw)
    if sd:
        price    = parse_price_separate(sd.group(2) + '-' + sd.group(3))
        norm_sd  = float(sd.group(1))
        if price is not None and norm_sd > 0 and price / norm_sd > 0.1:
            return {'norm_time': norm_sd, 'price_rub': price}

    # Fallback: возвращаем STD-интерпретацию даже при большой норме
    return {'norm_time': norm, 'price_rub': round(kopecks / 100.0, 4)}

def is_norm_combined(s):
    return parse_norm_combined(s) is not None

def parse_float(raw):
    raw = re.sub(r'\s+', '', raw).replace(',', '.')
    if not raw or raw == '-':
        return None
    try:
        return float(raw)
    except ValueError:
        return None

def parse_price_separate(raw):
    """Парсит "6-78" → 6.78, "0-37,9" → 0.379"""
    raw = re.sub(r'\s+', '', raw).replace(',', '.')
    if not raw or raw == '-':
        return None
    m = re.match(r'^(\d+)-(\d+(?:\.\d+)?)$', raw)
    if m:
        return round(int(m.group(1)) + float(m.group(2)) / 100.0, 4)
    return None

# ─── Определение формата таблицы ─────────────────────────────────────────────

# detect_table_format удалена — логика встроена в parse_norms_table

# ─── Парсинг горизонтальных секций ───────────────────────────────────────────

def _parse_horizontal(grid, fallback_work_type=''):
    """
    Парсит таблицы где условия — колонки, а не строки.
    Пример (Е3-11, Е3-26 секция Б, Е3-20 секция Б).
    
    Сегментирует по однострочным заголовкам-категориям.
    """
    norms = []
    row_num_counter = 1

    # Разбиваем на секции по строкам с одной ячейкой (категория)
    sections = []
    current = {'category': fallback_work_type, 'rows': []}
    for row in grid:
        non_empty = [c for c in row if c.strip()]
        is_category = (
            len(non_empty) == 1
            and not is_norm_combined(non_empty[0])
            and not re.match(r'^[а-яёa-zА-ЯA-Z]{1,2}$', non_empty[0])
            and len(non_empty[0]) > 3
        )
        if is_category:
            if current['rows']:
                sections.append(current)
            current = {'category': non_empty[0], 'rows': []}
        else:
            current['rows'].append(row)
    if current['rows']:
        sections.append(current)

    for section in sections:
        rows = section['rows']
        category = section['category']

        # Находим строку с данными — у неё больше всего combined-значений
        data_row_idx = None
        for ri, row in enumerate(rows):
            norm_count = sum(1 for c in row if is_norm_combined(c))
            if norm_count > 0:
                data_row_idx = ri
                break
        if data_row_idx is None:
            continue

        # Условия — строка прямо перед данными
        conditions = []
        if data_row_idx > 0:
            conditions = [c.strip() for c in rows[data_row_idx - 1]]

        data_row = rows[data_row_idx]
        for ci, cell in enumerate(data_row):
            val = parse_norm_combined(cell)
            if val is None:
                continue
            cond = conditions[ci] if ci < len(conditions) else ''
            norms.append({
                'row_num': row_num_counter,
                'work_type': category,
                'condition': cond,
                'thickness_mm': None,
                'norm_time': val['norm_time'],
                'price_rub': val['price_rub']
            })
            row_num_counter += 1

    return norms

# ─── Парсинг combined-таблиц (вертикальный формат) ───────────────────────────

def _parse_combined(grid):
    # Разделяем на заголовочные строки и строки с данными
    data_rows = [row for row in grid if any(is_norm_combined(c) for c in row)]
    header_rows = [row for row in grid if not any(is_norm_combined(c) for c in row)]

    # Если ни одна строка данных не имеет числового номера → горизонтальный формат
    any_row_num = any(
        re.match(r'^\d+$', (row[-1] if row else '').strip())
        for row in data_rows
    )
    if not any_row_num:
        work_type = _get_header_text(header_rows)
        return _parse_horizontal(grid, work_type)

    # Ищем колонки с толщинами в заголовках (вертикальный формат с параметром)
    thickness_by_col = {}
    for row in header_rows:
        prev_val = None
        for ci, cell in enumerate(row):
            v = cell.strip()
            if re.match(r'^\d{3,4}$', v):
                # Пропускаем смежные дубли (артефакт gridSpan)
                if v != prev_val:
                    thickness_by_col[ci] = int(v)
            prev_val = v if v else prev_val
    thickness_sorted = sorted(thickness_by_col.items())

    # Буквенные метки колонок (а, б, в...) из последней заголовочной строки
    col_labels: dict[int, str] = {}
    for row in header_rows:
        for ci, cell in enumerate(row):
            cs = cell.strip()
            if re.match(r'^[а-яa-z]$', cs, re.IGNORECASE):
                col_labels[ci] = cs

    norms = []
    current_work_type = ''
    current_condition = ''

    for row in grid:
        last = (row[-1] if row else '').strip()
        row_num = int(last) if re.match(r'^\d+$', last) else None

        if row_num is None:
            # Заголовочная строка — обновляем контекст
            for ci, cell in enumerate(row):
                cell = cell.strip()
                if (cell and ci == 0
                        and not is_norm_combined(cell)
                        and not re.match(r'^\d{3,4}$', cell)
                        and not re.match(r'^\d{3,4}-\d{3,4}$', cell)
                        and len(cell) > 3
                        and len(cell) < 100):
                    current_work_type = cell
            continue

        # Обновляем work_type / condition из нечисловых ячеек строки
        for ci in range(min(3, len(row) - 1)):
            cell = row[ci].strip()
            if not cell or is_norm_combined(cell) or re.match(r'^\d+$', cell):
                continue
            # Диапазон толщин типа "380-460" → condition, не work_type
            if re.match(r'^\d{3,4}-\d{3,4}$', cell):
                current_condition = cell
                continue
            # Слишком длинный текст — это состав работ, не тип работы
            if len(cell) > 100:
                continue
            if ci == 0:
                if cell[0].islower() and current_work_type:
                    old_wt = re.sub(r'\s+', ' ', current_work_type).strip()
                    current_work_type = current_work_type.rstrip() + ' ' + cell
                    new_wt = re.sub(r'\s+', ' ', current_work_type).strip()
                    for n in norms:
                        if n['work_type'] == old_wt:
                            n['work_type'] = new_wt
                else:
                    current_work_type = cell
            else:
                current_condition = cell

        # Все комбинированные значения в строке.
        # Соседние одинаковые ячейки — артефакт раскрытия gridSpan, берём только первую.
        norm_vals = []
        prev_raw = None
        for ci, c in enumerate(row[:-1]):
            if c == prev_raw:
                continue          # дубль от gridSpan — пропускаем
            val = parse_norm_combined(c)
            if val is not None:
                norm_vals.append((ci, val))
            prev_raw = c if c.strip() else prev_raw

        # Сопоставляем с толщинами по относительной позиции
        for i, (ci, val) in enumerate(norm_vals):
            thickness = thickness_sorted[i][1] if i < len(thickness_sorted) else None
            col_label = col_labels.get(ci, '')
            norms.append({
                'row_num': row_num,
                'work_type': re.sub(r'\s+', ' ', current_work_type).strip(),
                'condition': re.sub(r'\s+', ' ', current_condition).strip(),
                'thickness_mm': thickness,
                'column_label': col_label,
                'norm_time': val['norm_time'],
                'price_rub': val['price_rub']
            })

    return norms

def _get_header_text(header_rows):
    for row in header_rows:
        for cell in row:
            cell = cell.strip()
            if cell and len(cell) > 5 and not re.match(r'^[\dа-яa-z]+$', cell):
                return cell
    return ''

# ─── Парсинг separate-таблиц ─────────────────────────────────────────────────

def _parse_separate(grid):
    """
    Парсит таблицы с явными колонками Н.вр. и Расц.
    Использует позиции колонок из заголовка, с допуском на смещение.
    """
    norms = []

    # Позиции заголовков Н.вр. и Расц.
    nv_cols, rc_cols, num_col = [], [], None
    for row in grid:
        for ci, c in enumerate(row):
            cs = c.strip()
            # Пропускаем смежные дубли — артефакт раскрытия gridSpan:
            # если предыдущая колонка уже записана с тем же значением, это
            # продолжение объединённой ячейки, а не новая независимая колонка.
            if cs == 'Н.вр.':
                if not nv_cols or ci != nv_cols[-1] + 1:
                    nv_cols.append(ci)
            elif cs == 'Расц.':
                if not rc_cols or ci != rc_cols[-1] + 1:
                    rc_cols.append(ci)
            elif cs == '№' and num_col is None:
                num_col = ci

    current_work_type = ''
    current_condition = ''

    for row in grid:
        # Пропускаем заголовочные строки
        if any(c.strip() in ('Н.вр.', 'Расц.', '№', 'а', 'б', 'в', 'г', 'д', 'е', 'ж') for c in row):
            continue

        # row_num
        row_num = None
        for col in ([num_col] if num_col is not None else []) + [-1]:
            if col is not None and abs(col) < len(row):
                s = row[col].strip()
                if re.match(r'^\d+$', s):
                    row_num = int(s)
                    break

        # Ищем пары (Н.вр., Расц.) по позициям из заголовка
        pairs_found = []
        for nv_ci, rc_ci in zip(nv_cols, rc_cols):
            nv, rc = None, None
            # Ищем float в окрестности nv_ci (допуск 1 колонка на сдвиг строки)
            for offset in range(2):
                idx = nv_ci + offset
                if 0 <= idx < len(row):
                    nv = parse_float(row[idx])
                    if nv is not None:
                        break
            # Ищем цену в окрестности rc_ci
            for offset in range(2):
                idx = rc_ci + offset
                if 0 <= idx < len(row):
                    rc = parse_price_separate(row[idx])
                    if rc is not None:
                        break
            if nv is not None and rc is not None:
                # Буква колонки (а,б,в...) из заголовка
                col_label = ''
                for row in grid:
                    cs = row[nv_ci].strip() if nv_ci < len(row) else ''
                    if re.match(r'^[а-яa-z]$', cs, re.IGNORECASE):
                        col_label = cs
                        break
                pairs_found.append({'norm_time': nv, 'price_rub': rc, 'column_label': col_label})

        if not pairs_found:
            # Обновляем контекст из текстовых ячеек
            for ci, cell in enumerate(row):
                cell = cell.strip()
                if not cell or parse_float(cell) or parse_price_separate(cell):
                    continue
                if ci == 0:
                    current_work_type = cell
                else:
                    current_condition = cell
            continue

        # Обновляем work_type / condition из нечисловых ячеек начала строки
        for ci, cell in enumerate(row):
            cell_s = cell.strip()
            if not cell_s:
                continue
            if parse_float(cell_s) or parse_price_separate(cell_s) or re.match(r'^\d+$', cell_s):
                break
            if len(cell_s) > 100:
                continue  # состав работ, не тип работы
            if ci == 0:
                # Если текст начинается с маленькой буквы — это продолжение
                # предыдущей строки (перенос), а не новый вид работы
                if cell_s[0].islower() and current_work_type:
                    old_wt = re.sub(r'\s+', ' ', current_work_type).strip()
                    current_work_type = current_work_type.rstrip() + ' ' + cell_s
                    new_wt = re.sub(r'\s+', ' ', current_work_type).strip()
                    # Ретроактивно обновляем уже добавленные нормы со старым work_type
                    for n in norms:
                        if n['work_type'] == old_wt:
                            n['work_type'] = new_wt
                else:
                    current_work_type = cell_s
            else:
                current_condition = cell_s

        for pair in pairs_found:
            norms.append({
                'row_num': row_num,
                'work_type': re.sub(r'\s+', ' ', current_work_type).strip(),
                'condition': re.sub(r'\s+', ' ', current_condition).strip(),
                'thickness_mm': None,
                'column_label': pair.get('column_label', ''),
                'norm_time': pair['norm_time'],
                'price_rub': pair['price_rub']
            })

    return norms

# ─── Главный диспетчер ───────────────────────────────────────────────────────

def parse_norms_table(grid):
    """
    Если таблица имеет заголовки Н.вр./Расц. — пробуем separate-парсер первым.
    Если он не даёт норм (например, Н.вр. и Расц. в одной колонке) — используем combined.
    """
    flat = ' '.join(c for row in grid for c in row)
    if 'Н.вр.' in flat and 'Расц.' in flat:
        sep = _parse_separate(grid)
        if sep:
            return sep
    return _parse_combined(grid)

# ─── Вспомогательные ─────────────────────────────────────────────────────────

def parse_crew_table(grid):
    crew = []
    for row in grid:
        row_text = ' '.join(row)
        m = re.search(r'([А-Яа-яёЁ][А-Яа-яёЁ\s\(\)]+?)\s+(\d)\s+разр', row_text)
        if not m:
            continue
        profession = m.group(1).strip().strip('"«»').strip()
        grade = int(m.group(2))
        for val in row:
            if re.match(r'^\d+$', val.strip()):
                crew.append({'profession': profession, 'grade': grade, 'count': int(val.strip())})
    return crew

def parse_notes(texts):
    notes = []
    full = ' '.join(texts)
    parts = re.split(r'(?<!\d)(?<!\.)(\d+)\.\s+', full)
    i = 1
    while i < len(parts) - 1:
        num_str = parts[i]
        text = (parts[i + 1] if i + 1 < len(parts) else '').strip()
        if num_str.isdigit() and text:
            num = int(num_str)
            coef = None
            code = None
            cm = re.search(r'умножать на\s+([\d,\.]+)', text)
            if cm:
                coef = float(cm.group(1).replace(',', '.'))
            codm = re.search(r'\(([А-ЯA-Z]+-\d+)\)', text)
            if codm:
                code = codm.group(1)
            notes.append({'num': num, 'text': text.rstrip('. '), 'coefficient': coef, 'code': code})
        i += 2
    if not notes and re.match(r'[Пп]римечание', full):
        text = re.sub(r'^[Пп]римечание\.?\s*', '', full).strip()
        if text:
            coef = None
            cm = re.search(r'умножать на\s+([\d,\.]+)', text)
            if cm:
                coef = float(cm.group(1).replace(',', '.'))
            notes.append({'num': 1, 'text': text, 'coefficient': coef, 'code': None})
    return notes

# ─── Сборка документа ────────────────────────────────────────────────────────

elements = []
for el in body:
    tag = el.tag.split('}')[1] if '}' in el.tag else el.tag
    if tag == 'p':
        style_el = el.find('.//w:pStyle', ns)
        style = style_el.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', 'Normal') \
            if style_el is not None else 'Normal'
        elements.append(('p', style, get_text(el).strip()))
    elif tag == 'tbl':
        elements.append(('tbl', None, parse_table(el)))

PARA_RE = re.compile(r'^§\s*[ЕE][3З]-\d+')
para_starts = [i for i, (t, s, v) in enumerate(elements) if t == 'p' and PARA_RE.match(v)]

# ─── Парсинг параграфов ──────────────────────────────────────────────────────

def extract_code(text):
    m = re.search(r'[ЕE][3З]-(\d+[а-яa-z]?)', text)
    return 'Е3-' + m.group(1) if m else ''

NORM_HEADER_RE = re.compile(r'[Нн]орм[аы] времени')

paragraphs = []

for pi, start in enumerate(para_starts):
    end = para_starts[pi + 1] if pi + 1 < len(para_starts) else len(elements)
    chunk = elements[start:end]

    # Код и заголовок
    SECTION_HEADERS = re.compile(
        r'^(Состав\s+работ|Состав\s+звена|Нормы\s+времени|Примечани'
        r'|Таблица\s+\d|Указания\s+по)'
    )
    title_lines = []
    for typ, style, text in chunk[:8]:
        if typ == 'p' and text:
            if SECTION_HEADERS.match(text):
                break
            title_lines.append(text)
            if len(title_lines) >= 2:
                break
    full_title = ' '.join(title_lines)
    code = extract_code(full_title)
    title = PARA_RE.sub('', full_title).lstrip('. ').strip()

    # Единица измерения
    unit = None
    for typ, style, text in chunk:
        if typ == 'p' and re.search(r'[Нн]орм[аы]|[Рр]асценк[аи]', text):
            um = re.search(r'[Нн]а\s+\d+\s+([\w³²/]+(?:\s+[\w³²/]+){0,3})', text)
            if um:
                unit = um.group(1).strip()
                break

    # Состав работ
    work_compositions = []
    in_works = False
    current_cond = None
    current_ops = []

    for typ, style, text in chunk:
        if typ == 'tbl' and in_works:
            if current_cond and current_ops:
                work_compositions.append({'condition': current_cond, 'operations': current_ops})
            in_works = False; current_cond = None; current_ops = []
            continue
        if typ != 'p':
            continue
        if re.match(r'[Сс]остав работ', text):   # "работ" и "работы"
            in_works = True; continue
        if re.match(
            r'[Сс]остав звена|[Тт]аблица\s+\d'
            r'|[Нн]орм[аы]\s+|[Рр]асценк'
            r'|[Кк]аменщик|[Пп]ечник|[Мм]ашинист',
            text
        ) and in_works:
            if current_ops:   # сохраняем даже при пустом условии
                work_compositions.append({'condition': current_cond or '', 'operations': current_ops})
            in_works = False; current_cond = None; current_ops = []
            continue
        if not in_works:
            continue
        if re.match(r'^\d+\.', text):
            ops = re.split(r'\s+(?=\d+\.)', text)
            current_ops = [o.strip() for o in ops if o.strip()]
        elif text:
            if current_ops:   # сохраняем накопленное перед сменой условия
                work_compositions.append({'condition': current_cond or '', 'operations': current_ops})
                current_ops = []
            current_cond = text
    if in_works and current_ops:
        work_compositions.append({'condition': current_cond or '', 'operations': current_ops})

    # Состав звена, нормы, примечания
    crew = []
    norms = []
    notes_raw = []
    in_notes = False
    processed_tbl_ids: set = set()   # id() таблиц, уже включённых в нормы

    CREW_P_RE = re.compile(
        r'([А-Яа-яёЁ][А-Яа-яёЁ\s\-]+?)\s+(\d)\s+разр'
    )

    for i, (typ, style, text) in enumerate(chunk):
        if typ == 'p':
            if re.search(r'[Сс]остав звена', text):
                # Сначала ищем таблицу
                next_tbls = [v for t, s, v in chunk[i:] if t == 'tbl']
                if next_tbls:
                    crew = parse_crew_table(next_tbls[0])
                else:
                    # Состав звена записан в параграфах
                    for _, _, crew_text in chunk[i + 1:i + 6]:
                        for m in CREW_P_RE.finditer(crew_text):
                            profession = m.group(1).strip().strip('"«»').strip()
                            grade      = int(m.group(2))
                            # Количество — первое число после совпадения или 1
                            count_m = re.search(r'\s+(\d+)\s*$', crew_text[m.end():])
                            count   = int(count_m.group(1)) if count_m else 1
                            crew.append({'profession': profession,
                                         'grade': grade, 'count': count})

            # Crew в одном параграфе (без заголовка "Состав звена")
            if not crew and CREW_P_RE.search(text) and not re.search(r'[Сс]остав', text):
                for m in CREW_P_RE.finditer(text):
                    profession = m.group(1).strip().strip('"«»').strip()
                    grade      = int(m.group(2))
                    count_m    = re.search(r'\s+(\d+)\s*(?:чел|$)', text[m.end():])
                    count      = int(count_m.group(1)) if count_m else 1
                    crew.append({'profession': profession,
                                 'grade': grade, 'count': count})

            if NORM_HEADER_RE.search(text):
                # Каждая секция норм обрабатывается независимо (А., Б. и т.д.)
                # processed_tbl_ids запоминает id() уже добавленных grid-объектов,
                # чтобы не включать одну таблицу дважды при нескольких NORM_HEADER.
                section_tables = []
                for t2, s2, v2 in chunk[i + 1:]:
                    if t2 == 'tbl':
                        if id(v2) not in processed_tbl_ids:
                            section_tables.append(v2)
                            processed_tbl_ids.add(id(v2))
                    elif t2 == 'p' and v2 and (
                        re.search(r'^[Пп]римечани', v2) or
                        NORM_HEADER_RE.search(v2)
                    ):
                        break
                if section_tables:
                    section_grid = [row for g in section_tables for row in g]
                    norms.extend(parse_norms_table(section_grid))

            if re.search(r'^[Пп]римечани', text):
                in_notes = True
            if in_notes and text:
                notes_raw.append(text)

    notes = parse_notes(notes_raw)

    paragraphs.append({
        'code': code,
        'title': title,
        'unit': unit,
        'work_compositions': work_compositions,
        'crew': crew,
        'norms': norms,
        'notes': notes
    })

# ─── Вывод ───────────────────────────────────────────────────────────────────

# Подчищаем unit: обрезаем хвостовые стоп-слова и артефакты Н.вр.
_UNIT_STOP = re.compile(
    r'\s+(или|и|с|в|Н\.вр\.|Расц\.|по|от|для|из|а|до)(?:\s.*)?$',
    re.IGNORECASE
)
for p in paragraphs:
    if p['unit']:
        p['unit'] = _UNIT_STOP.sub('', p['unit']).strip()

out_path = Path(_args.out)
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(paragraphs, f, ensure_ascii=False, indent=2)
print(f"JSON сохранён: {out_path.resolve()}")

print(f"Параграфов: {len(paragraphs)}")
total_norms = sum(len(p['norms']) for p in paragraphs)
print(f"Всего норм: {total_norms}\n")
for p in paragraphs:
    flag = '' if p['norms'] or p['unit'] is None else ''
    print(f"  {p['code']:8s}  норм={len(p['norms']):3d}  звено={len(p['crew']):2d}  примеч={len(p['notes']):2d}  unit={p['unit']}")
