# Канонический JSON для ЕНИР (строгая DB-версия)

Этот формат — единый канон для сборников Е1, Е2, Е3 и следующих выпусков.
Логика: сначала хранится структура документа без потери табличных данных, а уже поверх неё можно строить SQL, view, поиск и расчёты.

## Верхний уровень

### Служебные поля

- `schema_version` — версия схемы, целое число
- `source_file` — имя исходного JSON/документа, из которого собран файл
- `description` — краткое описание файла

### Метаданные сборника

- `collection_name: string` — краткое обозначение сборника (`Е1`, `Е3`, ...)
- `collection_title: string` — полное название сборника (`КАМЕННЫЕ РАБОТЫ`, ...)
- `issuing_bodies: array[string]` — организации, утвердившие сборник
- `approval_date: string` — дата утверждения в формате `YYYY-MM-DD`
- `approval_number: string` — номер постановления об утверждении
- `developer: string` — организация-разработчик сборника
- `coordination: string` — организация, согласовавшая сборник
- `amendments: array[object]` — список изменений/поправок к сборнику; каждый объект содержит:
  - `amendment_date: string` — дата изменения (`YYYY-MM-DD`)
  - `amendment_number: string` — номер постановления об изменении
  - `issuing_bodies: array[string]` — организации, выпустившие изменение

Примечание: если сборник не содержит метаданных (например, ранние версии файлов), поля заполняются пустыми значениями по общему правилу канона.

### Данные параграфов

- `paragraphs` — список параграфов
- `paragraph_work_items` — составы работ
- `paragraph_crew_items` — составы звеньев
- `paragraph_notes` — примечания и коэффициенты
- `norm_tables` — таблицы норм; каждая запись хранится как JSONB и содержит вложенные колонки и строки со значениями

## 1. paragraphs

Одна запись = один параграф ЕНИР.

Поля:
- `paragraph_id: string` — внутренний ID параграфа
- `paragraph_order: integer` — порядок параграфа в сборнике
- `code: string` — код параграфа (`Е1-1`, `Е2-1-11`, `Е3-29`)
- `title: string` — заголовок параграфа
- `unit: string` — единица измерения нормы
- `technical_characteristics: array[string]` — технические характеристики, если выделены отдельно
- `application_notes: array[string]` — общие указания по применению норм для этого параграфа

Примечание: оба поля всегда присутствуют в схеме. Если исходный документ их содержит — заполняются; если нет — остаются пустым массивом `[]`. Не путать с `paragraph_notes`: там хранятся примечания с коэффициентами, привязанные к конкретному параграфу и влияющие на расчёт норм.

## 2. paragraph_work_items

Одна запись = один пункт состава работ.

Поля:
- `paragraph_id: string`
- `item_order: integer`
- `text: string`

## 3. paragraph_crew_items

Одна запись = один пункт состава звена.

Поля:
- `paragraph_id: string`
- `item_order: integer`
- `profession: string` — профессия/роль
- `grade: integer|null` — разряд, если выделен
- `count: integer|null` — количество, если выделено
- `raw: string` — исходная строка без потери текста

## 4. paragraph_notes

Одна запись = одно примечание или коэффициент.

Поля:
- `paragraph_id: string`
- `item_order: integer`
- `code: string|null` — например `ПР-1`, если выделяется
- `text: string`
- `coefficient: number|null` — числовой коэффициент, если явно извлекается

Примечание:
`application_notes` сюда не входят — они живут в `paragraphs.application_notes`.

## 5. norm_tables (JSONB)

Одна запись = одна таблица внутри параграфа. Хранится как JSONB-объект — колонки и строки вложены внутрь.

В БД это одна таблица `norm_tables` с JSONB-колонками `columns` и `rows`:

```sql
CREATE TABLE norm_tables (
  table_id     TEXT PRIMARY KEY,
  paragraph_id TEXT    NOT NULL,
  table_order  INTEGER NOT NULL,
  title        TEXT    NOT NULL,
  row_count    INTEGER NOT NULL,
  columns      JSONB   NOT NULL,  -- массив объектов колонок
  rows         JSONB   NOT NULL   -- массив объектов строк со значениями
);
```

### Поля верхнего уровня записи

- `table_id: string`
- `paragraph_id: string`
- `table_order: integer`
- `title: string`
- `row_count: integer`

### columns (JSONB-массив)

