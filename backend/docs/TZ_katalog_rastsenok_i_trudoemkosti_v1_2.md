# Техническое задание

## Каталог расценок и трудоёмкости с сопоставлением текущей taxonomy JSON

**Версия ТЗ:** 1.2
**Дата:** 22.06.2026
**Исходная taxonomy:** `construction_work_dictionary_v6_4_10.json`
**Целевая taxonomy:** `construction_work_dictionary_v6_4_11.json`
**Текущая taxonomy:** 19 разделов, 219 canonical subtype, код типа — `section_id/subtype_id`.

**Изменения v1.2 относительно v1.1:**
- Устранено противоречие приоритетов `manual / project-specific / catalog / FER / subtype default`.
- `market_estimate_observation` полностью запрещён к автоматическому применению без ручного подтверждения.
- Package conflict проверяется по группе связанных строк, а не только внутри одной строки.
- Зафиксирована новая версия taxonomy `v6.4.11` и policy version `1.2.0`.
- Переработана идемпотентность: отдельно `file_hash`, стабильный ключ строки, `row_content_hash` и revision.
- `mapping_mode` хранится только в `work_rate_mappings`; в `work_rate_items` оставлены агрегатные статусы.
- Поиск строки заголовков использует нормализацию и конфигурируемый лимит сканирования.

---

# 1. Цель

Создать отдельный каталог строительных расценок и трудоёмкости и связать его с текущими canonical типами работ из taxonomy JSON.

Новая подсистема должна отвечать на вопросы:

1. Какая конкретная операция выполняется?
2. К какому canonical типу работы она относится?
3. Какая единица измерения применима?
4. Какова ориентировочная цена за единицу?
5. Какова трудоёмкость на единицу?
6. Можно ли автоматически применить расценку к строке сметы?
7. Требуется ли ручной выбор из нескольких подходящих расценок?
8. Не возникает ли двойной расчёт из-за одновременного применения комплексной и атомарных расценок?

Текущая taxonomy продолжает отвечать на вопрос:

```text
Какой это тип строительной работы?
```

Новый каталог отвечает на вопрос:

```text
Какая конкретная операция, единица, цена и трудоёмкость применимы?
```

---

# 2. Исходные данные

В архиве находятся шесть Excel-файлов.

## 2.1. Нормализованные таблицы расценок

Пять файлов имеют единую структуру из 11 колонок:

```text
№
Вид работ
Ед. изм.
Расценка мин.
Расценка макс.
Расценка сред.
Трудоёмкость мин.
Трудоёмкость макс.
Трудоёмкость сред.
Часовая ставка
Примечания
```

Файлы:

```text
Жилое остальные дома.xlsx
Расценки на ландшафтные работы.xlsx
Расценки №1 11 июня 2026.xlsx
Строит-во каркасного дома.xlsx
Фахверк.xlsx
```

Общее количество строк расценок:

```text
280
```

Во всех этих таблицах используется базовая ставка:

```text
800 руб./чел.-ч
```

Трудоёмкость в них фактически рассчитана от цены:

```text
labor_hours_per_unit = price_per_unit / hourly_rate
```

Следовательно, эти данные являются рыночной оценкой трудоёмкости через стоимость, а не независимым нормативом ФЕР/ГЭСН.

Для таких строк обязательно хранить:

```text
labor_basis = derived_from_price
```

## 2.2. Коммерческая смета

Файл:

```text
грунтовые работы.xlsx
```

содержит:

- 10 строк физических работ;
- строки расходов, логистики и аренды;
- количество;
- стоимость единицы;
- итог;
- отсутствие отдельной нормативной трудоёмкости.

Этот файл должен импортироваться как:

```text
source_kind = market_estimate_observation
```

Его нельзя автоматически считать утверждённым каталогом норм.

## 2.3. Текущая taxonomy

Используется:

```text
construction_work_dictionary_v6_4_10.json
```

Canonical код:

```text
section_id/subtype_id
```

Примеры:

```text
foundation/foundation_rebar_formwork_concrete
landscape/base_geotextile_layers
earthworks/excavation_pit_trench
floor_slabs/monolithic_slab
mep_internal/heating
```

В JSON уже имеется:

```text
operation_object_resolution_policy
```

Его нужно расширять и переиспользовать, а не создавать второй несовместимый справочник операций.

---

# 3. Основной архитектурный принцип

Запрещается добавлять все строки Excel как новые subtype taxonomy.

Нужно разделить три уровня.

## 3.1. Canonical taxonomy

Стабильный укрупнённый тип работы:

```text
foundation/foundation_rebar_formwork_concrete
```

## 3.2. Атомарная или комплексная операция

Конкретное действие:

```text
formwork_installation
rebar_installation
concrete_placement
concrete_vibration
concrete_curing
block_masonry
geotextile_installation
```

## 3.3. Расценка

Конкретная рыночная запись:

```text
Монтаж опалубки
м²
700–900 руб.
0,9–1,1 чел.-ч
```

Связь:

```text
Строка сметы
    ↓
canonical subtype
    ↓
operation_code
    ↓
object_scope
    ↓
подходящие записи каталога
    ↓
выбранная расценка
    ↓
цена и трудоёмкость
```

---

# 4. Виды сопоставления

Для каждой записи каталога хранить `mapping_mode`.

Допустимые значения:

```text
direct
contextual
package
excluded
observation
unmapped
```

## 4.1. `direct`

Расценка однозначно относится к одному canonical subtype.

Пример:

```json
{
  "name": "Укладка бордюрного камня",
  "operation_code": "curb_installation",
  "mapping_mode": "direct",
  "taxonomy_code": "landscape/curbs_edging"
}
```

## 4.2. `contextual`

Операция одинаковая, но canonical subtype зависит от объекта.

Пример:

```json
{
  "name": "Укладка геотекстиля",
  "operation_code": "geotextile_installation",
  "mapping_mode": "contextual",
  "rules": [
    {
      "object_scope_code": "foundation",
      "taxonomy_code": "foundation/foundation_preparation_layers"
    },
    {
      "object_scope_code": "paving_base",
      "taxonomy_code": "landscape/base_geotextile_layers"
    }
  ]
}
```

Обязательные contextual операции:

```text
formwork_installation
rebar_installation
concrete_placement
concrete_vibration
concrete_curing
geotextile_installation
sand_backfill
gravel_backfill
compaction
waterproofing
insulation_installation
block_masonry
surface_preparation
```

## 4.3. `package`

Комплексная расценка включает несколько атомарных операций.

Пример:

```text
Устройство монолитного перекрытия
с армированием и опалубкой
```

Структура:

