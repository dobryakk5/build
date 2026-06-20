# Этап 2 — итоги, НДС и preview вложенных материалов

Реализован второй этап ТЗ поверх архива `services_v6_4_4_stage1_work_material_matrix.zip`.

## Что изменено

### `services/excel_work_material_matrix_parser.py`

- строки `Итого`, `НДС N%`, `ВСЕГО по смете` по-прежнему не создают `ParsedRow`;
- `meta["declared_totals"]` сохраняется в совместимом списочном формате;
- денежные значения объявленных итогов округляются до копеек через `Decimal` и `ROUND_HALF_UP`.

Пример:

```json
[
  {"kind": "total_without_vat", "label": "Итого", "total": 13901391.77},
  {"kind": "vat", "label": "НДС 22%", "rate": 22.0, "total": 3058306.19},
  {"kind": "grand_total", "label": "ВСЕГО по смете", "total": 16959697.96}
]
```

### `services/upload_service.py`

- добавлен единый разбор metadata: `_declared_totals_from_meta()`;
- `_declared_total_from_meta()` для нового профиля выбирает `total_without_vat`;
- старые PDF-форматы `grand_total` и `section_total` сохранены;
- fallback на строки подытогов выполняется только при `None`, а не через `or`;
- `_compute_preview()` включает вложенные материалы ровно один раз;
- добавлены поля:
  - `computed_work_total`;
  - `computed_material_total`;
  - `computed_total_without_vat`;
  - `computed_vat_total`;
  - `computed_total_with_vat`;
  - `declared_vat`;
  - `declared_vat_rate`;
  - `declared_total_with_vat`;
  - `difference_with_vat`;
- `computed_total_all_rows` теперь содержит полную сумму работ и вложенных материалов;
- финальный импорт использует ту же базу сверки, что и preview;
- `EstimateBatch.import_meta` и `job.result` получают новые суммы;
- `_material_dict()` сохраняет `unit_price`, `source_num`, `parent_work_num`, `source_excel_row`, `item_type_confidence`;
- нулевые `quantity`, `unit_price`, `total_price` не теряются;
- вложенные материалы доступны и в плоском `rows`, и в сгруппированном `groups` preview;
- групповые material totals включают вложенные материалы;
- предусмотрено исключение двойного подсчёта, если один материал одновременно представлен вложенно и верхнеуровневой строкой.

## Контрольные результаты

### Смета Здание 1

- работы: 36 / `8 097 673,26`;
- материалы: 97 / `5 803 718,51`;
- без НДС: `13 901 391,77`;
- НДС 22%: `3 058 306,19`;
- с НДС: `16 959 697,96`;
- `difference = 0.0`;
- `difference_with_vat = 0.0`.

### Смета Здание 2

- работы: 36 / `8 121 138,88`;
- материалы: 95 / `5 304 862,62`;
- без НДС: `13 426 001,50`;
- НДС 22%: `2 953 720,33`;
- с НДС: `16 379 721,83`;
- `difference = 0.0`;
- `difference_with_vat = 0.0`.

## Тесты

Добавлен файл `tests/services/test_upload_declared_totals.py`.

Проверяются:

1. суммы обеих реальных смет;
2. пустой `subtotal_rows` для нового профиля;
3. новый формат объявленных итогов;
4. обратная совместимость `grand_total`/`section_total`;
5. расширенные поля материала в двух preview-путях;
6. сохранение нулевых значений;
7. отсутствие двойного подсчёта материала.

Результат:

```text
11 passed
```

## Не входит в этап 2

- обновление JSON и переход на v6.4.6;
- исправление `StageClassifier`;
- новые этапы 7.5 для освещения, кабеленесущих систем, трансформаторов и ПНР;
- исправление `накладной светильник -> overhead`.

Это относится к этапу 3.
