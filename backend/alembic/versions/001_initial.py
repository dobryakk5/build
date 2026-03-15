"""
001_initial.py
Начальная схема БД — система управления строительными проектами.
Создаётся с нуля, все решения уже приняты правильно.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMPTZ

# ─────────────────────────────────────────────────────────────────────────────
# ПОРЯДОК СОЗДАНИЯ (важен из-за FK):
#
#  1. organizations
#  2. users
#  3. projects
#  4. project_members
#  5. holidays
#  6. estimates
#  7. gantt_tasks          ← self-reference: parent_id nullable
#  8. task_dependencies    ← FK на gantt_tasks с обеих сторон
#  9. jobs
# 10. daily_reports
# 11. daily_report_items
# 12. comments
# 13. task_history
# 14. materials
# 15. escalations
# 16. notifications
# 17. refresh_tokens
# ─────────────────────────────────────────────────────────────────────────────

revision = '001'
down_revision = None


def upgrade():

    # ─── 1. ОРГАНИЗАЦИИ ──────────────────────────────────────────────────────
    # Верхний уровень иерархии. Одна компания — один аккаунт.
    op.create_table('organizations',
        sa.Column('id',         UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name',       sa.String(255), nullable=False),
        sa.Column('slug',       sa.String(100), nullable=False, unique=True),
        # Тарифный план: free | pro | enterprise
        sa.Column('plan',       sa.String(20),  nullable=False, server_default='free'),
        sa.Column('logo_url',   sa.Text),
        sa.Column('created_at', TIMESTAMPTZ, server_default=sa.text('NOW()')),
    )

    # ─── 2. ПОЛЬЗОВАТЕЛИ ─────────────────────────────────────────────────────
    op.create_table('users',
        sa.Column('id',              UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', UUID, sa.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True),
        sa.Column('email',           sa.String(255), nullable=False, unique=True),
        sa.Column('name',            sa.String(255), nullable=False),
        sa.Column('password_hash',   sa.String(255), nullable=False),
        sa.Column('avatar_url',      sa.Text),
        sa.Column('is_active',       sa.Boolean, server_default='true'),
        sa.Column('created_at',      TIMESTAMPTZ, server_default=sa.text('NOW()')),
        sa.Column('updated_at',      TIMESTAMPTZ, server_default=sa.text('NOW()')),
    )
    op.create_index('idx_users_org',   'users', ['organization_id'])
    op.create_index('idx_users_email', 'users', ['email'])

    # ─── 3. ПРОЕКТЫ ───────────────────────────────────────────────────────────
    op.create_table('projects',
        sa.Column('id',              UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', UUID, sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by',      UUID, sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name',            sa.String(255), nullable=False),
        sa.Column('address',         sa.Text),
        # active | paused | done | archived
        sa.Column('status',          sa.String(20), nullable=False, server_default='active'),
        sa.Column('color',           sa.String(20)),
        sa.Column('start_date',      sa.Date),
        sa.Column('end_date',        sa.Date),
        # Вычисляемый статус для дашборда: green | yellow | red
        # Обновляется Celery-джобом каждое утро
        sa.Column('dashboard_status',sa.String(10), server_default='green'),
        sa.Column('created_at',      TIMESTAMPTZ, server_default=sa.text('NOW()')),
        sa.Column('updated_at',      TIMESTAMPTZ, server_default=sa.text('NOW()')),
        sa.Column('deleted_at',      TIMESTAMPTZ, nullable=True),
        sa.CheckConstraint("status IN ('active','paused','done','archived')", name='ck_project_status'),
        sa.CheckConstraint("dashboard_status IN ('green','yellow','red')",    name='ck_dashboard_status'),
    )
    op.create_index('idx_projects_org',    'projects', ['organization_id'])
    op.create_index('idx_projects_active', 'projects', ['organization_id'],
                    postgresql_where=sa.text("deleted_at IS NULL"))

    # ─── 4. УЧАСТНИКИ ПРОЕКТА (РОЛИ) ─────────────────────────────────────────
    # Роль привязана к конкретному проекту, не глобально.
    # Один пользователь — одна роль на проект.
    # Roles: owner | pm | foreman | supplier | viewer
    op.create_table('project_members',
        sa.Column('id',         UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('project_id', UUID, sa.ForeignKey('projects.id',  ondelete='CASCADE'), nullable=False),
        sa.Column('user_id',    UUID, sa.ForeignKey('users.id',     ondelete='CASCADE'), nullable=False),
        sa.Column('invited_by', UUID, sa.ForeignKey('users.id',     ondelete='SET NULL'), nullable=True),
        sa.Column('role',       sa.String(20), nullable=False),
        sa.Column('created_at', TIMESTAMPTZ, server_default=sa.text('NOW()')),
        sa.UniqueConstraint('project_id', 'user_id', name='uq_member_project_user'),
        sa.CheckConstraint(
            "role IN ('owner','pm','foreman','supplier','viewer')",
            name='ck_member_role'
        ),
    )
    op.create_index('idx_members_project', 'project_members', ['project_id'])
    op.create_index('idx_members_user',    'project_members', ['user_id'])

    # ─── 5. ПРАЗДНИКИ ────────────────────────────────────────────────────────
    # Для корректного расчёта рабочих дней.
    op.create_table('holidays',
        sa.Column('date',    sa.Date,       primary_key=True),
        sa.Column('name',    sa.String(255), nullable=False),
        sa.Column('country', sa.String(2),  nullable=False, server_default='RU'),
    )

    # ─── 6. СМЕТА ────────────────────────────────────────────────────────────
    op.create_table('estimates',
        sa.Column('id',          UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('project_id',  UUID, sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('section',     sa.String(255)),  # раздел: «Кровля», «Фундамент»
        sa.Column('work_name',   sa.Text,    nullable=False),
        sa.Column('unit',        sa.String(50)),  # ед. изм: м², м³, шт
        sa.Column('quantity',    sa.Numeric(12, 3)),
        sa.Column('unit_price',  sa.Numeric(12, 2)),
        sa.Column('total_price', sa.Numeric(14, 2)),
        sa.Column('enir_code',   sa.String(50)),  # код ЕНиР / ГЭСН
        sa.Column('labor_hours', sa.Numeric(10, 2)),  # трудоёмкость чел/час
        sa.Column('row_order',   sa.Integer, server_default='0'),
        sa.Column('raw_data',    JSONB),  # исходная строка Excel
        sa.Column('created_at',  TIMESTAMPTZ, server_default=sa.text('NOW()')),
        sa.Column('deleted_at',  TIMESTAMPTZ, nullable=True),
    )
    op.create_index('idx_estimates_project', 'estimates', ['project_id'],
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index('idx_estimates_section', 'estimates', ['project_id', 'section'])

    # ─── 7. ЗАДАЧИ ГАНТА ─────────────────────────────────────────────────────
    op.create_table('gantt_tasks',
        sa.Column('id',           UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('project_id',   UUID, sa.ForeignKey('projects.id',  ondelete='CASCADE'), nullable=False),
        sa.Column('estimate_id',  UUID, sa.ForeignKey('estimates.id', ondelete='SET NULL'), nullable=True),
        # Иерархия: задача может быть дочерней к другой задаче
        sa.Column('parent_id',    UUID, sa.ForeignKey('gantt_tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('assignee_id',  UUID, sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),

        sa.Column('name',         sa.Text,    nullable=False),
        # Дата начала. Пересчитывается при изменении зависимостей.
        sa.Column('start_date',   sa.Date,    nullable=False),
        # Длительность в РАБОЧИХ днях (пн–пт, без праздников из таблицы holidays)
        sa.Column('working_days', sa.Integer, nullable=False),
        # Прогресс хранится только у листовых задач (is_group=false).
        # У групп вычисляется как взвешенное среднее детей по working_days.
        sa.Column('progress',     sa.SmallInteger, server_default='0'),
        # is_group=true: задача является группой (имеет дочерние)
        # progress у группы не хранится — только вычисляется
        sa.Column('is_group',     sa.Boolean, server_default='false'),
        # task | project | milestone
        sa.Column('type',         sa.String(20), server_default='task'),
        sa.Column('color',        sa.String(20)),
        # Требует акта скрытых работ перед закрытием
        sa.Column('requires_act', sa.Boolean, server_default='false'),
        sa.Column('act_signed',   sa.Boolean, server_default='false'),
        # Порядок строк. NUMERIC позволяет вставить между двумя строками
        # без UPDATE соседей: midpoint = (prev + next) / 2
        sa.Column('row_order',    sa.Numeric(20, 10), server_default='1000'),
        sa.Column('created_at',   TIMESTAMPTZ, server_default=sa.text('NOW()')),
        sa.Column('updated_at',   TIMESTAMPTZ, server_default=sa.text('NOW()')),
        # Мягкое удаление: строки не удаляются физически → история сохраняется
        sa.Column('deleted_at',   TIMESTAMPTZ, nullable=True),
        sa.CheckConstraint("working_days > 0",                        name='ck_task_working_days'),
        sa.CheckConstraint("progress BETWEEN 0 AND 100",              name='ck_task_progress'),
        sa.CheckConstraint("type IN ('task','project','milestone')",   name='ck_task_type'),
    )
    op.create_index('idx_gantt_project',  'gantt_tasks', ['project_id'],
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index('idx_gantt_parent',   'gantt_tasks', ['parent_id'])
    op.create_index('idx_gantt_assignee', 'gantt_tasks', ['assignee_id'])
    op.create_index('idx_gantt_dates',    'gantt_tasks', ['project_id', 'start_date'])

    # ─── 8. ЗАВИСИМОСТИ ЗАДАЧ ────────────────────────────────────────────────
    # Связь M:M между задачами.
    # task_id зависит от depends_on (т.е. начнётся не раньше конца depends_on).
    # Оба FK — CASCADE: удаление любой стороны убирает только связь,
    # но не удаляет вторую задачу.
    op.create_table('task_dependencies',
        sa.Column('task_id',    UUID, sa.ForeignKey('gantt_tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('depends_on', UUID, sa.ForeignKey('gantt_tasks.id', ondelete='CASCADE'), nullable=False),
        sa.PrimaryKeyConstraint('task_id', 'depends_on'),
        sa.CheckConstraint('task_id != depends_on', name='ck_no_self_dep'),
    )
    op.create_index('idx_dep_task',       'task_dependencies', ['task_id'])
    op.create_index('idx_dep_depends_on', 'task_dependencies', ['depends_on'])
    # Второй индекс нужен для быстрого поиска «кто зависит от этой задачи»
    # при каскадном пересчёте дат после изменения предшественника

    # ─── 9. ФОНОВЫЕ ЗАДАЧИ (JOBS) ────────────────────────────────────────────
    # Для асинхронной обработки: парсинг Excel, построение Ганта, экспорт.
    # Frontend делает POST → получает job_id → polling GET /jobs/{id}.
    op.create_table('jobs',
        sa.Column('id',          UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('type',        sa.String(50),  nullable=False),   # estimate_upload | gantt_export | ...
        sa.Column('status',      sa.String(20),  nullable=False, server_default='pending'),
        sa.Column('project_id',  UUID, sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=True),
        sa.Column('created_by',  UUID, sa.ForeignKey('users.id',    ondelete='SET NULL'), nullable=True),
        sa.Column('input',       JSONB),         # параметры: file_key, start_date, workers, ...
        sa.Column('result',      JSONB),         # результат или {error: "..."}
        sa.Column('started_at',  TIMESTAMPTZ),
        sa.Column('finished_at', TIMESTAMPTZ),
        sa.Column('created_at',  TIMESTAMPTZ, server_default=sa.text('NOW()')),
        sa.CheckConstraint(
            "status IN ('pending','processing','done','failed')",
            name='ck_job_status'
        ),
    )
    op.create_index('idx_jobs_project', 'jobs', ['project_id', 'status'])
    op.create_index('idx_jobs_created', 'jobs', ['created_at'])

    # ─── 10. ЕЖЕДНЕВНЫЕ ОТЧЁТЫ ───────────────────────────────────────────────
    # Один отчёт на прораба в день на проект.
    op.create_table('daily_reports',
        sa.Column('id',           UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('project_id',   UUID, sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('author_id',    UUID, sa.ForeignKey('users.id',    ondelete='CASCADE'), nullable=False),
        sa.Column('report_date',  sa.Date, nullable=False),
        # draft → submitted → reviewed
        sa.Column('status',       sa.String(20), nullable=False, server_default='draft'),
        sa.Column('summary',      sa.Text),      # общая заметка за день
        sa.Column('issues',       sa.Text),      # проблемы/задержки
        sa.Column('weather',      sa.String(100)),
        sa.Column('submitted_at', TIMESTAMPTZ),
        sa.Column('reviewed_by',  UUID, sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reviewed_at',  TIMESTAMPTZ),
        sa.Column('created_at',   TIMESTAMPTZ, server_default=sa.text('NOW()')),
        sa.Column('updated_at',   TIMESTAMPTZ, server_default=sa.text('NOW()')),
        sa.UniqueConstraint('project_id', 'author_id', 'report_date', name='uq_report_per_day'),
        sa.CheckConstraint(
            "status IN ('draft','submitted','reviewed')",
            name='ck_report_status'
        ),
    )
    op.create_index('idx_reports_project', 'daily_reports', ['project_id', 'report_date'])
    op.create_index('idx_reports_author',  'daily_reports', ['author_id',  'report_date'])
    op.create_index('idx_reports_missing', 'daily_reports', ['project_id', 'status'],
                    postgresql_where=sa.text("status = 'draft'"))

    # ─── 11. СТРОКИ ОТЧЁТА ───────────────────────────────────────────────────
    # По одной строке на каждую задачу в отчёте.
    op.create_table('daily_report_items',
        sa.Column('id',             UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('report_id',      UUID, sa.ForeignKey('daily_reports.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_id',        UUID, sa.ForeignKey('gantt_tasks.id',   ondelete='CASCADE'), nullable=False),
        sa.Column('work_done',      sa.Text, nullable=False),
        sa.Column('volume_done',    sa.Numeric(12, 3)),
        sa.Column('volume_unit',    sa.String(50)),
        # Прогресс задачи ПОСЛЕ этого отчёта.
        # При submit отчёта → gantt_tasks.progress обновляется этим значением.
        sa.Column('progress_after', sa.SmallInteger, nullable=False),
        sa.Column('workers_count',  sa.SmallInteger),
        sa.Column('workers_note',   sa.Text),
        # [{name, quantity, unit}]
        sa.Column('materials_used', JSONB, server_default='[]'),
        sa.Column('created_at',     TIMESTAMPTZ, server_default=sa.text('NOW()')),
        sa.CheckConstraint('progress_after BETWEEN 0 AND 100', name='ck_item_progress'),
    )
    op.create_index('idx_report_items_report', 'daily_report_items', ['report_id'])
    op.create_index('idx_report_items_task',   'daily_report_items', ['task_id'])

    # ─── 12. КОММЕНТАРИИ ─────────────────────────────────────────────────────
    op.create_table('comments',
        sa.Column('id',          UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('task_id',     UUID, sa.ForeignKey('gantt_tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('author_id',   UUID, sa.ForeignKey('users.id',       ondelete='CASCADE'), nullable=False),
        # Роль сохраняется на момент написания — она может измениться позже
        sa.Column('author_role', sa.String(20), nullable=False),
        sa.Column('text',        sa.Text, nullable=False),
        # Вложения: [{name, url, size, mime}] — файлы хранятся в S3
        sa.Column('attachments', JSONB, server_default='[]'),
        sa.Column('edited_at',   TIMESTAMPTZ, nullable=True),
        sa.Column('created_at',  TIMESTAMPTZ, server_default=sa.text('NOW()')),
        sa.Column('deleted_at',  TIMESTAMPTZ, nullable=True),
    )
    op.create_index('idx_comments_task',    'comments', ['task_id'],
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index('idx_comments_created', 'comments', ['task_id', 'created_at'])

    # ─── 13. ИСТОРИЯ ИЗМЕНЕНИЙ (АУДИТ) ───────────────────────────────────────
    # SET NULL при удалении задачи — история не теряется.
    # Юридически значимый журнал: кто, когда, что изменил.
    op.create_table('task_history',
        sa.Column('id',         UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('task_id',    UUID, sa.ForeignKey('gantt_tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('project_id', UUID, sa.ForeignKey('projects.id',   ondelete='CASCADE'),  nullable=False),
        sa.Column('user_id',    UUID, sa.ForeignKey('users.id',      ondelete='SET NULL'), nullable=True),
        # created | updated | deleted | progress_changed | restored
        sa.Column('action',     sa.String(50), nullable=False),
        sa.Column('old_data',   JSONB),
        sa.Column('new_data',   JSONB),
        sa.Column('created_at', TIMESTAMPTZ, server_default=sa.text('NOW()')),
    )
    op.create_index('idx_history_task',    'task_history', ['task_id'])
    op.create_index('idx_history_project', 'task_history', ['project_id', 'created_at'])

    # ─── 14. МАТЕРИАЛЫ ───────────────────────────────────────────────────────
    # small  — мелочёвка, покупает прораб наличными на рынке
    # major  — основные, снабженец, безнал, с документами
    op.create_table('materials',
        sa.Column('id',            UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('project_id',    UUID, sa.ForeignKey('projects.id',    ondelete='CASCADE'), nullable=False),
        sa.Column('task_id',       UUID, sa.ForeignKey('gantt_tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name',          sa.Text,    nullable=False),
        sa.Column('unit',          sa.String(50)),
        sa.Column('quantity',      sa.Numeric(12, 3)),
        sa.Column('type',          sa.String(10), nullable=False, server_default='small'),
        # Логистика поставки
        sa.Column('order_date',    sa.Date),       # когда нужно заказать
        sa.Column('lead_days',     sa.Integer),    # срок поставки в календ. днях
        sa.Column('delivery_date', sa.Date),       # дата доставки на объект
        # planned | ordered | delivered
        sa.Column('status',        sa.String(20), server_default='planned'),
        sa.Column('supplier_note', sa.Text),
        sa.Column('created_at',    TIMESTAMPTZ, server_default=sa.text('NOW()')),
        sa.Column('deleted_at',    TIMESTAMPTZ, nullable=True),
        sa.CheckConstraint("type   IN ('small','major')",               name='ck_material_type'),
        sa.CheckConstraint("status IN ('planned','ordered','delivered')",name='ck_material_status'),
    )
    op.create_index('idx_materials_project',  'materials', ['project_id'],
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index('idx_materials_delivery', 'materials', ['project_id', 'delivery_date'])

    # ─── 15. ЭСКАЛАЦИИ ───────────────────────────────────────────────────────
    # Создаются автоматически Celery-джобом (07:00).
    # Через 48ч без решения → статус escalated → уведомление директору.
    op.create_table('escalations',
        sa.Column('id',           UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('project_id',   UUID, sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_id',      UUID, sa.ForeignKey('gantt_tasks.id', ondelete='SET NULL'), nullable=True),
        # no_report | plan_not_met | overdue | hidden_work_due
        sa.Column('type',         sa.String(50), nullable=False),
        sa.Column('meta',         JSONB, server_default='{}'),  # доп. данные (foreman_id, date, ...)
        # open → escalated (48ч) → resolved
        sa.Column('status',       sa.String(20), nullable=False, server_default='open'),
        sa.Column('detected_at',  TIMESTAMPTZ,   nullable=False, server_default=sa.text('NOW()')),
        sa.Column('escalated_at', TIMESTAMPTZ,   nullable=True),
        sa.Column('resolved_at',  TIMESTAMPTZ,   nullable=True),
        sa.Column('resolved_by',  UUID, sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.CheckConstraint(
            "status IN ('open','escalated','resolved')",
            name='ck_escalation_status'
        ),
    )
    op.create_index('idx_escalations_project', 'escalations', ['project_id', 'status'])
    op.create_index('idx_escalations_open',    'escalations', ['detected_at'],
                    postgresql_where=sa.text("status != 'resolved'"))

    # ─── 16. УВЕДОМЛЕНИЯ ─────────────────────────────────────────────────────
    op.create_table('notifications',
        sa.Column('id',          UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id',     UUID, sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('type',        sa.String(50), nullable=False),
        # report_reminder | missing_report | escalation | task_overdue |
        # material_due | hidden_work_due | task_assigned | comment_added
        sa.Column('title',       sa.Text, nullable=False),
        sa.Column('body',        sa.Text),
        sa.Column('entity_type', sa.String(30)),   # task | project | escalation | material
        sa.Column('entity_id',   UUID,    nullable=True),
        sa.Column('is_read',     sa.Boolean, server_default='false'),
        sa.Column('created_at',  TIMESTAMPTZ, server_default=sa.text('NOW()')),
    )
    op.create_index('idx_notif_user_unread', 'notifications', ['user_id', 'created_at'],
                    postgresql_where=sa.text("is_read = false"))

    # ─── 17. REFRESH ТОКЕНЫ ──────────────────────────────────────────────────
    # JWT access_token живёт 15 мин, refresh — 30 дней.
    # При logout → удаляем строку → токен инвалидирован.
    op.create_table('refresh_tokens',
        sa.Column('id',          UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id',     UUID, sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash',  sa.String(255), nullable=False, unique=True),
        sa.Column('expires_at',  TIMESTAMPTZ, nullable=False),
        sa.Column('created_at',  TIMESTAMPTZ, server_default=sa.text('NOW()')),
    )
    op.create_index('idx_tokens_user',    'refresh_tokens', ['user_id'])
    op.create_index('idx_tokens_expires', 'refresh_tokens', ['expires_at'])


def downgrade():
    # Удаляем в обратном порядке (дочерние → родительские)
    tables = [
        'refresh_tokens',
        'notifications',
        'escalations',
        'materials',
        'task_history',
        'comments',
        'daily_report_items',
        'daily_reports',
        'jobs',
        'task_dependencies',
        'gantt_tasks',
        'estimates',
        'holidays',
        'project_members',
        'projects',
        'users',
        'organizations',
    ]
    for table in tables:
        op.drop_table(table)
