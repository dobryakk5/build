# Загрузка нового ENIR JSON в текущую БД

Инструкция для загрузки нового файла `enir_*.json` в фактическую ENIR-схему проекта.

Актуально для:

- миграций Alembic до `007`
- импортёра [backend/import_enir.py](/Users/pavellebedev/Desktop/proj/build/backend/import_enir.py)
- таблиц `enir_*` в PostgreSQL

## Что реально поддерживается сейчас

Текущий импортёр поддерживает:

1. `paragraphs_v1`
   - top-level JSON = массив параграфов
   - это старый плоский формат
   - подходит только для базовых `enir_work_compositions`, `enir_crew_members`, `enir_norms`, `enir_notes`

2. `e1_db`
   - top-level JSON = объект
   - это текущий DB-oriented формат
   - именно он нужен для полной загрузки E1/E3 в текущую схему

3. optional annotated `cross_ref` JSON
   - top-level JSON = объект
   - передаётся отдельным файлом через `--cross-ref-json`
   - нужен для `html_anchor` и `enir_paragraph_refs`

Для нового импорта нужно ориентироваться на `e1_db`, а не на старый `canonical` с JSONB внутри `norm_tables`.

## Основной JSON: спецификация `e1_db`

### Обязательные top-level поля

```json
{
  "schema_version": 1,
  "source_file": "...",
  "issue": "Выпуск 1",
  "issue_title": "МЕХАНИЗИРОВАННЫЕ И РУЧНЫЕ ЗЕМЛЯНЫЕ РАБОТЫ",
  "description": "...",
  "paragraphs": [...],
  "paragraph_work_items": [...],
  "paragraph_crew_items": [...],
  "paragraph_notes": [...],
  "norm_tables": [...],
  "norm_columns": [...],
  "norm_rows": [...],
  "norm_values": [...]
}
```

Допустимы дополнительные поля вроде `merge_policy`, но `backend/import_enir.py` их не использует.

### Поля коллекции

Если они есть в JSON, импортёр берёт их по умолчанию:

- `collection_code` или `collection_name` -> код коллекции
- `collection_title` -> название коллекции
- `description` -> описание коллекции
- `issue` -> выпуск
- `issue_title` -> название выпуска
- `source_file` -> источник

Важно:

- `--collection-code` и `--collection-title` теперь необязательны
- если они переданы в CLI, они переопределяют значения из JSON
- если их нет в CLI, импортёр пытается взять их из JSON
- если в JSON нет кода или названия коллекции, импорт завершится ошибкой и попросит передать override через CLI

Практический нюанс:

- у E3-файла есть `collection_name='Е3'` и `collection_title='КАМЕННЫЕ РАБОТЫ'`, поэтому CLI можно не передавать
- у старых E1-файлов `collection_name`/`collection_title` может не быть, и тогда override через CLI всё ещё нужен

### Минимальная структура ключевых массивов

`paragraphs[]`:

- `paragraph_id`
- `code`
- `title`
- `unit`
- `paragraph_order`
- `technical_characteristics`
- `application_notes`

`paragraph_work_items[]`:

- `paragraph_id`
- `item_order`
- `text`

`paragraph_crew_items[]`:

- `paragraph_id`
- `item_order`
- `profession`
- `grade`
- `count`
- `raw`

`paragraph_notes[]`:

- `paragraph_id`
- `item_order`
- `code`
- `text`
- `coefficient`

`norm_tables[]`:

- `table_id`
- `paragraph_id`
- `table_order`
- `title`
- `row_count`

`norm_columns[]`:

- `table_id`
- `column_order`
- `column_key`
- `header`
- `label`

`norm_rows[]`:

- `row_id`
- `table_id`
- `row_order`
- `source_row_num`

`norm_values[]`:

- `row_id`
- `column_key`
- `value_type`
- `value_text`

Примечание по `norm_columns[].label`:

- в текущей схеме БД это `TEXT`
- длинные подписи столбцов допустимы

## Дополнительный JSON: спецификация annotated `cross_ref`

Этот файл передаётся отдельно:

```bash
--cross-ref-json /path/to/cross_references_annotated.json
```

Ожидается top-level объект:

