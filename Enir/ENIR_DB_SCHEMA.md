# Текущая схема БД ENIR

Описание текущих `enir_*` таблиц в проекте.

Источник:

- ORM-модели `backend/app/models/enir.py`
- миграции `003_enir.py`, `004_enir_e1.py` и `005_enir_collection_issue_meta.py`
- живая PostgreSQL БД из `backend/.env`

Проверено для текущего состояния БД:

- `alembic_version = 005` после применения новой миграции

## Общая структура

```text
enir_collections
└── enir_paragraphs
    ├── enir_work_compositions
    │   └── enir_work_operations
    ├── enir_crew_members
    ├── enir_norms
    ├── enir_notes
    ├── enir_paragraph_technical_characteristics
    ├── enir_paragraph_application_notes
    ├── enir_source_work_items
    ├── enir_source_crew_items
    ├── enir_source_notes
    └── enir_norm_tables
        ├── enir_norm_columns
        ├── enir_norm_rows
        └── enir_norm_values
```

Все внешние ключи в ENIR-схеме настроены с `ON DELETE CASCADE`.

## Что важно про текущую модель

- Схема состоит из двух слоёв:
  - старый прикладной слой `enir_work_compositions`, `enir_work_operations`, `enir_crew_members`, `enir_norms`, `enir_notes`
  - новый source/tabular слой из миграции `004`: `enir_source_*`, `enir_paragraph_*`, `enir_norm_tables`, `enir_norm_columns`, `enir_norm_rows`, `enir_norm_values`
  - расширенная meta-модель коллекции из миграции `005`: `issue`, `issue_title`
- Для полного импорта `e1_db` сейчас основная истина по таблицам норм хранится в:
  - `enir_norm_tables`
  - `enir_norm_columns`
  - `enir_norm_rows`
  - `enir_norm_values`
- `enir_norms` остаётся в схеме для старого плоского формата и совместимости, но при импорте `e1_db` обычно не заполняется.

## Таблицы

### `enir_collections`

Сборники ENIR: `Е1`, `Е2`, `Е3` и т.д.

| Поле | Тип | NULL | Описание |
|---|---|---|---|
| `id` | `bigint` | no | PK |
| `code` | `varchar(20)` | no | код сборника |
| `title` | `text` | no | название |
| `description` | `text` | yes | описание |
| `issue` | `varchar(100)` | yes | выпуск, например `Выпуск 1` |
| `issue_title` | `text` | yes | заголовок выпуска |
| `sort_order` | `integer` | no | порядок показа |
| `created_at` | `timestamptz` | yes | `NOW()` по умолчанию |
| `source_file` | `text` | yes | исходный файл импорта |
| `source_format` | `varchar(50)` | yes | `e1_db` или `paragraphs_v1` |

Ограничения и индексы:

- PK: `id`
- UNIQUE: `code`

### `enir_paragraphs`

Параграфы внутри сборника.

| Поле | Тип | NULL | Описание |
|---|---|---|---|
| `id` | `bigint` | no | PK |
| `collection_id` | `bigint` | no | FK -> `enir_collections.id` |
| `code` | `varchar(30)` | no | код параграфа |
| `title` | `text` | no | заголовок |
| `unit` | `varchar(100)` | yes | единица измерения |
| `sort_order` | `integer` | no | порядок внутри сборника |
| `source_paragraph_id` | `varchar(60)` | yes | исходный ID параграфа |

Ограничения и индексы:

- PK: `id`
- FK: `collection_id`
- UNIQUE: `(collection_id, code)`
- INDEX: `collection_id`

### `enir_work_compositions`

Блоки состава работ для UI-слоя.

| Поле | Тип | NULL | Описание |
|---|---|---|---|
| `id` | `bigint` | no | PK |
| `paragraph_id` | `bigint` | no | FK -> `enir_paragraphs.id` |
| `condition` | `text` | yes | условие применения |
| `sort_order` | `integer` | no | порядок |

Ограничения и индексы:

- PK: `id`
- FK: `paragraph_id`
- INDEX: `paragraph_id`

### `enir_work_operations`

Операции внутри блока состава работ.

| Поле | Тип | NULL | Описание |
|---|---|---|---|
| `id` | `bigint` | no | PK |
| `composition_id` | `bigint` | no | FK -> `enir_work_compositions.id` |
| `text` | `text` | no | текст операции |
| `sort_order` | `integer` | no | порядок |

Ограничения и индексы:

- PK: `id`
- FK: `composition_id`
- INDEX: `composition_id`

### `enir_crew_members`

Нормализованный состав звена для UI-слоя.

