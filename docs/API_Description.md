# Система управления строительными проектами — REST API

**Версия:** 1.0 · Март 2026  
**Базовый URL:** `/api`  
**Формат:** JSON, кодировка UTF-8

---

## Содержание

1. [Общие сведения](#1-общие-сведения)
2. [Роли и права доступа](#2-роли-и-права-доступа)
3. [Аутентификация](#3-аутентификация-auth)
4. [Проекты](#4-проекты-projects)
5. [Диаграмма Ганта](#5-диаграмма-ганта-projectsproject_idgantt)
6. [Смета](#6-смета-projectsproject_idestimates)
7. [Ежедневные отчёты](#7-ежедневные-отчёты-projectsproject_idreports)
8. [Комментарии](#8-комментарии-projectsproject_idtaskstask_idcomments)
9. [Материалы](#9-материалы-projectsproject_idmaterials)
10. [Уведомления](#10-уведомления-notifications)
11. [Дашборд](#11-дашборд-dashboard)
12. [Справочник ЕНИР](#12-справочник-енир-enir)
13. [Фоновые задачи](#13-фоновые-задачи-jobs)
14. [Примеры запросов](#14-примеры-запросов)

---

## 1. Общие сведения

### 1.1 Аутентификация

API использует JWT Bearer-токены. Каждый защищённый запрос должен содержать заголовок:

```
Authorization: Bearer <access_token>
```

| Токен | Срок действия |
|---|---|
| `access_token` | 30 минут |
| `refresh_token` | 7 дней |

По истечении access-токена используйте `POST /auth/refresh`. По истечении refresh-токена пользователь должен пройти повторную аутентификацию.

### 1.2 Стандартные коды ответов

| Код | Значение |
|---|---|
| `200 OK` | Запрос выполнен успешно. Тело содержит запрошенные данные. |
| `201 Created` | Ресурс создан. Тело содержит созданный объект или `{id}`. |
| `202 Accepted` | Запрос принят, обработка идёт асинхронно. Возвращается `job_id` для опроса. |
| `204 No Content` | Успешно, тело отсутствует (DELETE, logout). |
| `400 Bad Request` | Невалидные данные запроса. `detail` содержит описание ошибки. |
| `401 Unauthorized` | Токен отсутствует, истёк или недействителен. |
| `403 Forbidden` | Нет прав для выполнения действия (см. матрицу ролей). |
| `404 Not Found` | Ресурс не найден или удалён (soft delete). |
| `409 Conflict` | Конфликт: ресурс с такими данными уже существует. |
| `422 Unprocessable` | Ошибка валидации Pydantic. `errors` содержит список полей с ошибками. |
| `503 Service Unavailable` | Зависимость недоступна (база данных, файл ЕНИР). |

### 1.3 Пагинация

Эндпоинты, возвращающие списки, поддерживают query-параметры:

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `limit` | integer | 200 | Кол-во записей на странице. Максимум 500. |
| `offset` | integer | 0 | Смещение от начала. |

Ответ содержит поля `total` (всего записей) и `has_more` (есть ли ещё страницы).

### 1.4 Soft Delete

Большинство сущностей удаляются «мягко» — устанавливается поле `deleted_at`. Такие записи не возвращаются в списках и возвращают `404` при прямом обращении.

---

## 2. Роли и права доступа

Каждый участник проекта имеет одну роль. Роль определяет доступные действия.

| Действие | Описание | owner | pm | foreman | supplier | viewer |
|---|---|:---:|:---:|:---:|:---:|:---:|
| `VIEW` | Просматривать проект, задачи, смету | ✓ | ✓ | ✓ | ✓ | ✓ |
| `EDIT` | Редактировать задачи, смету, материалы | ✓ | ✓ | — | — | — |
| `DELETE` | Удалять проект | ✓ | — | — | — | — |
| `COMMENT` | Оставлять комментарии к задачам | ✓ | ✓ | ✓ | ✓ | — |
| `EDIT_PROGRESS` | Изменять прогресс задачи напрямую | ✓ | ✓ | — | — | — |
| `MANAGE_USERS` | Добавлять / удалять участников | ✓ | ✓ | — | — | — |
| `MANAGE_PROJECTS` | Изменять настройки проекта | ✓ | ✓ | — | — | — |
| `SUBMIT_REPORT` | Отправлять ежедневный отчёт | ✓ | — | ✓ | — | — |
| `VIEW_REPORTS` | Просматривать отчёты | ✓ | ✓ | — | — | — |

> **Примечание:** `foreman` может изменять прогресс задачи только через ежедневный отчёт (`POST /reports/{id}/submit`), но не напрямую через `PATCH` задачи.

---

## 3. Аутентификация (`/auth`)

| Метод | Путь | Авт. | Описание |
|---|---|:---:|---|
| `POST` | `/auth/register` | — | Регистрация. Автоматически создаёт организацию. |
| `POST` | `/auth/login` | — | Вход по email + пароль. Возвращает access и refresh токены. |
| `POST` | `/auth/refresh` | — | Обновление access-токена через refresh-токен. |
| `POST` | `/auth/logout` | — | Stateless logout. Клиент обязан удалить токены локально. |
| `GET` | `/auth/me` | JWT | Профиль текущего пользователя и список его проектов с ролями. |
| `PATCH` | `/auth/me` | JWT | Обновление имени и `avatar_url`. |
| `PATCH` | `/auth/me/password` | JWT | Смена пароля. Требует подтверждение старого пароля. |

### POST /auth/register — тело запроса

| Поле | Тип | Обяз. | Описание |
|---|---|:---:|---|
| `email` | string | да | Email пользователя. Должен быть уникальным. |
| `name` | string | да | Имя пользователя. Минимум 2 символа. |
| `password` | string | да | Пароль. Минимум 8 символов. |
| `org_name` | string | нет | Название организации. По умолчанию `«{name}'s workspace»`. |

### POST /auth/login — тело запроса

| Поле | Тип | Обяз. | Описание |
|---|---|:---:|---|
| `email` | string | да | Email пользователя. |
| `password` | string | да | Пароль. |

### Ответ /auth/login и /auth/register

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "user": {
    "id": "uuid",
    "name": "Иван Иванов",
    "email": "user@example.com",
    "avatar_url": null,
    "role": null
  }
}
```

---

## 4. Проекты (`/projects`)

| Метод | Путь | Авт. | Роли | Описание |
|---|---|:---:|---|---|
| `GET` | `/projects` | JWT | все | Список проектов пользователя с метриками: бюджет, задачи, участники. |
| `POST` | `/projects` | JWT | все | Создать проект. Создатель автоматически получает роль `owner`. |
| `GET` | `/projects/{project_id}` | JWT | все | Данные одного проекта. |
| `PATCH` | `/projects/{project_id}` | JWT | owner, pm | Обновить название, адрес, даты, статус, цвет. |
| `DELETE` | `/projects/{project_id}` | JWT | owner | Мягкое удаление проекта. |
| `GET` | `/projects/{project_id}/members` | JWT | все | Список участников с ролями и профилями. |
| `POST` | `/projects/{project_id}/members` | JWT | owner, pm | Добавить участника по `user_id` с указанием роли. |
| `PATCH` | `/projects/{project_id}/members/{user_id}` | JWT | owner, pm | Изменить роль участника. Нельзя убрать единственного `owner`. |
| `DELETE` | `/projects/{project_id}/members/{user_id}` | JWT | owner, pm | Удалить участника из проекта. |

### POST /projects — тело запроса

| Поле | Тип | Обяз. | Описание |
|---|---|:---:|---|
| `name` | string | да | Название проекта. |
| `address` | string | нет | Адрес объекта. |
| `start_date` | date | нет | Дата начала (`YYYY-MM-DD`). |
| `end_date` | date | нет | Плановая дата окончания. |
| `color` | string | нет | Цвет карточки (`#HEX`). |

### PATCH /projects/{project_id} — тело запроса

| Поле | Тип | Обяз. | Описание |
|---|---|:---:|---|
| `name` | string | нет | Новое название. |
| `address` | string | нет | Адрес объекта. |
| `start_date` | date | нет | Дата начала. |
| `end_date` | date | нет | Плановая дата окончания. |
| `color` | string | нет | Цвет карточки. |
| `status` | string | нет | Статус проекта. |

### POST /projects/{project_id}/members — тело запроса

| Поле | Тип | Обяз. | Описание |
|---|---|:---:|---|
| `user_id` | UUID | да | ID существующего пользователя. |
| `role` | string | да | Роль: `owner`, `pm`, `foreman`, `supplier`, `viewer`. |

---

## 5. Диаграмма Ганта (`/projects/{project_id}/gantt`)

| Метод | Путь | Авт. | Роли | Описание |
|---|---|:---:|---|---|
| `GET` | `/projects/{project_id}/gantt` | JWT | все | Список задач с пагинацией (`limit`, `offset`). Возвращает `tasks[]`, `total`, `has_more`. |
| `POST` | `/projects/{project_id}/gantt` | JWT | owner, pm | Создать задачу или группу. |
| `PATCH` | `/projects/{project_id}/gantt/{task_id}` | JWT | owner, pm | Обновить поля задачи. |
| `DELETE` | `/projects/{project_id}/gantt/{task_id}` | JWT | owner, pm | Мягкое удаление. Дочерние задачи также помечаются удалёнными. |
| `POST` | `/projects/{project_id}/gantt/reorder` | JWT | owner, pm | Переупорядочить задачи. Тело: `[{id, row_order}]`. |
| `POST` | `/projects/{project_id}/gantt/resolve` | JWT | owner, pm | Автоматически пересчитать даты с учётом зависимостей и рабочих дней. |
| `POST` | `/projects/{project_id}/gantt/{task_id}/dependencies` | JWT | owner, pm | Добавить зависимость Finish-to-Start. |
| `DELETE` | `/projects/{project_id}/gantt/{task_id}/dependencies/{dep_id}` | JWT | owner, pm | Удалить зависимость. |

### POST/PATCH — тело запроса задачи

| Поле | Тип | Обяз. | Описание |
|---|---|:---:|---|
| `name` | string | да | Название задачи. |
| `start_date` | date | да | Дата начала (`YYYY-MM-DD`). |
| `working_days` | integer | да | Длительность в рабочих днях (≥ 1). |
| `parent_id` | UUID | нет | ID родительской задачи для вложенности. |
| `is_group` | boolean | нет | `true` — группа (папка) задач. |
| `type` | string | нет | `task` / `milestone` / `phase`. |
| `color` | string | нет | Цвет задачи (`#HEX`). |
| `assignee_id` | UUID | нет | ID исполнителя (участник проекта). |
| `requires_act` | boolean | нет | Требуется подписание акта скрытых работ. |
| `act_signed` | boolean | нет | Акт подписан. |

### Объект задачи (TaskResponse)

| Поле | Тип | Описание |
|---|---|---|
| `id` | UUID | Уникальный идентификатор задачи. |
| `project_id` | UUID | ID проекта. |
| `parent_id` | UUID | ID родительской задачи (если есть). |
| `name` | string | Название задачи. |
| `start_date` | date | Дата начала. |
| `working_days` | integer | Длительность в рабочих днях. |
| `end_date` | date | Вычисляемая дата окончания (без учёта выходных). |
| `progress` | integer | Прогресс 0–100%. Для групп вычисляется по дочерним. |
| `is_group` | boolean | Является ли задача группой. |
| `type` | string | `task` / `milestone` / `phase`. |
| `depends_on` | string | ID зависимых задач через запятую. |
| `assignee` | object | Исполнитель: `{id, name, avatar_url}`. |
| `comments_count` | integer | Количество комментариев. |
| `requires_act` | boolean | Требуется акт скрытых работ. |
| `act_signed` | boolean | Акт подписан. |

### POST .../dependencies — тело запроса

| Поле | Тип | Обяз. | Описание |
|---|---|:---:|---|
| `depends_on` | UUID | да | ID задачи-предшественника (тип связи: Finish-to-Start). |

---

## 6. Смета (`/projects/{project_id}/estimates`)

| Метод | Путь | Авт. | Роли | Описание |
|---|---|:---:|---|---|
| `POST` | `/projects/{project_id}/estimates/upload` | JWT | owner, pm | Загрузить Excel-смету. Асинхронно: возвращает `202` + `job_id`. |
| `POST` | `/projects/{project_id}/estimates/upload/confirm-mapping` | JWT | owner, pm | Подтвердить ручной маппинг колонок (если авто-парсинг вернул `422`). |
| `GET` | `/projects/{project_id}/estimates` | JWT | все | Список строк сметы. Фильтр: `?section=...` |
| `GET` | `/projects/{project_id}/estimates/summary` | JWT | все | Итоги: общая сумма и разбивка по разделам. |

### POST /estimates/upload — параметры (multipart/form-data)

| Параметр | Тип | Обяз. | Описание |
|---|---|:---:|---|
| `file` | file | да | Excel-файл (`.xlsx`, `.xls`) со сметой. |
| `start_date` | date | нет | Дата начала строительства для Ганта. По умолчанию сегодня. |
| `workers` | integer | нет | Количество рабочих для расчёта сроков. По умолчанию 3. Диапазон 1–20. |

### POST /estimates/upload/confirm-mapping — тело запроса

| Поле | Тип | Обяз. | Описание |
|---|---|:---:|---|
| `tmp_path` | string | да | Путь к временному файлу (из ответа 422). |
| `sheet` | string | да | Имя листа Excel. |
| `col_mapping` | object | да | Маппинг колонок: `{col_index: "work_name"\|"unit"\|"quantity"\|"unit_price"\|"total_price"\|"section"\|"skip"}`. |
| `start_date` | date | да | Дата начала строительства. |
| `workers` | integer | нет | Количество рабочих. По умолчанию 3. |

### Ответ GET /estimates

```json
[
  {
    "id": "uuid",
    "section": "Фундаменты",
    "work_name": "Устройство монолитного фундамента",
    "unit": "м3",
    "quantity": 120.5,
    "unit_price": 4500.00,
    "total_price": 542250.00,
    "row_order": 1
  }
]
```

### Ответ GET /estimates/summary

```json
{
  "total": 12500000.00,
  "sections": [
    { "name": "Фундаменты", "subtotal": 2500000.00, "items": 15 },
    { "name": "Стены", "subtotal": 4800000.00, "items": 32 }
  ]
}
```

> **Важно:** после успешного завершения загрузки сметы (`job.status = "done"`) автоматически строится диаграмма Ганта на основе загруженных данных.

---

## 7. Ежедневные отчёты (`/projects/{project_id}/reports`)

| Метод | Путь | Авт. | Роли | Описание |
|---|---|:---:|---|---|
| `GET` | `/projects/{project_id}/reports` | JWT | owner, pm | Список отчётов. Фильтры: `?from_date=`, `?to_date=`. |
| `GET` | `/projects/{project_id}/reports/today` | JWT | owner, pm | Статус отчётов за сегодня по каждому прорабу. |
| `GET` | `/projects/{project_id}/reports/{id}` | JWT | owner, pm | Детальный отчёт с позициями. |
| `POST` | `/projects/{project_id}/reports` | JWT | foreman | Создать/сохранить черновик отчёта. |
| `POST` | `/projects/{project_id}/reports/{id}/submit` | JWT | foreman | Отправить отчёт. Обновляет прогресс задач в Ганте. |
| `POST` | `/projects/{project_id}/reports/{id}/review` | JWT | owner, pm | Принять отчёт. |

### POST /reports — тело запроса

| Поле | Тип | Обяз. | Описание |
|---|---|:---:|---|
| `report_date` | date | да | Дата отчёта (`YYYY-MM-DD`). |
| `summary` | string | нет | Общий текст по итогам дня. |
| `issues` | string | нет | Выявленные проблемы. |
| `weather` | string | нет | Погодные условия. |
| `items` | array | нет | Позиции отчёта (см. ниже). |

### Позиция отчёта (ReportItem)

| Поле | Тип | Обяз. | Описание |
|---|---|:---:|---|
| `task_id` | UUID | да | ID задачи из Ганта. |
| `work_done` | string | да | Описание выполненной работы. |
| `volume_done` | number | нет | Объём выполненного. |
| `volume_unit` | string | нет | Единица объёма. |
| `progress_after` | integer | да | Прогресс задачи после этого дня (0–100%). |
| `workers_count` | integer | нет | Количество рабочих на этой задаче. |
| `workers_note` | string | нет | Примечание по рабочим. |
| `materials_used` | array | нет | Использованные материалы: `[{name, quantity, unit}]`. |

### Ответ GET /reports/today

```json
[
  {
    "foreman": { "id": "uuid", "name": "Петров А.В." },
    "submitted": true,
    "status": "submitted",
    "report_id": "uuid"
  },
  {
    "foreman": { "id": "uuid", "name": "Сидоров К.И." },
    "submitted": false,
    "status": "missing",
    "report_id": null
  }
]
```

---

## 8. Комментарии (`/projects/{project_id}/tasks/{task_id}/comments`)

| Метод | Путь | Авт. | Роли | Описание |
|---|---|:---:|---|---|
| `GET` | `.../comments` | JWT | все | Список комментариев к задаче, по дате. |
| `POST` | `.../comments` | JWT | owner, pm, foreman, supplier | Добавить комментарий. Роль фиксируется на момент написания. |
| `PATCH` | `.../comments/{comment_id}` | JWT | автор / owner | Редактировать комментарий. |
| `DELETE` | `.../comments/{comment_id}` | JWT | автор / owner | Мягкое удаление комментария. |

### POST /comments — тело запроса

| Поле | Тип | Обяз. | Описание |
|---|---|:---:|---|
| `text` | string | да | Текст комментария. |
| `attachments` | array | нет | Вложения: `[{name, url, size, mime}]`. |

### Объект комментария (CommentResponse)

| Поле | Тип | Описание |
|---|---|---|
| `id` | UUID | ID комментария. |
| `task_id` | UUID | ID задачи. |
| `author` | object | Автор: `{id, name, avatar_url}`. |
| `author_role` | string | Роль автора на момент написания. |
| `text` | string | Текст комментария. |
| `attachments` | array | Вложения: `[{name, url, size, mime}]`. |
| `edited_at` | datetime | Время последнего редактирования (если было). |
| `created_at` | datetime | Время создания. |

---

## 9. Материалы (`/projects/{project_id}/materials`)

| Метод | Путь | Авт. | Роли | Описание |
|---|---|:---:|---|---|
| `GET` | `/projects/{project_id}/materials` | JWT | все | Список материалов. Фильтры: `?type=small\|major`, `?status=planned\|ordered\|delivered`. |
| `POST` | `/projects/{project_id}/materials` | JWT | owner, pm | Добавить материал. |
| `PATCH` | `/projects/{project_id}/materials/{id}` | JWT | owner, pm | Обновить материал. |
| `DELETE` | `/projects/{project_id}/materials/{id}` | JWT | owner, pm | Мягкое удаление. |

### Поля материала

| Поле | Тип | Обяз. | Описание |
|---|---|:---:|---|
| `name` | string | да | Наименование. |
| `unit` | string | нет | Единица измерения. |
| `quantity` | number | нет | Количество. |
| `type` | string | нет | `small` — мелочёвка прораба, `major` — снабженец. По умолчанию `small`. |
| `task_id` | UUID | нет | Привязка к задаче Ганта. |
| `order_date` | date | нет | Дата заказа. |
| `lead_days` | integer | нет | Срок поставки в днях. |
| `delivery_date` | date | нет | Плановая дата поставки. |
| `status` | string | нет | `planned` → `ordered` → `delivered`. |
| `supplier_note` | string | нет | Примечание поставщика. |

---

## 10. Уведомления (`/notifications`)

| Метод | Путь | Авт. | Описание |
|---|---|:---:|---|
| `GET` | `/notifications` | JWT | Уведомления текущего пользователя. Параметры: `?unread_only=true`, `?limit=N` (макс. 100). |
| `POST` | `/notifications/{id}/read` | JWT | Пометить уведомление как прочитанное. |
| `POST` | `/notifications/read-all` | JWT | Пометить все уведомления как прочитанные. |

### Типы уведомлений

| Тип | Описание |
|---|---|
| `report_reminder` | Напоминание о необходимости подать отчёт (07:00). |
| `missing_report` | Прораб не подал отчёт. |
| `escalation` | Задача эскалирована (48ч без решения). |
| `task_overdue` | Задача просрочена. |
| `material_due` | Приближается дата поставки материала. |
| `hidden_work_due` | Скрытые работы требуют подписания акта. |
| `task_assigned` | Пользователь назначен исполнителем задачи. |
| `comment_added` | Добавлен комментарий к задаче. |

### Объект уведомления

```json
{
  "id": "uuid",
  "type": "task_overdue",
  "title": "Задача просрочена",
  "body": "«Монтаж перекрытий» должна была завершиться 10.03.2026",
  "entity_type": "task",
  "entity_id": "uuid",
  "is_read": false,
  "created_at": "2026-03-18T07:00:00Z"
}
```

---

## 11. Дашборд (`/dashboard`)

| Метод | Путь | Авт. | Описание |
|---|---|:---:|---|
| `GET` | `/dashboard` | JWT | Все проекты пользователя с ключевыми метриками и итоговой сводкой. |

### Ответ GET /dashboard

```json
{
  "projects": [
    {
      "id": "uuid",
      "name": "ЖК Северный",
      "address": "ул. Строителей, 1",
      "status": "active",
      "dashboard_status": "yellow",
      "color": "#3B82F6",
      "start_date": "2025-04-01",
      "end_date": "2026-12-01",
      "my_role": "owner",
      "progress": 42,
      "tasks_total": 120,
      "tasks_done": 50,
      "budget": 45000000.00,
      "open_escalations": 2
    }
  ],
  "summary": {
    "total": 5,
    "green": 3,
    "yellow": 1,
    "red": 1,
    "total_budget": 215000000.00
  }
}
```

### dashboard_status

| Значение | Описание |
|---|---|
| `green` | Всё в норме. |
| `yellow` | Есть отставания или непрочитанные эскалации. |
| `red` | Критические проблемы: просроченные задачи, нет отчётов 2+ дня. |

> `dashboard_status` обновляется автоматически Celery-задачей в 07:00 каждый день.

---

## 12. Справочник ЕНИР (`/enir`)

Единые нормы и расценки. Данные хранятся в PostgreSQL.

> Эндпоинты ЕНИР **не требуют авторизации** — справочник является общедоступным.

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/enir` | Список всех сборников с количеством параграфов. |
| `GET` | `/enir/{collection_id}/paragraphs` | Параграфы сборника (краткий формат). `?q=` — текстовый фильтр по коду или названию. |
| `GET` | `/enir/paragraph/{paragraph_id}` | Полный параграф: состав работ, звено, нормы, примечания. |
| `GET` | `/enir/search?q={query}` | Поиск по всем сборникам. `?collection_id=N` — ограничить одним сборником. До 100 результатов. |

### Иерархия данных ЕНИР

```
EnirCollection          — сборник (Е1, Е2, Е3 …)
  └─ EnirParagraph      — параграф (Е3-1, Е3-2 …)
       ├─ EnirWorkComposition  — блок условий состава работ
       │    └─ EnirWorkOperation — одна операция
       ├─ EnirCrewMember       — профессия / разряд / кол-во в звене
       ├─ EnirNorm             — строка таблицы норм (Н.вр. + Расц.)
       └─ EnirNote             — примечание с коэффициентом поправки
```

### Ответ GET /enir

```json
[
  {
    "id": 1,
    "code": "Е3",
    "title": "Каменные работы",
    "description": null,
    "sort_order": 3,
    "paragraph_count": 30
  }
]
```

### Ответ GET /enir/{collection_id}/paragraphs

```json
[
  {
    "id": 1,
    "collection_id": 1,
    "source_paragraph_id": "Е3-1",
    "code": "Е3-1",
    "title": "Устройство фундаментов, стен и столбов из бутового камня...",
    "unit": "м3 кладки",
    "html_anchor": "i42863"
  }
]
```

### Ответ GET /enir/paragraph/{id}

```json
{
  "id": 1,
  "collection_id": 1,
  "source_paragraph_id": "Е3-1",
  "code": "Е3-1",
  "title": "Устройство фундаментов, стен и столбов из бутового камня...",
  "unit": "м3 кладки",
  "html_anchor": "i42863",
  "work_compositions": [
    {
      "condition": "При кладке фундаментов под лопатку",
      "operations": [
        "1. Опускание материалов в траншею.",
        "2. Натягивание причалки.",
        "3. Кладка верстовых рядов..."
      ]
    }
  ],
  "crew": [
    { "profession": "Каменщик", "grade": 5, "count": 1 }
  ],
  "norms": [
    {
      "row_num": 1,
      "work_type": "Из бутового камня под лопатку",
      "condition": "Ленточные фундаменты",
      "thickness_mm": 600,
      "column_label": "а",
      "norm_time": 2.92,
      "price_rub": 0.16
    }
  ],
  "notes": [
    {
      "num": 1,
      "text": "При глубине более 1,2 м Н.вр. и Расц. умножать на 1,15 (ПР-1)",
      "coefficient": 1.15,
      "pr_code": "ПР-1"
    }
  ],
  "refs": [
    {
      "sort_order": 0,
      "ref_type": "external",
      "link_text": "ГОСТ 530-80",
      "href": "../../1/4294823/4294823558.htm",
      "abs_url": "https://meganorm.ru/Data2/1/4294823/4294823558.htm",
      "context_text": "Наименование и размеры строительных материалов...",
      "is_meganorm": true
    }
  ]
}
```

### Загрузка данных ЕНИР

Для импорта JSON-файла сборника в PostgreSQL:

```bash
# Сначала применить миграцию
alembic upgrade head

# Загрузить сборник
python backend/import_enir.py enir_e3.json \
  --collection-code "Е3" \
  --collection-title "Каменные работы" \
  --cross-ref-json cross_references_annotated.json \
  --sort-order 3

# Перезаписать существующий сборник
python backend/import_enir.py enir_e3.json \
  --collection-code "Е3" \
  --collection-title "Каменные работы" \
  --cross-ref-json cross_references_annotated.json \
  --overwrite
```

---

## 13. Фоновые задачи (`/jobs`)

| Метод | Путь | Авт. | Описание |
|---|---|:---:|---|
| `GET` | `/jobs/{job_id}` | JWT | Статус и результат фоновой задачи. Опрашивать каждые 1–2 секунды. |

### Статусы задачи

| Статус | Описание |
|---|---|
| `pending` | Задача в очереди, ещё не началась. |
| `processing` | Задача выполняется прямо сейчас. |
| `done` | Успешно завершена. `result` содержит итоги. |
| `failed` | Завершена с ошибкой. `result.error` содержит описание. |

### Ответ GET /jobs/{job_id}

```json
{
  "id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "type": "estimate_upload",
  "status": "done",
  "result": {
    "estimate_rows": 150,
    "tasks_created": 42
  },
  "created_at": "2026-03-18T10:00:00Z",
  "started_at": "2026-03-18T10:00:01Z",
  "finished_at": "2026-03-18T10:00:08Z"
}
```

> Текущие типы задач: `estimate_upload` — парсинг Excel-сметы и построение Ганта.

---

## 14. Примеры запросов

### 14.1 Регистрация

```http
POST /api/auth/register
Content-Type: application/json

{
  "email": "ivanov@sk-gorizont.ru",
  "name": "Иван Иванов",
  "password": "secret123",
  "org_name": "СК Горизонт"
}
```

```json
// 201 Created
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": { "id": "uuid", "name": "Иван Иванов", "email": "ivanov@sk-gorizont.ru" }
}
```

### 14.2 Загрузка сметы (асинхронно)

**Шаг 1 — отправить файл:**

```http
POST /api/projects/{id}/estimates/upload?start_date=2026-04-01&workers=5
Authorization: Bearer <token>
Content-Type: multipart/form-data

file=@smeta_zhk_severny.xlsx
```

```json
// 202 Accepted
{ "job_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" }
```

**Шаг 2 — опрашивать статус (каждые 1–2 сек):**

```http
GET /api/jobs/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
Authorization: Bearer <token>
```

```json
// processing...
{ "id": "...", "status": "processing" }

// готово:
{ "id": "...", "status": "done", "result": { "estimate_rows": 150, "tasks_created": 42 } }
```

### 14.3 Создание задачи в Ганте

```http
POST /api/projects/{project_id}/gantt
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Монтаж монолитных перекрытий",
  "start_date": "2026-05-01",
  "working_days": 14,
  "parent_id": "uuid-группы-конструктив"
}
```

```json
// 201 Created
{
  "id": "uuid",
  "name": "Монтаж монолитных перекрытий",
  "start_date": "2026-05-01",
  "working_days": 14,
  "end_date": "2026-05-20",
  "progress": 0,
  "is_group": false
}
```

### 14.4 Поиск по ЕНИР

```http
GET /api/enir/search?q=кладка
```

```json
[
  { "id": 1, "collection_id": 1, "code": "Е3-1", "title": "Устройство фундаментов...", "unit": "м3 кладки" },
  { "id": 3, "collection_id": 1, "code": "Е3-3", "title": "Кладка стен из кирпича", "unit": "м3 кладки" }
]
```

```http
GET /api/enir/paragraph/3
```

```json
{
  "id": 3,
  "code": "Е3-3",
  "title": "Кладка стен из кирпича",
  "unit": "м3 кладки",
  "norms": [
    { "row_num": 1, "condition": "Толщина в 1/2 кирпича", "norm_time": 1.5, "price_rub": 0.89 }
  ]
}
```

### 14.5 Ежедневный отчёт прораба

```http
POST /api/projects/{project_id}/reports
Authorization: Bearer <token>
Content-Type: application/json

{
  "report_date": "2026-03-18",
  "summary": "Продолжили армирование 3-го этажа",
  "weather": "Солнечно, +8°C",
  "items": [
    {
      "task_id": "uuid-задачи",
      "work_done": "Армирование плиты перекрытия секции А",
      "volume_done": 45.5,
      "volume_unit": "м2",
      "progress_after": 65,
      "workers_count": 8
    }
  ]
}
```

```http
POST /api/projects/{project_id}/reports/{id}/submit
Authorization: Bearer <token>
```

```json
// 200 OK — прогресс задач в Ганте обновлён
{ "id": "uuid", "status": "submitted" }
```