```json
{
  "source_url": "...",
  "internal_links": [...],
  "external_links": [...],
  "anchor_targets": [...]
}
```

### Что реально использует импортёр

`internal_links[]`:

- импортёр берёт только записи с `link_type == "toc"`
- обязательные поля для импорта:
  - `paragraph_id`
  - `fragment`
- дополнительные поля вроде `text`, `href`, `abs_url`, `context` могут присутствовать, но для загрузки якоря не обязательны

`external_links[]`:

- обязательные поля для импорта:
  - `paragraph_id`
- сохраняемые поля:
  - `text` -> `enir_paragraph_refs.link_text`
  - `href` -> `enir_paragraph_refs.href`
  - `abs_url` -> `enir_paragraph_refs.abs_url`
  - `context` -> `enir_paragraph_refs.context_text`
  - `is_meganorm` -> `enir_paragraph_refs.is_meganorm`
- `ref_type` в БД всегда ставится как `external`

`anchor_targets[]`:

- сейчас не сохраняется в БД
- может использоваться только для внешней валидации/отладки

### Правила резолюции ссылок

- `paragraph_id` из annotated JSON матчится по `enir_paragraphs.code` и `enir_paragraphs.source_paragraph_id`
- matching регистронезависимый, с нормализацией `З -> 3`
- если `paragraph_id` не найден, запись пропускается с warning
- fallback-парсинга кода параграфа из текста TOC нет

## Как этот JSON маппится в БД

- `paragraphs` -> `enir_paragraphs`
- `paragraphs[].technical_characteristics` -> `enir_paragraph_technical_characteristics`
- `paragraphs[].application_notes` -> `enir_paragraph_application_notes`
- `paragraph_work_items` -> `enir_source_work_items`
- `paragraph_crew_items` -> `enir_source_crew_items`
- `paragraph_notes` -> `enir_source_notes`
- `norm_tables` -> `enir_norm_tables`
- `norm_columns` -> `enir_norm_columns`
- `norm_rows` -> `enir_norm_rows`
- `norm_values` -> `enir_norm_values`
- `internal_links[link_type=toc]` -> `enir_paragraphs.html_anchor`
- `external_links` -> `enir_paragraph_refs`

Дополнительно импортёр наполняет совместимые UI-таблицы:

- `enir_work_compositions`
- `enir_work_operations`
- `enir_crew_members`
- `enir_notes`

`enir_norms` в формате `e1_db` не заполняется.

## Важное отличие от старой документации

Сейчас таблицы норм в БД хранятся не JSONB-полями внутри `enir_norm_tables`, а в нормализованном виде:

- `enir_norm_tables`
- `enir_norm_columns`
- `enir_norm_rows`
- `enir_norm_values`

API уже само собирает их в вложенную структуру `columns` / `rows` / `cells` при чтении.

## Где лежит импортёр

- [backend/import_enir.py](/Users/pavellebedev/Desktop/proj/build/backend/import_enir.py)

## Откуда берётся БД

Импортёр читает:

- [backend/.env](/Users/pavellebedev/Desktop/proj/build/backend/.env)

Нужна переменная:

- `DATABASE_URL=...`

## Какие поля коллекции реально сохраняются

В `enir_collections` сейчас сохраняются:

- `code`
- `title`
- `description`
- `issue`
- `issue_title`
- `source_file`
- `source_format`
- `sort_order`

Важно:

- `code` берётся из `--collection-code`, а если аргумент не передан, то из `collection_code` или `collection_name` в JSON
- `title` берётся из `--collection-title`, а если аргумент не передан, то из `collection_title` в JSON
- `description` берётся из `--collection-description`, а если аргумент не передан, то из JSON-поля `description`
- `issue` и `issue_title` берутся из JSON, если они есть
- `source_file` берётся из JSON
- `source_format` определяется автоматически как `e1_db` или `paragraphs_v1`

Поля вроде `approval_date`, `approval_number`, `issuing_bodies`, `developer`, `coordination`, `amendments` в текущей схеме БД не хранятся.

## Подготовка перед новой загрузкой