| Поле | Тип | NULL | Описание |
|---|---|---|---|
| `id` | `bigint` | no | PK |
| `paragraph_id` | `bigint` | no | FK -> `enir_paragraphs.id` |
| `profession` | `varchar(200)` | no | профессия |
| `grade` | `numeric(4,1)` | yes | разряд |
| `count` | `smallint` | no | количество |

Ограничения и индексы:

- PK: `id`
- FK: `paragraph_id`
- INDEX: `paragraph_id`

### `enir_norms`

Старый плоский слой норм.

| Поле | Тип | NULL | Описание |
|---|---|---|---|
| `id` | `bigint` | no | PK |
| `paragraph_id` | `bigint` | no | FK -> `enir_paragraphs.id` |
| `row_num` | `smallint` | yes | номер строки |
| `work_type` | `text` | yes | вид работ |
| `condition` | `text` | yes | условие |
| `thickness_mm` | `integer` | yes | толщина / размер |
| `column_label` | `varchar(10)` | yes | буквенная колонка |
| `norm_time` | `numeric(10,4)` | yes | Н.вр. |
| `price_rub` | `numeric(12,4)` | yes | расценка |

Ограничения и индексы:

- PK: `id`
- FK: `paragraph_id`
- INDEX: `paragraph_id`

Примечание:

- после миграции `004` поле `row_num` стало nullable

### `enir_notes`

Прикладные примечания к параграфу.

| Поле | Тип | NULL | Описание |
|---|---|---|---|
| `id` | `bigint` | no | PK |
| `paragraph_id` | `bigint` | no | FK -> `enir_paragraphs.id` |
| `num` | `smallint` | no | номер примечания |
| `text` | `text` | no | текст |
| `coefficient` | `numeric(6,4)` | yes | коэффициент |
| `pr_code` | `varchar(20)` | yes | код типа `ПР-1` |

Ограничения и индексы:

- PK: `id`
- FK: `paragraph_id`
- INDEX: `paragraph_id`

### `enir_paragraph_technical_characteristics`

Сырые технические характеристики параграфа.

| Поле | Тип | NULL | Описание |
|---|---|---|---|
| `id` | `bigint` | no | PK |
| `paragraph_id` | `bigint` | no | FK -> `enir_paragraphs.id` |
| `sort_order` | `integer` | no | порядок |
| `raw_text` | `text` | no | исходный текст |

Ограничения и индексы:

- PK: `id`
- FK: `paragraph_id`
- INDEX: `paragraph_id`

### `enir_paragraph_application_notes`

Общие указания по применению норм для параграфа.

| Поле | Тип | NULL | Описание |
|---|---|---|---|
| `id` | `bigint` | no | PK |
| `paragraph_id` | `bigint` | no | FK -> `enir_paragraphs.id` |
| `sort_order` | `integer` | no | порядок |
| `text` | `text` | no | текст |

Ограничения и индексы:

- PK: `id`
- FK: `paragraph_id`
- INDEX: `paragraph_id`

### `enir_source_work_items`

Исходные элементы состава работ без потери текста.

| Поле | Тип | NULL | Описание |
|---|---|---|---|
| `id` | `bigint` | no | PK |
| `paragraph_id` | `bigint` | no | FK -> `enir_paragraphs.id` |
| `sort_order` | `integer` | no | порядок |
| `raw_text` | `text` | no | исходный текст |

Ограничения и индексы:

- PK: `id`
- FK: `paragraph_id`
- INDEX: `paragraph_id`

### `enir_source_crew_items`

Исходные элементы состава звена без потери raw-представления.

| Поле | Тип | NULL | Описание |
|---|---|---|---|
| `id` | `bigint` | no | PK |
| `paragraph_id` | `bigint` | no | FK -> `enir_paragraphs.id` |
| `sort_order` | `integer` | no | порядок |
| `profession` | `varchar(200)` | yes | профессия |
| `grade` | `numeric(4,1)` | yes | разряд |
| `count` | `smallint` | yes | количество |
| `raw_text` | `text` | yes | исходная строка |

Ограничения и индексы:

- PK: `id`
- FK: `paragraph_id`
- INDEX: `paragraph_id`

### `enir_source_notes`

Исходные примечания из нормализованного JSON.

| Поле | Тип | NULL | Описание |
|---|---|---|---|
| `id` | `bigint` | no | PK |
| `paragraph_id` | `bigint` | no | FK -> `enir_paragraphs.id` |
| `sort_order` | `integer` | no | порядок |
| `code` | `varchar(20)` | yes | код, например `ПР-1` |
| `text` | `text` | no | текст |
| `coefficient` | `numeric(6,4)` | yes | коэффициент |

Ограничения и индексы:

- PK: `id`
- FK: `paragraph_id`
- INDEX: `paragraph_id`

