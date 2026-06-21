# Отчёт о выполнении ТЗ 2.1

## Результат

Реализована контекстная классификация строк сметы по схеме:

```text
операция строки × кандидаты объектов блока × stage_options
```

Версия справочника:

```text
construction_work_dictionary_v6_4_10@1.8.0
```

## Изменённые файлы

- `services/materials_labor_pdf_parser.py`
- `services/resource_classifier.py`
- `services/work_taxonomy_service.py`
- `services/stage_classifier.py`
- `services/upload_service.py`
- `services/ktp_estimate_service.py`

Добавлены:

- `data/construction_work_dictionary_v6_4_10.json`
- `tests/test_contextual_taxonomy_v6410.py`
- `tests/test_ilyinskie_pdf_v6410.py`

## Реализованные изменения

### PDF-парсер

- `section_title` и `section_description` сохраняются отдельно.
- Добавлен стабильный `section_block_id`.
- Формируется `item_text = name + spec`.
- Сводная страница разбирается и сопоставляется с детальными блоками.
- Несопоставленная позиция «Утилизация грунта за пределы участка» создаётся как `summary_only`.
- Добавляется синтетическая работа «Планировка участка спецтехникой» без влияния на финансовый итог.

### Роли строк

- Разгрузка, доставка и погрузка материалов классифицируются как `logistics`.
- Утилизация и вывоз грунта остаются физическими работами.
- Надзор остаётся `overhead`.
- Материалы, механизмы, логистика и overhead не получают собственного `work_subtype_code`.

### Контекстная классификация

- Добавлено определение операции строки.
- Из title и description формируется несколько object candidates.
- Каждая строка mixed-object блока самостоятельно выбирает объект.
- Добавлена operation-object policy версии `1.1.0`.
- Добавлены операции `block_masonry` и `compaction`.
- Добавлен subtype `landscape/decorative_block_walls`.
- Добавлен stage option `decorative_block_walls` в этап `9.4.6`.
- Бетонная отмостка и основание гранитных ступеней явно распознаются как объекты ландшафтного основания.
- Чистовая планировка направляется в существующий этап `9.4.11`.

### Этапы и subtype

- Deterministic operation-object result передаёт `preferred_stage_number`.
- `stage_classifier` использует его до общего скоринга заголовков.
- `grouped_all` больше не назначает один primary subtype всем строкам.
- Строки одного PDF-блока могут получить разные object scope, subtype и этапы.

### Уверенность и preview

- Сохраняются отдельные `stage_confidence` и `work_type_confidence`.
- В preview добавлены operation/object diagnostics.
- Не-work строки не отображают уверенность собственного типа работы.

## Проверка на «Ильинские сады 02.04.2026.pdf»

### Финансы

| Показатель | Значение |
|---|---:|
| Заявленный итог | 12 725 959,27 руб. |
| Детальные блоки | 12 225 959,27 руб. |
| Summary-only | 500 000,00 руб. |
| Итог импорта | 12 725 959,27 руб. |
| Расхождение | 0,00 руб. |

Фактический PDF extractor выделяет:

- 23 сырые строки сводной таблицы;
- 22 ценовые позиции;
- 21 совпадение с детальными блоками;
- 1 `summary_only`;
- 1 информационную строку без финансовой позиции.

Это уточняет первоначальный ручной подсчёт строк, но не меняет финансовую reconciliation.

### Качество классификации

| Показатель | Значение |
|---|---:|
| Всего импортированных строк | 344 |
| Физические работы | 114 |
| Материалы | 134 |
| Overhead | 83 |
| Логистика | 9 |
| Механизмы | 4 |
| Неопределённые физические работы | 0 |
| Не-work строки с собственным subtype | 0 |
| Review + high subtype confidence | 0 |

### Проверенные примеры

- «Утилизация грунта за пределы участка» → `9.4.2 / earthworks/soil_disposal`.
- «Бурение для устройства буронабивных свай» → `9.4.3 / foundation/pile_foundation`.
- «Выполнение кладки из керамических блоков» → `9.4.6 / landscape/decorative_block_walls`.
- «Планировка участка спецтехникой» → `9.4.11 / landscape/landscape_grading`.
- «Разгрузка брусчатки вручную» → `logistics`, без собственного subtype.
- Геотекстиль, бетон, песок, корыто и трамбование различаются по объекту блока.

## Автоматические тесты

```text
7 passed
```

Покрыто:

- четыре зеркальные operation/object пары;
- mixed-object блок АРТ-стены;
- роли логистики, механизма, overhead и утилизации;
- наличие этапа `9.4.11`;
- полная PDF reconciliation;
- отсутствие subtype у не-work строк;
- отсутствие неизвестных физических работ в контрольной смете.

## Запуск тестов

```bash
export ILYINSKIE_PDF="/path/to/Ильинские сады 02.04.2026.pdf"
pytest tests/test_contextual_taxonomy_v6410.py        tests/test_ilyinskie_pdf_v6410.py -q
```

## Подключение

1. Скопировать `services/*.py` поверх соответствующих файлов проекта.
2. Поместить `construction_work_dictionary_v6_4_10.json` в `backend/app/data`.
3. Убедиться, что runtime загружает именно `construction_work_dictionary_v6_4_10.json`.
4. Перезапустить backend.
5. Прогнать приложенные тесты.