1. Проверить, что JSON соответствует формату `e1_db`
2. Проверить, что у каждого блока есть обязательные ключи
3. Проверить связность ссылок:
   - каждый `paragraph_work_items[].paragraph_id` существует в `paragraphs`
   - каждый `paragraph_crew_items[].paragraph_id` существует в `paragraphs`
   - каждый `paragraph_notes[].paragraph_id` существует в `paragraphs`
   - каждый `norm_tables[].paragraph_id` существует в `paragraphs`
   - каждый `norm_columns[].table_id` существует в `norm_tables`
   - каждый `norm_rows[].table_id` существует в `norm_tables`
   - каждый `norm_values[].row_id` существует в `norm_rows`
   - каждый `norm_values[].column_key` существует среди колонок соответствующей таблицы

Мини-проверка:

```bash
python3 - <<'PY'
import json
from pathlib import Path

p = Path('/Users/pavellebedev/Desktop/proj/build/Enir/FILE.json')
data = json.loads(p.read_text(encoding='utf-8'))

required_top = [
    'schema_version',
    'source_file',
    'paragraphs',
    'paragraph_work_items',
    'paragraph_crew_items',
    'paragraph_notes',
    'norm_tables',
    'norm_columns',
    'norm_rows',
    'norm_values',
]

for key in required_top:
    val = data.get(key)
    print(f'{key}: {type(val).__name__} = {len(val) if isinstance(val, list) else val}')

print('\nПримеры:')
print('paragraph:', data['paragraphs'][0])
print('norm_table:', data['norm_tables'][0])
print('norm_column:', data['norm_columns'][0])
print('norm_row:', data['norm_rows'][0])
print('norm_value:', data['norm_values'][0])
PY
```

Если коллекцию нужно перезалить полностью:

```sql
DELETE FROM enir_collections WHERE code = 'Е3';
```

Удаление каскадно удалит все связанные `enir_*` записи.

## Базовая загрузка

```bash
python3 /Users/pavellebedev/Desktop/proj/build/backend/import_enir.py \
  /Users/pavellebedev/Desktop/proj/build/Enir/FILE.json \
  --cross-ref-json '/Users/pavellebedev/Downloads/cross_references_annotated.json' \
  --sort-order 3
```

Если код и название коллекции не лежат в JSON:

```bash
python3 /Users/pavellebedev/Desktop/proj/build/backend/import_enir.py \
  /Users/pavellebedev/Desktop/proj/build/Enir/FILE.json \
  --collection-code 'Е3' \
  --collection-title 'КАМЕННЫЕ РАБОТЫ' \
  --cross-ref-json '/Users/pavellebedev/Downloads/cross_references_annotated.json' \
  --sort-order 3
```

Если коллекция уже существует:

```bash
python3 /Users/pavellebedev/Desktop/proj/build/backend/import_enir.py \
  /Users/pavellebedev/Desktop/proj/build/Enir/FILE.json \
  --cross-ref-json '/Users/pavellebedev/Downloads/cross_references_annotated.json' \
  --sort-order 3 \
  --overwrite
```

`--overwrite` не удаляет саму запись коллекции, а удаляет её `enir_paragraphs`, после чего перезаливает связанные данные заново.

## Надёжный вариант без проблем с CLI

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, '/Users/pavellebedev/Desktop/proj/build/backend')
from import_enir import import_collection

import_collection(
    json_path='/Users/pavellebedev/Desktop/proj/build/Enir/FILE.json',
    collection_code=None,
    collection_title=None,
    collection_description=None,
    sort_order=3,
    overwrite=False,
    cross_ref_json_path='/Users/pavellebedev/Downloads/cross_references_annotated.json',
)
PY
```

## Реальные кейсы, которые надо учитывать

1. `paragraph_crew_items` не всегда содержит полноценного члена звена.
   - запись с `profession = null` может быть сохранена в `enir_source_crew_items`
   - в `enir_crew_members` такая запись не копируется

2. `paragraph_work_items[].text` импортёр пытается распарсить как Python-словарь через `ast.literal_eval`.
   - если строка не парсится, она всё равно попадёт в `enir_source_work_items`
   - но `enir_work_compositions` и `enir_work_operations` для неё не создадутся

3. `paragraph_notes[].coefficient` может быть `null`
   - это нормально

4. `norm_values[].value_text` может быть пустой строкой `""`
   - это нормально

5. `norm_rows[].source_row_num` может быть `null`
   - это тоже допустимо

6. `description` в JSON полезен, но не обязателен для самой загрузки
   - если его нет и `--collection-description` не передан, в `enir_collections.description` будет `NULL`

7. если в основном JSON нет `collection_name`/`collection_title`
   - нужно передать `--collection-code` и `--collection-title`

8. если в annotated `cross_ref` JSON есть неизвестный `paragraph_id`
   - такая ссылка или TOC-запись будет пропущена с warning

## Проверка после загрузки

Минимальная проверка коллекции:

```bash
python3 - <<'PY'
import os
from pathlib import Path
import psycopg2