### `enir_norm_tables`

Таблицы норм в исходной логической форме.

| Поле | Тип | NULL | Описание |
|---|---|---|---|
| `id` | `bigint` | no | PK |
| `paragraph_id` | `bigint` | no | FK -> `enir_paragraphs.id` |
| `source_table_id` | `varchar(120)` | no | стабильный ID таблицы |
| `sort_order` | `integer` | no | порядок таблицы в параграфе |
| `title` | `text` | yes | заголовок таблицы |
| `row_count` | `integer` | yes | число строк из JSON |

Ограничения и индексы:

- PK: `id`
- FK: `paragraph_id`
- UNIQUE: `source_table_id`
- INDEX: `paragraph_id`

### `enir_norm_columns`

Колонки таблицы норм.

| Поле | Тип | NULL | Описание |
|---|---|---|---|
| `id` | `bigint` | no | PK |
| `norm_table_id` | `bigint` | no | FK -> `enir_norm_tables.id` |
| `source_column_key` | `text` | no | ключ колонки в JSON |
| `sort_order` | `integer` | no | порядок колонки |
| `header` | `text` | no | полный заголовок |
| `label` | `varchar(20)` | yes | краткая метка |

Ограничения и индексы:

- PK: `id`
- FK: `norm_table_id`
- UNIQUE: `(norm_table_id, source_column_key)`
- INDEX: `norm_table_id`

### `enir_norm_rows`

Логические строки таблицы норм.

| Поле | Тип | NULL | Описание |
|---|---|---|---|
| `id` | `bigint` | no | PK |
| `norm_table_id` | `bigint` | no | FK -> `enir_norm_tables.id` |
| `source_row_id` | `varchar(140)` | no | стабильный ID строки |
| `sort_order` | `integer` | no | порядок строки |
| `source_row_num` | `smallint` | yes | номер строки из источника |

Ограничения и индексы:

- PK: `id`
- FK: `norm_table_id`
- UNIQUE: `source_row_id`
- INDEX: `norm_table_id`

### `enir_norm_values`

Значения ячеек таблиц норм.

| Поле | Тип | NULL | Описание |
|---|---|---|---|
| `id` | `bigint` | no | PK |
| `norm_row_id` | `bigint` | no | FK -> `enir_norm_rows.id` |
| `norm_column_id` | `bigint` | no | FK -> `enir_norm_columns.id` |
| `value_type` | `varchar(30)` | no | тип значения: `cell`, `price_cell` и т.п. |
| `value_text` | `text` | yes | текстовое значение |

Ограничения и индексы:

- PK: `id`
- FK: `norm_row_id`
- FK: `norm_column_id`
- INDEX: `norm_row_id`
- INDEX: `norm_column_id`

## Основные связи

- `enir_collections 1:N enir_paragraphs`
- `enir_paragraphs 1:N enir_work_compositions`
- `enir_work_compositions 1:N enir_work_operations`
- `enir_paragraphs 1:N enir_crew_members`
- `enir_paragraphs 1:N enir_norms`
- `enir_paragraphs 1:N enir_notes`
- `enir_paragraphs 1:N enir_paragraph_technical_characteristics`
- `enir_paragraphs 1:N enir_paragraph_application_notes`
- `enir_paragraphs 1:N enir_source_work_items`
- `enir_paragraphs 1:N enir_source_crew_items`
- `enir_paragraphs 1:N enir_source_notes`
- `enir_paragraphs 1:N enir_norm_tables`
- `enir_norm_tables 1:N enir_norm_columns`
- `enir_norm_tables 1:N enir_norm_rows`
- `enir_norm_rows 1:N enir_norm_values`
- `enir_norm_columns 1:N enir_norm_values`

## Что используется приложением сейчас

- список сборников и параграфов идёт через `enir_collections` и `enir_paragraphs`
- полный параграф отдаёт:
  - UI-слой: `work_compositions`, `crew`, `norms`, `notes`
  - source/tabular слой: `technical_characteristics`, `application_notes`, `source_work_items`, `source_crew_items`, `source_notes`, `norm_tables`
- API при чтении преобразует:
  - `enir_norm_tables`
  - `enir_norm_columns`
  - `enir_norm_rows`
  - `enir_norm_values`
  в вложенную структуру `columns` / `rows` / `cells`

## Фактическое отличие от старого описания

- сейчас в БД нет JSONB-полей `columns` или `rows` внутри `enir_norm_tables`
- текущая схема хранит табличные нормы только в нормализованном виде через отдельные таблицы
- поля метаданных типа `approval_date`, `approval_number`, `issuing_bodies`, `developer`, `coordination`, `amendments` в `enir_collections` отсутствуют
