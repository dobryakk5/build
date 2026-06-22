# Work-rate catalogue v1.2 delivery

Основные документы:

- `IMPLEMENTATION_REPORT.md` — что реализовано и результаты тестов;
- `INTEGRATION_GUIDE.md` — подключение к полному backend;
- `docs/TZ_katalog_rastsenok_i_trudoemkosti_v1_2.md` — исходное ТЗ;
- `VALIDATION.json` — машинный отчёт;
- `data/work_rate_catalog_v1_summary.json` — статистика seed-каталога.

Ключевые файлы реализации:

```text
services/work_rate_models.py
services/work_rate_import_service.py
services/work_rate_mapping_service.py
services/work_rate_selection_service.py
services/work_rate_catalog_service.py
services/work_rate_ktp_integration.py
services/work_taxonomy_service.py
services/upload_service.py
services/gantt_builder.py
routers/work_rates.py
migrations/057_work_rate_catalog.sql
scripts/build_taxonomy_v6411.py
scripts/build_work_rate_catalog_v1.py
```