for p in [Path('/Users/pavellebedev/Desktop/proj/build/backend/.env')]:
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

url = os.environ['DATABASE_URL']
url = url.replace('postgresql+asyncpg://', 'postgresql://').replace('postgresql+psycopg2://', 'postgresql://')

conn = psycopg2.connect(url)
cur = conn.cursor()
cur.execute("""
    select id, code, title, issue, issue_title, description, source_file, source_format
    from enir_collections
    order by id
""")
for row in cur.fetchall():
    print(row)
conn.close()
PY
```

Проверка агрегатов JSON vs БД:

```bash
python3 - <<'PY'
import os, json
from pathlib import Path
import psycopg2

json_path = Path('/Users/pavellebedev/Desktop/proj/build/Enir/FILE.json')
data = json.loads(json_path.read_text(encoding='utf-8'))
collection_code = 'Е3'

for p in [Path('/Users/pavellebedev/Desktop/proj/build/backend/.env')]:
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

url = os.environ['DATABASE_URL']
url = url.replace('postgresql+asyncpg://', 'postgresql://').replace('postgresql+psycopg2://', 'postgresql://')

conn = psycopg2.connect(url)
cur = conn.cursor()

queries = {
    'paragraphs': """
        select count(*)
        from enir_paragraphs p
        join enir_collections c on c.id = p.collection_id
        where c.code = %(code)s
    """,
    'paragraph_work_items': """
        select count(*)
        from enir_source_work_items x
        join enir_paragraphs p on p.id = x.paragraph_id
        join enir_collections c on c.id = p.collection_id
        where c.code = %(code)s
    """,
    'paragraph_crew_items': """
        select count(*)
        from enir_source_crew_items x
        join enir_paragraphs p on p.id = x.paragraph_id
        join enir_collections c on c.id = p.collection_id
        where c.code = %(code)s
    """,
    'paragraph_notes': """
        select count(*)
        from enir_source_notes x
        join enir_paragraphs p on p.id = x.paragraph_id
        join enir_collections c on c.id = p.collection_id
        where c.code = %(code)s
    """,
    'norm_tables': """
        select count(*)
        from enir_norm_tables x
        join enir_paragraphs p on p.id = x.paragraph_id
        join enir_collections c on c.id = p.collection_id
        where c.code = %(code)s
    """,
    'norm_columns': """
        select count(*)
        from enir_norm_columns x
        join enir_norm_tables t on t.id = x.norm_table_id
        join enir_paragraphs p on p.id = t.paragraph_id
        join enir_collections c on c.id = p.collection_id
        where c.code = %(code)s
    """,
    'norm_rows': """
        select count(*)
        from enir_norm_rows x
        join enir_norm_tables t on t.id = x.norm_table_id
        join enir_paragraphs p on p.id = t.paragraph_id
        join enir_collections c on c.id = p.collection_id
        where c.code = %(code)s
    """,
    'norm_values': """
        select count(*)
        from enir_norm_values x
        join enir_norm_rows r on r.id = x.norm_row_id
        join enir_norm_tables t on t.id = r.norm_table_id
        join enir_paragraphs p on p.id = t.paragraph_id
        join enir_collections c on c.id = p.collection_id
        where c.code = %(code)s
    """,
}

expected = {
    'paragraphs': len(data['paragraphs']),
    'paragraph_work_items': len(data['paragraph_work_items']),
    'paragraph_crew_items': len(data['paragraph_crew_items']),
    'paragraph_notes': len(data['paragraph_notes']),
    'norm_tables': len(data['norm_tables']),
    'norm_columns': len(data['norm_columns']),
    'norm_rows': len(data['norm_rows']),
    'norm_values': len(data['norm_values']),
}