```json
{
  "mapping_mode": "package",
  "operation_code": "monolithic_slab_complete",
  "taxonomy_code": "floor_slabs/monolithic_slab",
  "included_operations": [
    "formwork_installation",
    "rebar_installation",
    "concrete_placement",
    "concrete_vibration"
  ]
}
```

Если применяется package-расценка, входящие в неё атомарные расценки не должны суммироваться повторно.

## 4.4. `excluded`

Строка не является производственной расценкой.

Примеры:

```text
Накладные расходы
Командировочные расходы
Непредвиденные работы
Расходные материалы
Бытовка
Погрузо-разгрузочные расходы как общий процент/комплект
```

## 4.5. `observation`

Строка получена из коммерческого предложения и используется как рыночное наблюдение.

Она может участвовать:

- в аналитике диапазона цен;
- в сравнении с каталогом;
- в ручной проверке;

но не становится нормативом трудоёмкости без подтверждения.

## 4.6. `unmapped`

Запись импортирована, но ещё не сопоставлена.

Такая запись:

- не применяется автоматически;
- отображается в очереди ручной разметки;
- не влияет на расчёт ГПР.

---

# 5. Новые сущности БД

Названия таблиц могут быть приведены к соглашениям проекта, но состав данных обязателен.

## 5.1. `work_rate_sources`

Источник каталога или рыночного наблюдения.

Поля:

```text
id UUID PK
name varchar
source_kind varchar
source_file varchar
source_sheet varchar nullable
source_version varchar
valid_from date nullable
valid_to date nullable
region varchar nullable
currency char(3), default RUB
hourly_rate numeric nullable
labor_basis varchar nullable
is_active boolean
metadata_json jsonb
created_at
updated_at
```

Допустимые `source_kind`:

```text
normalized_rate_catalog
market_estimate_observation
manual_catalog
external_normative
```

## 5.2. `work_rate_items`

Одна исходная строка расценки.

Поля:

```text
id UUID PK
source_id UUID FK

source_row integer
external_code varchar nullable
stable_row_key varchar
row_content_hash varchar
revision integer default 1
supersedes_rate_item_id UUID nullable

name varchar
normalized_name varchar
notes text nullable

unit_raw varchar nullable
unit_code varchar nullable
unit_dimension varchar nullable

price_min numeric nullable
price_max numeric nullable
price_avg numeric nullable

labor_min numeric nullable
labor_max numeric nullable
labor_avg numeric nullable

hourly_rate numeric nullable
labor_basis varchar nullable

mapping_status varchar
has_active_mapping boolean default false
is_package_candidate boolean default false
review_status varchar

is_active boolean default true

source_payload jsonb
created_at
updated_at
```

Допустимые `labor_basis`:

```text
derived_from_price
independent_market_estimate
normative
manual
unknown
```

Допустимые `mapping_status`:

```text
unmapped
mapped
partially_mapped
excluded
observation
orphaned
```

Допустимые `review_status`:

```text
new
auto_mapped
needs_review
approved
rejected
```

`work_rate_items` не является источником истины для `mapping_mode`.

Источник истины:

```text
work_rate_mappings.mapping_mode
```

Поля:

```text
mapping_status
has_active_mapping
is_package_candidate
```

являются денормализованными агрегатами и обновляются транзакционно после изменения active mappings.

## 5.3. `work_rate_mappings`

Связь расценки с taxonomy.

Поля:

```text
id UUID PK
rate_item_id UUID FK

operation_code varchar
taxonomy_section_id varchar nullable
taxonomy_subtype_id varchar nullable
taxonomy_code varchar nullable

object_scope_code varchar nullable

mapping_mode varchar
priority integer default 100
confidence numeric
mapping_source varchar

taxonomy_version varchar
operation_policy_version varchar

is_primary boolean
is_active boolean

approved_by UUID nullable
approved_at timestamp nullable
created_at
updated_at
```

Одна расценка может иметь несколько mapping rules.

## 5.4. `work_rate_package_components`

Состав комплексной расценки.

Поля:

```text
id UUID PK
package_rate_item_id UUID FK
included_operation_code varchar
included_taxonomy_code varchar nullable
required boolean default true
created_at
```

## 5.5. `work_rate_import_runs`

История импорта.

Поля:

```text
id UUID PK
source_id UUID nullable
filename varchar
file_hash varchar
status varchar

rows_total integer
rows_imported integer
rows_skipped integer
rows_created integer
rows_updated integer
rows_unmapped integer
rows_needs_review integer

errors_json jsonb
started_at
finished_at
created_by UUID nullable
```

## 5.6. `work_rate_unit_aliases`

Нормализация единиц.

Поля:

```text
id
alias
unit_code
unit_dimension
factor_to_base
is_active
```

Стандартные aliases:

```text
м2, м², кв.м        → m2         (area)
м3, м³, куб.м       → m3         (volume)
мп, м.п., пог.м     → m          (length)
шт.                 → pcs        (count)
т                   → t          (weight)
кг                  → kg         (weight)
чел.-час, чел.-ч    → person_hour
маш.-час, маш.-ч    → machine_hour
сотка               → are        (area_plot)
смена, смен, смены  → shift      (time_scope)
компл.              → set        (scope)
```

Дополнительные aliases (добавлены в v1.1):

```text
точка, точки                     → point    (count_scope)
проём, проема, проёма, проем     → opening  (count_scope)
участок, участка                 → site     (scope)
окно, окон, окна                 → window   (count_scope)
%                                → percent  (ratio)
```

Ограничения конверсии:

Нельзя автоматически приравнивать:

```text
точка  ≠ шт.
проём  ≠ шт.
окно   ≠ шт.
участок ≠ шт.
```

Это счётные единицы с разной экономической семантикой. Конверсия между ними запрещена без явного коэффициента.

Для строк с `unit_code = percent`:

```text
mapping_mode = excluded
row_role = overhead
```

если строка содержит накладные расходы, резерв или процентную надбавку.

---

# 6. Изменения существующих моделей

Для строки работы КТП или связанной Estimate необходимо хранить выбранную операцию и расценку.

Предпочтительно добавить поля в сущность строки КТП:

```text
operation_code varchar nullable
selected_rate_item_id UUID nullable
selected_rate_mapping_id UUID nullable

rate_selection_source varchar nullable
rate_confidence numeric nullable
rate_needs_review boolean default false

rate_unit_code varchar nullable
rate_price_min numeric nullable
rate_price_max numeric nullable
rate_price_avg numeric nullable

labor_hours_per_unit_min numeric nullable
labor_hours_per_unit_max numeric nullable
labor_hours_per_unit_avg numeric nullable

calculated_labor_hours_min numeric nullable
calculated_labor_hours_max numeric nullable
calculated_labor_hours_avg numeric nullable

labor_value_source varchar nullable
labor_source_mode varchar nullable

calculation_group_key varchar nullable
package_resolution_mode varchar nullable

rate_catalog_version varchar nullable
rate_calculation_payload jsonb nullable
```

