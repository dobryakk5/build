# Подключение каталога расценок v1.2

## 1. Файлы

Скопировать:

```text
services/work_rate_*.py                  → backend/app/services/
services/work_taxonomy_service.py        → backend/app/services/
services/upload_service.py               → backend/app/services/
services/gantt_builder.py                → backend/app/services/
routers/work_rates.py                    → backend/app/routers/
data/construction_work_dictionary_v6_4_11.json → backend/app/data/
data/work_rate_catalog_v1.json           → backend/app/data/
```

## 2. Миграция

Файл:

```text
migrations/057_work_rate_catalog.sql
```

Перенести в Alembic revision проекта либо выполнить через штатный механизм миграций.

Схема не предполагает конкретное имя KTP ORM и использует отдельную таблицу:

```text
work_rate_item_assignments
```

После уточнения реальной модели `ktp_item_id` можно заменить на настоящий FK.

## 3. Router

В точке создания FastAPI app:

```python
from pathlib import Path
from app.routers.work_rates import create_work_rate_router

app.include_router(
    create_work_rate_router(
        catalog_path=Path(__file__).resolve().parent / "data" / "work_rate_catalog_v1.json",
        taxonomy_path=Path(__file__).resolve().parent / "data" / "construction_work_dictionary_v6_4_11.json",
    )
)
```

JSON router можно использовать для preview. Для production рекомендуется реализовать repository с тем же сервисным API поверх SQLAlchemy.

## 4. Upload

`upload_service.py` автоматически использует:

```text
backend/app/data/work_rate_catalog_v1.json
```

Путь можно переопределить:

```bash
WORK_RATE_CATALOG_FILE=/absolute/path/work_rate_catalog_v1.json
```

Режим источника по умолчанию:

```text
hybrid
```

Переопределение:

```bash
WORK_RATE_LABOR_SOURCE_MODE=rate_catalog
```

Приоритет manual значений сохраняется в любом режиме.

## 5. Пересборка taxonomy

```bash
python scripts/build_taxonomy_v6411.py
```

Исходный v6.4.10 не изменяется.

## 6. Пересборка seed-каталога

```bash
python scripts/build_work_rate_catalog_v1.py /path/to/source/xlsx
```

В папке должны быть шесть файлов с исходными именами из ТЗ.

## 7. Проверка

```bash
pytest -q
```

Полный regression с PDF:

```bash
ILYINSKIE_PDF='/path/Ильинские сады 02.04.2026.pdf' pytest -q
```
