"""
load_enir.py — загружает enir_e3.json в БД.

SQLite (тест, без зависимостей):
    python3 load_enir.py --db sqlite:///enir_e3.db

PostgreSQL (продакшн):
    python3 load_enir.py --db postgresql://user:pass@host/dbname

Опции:
    --json FILE     путь к JSON (enir_e3.json)
    --para Е3-N     загрузить один параграф
    --drop          пересоздать таблицы перед загрузкой
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Профессии, которые могут просочиться в нормы из-за нестандартных таблиц
CREW_LEAK_RE = re.compile(r'\d\s+разр|Известегасильщик|Машинист|Печник')

# ─── Адаптер: SQLite vs PostgreSQL ────────────────────────────────────────────

def get_connection(db_url: str):
    """
    Возвращает (conn, placeholder) где placeholder — '?' (SQLite) или '%s' (PG).
    Оба коннектора реализуют DB-API 2.0, поэтому остальной код одинаков.
    """
    if db_url.startswith('sqlite'):
        import sqlite3
        path = db_url.replace('sqlite:///', '')
        conn = sqlite3.connect(path)
        conn.execute('PRAGMA foreign_keys = ON')
        conn.row_factory = sqlite3.Row
        return conn, '?'
    elif db_url.startswith('postgresql') or db_url.startswith('postgres'):
        import psycopg2
        conn = psycopg2.connect(db_url)
        return conn, '%s'
    else:
        sys.exit(f'Неизвестный драйвер: {db_url}')


# ─── DDL ──────────────────────────────────────────────────────────────────────

# SQLite не поддерживает SERIAL/NUMERIC — используем INTEGER/REAL.
# PostgreSQL использует нативные типы.
# Вместо ветвления — один DDL с маркерами, которые заменяются по драйверу.

DDL_PARAGRAPHS = """
CREATE TABLE IF NOT EXISTS paragraphs (
    id    {serial}     PRIMARY KEY,
    code  VARCHAR(16)  NOT NULL UNIQUE,
    title TEXT         NOT NULL,
    unit  VARCHAR(64)
)"""

DDL_NORMS = """
CREATE TABLE IF NOT EXISTS norms (
    id            {serial}      PRIMARY KEY,
    paragraph_id  INTEGER       NOT NULL REFERENCES paragraphs(id) ON DELETE CASCADE,
    row_num       INTEGER,              -- NULL для горизонтальных таблиц без №
    work_type     TEXT          NOT NULL DEFAULT '',
    condition     TEXT          NOT NULL DEFAULT '',
    thickness_mm  INTEGER,
    norm_time     {decimal}     NOT NULL,
    price_rub     {decimal}     NOT NULL,
    column_label  VARCHAR(4)    NOT NULL DEFAULT ''
)"""

DDL_CREW = """
CREATE TABLE IF NOT EXISTS crew_members (
    id            {serial}      PRIMARY KEY,
    paragraph_id  INTEGER       NOT NULL REFERENCES paragraphs(id) ON DELETE CASCADE,
    profession    VARCHAR(128)  NOT NULL,
    grade         INTEGER       NOT NULL,
    count         INTEGER       NOT NULL DEFAULT 1
)"""

DDL_COMPOSITIONS = """
CREATE TABLE IF NOT EXISTS work_compositions (
    id            {serial}      PRIMARY KEY,
    paragraph_id  INTEGER       NOT NULL REFERENCES paragraphs(id) ON DELETE CASCADE,
    condition     TEXT          NOT NULL DEFAULT '',
    sort_order    INTEGER       NOT NULL DEFAULT 0
)"""

DDL_OPERATIONS = """
CREATE TABLE IF NOT EXISTS work_operations (
    id              {serial}    PRIMARY KEY,
    composition_id  INTEGER     NOT NULL REFERENCES work_compositions(id) ON DELETE CASCADE,
    sort_order      INTEGER     NOT NULL,
    text            TEXT        NOT NULL
)"""

DDL_NOTES = """
CREATE TABLE IF NOT EXISTS notes (
    id            {serial}      PRIMARY KEY,
    paragraph_id  INTEGER       NOT NULL REFERENCES paragraphs(id) ON DELETE CASCADE,
    num           INTEGER       NOT NULL,
    text          TEXT          NOT NULL,
    coefficient   {decimal},
    ref_code      VARCHAR(16)
)"""

DDL_INDEXES = [
    'CREATE INDEX IF NOT EXISTS norms_paragraph_id_idx          ON norms(paragraph_id)',
    'CREATE INDEX IF NOT EXISTS crew_paragraph_id_idx           ON crew_members(paragraph_id)',
    'CREATE INDEX IF NOT EXISTS compositions_paragraph_id_idx   ON work_compositions(paragraph_id)',
    'CREATE INDEX IF NOT EXISTS operations_composition_id_idx   ON work_operations(composition_id)',
    'CREATE INDEX IF NOT EXISTS notes_paragraph_id_idx          ON notes(paragraph_id)',
]

DROP_ORDER = [
    'work_operations', 'work_compositions',
    'notes', 'crew_members', 'norms', 'paragraphs',
]


def apply_types(ddl: str, is_sqlite: bool) -> str:
    if is_sqlite:
        return ddl.replace('{serial}', 'INTEGER').replace('{decimal}', 'REAL')
    return ddl.replace('{serial}', 'SERIAL').replace('{decimal}', 'NUMERIC(10,4)')


def create_tables(cur, is_sqlite: bool, drop: bool):
    if drop:
        for tbl in DROP_ORDER:
            cur.execute(f'DROP TABLE IF EXISTS {tbl}')
        print('Таблицы удалены.')

    for ddl in [DDL_PARAGRAPHS, DDL_NORMS, DDL_CREW,
                DDL_COMPOSITIONS, DDL_OPERATIONS, DDL_NOTES]:
        cur.execute(apply_types(ddl, is_sqlite))

    for idx in DDL_INDEXES:
        cur.execute(idx)

    print('Таблицы созданы (или уже существуют).')


# ─── Загрузка одного параграфа ────────────────────────────────────────────────

def upsert_paragraph(cur, p: str, para: dict, is_sqlite: bool) -> int:
    """Вставляет или обновляет параграф. Возвращает paragraph_id."""
    cur.execute(
        f'SELECT id FROM paragraphs WHERE code = {p}',
        (para['code'],)
    )
    row = cur.fetchone()
    if row:
        para_id = row[0]
        cur.execute(
            f'UPDATE paragraphs SET title={p}, unit={p} WHERE id={p}',
            (para['title'], para['unit'], para_id)
        )
        # Удаляем старые дочерние строки явно (SQLite PRAGMA + PG CASCADE)
        for tbl in ['norms', 'crew_members', 'work_compositions', 'notes']:
            cur.execute(f'DELETE FROM {tbl} WHERE paragraph_id = {p}', (para_id,))
        # work_operations удалятся каскадом из work_compositions
    else:
        if is_sqlite:
            cur.execute(
                f'INSERT INTO paragraphs (code, title, unit) VALUES ({p},{p},{p})',
                (para['code'], para['title'], para['unit'])
            )
            para_id = cur.lastrowid
        else:
            cur.execute(
                f'INSERT INTO paragraphs (code, title, unit) VALUES ({p},{p},{p}) RETURNING id',
                (para['code'], para['title'], para['unit'])
            )
            para_id = cur.fetchone()[0]

    return para_id


def _insert_returning(cur, p: str, sql: str, vals: tuple, is_sqlite: bool) -> int:
    """INSERT и возврат id: SQLite → lastrowid, PG → RETURNING id."""
    if is_sqlite:
        cur.execute(sql, vals)
        return cur.lastrowid
    else:
        cur.execute(sql + ' RETURNING id', vals)
        return cur.fetchone()[0]


def load_paragraph(cur, p: str, para: dict, is_sqlite: bool) -> dict:
    para_id = upsert_paragraph(cur, p, para, is_sqlite)

    stats = {'norms': 0, 'crew': 0, 'compositions': 0, 'operations': 0, 'notes': 0}

    for n in para.get('norms', []):
        if CREW_LEAK_RE.search(n.get('work_type', '')):
            continue  # состав звена просочился в нормы — пропускаем
        cur.execute(
            f'INSERT INTO norms '
            f'(paragraph_id, row_num, work_type, condition, thickness_mm, norm_time, price_rub, column_label) '
            f'VALUES ({p},{p},{p},{p},{p},{p},{p},{p})',
            (para_id, n['row_num'], n['work_type'], n['condition'],
             n.get('thickness_mm'), n['norm_time'], n['price_rub'],
             n.get('column_label', ''))
        )
        stats['norms'] += 1

    # Состав звена
    for cm in para.get('crew', []):
        cur.execute(
            f'INSERT INTO crew_members (paragraph_id, profession, grade, count) '
            f'VALUES ({p},{p},{p},{p})',
            (para_id, cm['profession'], cm['grade'], cm['count'])
        )
        stats['crew'] += 1

    # Состав работ
    for si, wc in enumerate(para.get('work_compositions', [])):
        comp_id = _insert_returning(
            cur, p,
            f'INSERT INTO work_compositions (paragraph_id, condition, sort_order) VALUES ({p},{p},{p})',
            (para_id, wc['condition'], si),
            is_sqlite
        )
        stats['compositions'] += 1

        for oi, op_text in enumerate(wc.get('operations', [])):
            cur.execute(
                f'INSERT INTO work_operations (composition_id, sort_order, text) '
                f'VALUES ({p},{p},{p})',
                (comp_id, oi, op_text)
            )
            stats['operations'] += 1

    # Примечания
    for note in para.get('notes', []):
        cur.execute(
            f'INSERT INTO notes (paragraph_id, num, text, coefficient, ref_code) '
            f'VALUES ({p},{p},{p},{p},{p})',
            (para_id, note['num'], note['text'],
             note.get('coefficient'), note.get('code'))
        )
        stats['notes'] += 1

    return stats


# ─── Проверочные запросы ──────────────────────────────────────────────────────

def run_checks(cur, p: str, code: str):
    print(f'\n── Проверка {code} ──')

    cur.execute(f'SELECT id, code, title, unit FROM paragraphs WHERE code={p}', (code,))
    row = cur.fetchone()
    if not row:
        print('  ОШИБКА: параграф не найден!')
        return
    para_id = row[0]
    print(f'  paragraphs: id={row[0]} code={row[1]} unit={row[3]}')
    print(f'  title: {str(row[2])[:60]}')

    cur.execute(f'SELECT COUNT(*) FROM norms WHERE paragraph_id={p}', (para_id,))
    n_norms = cur.fetchone()[0]
    cur.execute(f'SELECT COUNT(*) FROM crew_members WHERE paragraph_id={p}', (para_id,))
    n_crew = cur.fetchone()[0]
    cur.execute(f'SELECT COUNT(*) FROM work_compositions WHERE paragraph_id={p}', (para_id,))
    n_comp = cur.fetchone()[0]
    cur.execute(f'''
        SELECT COUNT(*) FROM work_operations wo
        JOIN work_compositions wc ON wc.id = wo.composition_id
        WHERE wc.paragraph_id={p}''', (para_id,))
    n_ops = cur.fetchone()[0]
    cur.execute(f'SELECT COUNT(*) FROM notes WHERE paragraph_id={p}', (para_id,))
    n_notes = cur.fetchone()[0]

    print(f'  нормы={n_norms}  звено={n_crew}  '
          f'составы={n_comp}  операции={n_ops}  примечания={n_notes}')

    cur.execute(f'''
        SELECT row_num, work_type, condition, thickness_mm, norm_time, price_rub
        FROM norms WHERE paragraph_id={p}
        ORDER BY row_num, id LIMIT 5''', (para_id,))
    print('  Первые 5 норм:')
    for row in cur.fetchall():
        rn, wt, cond, th, nt, pr = row
        th_s = f' th={th}мм' if th else ''
        wt_s  = str(wt)[:30]
        cond_s = str(cond)[:20]
        print(f'    №{rn}{th_s} | {wt_s:30s} | {cond_s:20s} | н.вр.={nt}  руб={pr}')

    cur.execute(f'''
        SELECT profession, grade, count FROM crew_members
        WHERE paragraph_id={p}''', (para_id,))
    rows = cur.fetchall()
    if rows:
        print('  Звено:', ', '.join(f'{r[0]} {r[1]}р.×{r[2]}' for r in rows))

    cur.execute(f'''
        SELECT num, coefficient, ref_code, text
        FROM notes WHERE paragraph_id={p} AND coefficient IS NOT NULL''', (para_id,))
    for row in cur.fetchall():
        print(f'  Примеч. №{row[0]}: коэф={row[1]} ({row[2]}) — {str(row[3])[:60]}...')

    cur.execute(f'''
        SELECT wc.condition, COUNT(wo.id) as ops
        FROM work_compositions wc
        LEFT JOIN work_operations wo ON wo.composition_id = wc.id
        WHERE wc.paragraph_id={p}
        GROUP BY wc.id, wc.condition
        ORDER BY wc.sort_order''', (para_id,))
    rows = cur.fetchall()
    if rows:
        print('  Состав работ:')
        for r in rows:
            print(f'    [{r[1]} операций] {str(r[0])[:60]}')


# ─── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db',   default='sqlite:///enir_e3.db')
    ap.add_argument('--json', default='enir_e3.json',
                    help='JSON от парсера (совпадает с --out parse_enir_v3.py)')
    ap.add_argument('--para', default=None, help='Загрузить один параграф, например Е3-3')
    ap.add_argument('--drop', action='store_true', help='Пересоздать таблицы')
    args = ap.parse_args()

    json_path = Path(args.json)
    if not json_path.exists():
        sys.exit(f'Файл не найден: {json_path}')

    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)

    conn, p = get_connection(args.db)
    is_sqlite = args.db.startswith('sqlite')

    try:
        cur = conn.cursor()
        create_tables(cur, is_sqlite, args.drop)

        targets = (
            [next(para for para in data if para['code'] == args.para)]
            if args.para else data
        )

        total = {'norms': 0, 'crew': 0, 'compositions': 0, 'operations': 0, 'notes': 0}

        for para in targets:
            stats = load_paragraph(cur, p, para, is_sqlite)
            for k in total:
                total[k] += stats[k]
            print(f'  {para["code"]:8s}  '
                  f'нормы={stats["norms"]:3d}  '
                  f'звено={stats["crew"]:2d}  '
                  f'операции={stats["operations"]:3d}  '
                  f'примечания={stats["notes"]:2d}')

        conn.commit()

        print(f'\nВсего загружено:')
        for k, v in total.items():
            print(f'  {k}: {v}')

        # Проверочные запросы
        for para in targets:
            run_checks(cur, p, para['code'])

    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