Допустимые `labor_source_mode`:

```text
manual
rate_catalog
fer
hybrid
```

Допустимые `package_resolution_mode`:

```text
package_only
atomic_only
manual_split
```

`calculation_group_key` используется для поиска package conflict между несколькими строками одной родительской работы.

Рекомендуемый состав ключа:

```text
project_id
+ parent_work_id или section_block_id
+ taxonomy_code
+ object_scope_code
+ volume_scope
```

Если на первом этапе изменение модели невозможно, временно допускается хранение в `raw_data`, но это не является целевой архитектурой.

# 7. Импорт Excel

Создать сервис:

```text
work_rate_import_service.py
```

## 7.1. Определение формата

Поддержать два parser profile.

### `normalized_rate_catalog_v1`

Признаки определяются токен-матчингом заголовков (см. 7.1.1).

Ключевые токены:

```text
Вид работ
Ед. изм.
Расценка     + мин
Расценка     + макс
Расценка     + сред
Трудоёмкость + мин
Трудоёмкость + макс
Трудоёмкость + сред
Часовая      + ставк
```

### `market_estimate_observation_v1`

Признаки:

```text
Наименование работ, материалов
Ед. изм.
Кол-во
Стоимость единицы
Всего
```

## 7.1.1. Поиск строки заголовков

Нельзя считать первую строку файла строкой заголовков.

Парсер должен:

1. нормализовать каждую просматриваемую строку;
2. искать группы обязательных токенов;
3. использовать конфигурируемый предел сканирования.

```python
DEFAULT_MAX_HEADER_SCAN_ROWS = 50

HEADER_TOKEN_GROUPS = {
    "normalized_rate_catalog_v1": [
        ("вид", "работ"),
        ("ед", "изм"),
        ("расценк",),
    ],
    "market_estimate_observation_v1": [
        ("наименован",),
        ("ед", "изм"),
        ("кол",),
    ],
}

def find_header_row(
    ws,
    profile: str,
    max_scan_rows: int = DEFAULT_MAX_HEADER_SCAN_ROWS,
) -> int | None:
    groups = HEADER_TOKEN_GROUPS[profile]

    for i, row in enumerate(
        ws.iter_rows(max_row=max_scan_rows, values_only=True),
        1,
    ):
        row_text = normalize_header(
            " ".join(str(v) for v in row if v is not None)
        )

        if all(
            all(token in row_text for token in group)
            for group in groups
        ):
            return i

    return None
```

Строки до найденного заголовка игнорируются как мета-данные.

Если строка заголовков не найдена:

```text
import status = failed
error code = header_not_found
```

Предел `max_header_scan_rows` должен задаваться конфигурацией parser profile.

## 7.1.2. Токен-матчинг заголовков колонок

Нельзя использовать exact match заголовков колонок.

Нормализация заголовка:

```python
import re

def normalize_header(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[,\.\(\)\-/]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
```

Правила токен-матчинга колонок для `normalized_rate_catalog_v1`:

| Поле | Обязательные токены |
|---|---|
| `price_min` | содержит `расценк` и `мин` |
| `price_max` | содержит `расценк` и `макс` |
| `price_avg` | содержит `расценк` и `сред` |
| `labor_min` | содержит `трудоемк` или `трудоёмк`, и `мин` |
| `labor_max` | содержит `трудоемк` или `трудоёмк`, и `макс` |
| `labor_avg` | содержит `трудоемк` или `трудоёмк`, и `сред` |
| `hourly_rate` | содержит `часов` и `ставк` |

При совпадении нескольких колонок по одному правилу — брать первую по порядку и логировать конфликт.

## 7.2. Идемпотентность и revisions

Идемпотентность файла и идентичность строки являются разными механизмами.

### 7.2.1. Идемпотентность import run

Для файла рассчитывается:

```text
file_hash
```

Если уже существует успешный import run с тем же:

```text
source_id + file_hash
```

повторный импорт не выполняется.

### 7.2.2. Стабильный ключ строки

Предпочтительный ключ:

```text
source_id
+ sheet
+ external_code
```

Если `external_code` отсутствует:

```text
source_id
+ sheet
+ source_row
```

Дополнительный fallback при смещении строк:

```text
source_id
+ sheet
+ normalized_name
+ unit_code
+ source_section
```

Стабильный ключ хранится в:

```text
stable_row_key
```

### 7.2.3. Хеш содержимого

Для каждой строки рассчитывается:

```text
row_content_hash
```

Он должен включать:

```text
normalized_name
unit_code
price_min/max/avg
labor_min/max/avg
hourly_rate
normalized_notes
```

### 7.2.4. Алгоритм revision

```text
тот же source_id + file_hash
→ импорт не повторять;

тот же stable_row_key и тот же row_content_hash
→ строка без изменений;

тот же stable_row_key, но новый row_content_hash
→ создать revision либо обновить запись с обязательной историей;

новый stable_row_key
→ создать новую запись.
```

При создании revision:

```text
revision = previous.revision + 1
supersedes_rate_item_id = previous.id
previous.is_active = false
```

Утверждённые manual mappings не копируются молча на новую revision.

Допускается создать mapping candidate на основе предыдущей версии, но:

```text
review_status = needs_review
mapping_source = inherited_candidate
```

Оператор должен подтвердить перенос.

## 7.3. Нормализация названия

Формировать:

```text
normalized_name
```

Правила:

- lowercase;
- нормализация `ё/е`;
- унификация дефисов;
- удаление лишних пробелов;
- нормализация единиц внутри текста;
- сохранение значимых скобок;
- не удалять объектные уточнения: `стены`, `плита`, `ростверк`, `перекрытие`;
- **удалять маркеры `[reference:N]`** из имени и примечаний.

### Очистка `[reference:N]`

```python
import re

REFERENCE_MARKER_RE = re.compile(r"\[reference:\d+\]", re.IGNORECASE)

def clean_reference_markers(text: str) -> str:
    return REFERENCE_MARKER_RE.sub("", text).strip()
```

Применять при формировании `normalized_name` и `normalized_notes`.

Исходное значение с маркерами сохраняется в `source_payload`.

## 7.4. Нормализация чисел

Поддержать:

```text
1 500
1500
1 500,50
1500.50
-
пустое значение
```

Правила:

- `-` и пустое значение → `null`;
- ноль не равен `null`;
- отрицательная цена запрещена;
- `price_min <= price_avg <= price_max`;
- `labor_min <= labor_avg <= labor_max`.

Нормализация строки `-` должна происходить **до** числовой валидации, так что `null` не нарушает ограничения на диапазон.

Если среднее отсутствует:

```text
avg = (min + max) / 2
```

