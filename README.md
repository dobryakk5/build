# Система управления строительством

## Быстрый старт

```bash
# 1. Клонировать / распаковать проект
cd construction-project

# 2. Настроить переменные окружения
cp backend/.env.example backend/.env
# Отредактировать backend/.env (SECRET_KEY обязателен)

# 3. Поднять все сервисы
docker-compose up -d

# 4. Применить миграции БД
docker-compose exec backend alembic upgrade head

# 5. Готово
# Frontend → http://localhost:3000
# Backend  → http://localhost:8000
# API docs → http://localhost:8000/docs
# Логи     → backend/logs/*.log и frontend/logs/*.log
```

Логи `backend` и `frontend` теперь пишутся в свои папки и ротируются понедельно.
Примеры файлов: `backend/logs/api-2026-W15.log`, `backend/logs/celery-worker-2026-W15.log`, `frontend/logs/frontend-2026-W15.log`.

## Структура проекта

```
construction-project/
├── docker-compose.yml
├── backend/
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   │       └── 001_initial.py        ← полная схема БД (17 таблиц)
│   ├── app/
│   │   ├── main.py                   ← FastAPI приложение
│   │   ├── core/
│   │   │   ├── config.py             ← настройки через pydantic-settings
│   │   │   ├── database.py           ← async SQLAlchemy engine
│   │   │   ├── permissions.py        ← матрица ролей (owner/pm/foreman/supplier/viewer)
│   │   │   └── date_utils.py         ← рабочие дни (единая функция для всего проекта)
│   │   ├── models/
│   │   │   ├── base.py               ← Base, TimestampMixin, SoftDeleteMixin
│   │   │   ├── organization.py
│   │   │   ├── user.py
│   │   │   ├── project.py            ← Project, ProjectMember
│   │   │   ├── estimate.py
│   │   │   ├── gantt.py              ← GanttTask, TaskDependency
│   │   │   └── other.py              ← Comment, TaskHistory, Job, DailyReport,
│   │   │                               DailyReportItem, Material, Escalation, Notification
│   │   ├── schemas.py                ← все Pydantic схемы
│   │   ├── api/
│   │   │   ├── deps.py               ← get_current_user, require_action, require_task_in_project
│   │   │   └── routes/
│   │   │       ├── auth.py           ← /auth/register, login, refresh, me
│   │   │       ├── projects.py       ← /projects CRUD + members
│   │   │       ├── gantt.py          ← /projects/{id}/gantt CRUD + reorder + deps
│   │   │       ├── estimates.py      ← /projects/{id}/estimates + async upload
│   │   │       ├── comments.py       ← /projects/{id}/tasks/{id}/comments
│   │   │       ├── reports.py        ← /projects/{id}/reports (ежедневные отчёты)
│   │   │       └── notifications.py  ← /notifications
│   │   ├── services/
│   │   │   ├── gantt_service.py      ← progress, resolve_dates, reorder, soft_delete
│   │   │   ├── upload_service.py     ← async upload + job polling
│   │   │   └── excel_parser.py       ← парсер Excel (3 стратегии: row/column/block)
│   │   └── tasks/
│   │       └── celery_tasks.py       ← Celery beat: напоминания, эскалации, дашборд
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── Dockerfile
│   └── .env.example
│
└── frontend/
    ├── app/                          ← Next.js 15 App Router
    ├── lib/
    │   └── index.ts                  ← api клиент + dateUtils + useJobPoller
    ├── next.config.ts                ← proxy /api/* → :8000
    ├── package.json
    └── Dockerfile
```

## Роли и права

| Роль      | Просмотр | Редактирование | Удаление | Комментарии | Управление |
|-----------|:--------:|:--------------:|:--------:|:-----------:|:----------:|
| owner     | ✓        | ✓              | ✓        | ✓           | ✓          |
| pm        | ✓        | ✓              | —        | ✓           | проекты    |
| foreman   | ✓        | прогресс*      | —        | ✓           | —          |
| supplier  | ✓        | —              | —        | ✓           | —          |
| viewer    | ✓        | —              | —        | —           | —          |

*прогресс только через ежедневный отчёт

## Важные архитектурные решения

- **`working_days`** — длительность задач в РАБОЧИХ днях (пн–пт, без праздников)
- **`task_dependencies`** — отдельная таблица M:M, не TEXT поле
- **`progress`** у группы — вычисляется из листовых потомков через SQL CTE, не хранится
- **`deleted_at`** — мягкое удаление, история `task_history` не теряется
- **Async upload** — POST возвращает 202 + job_id, polling через GET /jobs/{id}
- **Роль на уровне проекта** — один пользователь может быть pm на одном объекте и viewer на другом
