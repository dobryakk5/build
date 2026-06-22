# Отчёт о реализации каталога расценок и трудоёмкости v1.2

## Реализовано

### Каталог и импорт

- Добавлен отдельный каталог расценок, не смешанный с canonical taxonomy.
- Поддержаны два профиля Excel:
  - `normalized_rate_catalog_v1`;
  - `market_estimate_observation_v1`.
- Реализованы:
  - поиск заголовка по нормализованным группам токенов;
  - два варианта названий колонок;
  - чтение формул и cached values;
  - безопасное вычисление простых формул без `eval()`;
  - очистка `[reference:N]`;
  - нормализация единиц, включая `point/opening/site/window/percent/shift`;
  - идемпотентность import run;
  - `stable_row_key`, `row_content_hash`, revisions и `supersedes_rate_item_id`;
  - проверка трудоёмкости, выведенной из ставки 800 руб./чел.-ч.

### Mapping

- Поддержаны режимы:
  - `direct`;
  - `contextual`;
  - `package`;
  - `excluded`;
  - `observation`;
  - `unmapped`.
- Сохранена обратная совместимость rules JSON:
  - `operation` читается как `operation_code`;
  - `object` читается как `object_scope_code`.
- Добавлен автоматический mapping с порогами confidence и unit gate.
- Неуверенные mapping не применяются автоматически.
- Ручное утверждение защищено от автоматической перезаписи.

### Расценки и трудоёмкость

- Observation никогда не выбирается автоматически.
- Observation может стать project-specific rate только после ручного approve.
- Реализован выбор по:
  - operation;
  - canonical subtype;
  - object scope;
  - единице;
  - приоритету источника.
- Рассчитываются:
  - min/avg/max трудоёмкости;
  - duration;
  - output per day.
- Реализованы режимы источника:
  - `manual`;
  - `rate_catalog`;
  - `fer`;
  - `hybrid`.
- Ручная трудоёмкость всегда имеет высший приоритет.

### Package conflict

- `formwork_rebar_concrete` сохранён как legacy package.
- `monolithic_slab_complete` добавлен как отдельный package.
- Конфликт package/atomic проверяется между всеми строками одного `calculation_group_key`.
- Неоднозначный конфликт переводится в `manual_split` и блокирует автоматический расчёт.

### Taxonomy

- Исходный `construction_work_dictionary_v6_4_10.json` не изменён.
- Создан `construction_work_dictionary_v6_4_11.json`.
- Policy version: `1.2.0`.
- Сохранена структура:
  - `operations: dict code → terms`;
  - старые поля rules `operation/object`.
- Добавлены:
  - 80 operation codes в сумме;
  - `operation_metadata` для каждой операции;
  - `operation_packages`;
  - атомарные правила operation × object → subtype.
- Валидатор проверяет metadata, packages, atomic components и rule references.

### Интеграция с существующими сервисами

- `work_taxonomy_service.py` переведён на v6.4.11 и получил публичные API operation registry.
- `upload_service.py` после определения subtype/operation:
  - ищет утверждённую совместимую расценку;
  - сохраняет выбранную rate и трудоёмкость;
  - не блокирует импорт при отсутствии rate;
  - отмечает package conflicts.
- `gantt_builder.py`:
  - сначала использует manual labor;
  - затем resolved catalog/FER labor;
  - не строит автоматическую длительность при unresolved package conflict.

### БД и API

- Добавлена PostgreSQL-схема `057_work_rate_catalog.sql`.
- Добавлен JSON-backed FastAPI router factory со следующими группами endpoints:
  - импорт и import runs;
  - каталог и редактирование rate items;
  - CRUD/approve mappings;
  - auto-map всех или одной записи;
  - approve observation;
  - calculation preview.
- JSON repository предназначен для preview/тестирования; SQL-схема — целевой production storage.

## Начальное наполнение

Импортировано:

- 280 строк нормализованных каталогов;
- 16 строк коммерческой сметы-observation;
- всего 296 записей.

Результат auto-map:

- `mapped`: 62;
- `partially_mapped`: 81;
- `unmapped`: 135;
- `excluded`: 8;
- `observation`: 10;
- автоматически применимых физических работ: 62;
- требуют review: 226.

Большое число review является ожидаемым: ТЗ запрещает автоматически утверждать неоднозначные contextual и неизвестные операции.

## Проверка

Команда:

```bash
ILYINSKIE_PDF='/mnt/data/Ильинские сады 02.04.2026.pdf' pytest -q
```

Результат:

```text
19 passed
```

Проверены:

- существующая PDF-регрессия;
- contextual taxonomy v6.4.11;
- импорт 280 строк;
- observation и формулы;
- revisions;
- новые единицы;
- direct/contextual/package mapping;
- неверная единица бурения свай;
- запрет auto-use observation;
- приоритет manual labor;
- group-level package conflict;
- Gantt priority;
- upload rate enrichment.

## Ограничения переданного исходного проекта

В архиве отсутствовали:

- реальные SQLAlchemy-модели и общий `Base`;
- Alembic environment;
- файл регистрации FastAPI routers;
- frontend административной страницы;
- точная ORM-модель строки КТП для добавления FK/полей.

Поэтому в пакет включены:

- готовая PostgreSQL-схема;
- отдельная assignment-таблица, не зависящая от названия KTP ORM;
- router factory;
- framework-neutral сервисы;
- инструкция подключения.

Для production нужно перенести SQL в Alembic revision проекта, зарегистрировать router и при необходимости заменить JSON repository на SQLAlchemy repository. Бизнес-логика и тестируемое ядро для этого готовы.