Если есть только одна цена:

```text
price_min = price_avg = price_max
```

## 7.5. Чтение формул Excel

Открывать книгу дважды:

```python
formula_wb = load_workbook(path, data_only=False)
value_wb   = load_workbook(path, data_only=True)
```

Для каждой числовой ячейки сохранять:

```text
formula_text    — формула или None
cached_value    — значение из value_wb
```

Если `cached_value` отсутствует (файл сохранён без пересчёта), поддержать безопасное вычисление простых формул:

```text
ссылки на ячейки в пределах листа
операторы: +  -  *  /
скобки
SUM(диапазон)
```

Запрещено использовать `eval()`. Реализовать минимальный safe evaluator или использовать библиотеку `formulas` / `xlcalculator`.

Если формула не вычислима безопасно:

```text
review_status = needs_review
review_reason = formula_not_evaluated
```

Пример ожидаемых результатов для `грунтовые работы.xlsx`:

```text
=E13*D13           → 300 * 500 = 150 000
=(10+10+5*6+15+10+20)*1000 → (10+10+30+15+10+20)*1000 = 95 000
```

## 7.6. Проверка derived labor

Для источников с `labor_basis=derived_from_price`:

```text
expected_labor = price / hourly_rate
```

Допуск расхождения:

```text
max(0,05 чел.-ч; 3%)
```

При большем расхождении:

```text
review_status = needs_review
```

## 7.7. Коммерческая смета

Для `market_estimate_observation_v1`:

- физические работы импортировать как `observation`;
- накладные строки — `excluded`;
- логистические строки — `excluded` либо отдельный observation с row_role;
- строки с нулём и пометкой `Заказчик` хранить как observation, но не учитывать в средней цене;
- не рассчитывать трудоёмкость автоматически без явно заданной ставки.

---

# 8. Каталог операций

Текущий `operation_object_resolution_policy` использовать как основной registry.

## 8.1. Структура в JSON

Текущий формат `operations` **сохраняется без изменения**:

```json
{
  "operations": {
    "excavation": [
      "формирование корыта",
      "разработка грунта",
      "рытье корыта",
      "выемка грунта"
    ],
    "formwork_installation": [
      "монтаж опалубки",
      "устройство опалубки",
      "установка опалубки"
    ]
  }
}
```

Дополнительные свойства выносятся в отдельный блок `operation_metadata`:

```json
{
  "operation_metadata": {
    "formwork_installation": {
      "negative_terms": [],
      "unit_hints": ["m2"],
      "row_role": "work",
      "kind": "atomic"
    },
    "formwork_rebar_concrete": {
      "negative_terms": [],
      "unit_hints": ["m3", "m2", "t"],
      "row_role": "work",
      "kind": "package",
      "legacy": true
    },
    "monolithic_slab_complete": {
      "negative_terms": [],
      "unit_hints": ["m3", "m2"],
      "row_role": "work",
      "kind": "package",
      "legacy": false
    }
  }
}
```

Состав комплексных операций выносится в блок `operation_packages`:

```json
{
  "operation_packages": {
    "formwork_rebar_concrete": {
      "kind": "package",
      "legacy": true,
      "included_operations": [
        "formwork_installation",
        "rebar_installation",
        "concrete_placement",
        "concrete_vibration"
      ]
    },
    "monolithic_slab_complete": {
      "kind": "package",
      "legacy": false,
      "included_operations": [
        "formwork_installation",
        "rebar_installation",
        "concrete_placement",
        "concrete_vibration"
      ]
    }
  }
}
```

## 8.2. Разграничение блоков

```text
operations           → термины распознавания строк сметы (классификатор)
operation_metadata   → единицы, роль, вид операции (каталог расценок)
operation_packages   → состав комплексных операций (защита от двойного расчёта)
rules                → разрешение operation × object → subtype (классификатор)
```

Не для каждой новой атомарной операции обязательно создавать правило в `rules`. Операция может существовать в `operations` и иметь mapping в БД без отдельного правила классификации строк сметы.

## 8.3. Минимальный набор новых операций

Добавить в `operations` отсутствующие коды:

```text
site_survey_layout
site_clearing
topsoil_removal
trench_excavation
backfill

pile_layout
screw_pile_installation
driven_pile_installation
pile_cutting
pile_concreting
pile_head_installation

formwork_installation
formwork_sealing
formwork_lubrication
formwork_stripping
temporary_support_installation

rebar_installation
rebar_tying
rebar_welding
embedded_parts_installation
protective_layer_spacer_installation

concrete_pumping
concrete_placement
concrete_vibration
concrete_finishing
concrete_joint_installation
concrete_curing

brick_masonry
sip_panel_installation
lgtk_frame_installation
timber_frame_installation
fachwerk_frame_installation
sandwich_panel_installation

slab_installation
monolithic_slab_complete
wood_floor_structure
roof_structure_installation

waterproofing
thermal_insulation
wind_membrane_installation
vapor_barrier_installation

facade_cladding
facade_plastering
painting
wood_protection
metal_corrosion_protection

natural_stone_paving
retaining_wall_construction
gabion_wall_construction
lawn_installation
landscape_grading

drainage_installation
storm_sewer_installation
drainage_well_installation

radiator_installation
underfloor_heating_pipe_installation
```

Каждая операция в `operations` имеет массив терминов:

```json
"formwork_installation": [
  "монтаж опалубки",
  "устройство опалубки",
  "установка опалубки"
]
```

В `operation_metadata` для каждой указывается `unit_hints`, `row_role`, `kind`.

---

# 9. Первичное автоматическое сопоставление

Создать сервис:

```text
work_rate_mapping_service.py
```

## 9.1. Адаптер имён полей

Текущий JSON использует имена `operation` и `object` в rules. В БД и API используются `operation_code` и `object_scope_code`.

Обязательный адаптер при чтении rules:

```python
def adapt_rule(rule: dict) -> dict:
    return {
        "operation_code": (
            rule.get("operation_code") or rule.get("operation")
        ),
        "object_scope_code": (
            rule.get("object_scope_code") or rule.get("object")
        ),
        "section_id":  rule.get("section_id"),
        "subtype_id":  rule.get("subtype_id"),
        "preferred_stage_number": rule.get("preferred_stage_number"),
    }
```

Применять ко всем правилам при загрузке, не изменяя JSON.

## 9.2. Вход

```text
rate_item.name
rate_item.notes
rate_item.unit_code
operation registry (operations + operation_metadata)
taxonomy sections/subtypes
object terms
existing operation-object rules (через адаптер)
```

## 9.3. Этапы

### Шаг 1. Определить row role

Результат:

```text
work
mechanism
logistics
overhead
material
unknown
```

Только `work` участвует в обычном subtype mapping.