Каждый элемент:
- `column_order: integer`
- `column_key: string` — стабильный ключ колонки (`c1`, `c2`, ... или семантический: `norm_time`, `price_rub`, ...)
- `header: string` — полный заголовок колонки
- `label: string` — короткая метка; если не выделена отдельно, дублирует `header`

### rows (JSONB-массив)

Каждый элемент:
- `row_id: string`
- `row_order: integer`
- `source_row_num: integer|null` — номер строки в исходной таблице, если известен
- `values: object` — словарь `column_key → { value_type, value_text }`
  - `value_type: string` — обычно `cell`, возможны специальные типы вроде `price_cell`
  - `value_text: string`

Важно: `rows` — логические строки, не визуальные строки DOCX. Одна логическая строка = один набор значений, к которому относятся все ячейки.

## Принципы канона

1. Схема должна быть одинаковой для всех сборников.
2. Если поле отсутствует в исходнике, оно не удаляется из схемы, а заполняется пустым значением:
   - строка: `""`
   - массив: `[]`
   - число/nullable: `null`
3. `application_notes` хранятся в `paragraphs`, а не в `paragraph_notes`.
4. Таблицы норм хранятся в `norm_tables` как JSONB: колонки (`columns`) и строки со значениями (`rows`) вложены внутрь каждой записи таблицы. Отдельные плоские массивы `norm_columns`, `norm_rows`, `norm_values` не используются.
5. Нельзя насильно уплощать разные таблицы в один набор полей вроде `time_norm/price/condition`, если это разрушает структуру исходника.
6. Сначала сохраняется истина документа, потом поверх строятся производные модели для БД, поиска и расчётов.

## Мини-пример

```json
{
  "schema_version": 1,
  "source_file": "enir_e1_cleaned_v3.json",
  "description": "Unified DB-oriented representation of ENiR.",
  "collection_name": "Е1",
  "collection_title": "ЗЕМЛЯНЫЕ РАБОТЫ",
  "issuing_bodies": [
    "Государственный строительный комитет СССР"
  ],
  "approval_date": "1986-12-05",
  "approval_number": "43/512/29-50",
  "developer": "",
  "coordination": "",
  "amendments": [],
  "paragraphs": [
    {
      "paragraph_id": "Е1-1",
      "paragraph_order": 1,
      "code": "Е1-1",
      "title": "Пример заголовка",
      "unit": "100 м3",
      "technical_characteristics": [],
      "application_notes": []
    }
  ],
  "paragraph_work_items": [
    {
      "paragraph_id": "Е1-1",
      "item_order": 1,
      "text": "Подготовить рабочее место."
    }
  ],
  "paragraph_crew_items": [
    {
      "paragraph_id": "Е1-1",
      "item_order": 1,
      "profession": "Машинист",
      "grade": 6,
      "count": 1,
      "raw": "Машинист 6 разр. — 1"
    }
  ],
  "paragraph_notes": [
    {
      "paragraph_id": "Е1-1",
      "item_order": 1,
      "code": "ПР-1",
      "text": "Н.вр. и Расц. умножать на 1,2.",
      "coefficient": 1.2
    }
  ],
  "norm_tables": [
    {
      "table_id": "Е1-1_t1",
      "paragraph_id": "Е1-1",
      "table_order": 1,
      "title": "Нормы времени и расценки",
      "row_count": 2,
      "columns": [
        { "column_order": 1, "column_key": "condition", "header": "Условие",        "label": "Условие" },
        { "column_order": 2, "column_key": "norm_time", "header": "Н.вр. чел-ч",   "label": "Н.вр." },
        { "column_order": 3, "column_key": "price_rub", "header": "Расценка, руб.", "label": "Расц." }
      ],
      "rows": [
        {
          "row_id": "Е1-1_t1_r1",
          "row_order": 1,
          "source_row_num": 1,
          "values": {
            "condition": { "value_type": "cell", "value_text": "Грунт I группы" },
            "norm_time": { "value_type": "cell", "value_text": "1.8" },
            "price_rub": { "value_type": "cell", "value_text": "0-10" }
          }
        },
        {
          "row_id": "Е1-1_t1_r2",
          "row_order": 2,
          "source_row_num": 2,
          "values": {
            "condition": { "value_type": "cell", "value_text": "Грунт II группы" },
            "norm_time": { "value_type": "cell", "value_text": "2.1" },
            "price_rub": { "value_type": "cell", "value_text": "0-12" }
          }
        }
      ]
    }
  ]
}
```
