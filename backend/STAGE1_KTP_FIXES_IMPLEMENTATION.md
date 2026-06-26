# Исправление Stage 1 KTP по последней версии app.zip

## Реализовано

### 1. Snapshot-first для нового варианта 2.7

- Dynamic stage instances строятся из `EstimateBatch.taxonomy_snapshot`.
- Snapshot проверяется через `load_immutable_taxonomy_snapshot()` до использования.
- Для `residential_construction_kirpichnye_doma` отсутствие snapshot блокирует Stage 1 с `taxonomy_snapshot_required`.
- Runtime taxonomy `v6.4.14` оставлена только для совместимых legacy/non-snapshot batch.
- Diagnostics содержит фактический источник: `batch_snapshot_dynamic`, `batch_snapshot_static`, `persisted_legacy_stage_catalog` или `runtime_legacy_dictionary`.

### 2. Защита Stage 1 job от гонок

- Добавлено поле `KtpEstimateSession.stage1_generation`.
- `start_stage1_job()` блокирует session через `SELECT ... FOR UPDATE`.
- Существующий `pending/processing` job переиспользуется при `force=false`.
- `force=true` при активном job возвращает `409 stage1_job_already_running`.
- Worker захватывает job атомарным `UPDATE ... WHERE status='pending' RETURNING`.
- Перед progress и финальным commit проверяются `stage1_job_id` и `stage1_generation`.
- Stale/superseded worker не может сохранить WBS поверх нового запуска.

### 3. Review-state

- Вычисление review вынесено в чистую `compute_item_review_state()`.
- `GET session` и `GET /wbs` не выполняют lazy persisted writes.
- `_attach_stage_review_metadata()` добавляет только transient response-поля.
- `approve_stage1()` проверяет все items, синхронизирует все persisted review flags, выполняет commit и возвращает структурированный `409 stage1_review_required` со списком проблем.

### 4. Строгий lineage

- Неизвестный `row_key` больше не преобразуется в `origin=ai_added`.
- Ошибка сохраняется в `diagnostics.invalid_estimate_row_keys`.
- Для stage-aware режима неизвестный или повторный `row_key` является invariant violation.
- В LLM-режиме некорректный AI item не создаётся, а непокрытая исходная строка остаётся в fallback с review reason.

### 5. UTC-aware timestamps

- Добавлен `app.core.time.utc_now()`.
- Stage 1 timestamps переведены на aware UTC.
- `TimestampMixin.updated_at` использует aware callable.
- Исторические naive timestamps при stale-check временно интерпретируются как UTC.

### 6. Prompt и API errors

- Жёсткий `estimates[:80]` заменён на `settings.KTP_ESTIMATE_CHUNK_ROWS`.
- При truncation prompt явно сообщает число пропущенных строк.
- Известный контекст для вопросов обрабатывается чанками; конфликтующие ответы не принимаются автоматически.
- Добавлены typed KTP domain errors и стабильные HTTP-коды.
- Строковая эвристика `"не найден"` больше не определяет 404 для новых ошибок.

### 7. Legacy subtype compatibility

- Для legacy batch выполняется попытка разрешить старый subtype code через `WorkSubtype.code`, `legacy_code` и `legacy_csv_codes`.
- Для новых snapshot batch canonical `section_id/subtype_id` остаётся обязательной.

## Изменённые файлы

- `app/api/routes/ktp_estimate.py`
- `app/core/time.py`
- `app/migrations/073_ktp_stage1_generation.sql`
- `app/models/base.py`
- `app/models/ktp_estimate.py`
- `app/services/ktp_errors.py`
- `app/services/ktp_estimate_service.py`
- `tests/test_ktp_stage1_fixes.py`

## Проверки

```text
python -m compileall -q app
→ успешно

pytest tests/test_ktp_stage1_fixes.py
→ 13 passed
```

Дополнительно проверено:

- snapshot v6.5.0 создаёт 25 stage instances для 3 этажей, цоколя и мансарды;
- присутствуют `2.7.9` и `2.7.11` для floor 0;
- отсутствует `2.7.8` для floor 0;
- изменённый snapshot отклоняется;
- route импортируется, typed `Stage1ReviewRequired` преобразуется в HTTP 409.

## Ограничения проверки

В архиве отсутствовали:

- production Alembic environment;
- production PostgreSQL instance;
- запущенный Celery broker/worker;
- прежний полный набор backend tests.

Поэтому `073_ktp_stage1_generation.sql` является SQL-контрактом. В основном repository его нужно оформить как следующую Alembic revision после фактического head.

Атомарный claim и generation fencing реализованы в коде и покрыты focused-тестами/статическими проверками, но перед production rollout дополнительно обязательны интеграционные тесты на PostgreSQL и реальная duplicate delivery Celery.