### Шаг 2. Определить `operation_code`

Использовать:

- exact phrase;
- strong term;
- action-object pair;
- note;
- unit hints из `operation_metadata`.

### Шаг 3. Определить объектные кандидаты

Примеры:

```text
плита
стены
колонны
ростверк
перекрытие
лестница
фасад
фундамент
дорожка
газон
дренаж
```

### Шаг 4. Получить taxonomy candidates

Фильтровать:

```text
operation_code
× object_scope
× unit compatibility
× taxonomy scope
```

### Шаг 5. Определить mapping mode

- один уверенный кандидат → `direct`;
- одна операция, несколько объектов → `contextual`;
- строка содержит комплекс работ → `package`;
- overhead/material → `excluded`;
- источник commercial estimate → `observation`;
- нет результата → `unmapped`.

## 9.4. Порог автоматического принятия

Автоматически устанавливать `auto_mapped`, только если:

```text
confidence >= 0.90
top1 - top2 >= 0.15
operation_code определён
unit совместима
нет package conflict
```

Иначе:

```text
needs_review
```

## 9.5. Запрещённые упрощения

Нельзя автоматически выбирать subtype только по одному слову:

```text
плита
монтаж
устройство
стены
арматура
бетон
```

Нельзя использовать только similarity полного названия без object scope.

---

# 10. Ручная разметка

Нужна административная страница:

```text
Каталог расценок → Сопоставление
```

## 10.1. Таблица

Колонки:

```text
Источник
Исходная строка
Единица
Цена
Трудоёмкость
Operation code
Mapping mode
Canonical subtype
Object scope
Уверенность
Статус
```

## 10.2. Фильтры

```text
Источник
Статус
Mapping mode
Раздел taxonomy
Operation code
Единица
Needs review
Без сопоставления
```

## 10.3. Действия

Оператор может:

- выбрать operation code;
- выбрать один canonical subtype;
- добавить несколько contextual rules;
- отметить package;
- задать included operations;
- исключить строку;
- утвердить mapping;
- применить такое же правило к похожим строкам;
- вернуть запись в review.

## 10.4. Защита ручных решений

Утверждённое вручную сопоставление:

```text
mapping_source = manual
```

не должно перезаписываться при:

- повторном импорте;
- обновлении taxonomy;
- повторном auto-mapping.

При исчезновении subtype mapping помечается:

```text
orphaned_taxonomy_mapping
```

и требует review.

---

# 11. Выбор расценки для строки сметы

Создать сервис:

```text
work_rate_selection_service.py
```

## 11.1. Вход

Из строки КТП:

```text
work_subtype_code
operation_code
selected_object_scope_code
quantity
unit
section_title
section_description
```

## 11.2. Фильтрация кандидатов

Порядок:

1. Только активные и approved/auto_mapped записи.
2. Совпадение `operation_code`.
3. Совпадение canonical subtype.
4. Совпадение object scope для contextual mapping.
5. Совместимая единица.
6. Регион и период действия.
7. Исключение package conflicts.
8. Приоритет источника.

## 11.3. Приоритет источников и запрет auto-use observation

Рекомендуемый порядок для автоматически применимых источников:

```text
manual project-specific
approved normative
approved normalized catalog
approved market catalog
```

`market_estimate_observation`:

- никогда не выбирается автоматически;
- не участвует в автоматическом расчёте трудоёмкости;
- не участвует в автоматическом расчёте длительности;
- может отображаться как справочный кандидат;
- может участвовать в сравнении цен;
- может быть выбрана вручную;
- может быть преобразована оператором в project-specific approved rate.

Для observation добавить поле:

```text
approved_as_rate boolean default false
```

Только при:

```text
approved_as_rate = true
```

и наличии ручного подтверждения запись может участвовать в расчётах как project-specific rate.

Отсутствие approved catalog rate не является основанием для автоматического выбора observation.

## 11.4. Результат выбора

```json
{
  "rate_item_id": "...",
  "rate_mapping_id": "...",
  "selection_source": "approved_catalog",
  "selection_confidence": 0.97,

  "operation_code": "formwork_installation",
  "taxonomy_code": "foundation/foundation_rebar_formwork_concrete",

  "unit_code": "m2",
  "price_min": 700,
  "price_max": 900,
  "price_avg": 800,

  "labor_min": 0.9,
  "labor_max": 1.1,
  "labor_avg": 1.0,

  "labor_basis": "derived_from_price",
  "needs_review": false
}
```

## 11.5. Несколько кандидатов

Если остаётся более одного равнозначного кандидата:

```text
rate_needs_review = true
```

Автоматически не выбирать «первую» запись.

В UI показать варианты сравнения.

---

# 12. Совместимость единиц

## 12.1. Автоматически допустимые преобразования

```text
kg ↔ t
mm ↔ m
m2 aliases ↔ m2
m3 aliases ↔ m3
```

## 12.2. Запрещённые преобразования

Без отдельного коэффициента нельзя преобразовывать:

```text
m2 ↔ m3
m  ↔ m2
pcs ↔ m
set ↔ pcs
shift ↔ machine_hour
point ↔ pcs
opening ↔ pcs
site ↔ pcs
window ↔ pcs
```

## 12.3. Коэффициент конкретной работы

Если нужна конверсия, она должна задаваться явно:

```text
conversion_factor
conversion_source
conversion_comment
```

Пример:

```text
кирпичная кладка: m2 → m3
```

не должна пересчитываться автоматически без толщины стены.

## 12.4. Несовместимые unit_hints

Если `unit_code` строки не входит в `unit_hints` операции из `operation_metadata`:

```json
{
  "unit_compatibility": "invalid",
  "review_status": "needs_review",
  "auto_applicable": false,
  "review_reason": "operation_unit_conflict"
}
```

Оператор вручную исправляет единицу, задаёт коэффициент или оставляет строку только как рыночное наблюдение.

---

# 13. Расчёт трудоёмкости

## 13.1. Основная формула

```text
calculated_labor_hours =
quantity_in_rate_unit × labor_hours_per_unit
```

Диапазон:

```text
labor_min_total = quantity × labor_min
labor_avg_total = quantity × labor_avg
labor_max_total = quantity × labor_max
```

## 13.2. Derived labor

Для текущих пяти таблиц:

```text
labor_basis = derived_from_price
```

В интерфейсе показывать:

```text
Трудоёмкость рассчитана из цены при ставке 800 руб./чел.-ч
```

Она не должна отображаться как норматив ФЕР/ГЭСН.

## 13.3. Выработка в день

При наличии бригады:

```text
output_per_day =
crew_size × hours_per_day / labor_hours_per_unit
```

При наличии объёма:

```text
working_days =
ceil(total_labor_hours / (crew_size × hours_per_day))
```

## 13.4. Приоритет источников трудоёмкости

