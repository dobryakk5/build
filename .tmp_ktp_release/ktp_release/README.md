# КТП — Инструкция по внедрению

## Что входит в пакет

```
backend/
  alembic/versions/036_ktp_groups_and_cards.py   # миграция БД
  app/
    api/routes/ktp.py          # новый роутер (5 эндпоинтов)
    core/config.py             # ЗАМЕНИТЬ целиком — добавлены KTP_GENERATION_MODEL, KTP_MAX_TOKENS
    main.py                    # ЗАМЕНИТЬ целиком — зарегистрирован ktp_router
    models/
      ktp.py                   # новые модели KtpGroup, KtpCard
      __init__.py              # ЗАМЕНИТЬ целиком — добавлены импорты KtpGroup, KtpCard
    services/ktp_service.py    # новый сервис
  tests/test_ktp_service.py    # 23 теста

frontend/
  app/projects/[id]/
    ktp/page.tsx               # новая страница КТП
    layout.tsx                 # ЗАМЕНИТЬ целиком — добавлена вкладка КТП
    upload.page.tsx            # ЗАМЕНИТЬ upload/page.tsx — добавлена кнопка «Создать КТП»
  lib/
    api.ts                     # ЗАМЕНИТЬ целиком — добавлен export const ktp
    types.ts                   # ЗАМЕНИТЬ целиком — добавлены KTP-типы
```

---

## Шаг 1 — Backend: новые файлы (просто скопировать)

Скопировать как есть, файлов в проекте ещё нет:

```bash
cp backend/alembic/versions/036_ktp_groups_and_cards.py  <project>/backend/alembic/versions/
cp backend/app/api/routes/ktp.py                          <project>/backend/app/api/routes/
cp backend/app/models/ktp.py                              <project>/backend/app/models/
cp backend/app/services/ktp_service.py                    <project>/backend/app/services/
cp backend/tests/test_ktp_service.py                      <project>/backend/tests/
```

## Шаг 2 — Backend: изменённые файлы (заменить целиком)

Эти файлы содержат только добавления к оригиналу — можно заменить целиком без риска:

```bash
cp backend/app/core/config.py    <project>/backend/app/core/config.py
cp backend/app/main.py           <project>/backend/app/main.py
cp backend/app/models/__init__.py <project>/backend/app/models/__init__.py
```

> Что добавлено в каждом:
> - `config.py` — две строки: `KTP_GENERATION_MODEL` и `KTP_MAX_TOKENS`
> - `main.py` — один импорт и одна строка `app.include_router(ktp_router)`
> - `models/__init__.py` — импорт `KtpGroup, KtpCard` и две строки в `__all__`

## Шаг 3 — Миграция БД

```bash
cd <project>/backend
alembic upgrade head
```

Создаёт таблицы `ktp_groups` и `ktp_cards` с индексами.

## Шаг 4 — Проверка backend (опционально)

```bash
cd <project>/backend
pytest tests/test_ktp_service.py -v --asyncio-mode=auto
# Должно быть: 23 passed
```

## Шаг 5 — Frontend: новый файл (просто скопировать)

```bash
mkdir -p <project>/frontend/app/projects/[id]/ktp
cp "frontend/app/projects/[id]/ktp/page.tsx"  "<project>/frontend/app/projects/[id]/ktp/page.tsx"
```

## Шаг 6 — Frontend: изменённые файлы (заменить целиком)

```bash
cp "frontend/app/projects/[id]/layout.tsx"      "<project>/frontend/app/projects/[id]/layout.tsx"
cp "frontend/app/projects/[id]/upload.page.tsx"  "<project>/frontend/app/projects/[id]/upload/page.tsx"
cp  frontend/lib/api.ts                          <project>/frontend/lib/api.ts
cp  frontend/lib/types.ts                        <project>/frontend/lib/types.ts
```

> Обратите внимание: `upload.page.tsx` → кладётся как `upload/page.tsx` (убрать точку).

> Что добавлено в каждом:
> - `layout.tsx` — вкладка `🗂 КТП` в массив `tabs`
> - `upload/page.tsx` — кнопка «Далее: создать КТП →» как основная после успешной загрузки
> - `api.ts` — `export const ktp = { groups, buildGroups, group, generate, card }`
> - `types.ts` — интерфейсы `KtpGroup`, `KtpQuestion`, `KtpStep`, `KtpCard`, `KtpGenerateResponse`

---

## Переменные окружения

Убедитесь, что в `.env` (или в конфиге) настроены:

```env
OPENROUTER_API_KEY=sk-or-...   # уже должен быть в проекте
KTP_GENERATION_MODEL=openai/gpt-4o-mini   # по умолчанию, можно переопределить
KTP_MAX_TOKENS=3000                        # по умолчанию
```

`KTP_GENERATION_MODEL` можно поменять на любую модель OpenRouter,
например `anthropic/claude-3-haiku` или `openai/gpt-4o`.

---

## Как это работает после внедрения

1. Загружаете смету → статус `done` → кнопка **«Далее: создать КТП →»**
2. Открывается `/projects/<id>/ktp?batch=<batch_id>`
3. Backend группирует строки сметы по `section → fer_group_title → fallback`
4. Слева — таблица групп со статусами, справа — панель
5. Нажимаете «Создать КТП» по группе → LLM генерирует
6. Если LLM просит уточнения — появляется форма с вопросами → отвечаете → КТП создаётся
7. Кнопка **«Далее →»** переходит к следующей группе без КТП
8. Все КТП хранятся в БД, доступны в любой момент через вкладку «КТП»

---

## Структура БД (справочно)

```
ktp_groups   — группы работ из сметы
  status: new | questions_required | generated | failed

ktp_cards    — КТП по группе
  steps_json        — шаги: [{no, stage, work_details, control_points}]
  recommendations_json — рекомендации: ["..."]
  questions_json    — вопросы LLM если данных не хватило
  answers_json      — ответы пользователя
  status: draft | questions_required | generated | failed
```