actual = {}
for key, sql in queries.items():
    cur.execute(sql, {'code': collection_code})
    actual[key] = cur.fetchone()[0]

print(f'Коллекция: {collection_code}')
print(f'{"Ключ":<24} {"JSON":>8} {"DB":>8} {"OK":>4}')
print('-' * 50)
for key in expected:
    e = expected[key]
    a = actual[key]
    ok = '✓' if e == a else '✗'
    print(f'{key:<24} {e:>8} {a:>8} {ok:>4}')

conn.close()
PY
```

## Проверка API без поднятия сервера

```bash
python3 - <<'PY'
import os, sys, asyncio
from pathlib import Path
sys.path.insert(0, '/Users/pavellebedev/Desktop/proj/build/backend')

for p in [Path('/Users/pavellebedev/Desktop/proj/build/backend/.env')]:
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

from app.api.routes.enir import list_collections, get_paragraph
from app.core.database import AsyncSessionLocal
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as db:
        collections = await list_collections(db)
        print('Коллекции:', [(c['code'], c['issue'], c['title'], c['source_format']) for c in collections])

        row = await db.execute(text(
            "select p.id from enir_paragraphs p "
            "join enir_collections c on c.id = p.collection_id "
            "where c.code = 'Е3' order by p.sort_order limit 1"
        ))
        paragraph_id = row.scalar_one()
        detail = await get_paragraph(paragraph_id, db)
        print('Параграф:', detail['code'])
        print('source_work_items:', len(detail['source_work_items']))
        print('source_crew_items:', len(detail['source_crew_items']))
        print('source_notes:', len(detail['source_notes']))
        print('norm_tables:', len(detail['norm_tables']))
        if detail['norm_tables']:
            first_table = detail['norm_tables'][0]
            print('  columns:', len(first_table['columns']))
            print('  rows:', len(first_table['rows']))

asyncio.run(main())
PY
```

## Практический шаблон для следующего JSON

1. Положить новый файл в `Enir/`
2. Убедиться, что это именно `e1_db`, а не `canonical` с вложенными `columns` / `rows` внутри `norm_tables`
3. Проверить top-level поля `paragraphs`, `paragraph_work_items`, `paragraph_crew_items`, `paragraph_notes`, `norm_tables`, `norm_columns`, `norm_rows`, `norm_values`
4. Проверить ссылочную связность между `paragraph_id`, `table_id`, `row_id`, `column_key`
5. Если надо, удалить старую коллекцию: `DELETE FROM enir_collections WHERE code = 'ЕX';`
6. Запустить импорт через `backend/import_enir.py`
7. Сверить агрегаты JSON vs БД
8. Проверить `list_collections()` и `get_paragraph()`
9. Открыть UI `/projects/<id>/enir` и убедиться, что сборник виден

## Если на руках только `canonical`-JSON

Такой файл сначала надо конвертировать в `e1_db`.

Прямо сейчас `backend/import_enir.py` не принимает JSON вида:

- `norm_tables[].columns`
- `norm_tables[].rows`
- без top-level `norm_columns`
- без top-level `norm_rows`
- без top-level `norm_values`

Если подать такой файл напрямую, импортёр завершится с `ValueError: Unsupported ENIR JSON format`.

## Если загрузка упала

Сначала смотреть:

- не отсутствует ли один из обязательных top-level массивов
- совпадают ли `paragraph_id` между блоками
- совпадают ли `table_id` между `norm_tables`, `norm_columns`, `norm_rows`
- существует ли каждая пара `row_id` + `column_key` в своей таблице
- не сломался ли `paragraph_work_items[].text`, если нужен автозаполнитель `enir_work_compositions`
- нет ли конфликта по `source_table_id` или `source_row_id` при повторной загрузке без `--overwrite`

Правило:

- source/raw-таблицы должны хранить данные без потерь
- производные UI-таблицы могут не заполниться полностью, если исходный текст не удалось распарсить
- табличная истина для `e1_db` живёт в `enir_norm_tables` + `enir_norm_columns` + `enir_norm_rows` + `enir_norm_values`