Значение с:

```text
labor_value_source = manual
```

никогда не перезаписывается автоматически.

Приоритет зависит от `labor_source_mode`.

### `manual`

```text
1. manual labor_hours
2. иначе требуется ручное заполнение
```

### `rate_catalog`

```text
1. manual labor_hours
2. approved project-specific rate
3. approved catalog rate с independent labor
4. approved catalog rate с derived labor
5. WorkSubtype.output_per_day
6. manual review
```

### `fer`

```text
1. manual labor_hours
2. FER labor hours
3. WorkSubtype.output_per_day
4. manual review
```

### `hybrid`

```text
1. manual labor_hours
2. approved project-specific rate
3. approved catalog rate с independent labor
4. FER labor hours
5. approved catalog rate с derived labor
6. WorkSubtype.output_per_day
7. manual review
```

`market_estimate_observation` не входит ни в один автоматический приоритет, пока не подтверждён как project-specific rate.

## 13.5. Отсутствие количества

Если количество отсутствует или равно нулю:

- не рассчитывать total labor;
- сохранить выбранную расценку;
- установить `rate_needs_review=true`;
- запросить объём у оператора.

---

# 14. Защита от двойного расчёта

## 14.1. Package conflict внутри строки

Если одна строка одновременно содержит package и атомарные компоненты, это конфликт.

Пример:

```text
monolithic_slab_complete
+
formwork_installation
+
rebar_installation
```

## 14.2. Package conflict между строками

Основной реальный сценарий:

```text
Родительская работа: Монолитное перекрытие

Строка 1:
Устройство монолитного перекрытия — package

Строка 2:
Монтаж опалубки — atomic

Строка 3:
Армирование — atomic

Строка 4:
Бетонирование — atomic
```

Проверка должна выполняться по всей группе строк с одинаковым:

```text
calculation_group_key
```

Рекомендуемый ключ:

```text
project_id
+ parent_work_id или section_block_id
+ taxonomy_code
+ object_scope_code
+ volume_scope
```

Сервис:

```python
def detect_package_conflicts(
    rows: list[WorkRateCalculationRow],
    calculation_group_key: str,
) -> list[PackageConflict]:
    ...
```

Правило:

```text
package
и его included_operations
не могут одновременно рассчитывать трудоёмкость
в пределах одного calculation_group_key
```

## 14.3. Legacy package `formwork_rebar_concrete`

Операция `formwork_rebar_concrete` не удаляется.

Она сохраняется как legacy package для строк:

```text
Бетонные работы с армированием
```

Правило выбора:

```text
отдельный «Монтаж опалубки»
→ formwork_installation

«Бетонные работы с армированием»
→ formwork_rebar_concrete

«Устройство монолитной плиты с армированием и опалубкой»
→ monolithic_slab_complete
```

## 14.4. Стратегии разрешения

Допустимые значения:

```text
package_only
atomic_only
manual_split
```

По умолчанию:

```text
комплексная строка без отдельных дочерних операций
→ package_only

отдельные строки атомарных операций
→ atomic_only

неоднозначная структура
→ manual_split
```

При `manual_split` автоматический расчёт блокируется до решения оператора.

## 14.5. Диагностика

Сохранять:

```json
{
  "calculation_group_key": "...",
  "package_conflict": true,
  "package_rate_item_ids": ["..."],
  "atomic_rate_item_ids": ["..."],
  "conflicting_operation_codes": [
    "formwork_installation",
    "rebar_installation",
    "concrete_placement"
  ],
  "resolution": "manual_required"
}
```

Проверка конфликта обязательна:

- при импорте/обновлении строк КТП;
- при выборе или замене расценки;
- перед расчётом трудоёмкости;
- перед построением ГПР.

# 15. Интеграция с текущим JSON

## 15.1. Что хранится в taxonomy JSON

Оставить в taxonomy:

- sections;
- subtypes;
- terms;
- operation registry (`operations`, `operation_metadata`, `operation_packages`);
- object registry;
- operation-object resolution rules;
- project hierarchy;
- stage options.

## 15.2. Что не хранится в taxonomy JSON

Не добавлять туда:

- цены;
- min/max/avg;
- регион;
- период действия;
- конкретный источник Excel;
- трудоёмкость, выведенную из рыночной ставки;
- коммерческие наблюдения.

## 15.3. Версионирование taxonomy и policy

Исходный файл:

```text
construction_work_dictionary_v6_4_10.json
```

не изменять задним числом.

После добавления:

- новых operation codes;
- `operation_metadata`;
- `operation_packages`;
- новых policy rules;

создать:

```text
construction_work_dictionary_v6_4_11.json
```

Версии:

```json
{
  "dictionary_version": "6.4.11",
  "operation_object_resolution_policy": {
    "version": "1.2.0"
  }
}
```

Mapping хранит:

```text
taxonomy_version
operation_policy_version
rate_catalog_version
```

После обновления taxonomy выполнить проверку:

```text
валиден ли taxonomy_code
существует ли operation_code
существует ли object_scope_code
изменился ли title
появился ли package conflict
```

Не выполнять silent remap утверждённых связей.

## 15.4. Валидация новой структуры

Валидатор `v6.4.11` обязан проверять:

1. Каждый ключ `operations` имеет запись в `operation_metadata`.
2. Каждый package из `operation_packages` существует в `operations`.
3. Каждый package имеет `kind=package`.
4. Все `included_operations` существуют в `operations`.
5. Все included operations имеют `kind=atomic`.
6. Все operation codes из rules существуют.
7. Старые поля rules `operation`/`object` читаются через адаптер.
8. Все старые rules остаются валидны.
9. `dictionary_version` и policy version увеличены.
10. В JSON отсутствуют цены и конкретные rate items.

# 16. Интеграция с текущими сервисами

## 16.1. `work_taxonomy_service.py`

Добавить API:

```python
get_operation_registry()
validate_taxonomy_code(code)
get_subtype_context(code)
get_operation_object_candidates(operation_code, object_scope_code)
```

Расширить `operation_object_resolution_policy` недостающими операциями.

При чтении rules использовать адаптер из раздела 9.1.

## 16.2. `upload_service.py`

После определения subtype:

1. сохранить `operation_code`;
2. вызвать rate selection;
3. сохранить найденную расценку и расчёт;
4. не блокировать импорт при отсутствии rate;
5. выставлять review flag.

## 16.3. `ktp_estimate_service.py`

При построении `KtpSessionSubtype`/строки производительности:

- использовать выбранную rate;
- рассчитывать labor и output;
- соблюдать приоритет ручных значений;
- не схлопывать разные работы одного subtype;
- показывать источник расчёта.

## 16.4. Gantt builder

Gantt builder не задаёт собственный альтернативный порядок приоритетов.

