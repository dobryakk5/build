# ЕНиР Е3 — пайплайн обработки

## Схема

```
.doc → [распаковать] → document.xml
                           ↓
                    parse_enir_v3.py  →  enir_e3.json
                                              ↓
                    validate_enir.py  →  авто-проверка
                                         + Qwen кропы  →  enir_e3_validated.json
                                              ↓
                    load_enir.py      →  enir_e3.db (SQLite / PostgreSQL)
```

---

## Шаг 0 — подготовка (один раз)

```bash
# Распаковать .doc → .docx → XML
libreoffice --headless --convert-to docx 22_ЕНиР_Сборник_Е_3.doc
mkdir -p unpacked_e3 && unzip -q 22_ЕНиР_Сборник_Е_3.docx -d unpacked_e3

# Для Qwen нужен PDF
libreoffice --headless --convert-to pdf 22_ЕНиР_Сборник_Е_3.doc
```

---

## Шаг 1 — парсинг

```bash
python3 parse_enir_v3.py \
  --docx unpacked_e3/word/document.xml \
  --out  enir_e3.json
```

Выход: `enir_e3.json` — 30 параграфов, 328 норм.

---

## Шаг 2 — валидация

```bash
# Без Qwen (только авто-проверка):
python3 validate_enir.py \
  --json enir_e3.json \
  --docx unpacked_e3/word/document.xml

# С Qwen (точечные кропы для флагнутых параграфов):
python3 validate_enir.py \
  --json    enir_e3.json \
  --docx    unpacked_e3/word/document.xml \
  --pdf     22_ЕНиР_Сборник_Е_3.pdf \
  --api-key $OPENROUTER_API_KEY \
  --out     enir_e3_validated.json

# Один параграф + сохранить кропы для отладки:
python3 validate_enir.py \
  --para    Е3-4 \
  --pdf     22_ЕНиР_Сборник_Е_3.pdf \
  --api-key $OPENROUTER_API_KEY \
  --save-crops
```

### Флаги валидатора

| Флаг | Тип | Описание | Действие |
|---|---|---|---|
| `NO_NORMS` | структурный | в XML есть таблица с №, в JSON норм нет | → Qwen |
| `MISSING_ROWS` | структурный | в JSON отсутствуют некоторые строки таблицы | → Qwen |
| `CREW_SHORT` | структурный | в XML больше профессий, чем в JSON | → Qwen |
| `NO_WORK_COMP` | структурный | есть «Состав работ», в JSON пусто | → Qwen |
| `NO_UNIT` | структурный | нет единицы измерения без явной причины | → Qwen |
| `NUMERIC_ANOMALY` | числовой | `price < 0.001`, `norm > 35`, `price/norm < 0.01` | → Qwen |
| `EMPTY_WORK_TYPE` | информационный | горизонтальный формат таблицы, work_type в заголовке | ок |
| `NO_ROW_NUM` | информационный | таблица без колонки №, горизонтальный формат | ок |

В Qwen отправляются только `NUMERIC_ANOMALY` и структурные флаги первой группы.
Для каждого типа флага — **отдельный запрос** с точечным кропом нужной части страницы.

### Текущее состояние (Е3)

- **18/30** параграфов чистые
- **4** с `NUMERIC_ANOMALY` (Е3-4, Е3-5, Е3-6, Е3-20) — реальные данные с ценой 1–3 коп/м³, Qwen подтверждает
- **8** с `EMPTY_WORK_TYPE` / `NO_ROW_NUM` — горизонтальные таблицы, данные верны

---

## Шаг 3 — загрузка в БД

```bash
# SQLite (локально):
python3 load_enir.py \
  --json enir_e3.json \
  --db   sqlite:///enir_e3.db

# PostgreSQL:
python3 load_enir.py \
  --json enir_e3.json \
  --db   postgresql://user:pass@host/dbname

# Пересоздать таблицы (при повторном запуске):
python3 load_enir.py --drop \
  --json enir_e3.json \
  --db   sqlite:///enir_e3.db

# Один параграф (дообновить):
python3 load_enir.py --para Е3-4 \
  --json enir_e3.json \
  --db   sqlite:///enir_e3.db
```

### Схема БД

| Таблица | Строк | Описание |
|---|---|---|
| `paragraphs` | 30 | параграфы — code, title, unit |
| `norms` | 328 | нормы — row_num, work_type, condition, column_label, thickness_mm, norm_time, price_rub |
| `crew_members` | 40 | состав звена — profession, grade, count |
| `work_compositions` | 40 | секции состава работ |
| `work_operations` | 217 | операции внутри секций |
| `notes` | 44 | примечания — text, coefficient, ref_code |

---

## Итерационный цикл при правке парсера

```bash
python3 parse_enir_v3.py --out enir_e3.json   # пересобрать JSON
python3 validate_enir.py ...                   # проверить
python3 load_enir.py --drop ...                # перезагрузить в БД
```

Все три скрипта независимы и связаны только через `enir_e3.json`.
Если JSON устраивает — `load_enir` запускается без повторного парсинга.