Он обязан использовать уже разрешённый результат:

```text
resolved_labor_hours
resolved_labor_source
```

который формируется по правилам раздела 13.4.

Запрещено:

```text
calculated catalog labor
→ поверх manual labor
```

Обязательное правило:

```text
labor_value_source = manual
→ значение не перезаписывается
```

`labor_source_mode` проекта:

```text
manual
rate_catalog
fer
hybrid
```

При отсутствии разрешённой трудоёмкости использовать:

```text
WorkSubtype.output_per_day
```

только если это допускает выбранный режим.

Перед построением задачи Ганта обязательна проверка package conflict по `calculation_group_key`.

# 17. API

Минимальные endpoints.

## 17.1. Импорт

```text
POST /api/work-rates/import
GET  /api/work-rates/import-runs
GET  /api/work-rates/import-runs/{id}
```

## 17.2. Каталог

```text
GET   /api/work-rates
GET   /api/work-rates/{id}
PATCH /api/work-rates/{id}
```

## 17.3. Сопоставления

```text
GET    /api/work-rates/{id}/mappings
POST   /api/work-rates/{id}/mappings
PATCH  /api/work-rate-mappings/{id}
DELETE /api/work-rate-mappings/{id}
POST   /api/work-rate-mappings/{id}/approve
POST   /api/work-rates/{id}/approve-observation-as-rate
```

## 17.4. Автоматическая разметка

```text
POST /api/work-rates/auto-map
POST /api/work-rates/{id}/auto-map
```

## 17.5. Подбор для строки КТП

```text
GET  /api/ktp/items/{item_id}/rate-candidates
POST /api/ktp/items/{item_id}/select-rate
DELETE /api/ktp/items/{item_id}/selected-rate
```

## 17.6. Preview расчёта

```text
POST /api/work-rates/calculate-preview
```

Вход:

```json
{
  "taxonomy_code": "foundation/foundation_rebar_formwork_concrete",
  "operation_code": "formwork_installation",
  "object_scope_code": "foundation",
  "quantity": 120,
  "unit": "m2",
  "crew_size": 4,
  "hours_per_day": 8
}
```

---

# 18. UI строки КТП

На странице работы показывать:

```text
Canonical тип
Операция
Выбранная расценка
Единица расценки
Цена min/avg/max
Трудоёмкость на единицу
Общая трудоёмкость
Основание трудоёмкости
Источник
Уверенность
Требуется проверка
```

Пример:

```text
Монтаж опалубки ростверка
120 м²

Тип:
Фундаменты / Армирование, опалубка и бетонирование

Операция:
Монтаж опалубки

Расценка:
700–900 руб./м²
Средняя: 800 руб./м²

Трудоёмкость:
0,9–1,1 чел.-ч/м²
Средняя: 1,0 чел.-ч/м²

Итого:
120 чел.-ч

Основание:
Рассчитано из цены при ставке 800 руб./чел.-ч
```

---

# 19. Начальное наполнение mapping

## 19.1. Автоматический этап

Выполнить auto-map всех 280 нормализованных строк.

Результат разбить:

```text
approved candidates
needs_review
unmapped
excluded
package candidates
```

## 19.2. Ручной этап

Обязательно вручную проверить:

- опалубку;
- арматуру;
- бетон;
- гидроизоляцию;
- утепление;
- кладку;
- перекрытия;
- кровлю;
- фасады;
- инженерные системы;
- строки с единицей `компл.`;
- комплексные расценки;
- строки с нулевой ценой.

## 19.3. Запрещённая цель

Не ставить требование:

```text
100% строк должны автоматически получить mapping
```

Корректная цель:

```text
100% строк импортированы;
100% строк имеют статус;
неуверенные mapping не применяются автоматически.
```

---

# 20. Контрольные примеры

## 20.1. Опалубка

```text
Монтаж опалубки
```

Ожидание:

```text
operation_code = formwork_installation
mapping_mode = contextual
```

Возможные subtype:

```text
foundation/foundation_rebar_formwork_concrete
structural_frame/rc_monolithic_frame
floor_slabs/monolithic_slab
monolithic_stairs/stair_formwork_rebar
```

## 20.2. Геотекстиль

```text
Укладка геотекстиля
```

Ожидание:

```text
foundation → foundation/foundation_preparation_layers
paving_base → landscape/base_geotextile_layers
```

## 20.3. Монолитное перекрытие

```text
Устройство монолитного перекрытия
с армированием и опалубкой
```

Ожидание:

```text
mapping_mode = package
taxonomy_code = floor_slabs/monolithic_slab
```

## 20.4. Бордюр

```text
Укладка бордюрного камня
```

Ожидание:

```text
mapping_mode = direct
taxonomy_code = landscape/curbs_edging
```

## 20.5. Накладные

```text
Накладные, командировочные и транспортные расходы
```

Ожидание:

```text
mapping_mode = excluded
row_role = overhead
```

## 20.6. Коммерческое наблюдение

```text
разработка грунта с погрузкой в самосвал
400 руб./м³
```

Ожидание:

```text
source_kind = market_estimate_observation
mapping_mode = observation
operation_code = excavation либо soil_disposal по утверждённому правилу
auto_normative = false
```

---

# 21. Тестирование

## 21.1. Unit: import

Проверить:

1. Все 280 строк пяти каталогов импортируются.
2. Повторный импорт того же `file_hash` не создаёт новый run.
3. Изменённый файл создаёт новый import run.
4. Неизменённая строка с тем же `row_content_hash` не создаёт revision.
5. Изменённая строка с тем же `stable_row_key` создаёт новую revision.
6. Manual mapping не переносится на revision без review.
7. Единицы нормализуются.
8. Запятая и точка в числах обрабатываются.
9. `-` преобразуется в null.
10. Ноль сохраняется как ноль.
11. Derived labor проверяется по ставке.
12. Ошибочная строка получает needs_review.

## 21.2. Unit: import — форматы и специальные случаи

1. Оба варианта заголовков колонок распознаются одним профилем.
2. Заголовок находится после 11 мета-строк.
3. Поиск использует нормализованные группы токенов.
4. Настраиваемый `max_header_scan_rows=50` работает.
5. Cached formula value читается.
6. Формула без кеша вычисляется safe evaluator.
7. Невычислимая формула получает needs_review.
8. `[reference:N]` удаляется из normalized fields.
9. Исходный текст сохраняется в source payload.
10. `точка` → `point`.
11. `проём` → `opening`.
12. `участок` → `site`.
13. `окно` → `window`.
14. `%` + резерв → excluded overhead.

## 21.3. Unit: mapping

Проверить:

1. Direct mapping.
2. Contextual mapping.
3. Package mapping.
4. Excluded mapping.
5. Observation mapping.
6. Observation не применяется автоматически.
7. Observation после ручного approve становится project-specific rate.
8. Unit conflict.
9. Несколько одинаковых кандидатов.
10. Invalid taxonomy code.
11. Ручной mapping не перезаписывается.
12. Legacy rule fields читаются через адаптер.
13. `pile_drilling + m2` → invalid.
14. `mapping_mode` берётся из `work_rate_mappings`.
15. Агрегаты `mapping_status/has_active_mapping` обновляются транзакционно.

## 21.4. Unit: calculation

Проверить:

```text
quantity = 120 m2
labor_avg = 1.0 person-hour/m2
→ total = 120 person-hours
```

Проверить min/max.

Проверить:

```text
120 / (4 × 8) = 3.75
→ 4 рабочих дня
```

Для каждого `labor_source_mode` проверить порядок приоритетов.

Отдельно:

```text
manual labor
→ никогда не перезаписывается
```

## 21.5. Unit: package conflict

Проверить:

1. Package и atomic в одной строке.
2. Package и atomic в разных строках одной `calculation_group_key`.
3. Одинаковые операции в разных group key не конфликтуют.
4. `package_only`.
5. `atomic_only`.
6. `manual_split`.
7. ГПР не строится при unresolved manual split.

## 21.6. Integration: taxonomy

Для всех active mapping:

```text
taxonomy_code существует в v6.4.11
operation_code существует
object scope существует либо null
unit совместима
```

Валидатор проверяет:

- metadata для каждой operation;
- packages;
- atomic components;
- legacy rules;
- policy version 1.2.0.

## 21.7. Integration: KTP/Gantt

Проверить:

1. Выбранная rate попадает в строку КТП.
2. Labor hours попадает в задачу Ганта.
3. Manual labor не перезаписывается.
4. Строки одного subtype с разными операциями не схлопываются.
5. Отсутствие rate не ломает ГПР.
6. Review flag виден оператору.
7. Observation без approve не используется.
8. Group package conflict блокирует автоматический расчёт.
9. Gantt использует resolved labor source из раздела 13.4.

## 21.8. Регрессия

Проверить:

```text
распознавание PDF-сметы
классификация stage/subtype
ручная смена subtype
построение KTP
формирование ГПР
FER-режим
ручные значения производительности
taxonomy v6.4.10 остаётся неизменной
taxonomy v6.4.11 загружается и валидируется
```

# 22. Критерии приёмки

Работа считается принятой, если:

1. Создан отдельный каталог расценок, не смешанный с taxonomy.
2. Импортированы все 280 строк нормализованных файлов.
3. Коммерческая смета импортируется как observation.
4. Повторный импорт того же файла идемпотентен.
5. Изменённые строки создают revision без потери истории.
6. Каждая строка имеет mapping status.
7. `mapping_mode` хранится только в `work_rate_mappings`.
8. Поддерживаются direct/contextual/package/excluded/observation/unmapped.
9. Mapping ссылается на существующий canonical subtype.
10. Operation registry сохраняет текущую dict-структуру.
11. Создана taxonomy v6.4.11; v6.4.10 не изменена.
12. Policy version повышена до 1.2.0.
13. Валидатор проверяет metadata, packages и atomic components.
14. Unit conversion выполняется только для совместимых единиц.
15. Derived labor явно отмечен как derived_from_price.
16. Рыночная трудоёмкость не называется нормативом ФЕР/ГЭСН.
17. Observation никогда не применяется автоматически без approve.
18. Package не дублируется атомарными операциями внутри calculation group.
19. Неуверенные mapping не применяются автоматически.
20. Ручные mapping защищены от перезаписи.
21. Manual labor никогда не перезаписывается.
22. Для каждого labor_source_mode действует зафиксированный приоритет.
23. Для строки КТП можно выбрать и заменить расценку.
24. Рассчитываются min/avg/max labor hours.
25. Рассчитывается duration с учётом бригады.
26. Текущий subtype и этап не изменяются выбором расценки.
27. Отсутствие расценки не блокирует импорт сметы.
28. Legacy rule fields читаются через адаптер.
29. Поиск заголовков использует нормализованные группы токенов.
30. Все unit-, integration- и regression-тесты проходят.

# 23. Вне объёма первой версии

Не требуется:

- создавать полноценную замену ФЕР/ГЭСН;
- автоматически индексировать цены по инфляции;
- учитывать региональные коэффициенты без исходных данных;
- рассчитывать стоимость материалов;
- преобразовывать несовместимые единицы без явных коэффициентов;
- автоматически утверждать все 280 mapping;
- менять существующую project hierarchy;
- добавлять каждую расценку как subtype;
- использовать коммерческое предложение как норматив без проверки;
- переименовывать поля `operation`/`object` в существующих rules JSON;
- изменять задним числом `construction_work_dictionary_v6_4_10.json`.

---

# 24. Порядок реализации

## Этап A. Модель и миграции

1. Таблицы источников, расценок, mappings и import runs.
2. Stable row key, content hash и revision chain.
3. Unit aliases.
4. Поля выбранной расценки в строках КТП.
5. `calculation_group_key` и package resolution fields.
6. Индексы и ограничения.
7. Единственный источник `mapping_mode` в mappings.

## Этап B. Импорт

1. Parser normalized catalog с token-based header matching.
2. Parser market observation с поиском строки заголовков.
3. Нормализация единиц и чисел.
4. Чтение Excel формул (data_only + safe evaluator).
5. Очистка `[reference:N]`.
6. Идемпотентность.
7. Отчёт импорта.

## Этап C. Operation registry

1. Создать taxonomy v6.4.11 на основе v6.4.10.
2. Расширить `operations` dict новыми кодами.
3. Добавить `operation_metadata`.
4. Добавить `operation_packages`.
5. Добавить object terms.
6. Повысить policy version до 1.2.0.
7. Добавить валидатор новой структуры.

## Этап D. Mapping

1. Auto-map с адаптером имён полей.
2. Confidence.
3. Direct/contextual/package.
4. Manual review.
5. Защита ручных решений.

## Этап E. Selection и расчёт

1. Подбор кандидатов для строки КТП.
2. Запрет auto-use observation.
3. Unit compatibility.
4. Labor min/avg/max.
5. Разрешение labor source mode.
6. Duration.
7. Group-level package conflict.
8. Package resolution.

## Этап F. UI/API

1. Импорт.
2. Каталог.
3. Очередь review.
4. Выбор расценки в КТП.
5. Источник и диагностика.

## Этап G. Тесты и начальная разметка

1. Unit tests (21.1–21.8 включая все дополнительные случаи v1.1).
2. Integration tests.
3. Регрессия ГПР.
4. Auto-map 280 строк.
5. Ручная проверка спорных групп.
