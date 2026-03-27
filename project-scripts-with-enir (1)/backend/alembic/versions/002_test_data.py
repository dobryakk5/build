"""
002_test_data.py
Тестовые данные — организация, пользователь-PM и два демо-проекта
с полноценной иерархией задач (3 уровня вложенности).

Логин: test@test.local
Пароль: test123
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text
from datetime import date, timedelta
from app.core.security import hash_password

revision = '002'
down_revision = '001'

# ─── Фиксированные UUID ───────────────────────────────────────────────────────
ORG_ID      = 'a0000000-0000-0000-0000-000000000001'
USER_ID     = 'b0000000-0000-0000-0000-000000000001'
PROJECT1_ID = 'c0000000-0000-0000-0000-000000000001'
PROJECT2_ID = 'c0000000-0000-0000-0000-000000000002'

# ── Проект 1: ЖК «Сосновый бор» ──────────────────────────────────────────────
# Уровень 1 — фазы (группы верхнего уровня)
P1_PHASE_PREP    = 'd1000000-0000-0000-0000-000000000001'  # Подготовительный этап
P1_PHASE_FOUND   = 'd1000000-0000-0000-0000-000000000002'  # Фундамент
P1_PHASE_STRUCT  = 'd1000000-0000-0000-0000-000000000003'  # Несущие конструкции
P1_PHASE_ENVELOP = 'd1000000-0000-0000-0000-000000000004'  # Внешний контур
P1_PHASE_MEP     = 'd1000000-0000-0000-0000-000000000005'  # Инженерные системы
P1_PHASE_FINISH  = 'd1000000-0000-0000-0000-000000000006'  # Отделка и сдача

# Уровень 2 — разделы
P1_PREP_GEODESY  = 'd1100000-0000-0000-0000-000000000001'
P1_PREP_FENCE    = 'd1100000-0000-0000-0000-000000000002'
P1_PREP_ROADS    = 'd1100000-0000-0000-0000-000000000003'
P1_PREP_UTILITY  = 'd1100000-0000-0000-0000-000000000004'

P1_FOUND_EXCAV   = 'd1200000-0000-0000-0000-000000000001'
P1_FOUND_PILES   = 'd1200000-0000-0000-0000-000000000002'
P1_FOUND_RAFT    = 'd1200000-0000-0000-0000-000000000003'
P1_FOUND_WATERP  = 'd1200000-0000-0000-0000-000000000004'

P1_STRUCT_FRAME  = 'd1300000-0000-0000-0000-000000000001'
P1_STRUCT_FLOOR1 = 'd1300000-0000-0000-0000-000000000002'
P1_STRUCT_FLOOR2 = 'd1300000-0000-0000-0000-000000000003'
P1_STRUCT_FLOOR3 = 'd1300000-0000-0000-0000-000000000004'
P1_STRUCT_STAIRS = 'd1300000-0000-0000-0000-000000000005'

P1_ENV_ROOF      = 'd1400000-0000-0000-0000-000000000001'
P1_ENV_FACADE    = 'd1400000-0000-0000-0000-000000000002'
P1_ENV_WINDOWS   = 'd1400000-0000-0000-0000-000000000003'
P1_ENV_ENTRANCE  = 'd1400000-0000-0000-0000-000000000004'

P1_MEP_HEAT      = 'd1500000-0000-0000-0000-000000000001'
P1_MEP_WATER     = 'd1500000-0000-0000-0000-000000000002'
P1_MEP_ELEC      = 'd1500000-0000-0000-0000-000000000003'
P1_MEP_VENT      = 'd1500000-0000-0000-0000-000000000004'
P1_MEP_FIRE      = 'd1500000-0000-0000-0000-000000000005'

P1_FIN_COMMON    = 'd1600000-0000-0000-0000-000000000001'
P1_FIN_FLATS     = 'd1600000-0000-0000-0000-000000000002'
P1_FIN_TERR      = 'd1600000-0000-0000-0000-000000000003'
P1_FIN_HANDOVER  = 'd1600000-0000-0000-0000-000000000004'

# Уровень 3 — листовые задачи
P1_GEO_SURVEY    = 'd1110000-0000-0000-0000-000000000001'
P1_GEO_MARKS     = 'd1110000-0000-0000-0000-000000000002'

P1_FENCE_INST    = 'd1120000-0000-0000-0000-000000000001'
P1_FENCE_GATE    = 'd1120000-0000-0000-0000-000000000002'
P1_FENCE_LIGHT   = 'd1120000-0000-0000-0000-000000000003'

P1_ROAD_PLAN     = 'd1130000-0000-0000-0000-000000000001'
P1_ROAD_GRAVEL   = 'd1130000-0000-0000-0000-000000000002'

P1_UTL_POWER     = 'd1140000-0000-0000-0000-000000000001'
P1_UTL_WATER     = 'd1140000-0000-0000-0000-000000000002'

P1_EXC_STRIP     = 'd1210000-0000-0000-0000-000000000001'
P1_EXC_BULK      = 'd1210000-0000-0000-0000-000000000002'
P1_EXC_REFINE    = 'd1210000-0000-0000-0000-000000000003'

P1_PILE_DRILL    = 'd1220000-0000-0000-0000-000000000001'
P1_PILE_POUR     = 'd1220000-0000-0000-0000-000000000002'
P1_PILE_TEST     = 'd1220000-0000-0000-0000-000000000003'

P1_RAFT_FORM     = 'd1230000-0000-0000-0000-000000000001'
P1_RAFT_REBAR    = 'd1230000-0000-0000-0000-000000000002'
P1_RAFT_POUR     = 'd1230000-0000-0000-0000-000000000003'
P1_RAFT_CURE     = 'd1230000-0000-0000-0000-000000000004'

P1_WP_PREP       = 'd1240000-0000-0000-0000-000000000001'
P1_WP_COAT       = 'd1240000-0000-0000-0000-000000000002'
P1_WP_PROTECT    = 'd1240000-0000-0000-0000-000000000003'

P1_FRM_COL       = 'd1310000-0000-0000-0000-000000000001'
P1_FRM_BEAM      = 'd1310000-0000-0000-0000-000000000002'
P1_FRM_BRACE     = 'd1310000-0000-0000-0000-000000000003'

P1_FL1_FORM      = 'd1320000-0000-0000-0000-000000000001'
P1_FL1_REBAR     = 'd1320000-0000-0000-0000-000000000002'
P1_FL1_POUR      = 'd1320000-0000-0000-0000-000000000003'

P1_FL2_FORM      = 'd1330000-0000-0000-0000-000000000001'
P1_FL2_REBAR     = 'd1330000-0000-0000-0000-000000000002'
P1_FL2_POUR      = 'd1330000-0000-0000-0000-000000000003'

P1_FL3_FORM      = 'd1340000-0000-0000-0000-000000000001'
P1_FL3_REBAR     = 'd1340000-0000-0000-0000-000000000002'
P1_FL3_POUR      = 'd1340000-0000-0000-0000-000000000003'

P1_ROOF_BASE     = 'd1410000-0000-0000-0000-000000000001'
P1_ROOF_INSUL    = 'd1410000-0000-0000-0000-000000000002'
P1_ROOF_MEMBR    = 'd1410000-0000-0000-0000-000000000003'
P1_ROOF_DRAIN    = 'd1410000-0000-0000-0000-000000000004'

P1_FAC_INSUL     = 'd1420000-0000-0000-0000-000000000001'
P1_FAC_PLASTER   = 'd1420000-0000-0000-0000-000000000002'
P1_FAC_PAINT     = 'd1420000-0000-0000-0000-000000000003'

P1_WIN_FRAME     = 'd1430000-0000-0000-0000-000000000001'
P1_WIN_GLASS     = 'd1430000-0000-0000-0000-000000000002'
P1_WIN_SEAL      = 'd1430000-0000-0000-0000-000000000003'

P1_HEAT_BOIL     = 'd1510000-0000-0000-0000-000000000001'
P1_HEAT_PIPES    = 'd1510000-0000-0000-0000-000000000002'
P1_HEAT_RAD      = 'd1510000-0000-0000-0000-000000000003'

P1_WAT_COLD      = 'd1520000-0000-0000-0000-000000000001'
P1_WAT_HOT       = 'd1520000-0000-0000-0000-000000000002'
P1_WAT_DRAIN     = 'd1520000-0000-0000-0000-000000000003'

P1_EL_MAIN       = 'd1530000-0000-0000-0000-000000000001'
P1_EL_DIST       = 'd1530000-0000-0000-0000-000000000002'
P1_EL_LIGHT      = 'd1530000-0000-0000-0000-000000000003'
P1_EL_SOCKET     = 'd1530000-0000-0000-0000-000000000004'

P1_VENT_DUCT     = 'd1540000-0000-0000-0000-000000000001'
P1_VENT_UNIT     = 'd1540000-0000-0000-0000-000000000002'

P1_FIRE_DET      = 'd1550000-0000-0000-0000-000000000001'
P1_FIRE_SPRINK   = 'd1550000-0000-0000-0000-000000000002'

P1_COM_LOBBY     = 'd1610000-0000-0000-0000-000000000001'
P1_COM_LIFT      = 'd1610000-0000-0000-0000-000000000002'
P1_COM_FLOOR     = 'd1610000-0000-0000-0000-000000000003'

P1_FLAT_PLAST    = 'd1620000-0000-0000-0000-000000000001'
P1_FLAT_FLOOR    = 'd1620000-0000-0000-0000-000000000002'
P1_FLAT_TILE     = 'd1620000-0000-0000-0000-000000000003'
P1_FLAT_PAINT    = 'd1620000-0000-0000-0000-000000000004'

P1_TERR_CURB     = 'd1630000-0000-0000-0000-000000000001'
P1_TERR_ASPH     = 'd1630000-0000-0000-0000-000000000002'
P1_TERR_GREEN    = 'd1630000-0000-0000-0000-000000000003'
P1_TERR_PLAY     = 'd1630000-0000-0000-0000-000000000004'

P1_HDO_INSPECT   = 'd1640000-0000-0000-0000-000000000001'
P1_HDO_DOCS      = 'd1640000-0000-0000-0000-000000000002'
P1_HDO_SIGN      = 'd1640000-0000-0000-0000-000000000003'

# ── Проект 2: ТЦ «Меркурий» ──────────────────────────────────────────────────
P2_PHASE_DEMO    = 'e1000000-0000-0000-0000-000000000001'
P2_PHASE_FOUND   = 'e1000000-0000-0000-0000-000000000002'
P2_PHASE_STRUCT  = 'e1000000-0000-0000-0000-000000000003'
P2_PHASE_MEP     = 'e1000000-0000-0000-0000-000000000004'
P2_PHASE_FINISH  = 'e1000000-0000-0000-0000-000000000005'

P2_DEMO_ASPH     = 'e1100000-0000-0000-0000-000000000001'
P2_DEMO_STRUCT   = 'e1100000-0000-0000-0000-000000000002'
P2_DEMO_UTIL     = 'e1100000-0000-0000-0000-000000000003'

P2_FND_PILE      = 'e1200000-0000-0000-0000-000000000001'
P2_FND_SLAB      = 'e1200000-0000-0000-0000-000000000002'

P2_STR_COL       = 'e1300000-0000-0000-0000-000000000001'
P2_STR_FLOOR1    = 'e1300000-0000-0000-0000-000000000002'
P2_STR_FLOOR2    = 'e1300000-0000-0000-0000-000000000003'
P2_STR_ROOF      = 'e1300000-0000-0000-0000-000000000004'

P2_MEP_HVAC      = 'e1400000-0000-0000-0000-000000000001'
P2_MEP_ELEC      = 'e1400000-0000-0000-0000-000000000002'
P2_MEP_FIRE      = 'e1400000-0000-0000-0000-000000000003'
P2_MEP_IT        = 'e1400000-0000-0000-0000-000000000004'

P2_FIN_FLOOR     = 'e1500000-0000-0000-0000-000000000001'
P2_FIN_WALLS     = 'e1500000-0000-0000-0000-000000000002'
P2_FIN_FACADE    = 'e1500000-0000-0000-0000-000000000003'
P2_FIN_SIGNAGE   = 'e1500000-0000-0000-0000-000000000004'

TODAY = date.today()


def upgrade():
    conn = op.get_bind()

    password_hash = hash_password('test123')

    # ─── Организация ─────────────────────────────────────────────────────────
    conn.execute(text("""
        INSERT INTO organizations (id, name, slug, plan)
        VALUES (:id, 'СтройГрупп Демо', 'stroygroup-demo', 'pro')
        ON CONFLICT (id) DO NOTHING
    """), {'id': ORG_ID})

    # ─── Пользователь ────────────────────────────────────────────────────────
    conn.execute(text("""
        INSERT INTO users (id, organization_id, email, name, password_hash, is_active)
        VALUES (:id, :org, 'test@example.com', 'Тестов Иван Петрович', :pwd, true)
        ON CONFLICT (id) DO NOTHING
    """), {'id': USER_ID, 'org': ORG_ID, 'pwd': password_hash})

    # ─── Проект 1 ─────────────────────────────────────────────────────────────
    conn.execute(text("""
        INSERT INTO projects
            (id, organization_id, created_by, name, address, status, color,
             start_date, end_date, dashboard_status)
        VALUES (:id, :org, :user, 'ЖК «Сосновый бор»',
                'г. Москва, ул. Лесная, 12', 'active', '#3b82f6',
                :start, :end, 'yellow')
        ON CONFLICT (id) DO NOTHING
    """), {
        'id': PROJECT1_ID, 'org': ORG_ID, 'user': USER_ID,
        'start': TODAY - timedelta(days=90),
        'end':   TODAY + timedelta(days=270),
    })

    # ─── Проект 2 ─────────────────────────────────────────────────────────────
    conn.execute(text("""
        INSERT INTO projects
            (id, organization_id, created_by, name, address, status, color,
             start_date, end_date, dashboard_status)
        VALUES (:id, :org, :user, 'ТЦ «Меркурий»',
                'г. Москва, пр. Победы, 55', 'active', '#10b981',
                :start, :end, 'green')
        ON CONFLICT (id) DO NOTHING
    """), {
        'id': PROJECT2_ID, 'org': ORG_ID, 'user': USER_ID,
        'start': TODAY - timedelta(days=20),
        'end':   TODAY + timedelta(days=340),
    })

    for pid in [PROJECT1_ID, PROJECT2_ID]:
        conn.execute(text("""
            INSERT INTO project_members (id, project_id, user_id, role)
            VALUES (gen_random_uuid(), :pid, :uid, 'owner')
            ON CONFLICT (project_id, user_id) DO NOTHING
        """), {'pid': pid, 'uid': USER_ID})

    # ─── Смета проекта 1 ──────────────────────────────────────────────────────
    estimates_p1 = [
        ('Подготовительные работы', 'Геодезическая съёмка участка',              'га',    1.2,   85000),
        ('Подготовительные работы', 'Устройство ограждения строительной площадки','м',    320,    1800),
        ('Подготовительные работы', 'Устройство временных дорог (гравий)',        'м²',   480,     650),
        ('Подготовительные работы', 'Подключение временного электроснабжения',    'компл',  1,   95000),
        ('Подготовительные работы', 'Подключение временного водоснабжения',       'компл',  1,   65000),
        ('Земляные работы',         'Срезка растительного слоя',                  'м³',   420,     180),
        ('Земляные работы',         'Разработка котлована экскаватором',           'м³',  3800,     320),
        ('Земляные работы',         'Зачистка дна котлована вручную',              'м²',   950,     380),
        ('Фундамент',               'Бурение скважин под сваи d400',               'шт',    64,    4200),
        ('Фундамент',               'Установка арматурных каркасов свай',          'шт',    64,    2800),
        ('Фундамент',               'Бетонирование свай B25',                      'м³',    48,   12500),
        ('Фундамент',               'Испытание свай статической нагрузкой',        'шт',     4,   45000),
        ('Фундамент',               'Устройство опалубки ростверка',               'м²',   380,    1200),
        ('Фундамент',               'Армирование ростверка А500С',                 'т',     18,   62000),
        ('Фундамент',               'Бетонирование ростверка B30',                 'м³',   210,   11500),
        ('Фундамент',               'Гидроизоляция фундамента обмазочная',         'м²',   640,     850),
        ('Фундамент',               'Гидроизоляция фундамента рулонная',           'м²',   640,    1250),
        ('Конструкции',             'Монтаж металлических колонн',                 'т',     28,   98000),
        ('Конструкции',             'Монтаж ригелей и прогонов',                   'т',     22,   92000),
        ('Конструкции',             'Монтаж связей и раскосов',                    'т',      8,   88000),
        ('Конструкции',             'Устройство монолитного перекрытия 1 эт.',     'м²',   820,    4800),
        ('Конструкции',             'Устройство монолитного перекрытия 2 эт.',     'м²',   820,    4800),
        ('Конструкции',             'Устройство монолитного перекрытия 3 эт.',     'м²',   820,    4800),
        ('Конструкции',             'Монолитная лестница (марш)',                   'шт',     6,   38000),
        ('Кровля',                  'Основание кровли (стяжка)',                   'м²',   820,     680),
        ('Кровля',                  'Утепление кровли PIR 150мм',                  'м²',   820,    2200),
        ('Кровля',                  'Мембрана ПВХ Logicroof',                      'м²',   850,    1950),
        ('Кровля',                  'Водосточная система',                         'пог.м', 320,   2400),
        ('Фасад',                   'Утепление фасада минвата 150мм',              'м²',  1650,    1950),
        ('Фасад',                   'Штукатурка фасада',                           'м²',  1650,    1600),
        ('Фасад',                   'Покраска фасада (2 слоя)',                    'м²',  1650,     480),
        ('Окна',                    'Монтаж оконных блоков ПВХ',                   'м²',   380,   12500),
        ('Окна',                    'Остекление фасада витражное',                 'м²',    48,   28000),
        ('Инж. системы',            'Котельная (монтаж котлов)',                   'компл',  1, 1250000),
        ('Инж. системы',            'Разводка отопления',                         'пог.м',1840,    1200),
        ('Инж. системы',            'Установка радиаторов',                        'шт',   184,    3800),
        ('Инж. системы',            'Холодное водоснабжение',                     'пог.м', 960,    1400),
        ('Инж. системы',            'Горячее водоснабжение',                      'пог.м', 960,    1600),
        ('Инж. системы',            'Канализация',                                'пог.м', 840,    1350),
        ('Инж. системы',            'ГРЩ + кабельные трассы',                     'компл',  1,  480000),
        ('Инж. системы',            'Распределительные щиты по этажам',            'шт',     3,   65000),
        ('Инж. системы',            'Освещение общих зон',                         'точка', 280,   4200),
        ('Инж. системы',            'Вентиляция и кондиционирование',              'компл',  1,  920000),
        ('Инж. системы',            'Пожарная сигнализация',                       'компл',  1,  380000),
        ('Инж. системы',            'Спринклерное пожаротушение',                  'шт',   240,    4500),
        ('Отделка',                 'Штукатурка стен общих зон',                   'м²',  2400,    1200),
        ('Отделка',                 'Устройство стяжки в квартирах',               'м²',  2100,     680),
        ('Отделка',                 'Плитка в санузлах',                           'м²',   380,    3200),
        ('Отделка',                 'Покраска стен квартир',                       'м²',  4200,     420),
        ('Благоустройство',         'Устройство бортового камня',                 'пог.м', 480,    1800),
        ('Благоустройство',         'Асфальтирование',                             'м²',   960,    2800),
        ('Благоустройство',         'Озеленение',                                  'м²',   640,    1200),
        ('Благоустройство',         'Детская площадка',                            'компл',  1,  380000),
    ]
    for i, (section, work, unit, qty, price) in enumerate(estimates_p1):
        conn.execute(text("""
            INSERT INTO estimates (id, project_id, section, work_name, unit,
                quantity, unit_price, total_price, row_order)
            VALUES (gen_random_uuid(), :pid, :sec, :work, :unit,
                :qty, :price, :total, :order)
        """), {
            'pid': PROJECT1_ID, 'sec': section, 'work': work,
            'unit': unit, 'qty': qty, 'price': price,
            'total': qty * price, 'order': i * 10,
        })

    # ─── Задачи Ганта проекта 1 ───────────────────────────────────────────────
    # (id, parent_id, name, start_offset, working_days, progress, is_group, type, color)
    gantt_p1 = [
        # ── Фаза 1: Подготовительный этап (завершён) ─────────────────────────
        (P1_PHASE_PREP,   None,            'Подготовительный этап',       -85, 18,  0, True,  'project', '#6366f1'),
        (P1_PREP_GEODESY, P1_PHASE_PREP,   'Геодезия',                    -85,  4,  0, True,  'project', '#818cf8'),
        (P1_GEO_SURVEY,   P1_PREP_GEODESY, 'Топографическая съёмка',      -85,  2,100, False, 'task',    '#a5b4fc'),
        (P1_GEO_MARKS,    P1_PREP_GEODESY, 'Вынос осей в натуру',         -83,  2,100, False, 'task',    '#a5b4fc'),
        (P1_PREP_FENCE,   P1_PHASE_PREP,   'Ограждение площадки',         -81,  5,  0, True,  'project', '#818cf8'),
        (P1_FENCE_INST,   P1_PREP_FENCE,   'Монтаж забора',               -81,  3,100, False, 'task',    '#a5b4fc'),
        (P1_FENCE_GATE,   P1_PREP_FENCE,   'Установка ворот и КПП',       -78,  1,100, False, 'task',    '#a5b4fc'),
        (P1_FENCE_LIGHT,  P1_PREP_FENCE,   'Прожекторное освещение',      -77,  1,100, False, 'task',    '#a5b4fc'),
        (P1_PREP_ROADS,   P1_PHASE_PREP,   'Временные дороги',            -76,  4,  0, True,  'project', '#818cf8'),
        (P1_ROAD_PLAN,    P1_PREP_ROADS,   'Планировка территории',       -76,  2,100, False, 'task',    '#a5b4fc'),
        (P1_ROAD_GRAVEL,  P1_PREP_ROADS,   'Отсыпка гравием',             -74,  2,100, False, 'task',    '#a5b4fc'),
        (P1_PREP_UTILITY, P1_PHASE_PREP,   'Временные коммуникации',      -72,  5,  0, True,  'project', '#818cf8'),
        (P1_UTL_POWER,    P1_PREP_UTILITY, 'Временное электроснабжение',  -72,  3,100, False, 'task',    '#a5b4fc'),
        (P1_UTL_WATER,    P1_PREP_UTILITY, 'Временное водоснабжение',     -69,  2,100, False, 'task',    '#a5b4fc'),

        # ── Фаза 2: Фундамент (завершён) ─────────────────────────────────────
        (P1_PHASE_FOUND,  None,            'Фундамент',                   -67, 38,  0, True,  'project', '#f59e0b'),
        (P1_FOUND_EXCAV,  P1_PHASE_FOUND,  'Земляные работы',             -67, 10,  0, True,  'project', '#fbbf24'),
        (P1_EXC_STRIP,    P1_FOUND_EXCAV,  'Срезка растительного слоя',  -67,  3,100, False, 'task',    '#fde68a'),
        (P1_EXC_BULK,     P1_FOUND_EXCAV,  'Разработка котлована',        -64,  5,100, False, 'task',    '#fde68a'),
        (P1_EXC_REFINE,   P1_FOUND_EXCAV,  'Зачистка дна котлована',      -59,  2,100, False, 'task',    '#fde68a'),
        (P1_FOUND_PILES,  P1_PHASE_FOUND,  'Свайные работы',              -57, 12,  0, True,  'project', '#fbbf24'),
        (P1_PILE_DRILL,   P1_FOUND_PILES,  'Бурение скважин',             -57,  6,100, False, 'task',    '#fde68a'),
        (P1_PILE_POUR,    P1_FOUND_PILES,  'Бетонирование свай',          -51,  4,100, False, 'task',    '#fde68a'),
        (P1_PILE_TEST,    P1_FOUND_PILES,  'Испытание свай',              -47,  2,100, False, 'task',    '#fde68a'),
        (P1_FOUND_RAFT,   P1_PHASE_FOUND,  'Ростверк',                    -45, 13,  0, True,  'project', '#fbbf24'),
        (P1_RAFT_FORM,    P1_FOUND_RAFT,   'Опалубка ростверка',          -45,  3,100, False, 'task',    '#fde68a'),
        (P1_RAFT_REBAR,   P1_FOUND_RAFT,   'Армирование ростверка',       -42,  3,100, False, 'task',    '#fde68a'),
        (P1_RAFT_POUR,    P1_FOUND_RAFT,   'Бетонирование ростверка',     -39,  2,100, False, 'task',    '#fde68a'),
        (P1_RAFT_CURE,    P1_FOUND_RAFT,   'Выдержка бетона 28 сут.',     -37,  5,100, False, 'task',    '#fde68a'),
        (P1_FOUND_WATERP, P1_PHASE_FOUND,  'Гидроизоляция фундамента',    -32,  3,  0, True,  'project', '#fbbf24'),
        (P1_WP_PREP,      P1_FOUND_WATERP, 'Подготовка поверхности',      -32,  1,100, False, 'task',    '#fde68a'),
        (P1_WP_COAT,      P1_FOUND_WATERP, 'Обмазочная гидроизоляция',    -31,  1,100, False, 'task',    '#fde68a'),
        (P1_WP_PROTECT,   P1_FOUND_WATERP, 'Защитный слой',               -30,  1,100, False, 'task',    '#fde68a'),

        # ── Фаза 3: Несущие конструкции (в работе) ───────────────────────────
        (P1_PHASE_STRUCT, None,            'Несущие конструкции',         -29, 46,  0, True,  'project', '#ef4444'),
        (P1_STRUCT_FRAME, P1_PHASE_STRUCT, 'Металлический каркас',        -29, 15,  0, True,  'project', '#f87171'),
        (P1_FRM_COL,      P1_STRUCT_FRAME, 'Монтаж колонн',               -29,  6,100, False, 'task',    '#fca5a5'),
        (P1_FRM_BEAM,     P1_STRUCT_FRAME, 'Монтаж ригелей и прогонов',   -23,  6, 85, False, 'task',    '#fca5a5'),
        (P1_FRM_BRACE,    P1_STRUCT_FRAME, 'Монтаж связей и раскосов',    -17,  3, 40, False, 'task',    '#fca5a5'),
        (P1_STRUCT_FLOOR1,P1_PHASE_STRUCT, 'Перекрытие 1-го этажа',       -14,  8,  0, True,  'project', '#f87171'),
        (P1_FL1_FORM,     P1_STRUCT_FLOOR1,'Опалубка',                    -14,  3, 70, False, 'task',    '#fca5a5'),
        (P1_FL1_REBAR,    P1_STRUCT_FLOOR1,'Армирование',                 -11,  3, 30, False, 'task',    '#fca5a5'),
        (P1_FL1_POUR,     P1_STRUCT_FLOOR1,'Бетонирование и выдержка',     -8,  2,  0, False, 'task',    '#fca5a5'),
        (P1_STRUCT_FLOOR2,P1_PHASE_STRUCT, 'Перекрытие 2-го этажа',        -6,  8,  0, True,  'project', '#f87171'),
        (P1_FL2_FORM,     P1_STRUCT_FLOOR2,'Опалубка',                     -6,  3,  0, False, 'task',    '#fca5a5'),
        (P1_FL2_REBAR,    P1_STRUCT_FLOOR2,'Армирование',                  -3,  3,  0, False, 'task',    '#fca5a5'),
        (P1_FL2_POUR,     P1_STRUCT_FLOOR2,'Бетонирование и выдержка',      0,  2,  0, False, 'task',    '#fca5a5'),
        (P1_STRUCT_FLOOR3,P1_PHASE_STRUCT, 'Перекрытие 3-го этажа',         3,  8,  0, True,  'project', '#f87171'),
        (P1_FL3_FORM,     P1_STRUCT_FLOOR3,'Опалубка',                      3,  3,  0, False, 'task',    '#fca5a5'),
        (P1_FL3_REBAR,    P1_STRUCT_FLOOR3,'Армирование',                   6,  3,  0, False, 'task',    '#fca5a5'),
        (P1_FL3_POUR,     P1_STRUCT_FLOOR3,'Бетонирование и выдержка',       9,  2,  0, False, 'task',    '#fca5a5'),
        (P1_STRUCT_STAIRS,P1_PHASE_STRUCT, 'Монолитные лестницы',            5, 10,  0, False, 'task',    '#fca5a5'),

        # ── Фаза 4: Внешний контур ────────────────────────────────────────────
        (P1_PHASE_ENVELOP,None,            'Внешний контур',               12, 36,  0, True,  'project', '#8b5cf6'),
        (P1_ENV_ROOF,     P1_PHASE_ENVELOP,'Кровля',                       12, 12,  0, True,  'project', '#a78bfa'),
        (P1_ROOF_BASE,    P1_ENV_ROOF,     'Основание (стяжка)',            12,  3,  0, False, 'task',    '#c4b5fd'),
        (P1_ROOF_INSUL,   P1_ENV_ROOF,     'Утепление PIR',                 15,  3,  0, False, 'task',    '#c4b5fd'),
        (P1_ROOF_MEMBR,   P1_ENV_ROOF,     'Укладка мембраны ПВХ',          18,  4,  0, False, 'task',    '#c4b5fd'),
        (P1_ROOF_DRAIN,   P1_ENV_ROOF,     'Водосточная система',           22,  2,  0, False, 'task',    '#c4b5fd'),
        (P1_ENV_FACADE,   P1_PHASE_ENVELOP,'Фасад',                        20, 16,  0, True,  'project', '#a78bfa'),
        (P1_FAC_INSUL,    P1_ENV_FACADE,   'Утепление минватой',            20,  6,  0, False, 'task',    '#c4b5fd'),
        (P1_FAC_PLASTER,  P1_ENV_FACADE,   'Штукатурка',                   26,  6,  0, False, 'task',    '#c4b5fd'),
        (P1_FAC_PAINT,    P1_ENV_FACADE,   'Покраска (2 слоя)',             32,  4,  0, False, 'task',    '#c4b5fd'),
        (P1_ENV_WINDOWS,  P1_PHASE_ENVELOP,'Окна и витражи',                18, 10,  0, True,  'project', '#a78bfa'),
        (P1_WIN_FRAME,    P1_ENV_WINDOWS,  'Монтаж оконных рам',            18,  4,  0, False, 'task',    '#c4b5fd'),
        (P1_WIN_GLASS,    P1_ENV_WINDOWS,  'Вставка стеклопакетов',         22,  4,  0, False, 'task',    '#c4b5fd'),
        (P1_WIN_SEAL,     P1_ENV_WINDOWS,  'Герметизация',                  26,  2,  0, False, 'task',    '#c4b5fd'),
        (P1_ENV_ENTRANCE, P1_PHASE_ENVELOP,'Входные группы',                28,  4,  0, False, 'task',    '#c4b5fd'),

        # ── Фаза 5: Инженерные системы ────────────────────────────────────────
        (P1_PHASE_MEP,    None,            'Инженерные системы',            24, 40,  0, True,  'project', '#0ea5e9'),
        (P1_MEP_HEAT,     P1_PHASE_MEP,    'Отопление',                     24, 14,  0, True,  'project', '#38bdf8'),
        (P1_HEAT_BOIL,    P1_MEP_HEAT,     'Монтаж котельной',              24,  5,  0, False, 'task',    '#7dd3fc'),
        (P1_HEAT_PIPES,   P1_MEP_HEAT,     'Разводка трубопроводов',        29,  6,  0, False, 'task',    '#7dd3fc'),
        (P1_HEAT_RAD,     P1_MEP_HEAT,     'Установка радиаторов',          35,  3,  0, False, 'task',    '#7dd3fc'),
        (P1_MEP_WATER,    P1_PHASE_MEP,    'Водоснабжение и канализация',   26, 14,  0, True,  'project', '#38bdf8'),
        (P1_WAT_COLD,     P1_MEP_WATER,    'Холодное водоснабжение',        26,  5,  0, False, 'task',    '#7dd3fc'),
        (P1_WAT_HOT,      P1_MEP_WATER,    'Горячее водоснабжение',         31,  4,  0, False, 'task',    '#7dd3fc'),
        (P1_WAT_DRAIN,    P1_MEP_WATER,    'Канализация',                   26,  6,  0, False, 'task',    '#7dd3fc'),
        (P1_MEP_ELEC,     P1_PHASE_MEP,    'Электроснабжение',              30, 16,  0, True,  'project', '#38bdf8'),
        (P1_EL_MAIN,      P1_MEP_ELEC,     'ГРЩ и кабельные трассы',       30,  5,  0, False, 'task',    '#7dd3fc'),
        (P1_EL_DIST,      P1_MEP_ELEC,     'Этажные щиты',                  35,  3,  0, False, 'task',    '#7dd3fc'),
        (P1_EL_LIGHT,     P1_MEP_ELEC,     'Освещение общих зон',           38,  5,  0, False, 'task',    '#7dd3fc'),
        (P1_EL_SOCKET,    P1_MEP_ELEC,     'Розетки и выключатели',         43,  3,  0, False, 'task',    '#7dd3fc'),
        (P1_MEP_VENT,     P1_PHASE_MEP,    'Вентиляция и кондиционирование',30, 18,  0, True,  'project', '#38bdf8'),
        (P1_VENT_DUCT,    P1_MEP_VENT,     'Монтаж воздуховодов',           30, 10,  0, False, 'task',    '#7dd3fc'),
        (P1_VENT_UNIT,    P1_MEP_VENT,     'Монтаж вентустановок',          40,  8,  0, False, 'task',    '#7dd3fc'),
        (P1_MEP_FIRE,     P1_PHASE_MEP,    'Пожарная безопасность',         35, 15,  0, True,  'project', '#38bdf8'),
        (P1_FIRE_DET,     P1_MEP_FIRE,     'Пожарная сигнализация',         35,  8,  0, False, 'task',    '#7dd3fc'),
        (P1_FIRE_SPRINK,  P1_MEP_FIRE,     'Спринклерное пожаротушение',    38, 12,  0, False, 'task',    '#7dd3fc'),

        # ── Фаза 6: Отделка и сдача ───────────────────────────────────────────
        (P1_PHASE_FINISH, None,            'Отделка и сдача',               50, 50,  0, True,  'project', '#10b981'),
        (P1_FIN_COMMON,   P1_PHASE_FINISH, 'Общие помещения',               50, 20,  0, True,  'project', '#34d399'),
        (P1_COM_LOBBY,    P1_FIN_COMMON,   'Отделка лобби',                 50, 10,  0, False, 'task',    '#6ee7b7'),
        (P1_COM_LIFT,     P1_FIN_COMMON,   'Установка лифтов',              52, 14,  0, False, 'task',    '#6ee7b7'),
        (P1_COM_FLOOR,    P1_FIN_COMMON,   'Напольные покрытия коридоров',  58,  6,  0, False, 'task',    '#6ee7b7'),
        (P1_FIN_FLATS,    P1_PHASE_FINISH, 'Квартиры',                      55, 30,  0, True,  'project', '#34d399'),
        (P1_FLAT_PLAST,   P1_FIN_FLATS,    'Штукатурка стен',               55, 10,  0, False, 'task',    '#6ee7b7'),
        (P1_FLAT_FLOOR,   P1_FIN_FLATS,    'Стяжка пола',                   55,  8,  0, False, 'task',    '#6ee7b7'),
        (P1_FLAT_TILE,    P1_FIN_FLATS,    'Плитка в санузлах',             63,  8,  0, False, 'task',    '#6ee7b7'),
        (P1_FLAT_PAINT,   P1_FIN_FLATS,    'Покраска',                      71,  9,  0, False, 'task',    '#6ee7b7'),
        (P1_FIN_TERR,     P1_PHASE_FINISH, 'Территория',                    70, 15,  0, True,  'project', '#34d399'),
        (P1_TERR_CURB,    P1_FIN_TERR,     'Бортовой камень',               70,  4,  0, False, 'task',    '#6ee7b7'),
        (P1_TERR_ASPH,    P1_FIN_TERR,     'Асфальтирование',               74,  5,  0, False, 'task',    '#6ee7b7'),
        (P1_TERR_GREEN,   P1_FIN_TERR,     'Озеленение',                    78,  4,  0, False, 'task',    '#6ee7b7'),
        (P1_TERR_PLAY,    P1_FIN_TERR,     'Детская площадка',              80,  5,  0, False, 'task',    '#6ee7b7'),
        (P1_FIN_HANDOVER, P1_PHASE_FINISH, 'Сдача объекта',                 85,  8,  0, True,  'project', '#34d399'),
        (P1_HDO_INSPECT,  P1_FIN_HANDOVER, 'Комиссионный осмотр',           85,  3,  0, False, 'task',    '#6ee7b7'),
        (P1_HDO_DOCS,     P1_FIN_HANDOVER, 'Оформление документов',         88,  3,  0, False, 'task',    '#6ee7b7'),
        (P1_HDO_SIGN,     P1_FIN_HANDOVER, 'Подписание акта сдачи-приёмки', 91,  2,  0, False, 'milestone','#6ee7b7'),
    ]

    for i, row in enumerate(gantt_p1):
        tid, parent, name, offset, days, progress, is_group, gtype, color = row
        conn.execute(text("""
            INSERT INTO gantt_tasks
                (id, project_id, parent_id, name, start_date,
                 working_days, progress, is_group, type, color, row_order)
            VALUES (:id, :pid, :parent, :name, :start,
                    :days, :progress, :is_group, :type, :color, :order)
            ON CONFLICT (id) DO NOTHING
        """), {
            'id': tid, 'pid': PROJECT1_ID,
            'parent': parent if parent else None,
            'name': name,
            'start': TODAY + timedelta(days=offset),
            'days': days, 'progress': progress,
            'is_group': bool(is_group),
            'type': gtype, 'color': color,
            'order': (i + 1) * 100,
        })

    deps_p1 = [
        (P1_GEO_MARKS,    P1_GEO_SURVEY),
        (P1_FENCE_GATE,   P1_FENCE_INST),
        (P1_FENCE_LIGHT,  P1_FENCE_GATE),
        (P1_ROAD_GRAVEL,  P1_ROAD_PLAN),
        (P1_UTL_WATER,    P1_UTL_POWER),
        (P1_FOUND_EXCAV,  P1_PREP_UTILITY),
        (P1_EXC_BULK,     P1_EXC_STRIP),
        (P1_EXC_REFINE,   P1_EXC_BULK),
        (P1_FOUND_PILES,  P1_FOUND_EXCAV),
        (P1_PILE_POUR,    P1_PILE_DRILL),
        (P1_PILE_TEST,    P1_PILE_POUR),
        (P1_FOUND_RAFT,   P1_FOUND_PILES),
        (P1_RAFT_REBAR,   P1_RAFT_FORM),
        (P1_RAFT_POUR,    P1_RAFT_REBAR),
        (P1_RAFT_CURE,    P1_RAFT_POUR),
        (P1_FOUND_WATERP, P1_FOUND_RAFT),
        (P1_WP_COAT,      P1_WP_PREP),
        (P1_WP_PROTECT,   P1_WP_COAT),
        (P1_STRUCT_FRAME, P1_FOUND_WATERP),
        (P1_FRM_BEAM,     P1_FRM_COL),
        (P1_FRM_BRACE,    P1_FRM_BEAM),
        (P1_STRUCT_FLOOR1,P1_STRUCT_FRAME),
        (P1_FL1_REBAR,    P1_FL1_FORM),
        (P1_FL1_POUR,     P1_FL1_REBAR),
        (P1_STRUCT_FLOOR2,P1_STRUCT_FLOOR1),
        (P1_FL2_REBAR,    P1_FL2_FORM),
        (P1_FL2_POUR,     P1_FL2_REBAR),
        (P1_STRUCT_FLOOR3,P1_STRUCT_FLOOR2),
        (P1_FL3_REBAR,    P1_FL3_FORM),
        (P1_FL3_POUR,     P1_FL3_REBAR),
        (P1_STRUCT_STAIRS,P1_STRUCT_FLOOR1),
        (P1_ENV_ROOF,     P1_STRUCT_FLOOR3),
        (P1_ROOF_INSUL,   P1_ROOF_BASE),
        (P1_ROOF_MEMBR,   P1_ROOF_INSUL),
        (P1_ROOF_DRAIN,   P1_ROOF_MEMBR),
        (P1_ENV_FACADE,   P1_ENV_WINDOWS),
        (P1_FAC_PLASTER,  P1_FAC_INSUL),
        (P1_FAC_PAINT,    P1_FAC_PLASTER),
        (P1_WIN_GLASS,    P1_WIN_FRAME),
        (P1_WIN_SEAL,     P1_WIN_GLASS),
        (P1_ENV_ENTRANCE, P1_ENV_FACADE),
        (P1_MEP_HEAT,     P1_STRUCT_FLOOR1),
        (P1_HEAT_PIPES,   P1_HEAT_BOIL),
        (P1_HEAT_RAD,     P1_HEAT_PIPES),
        (P1_WAT_HOT,      P1_WAT_COLD),
        (P1_MEP_ELEC,     P1_STRUCT_FLOOR1),
        (P1_EL_DIST,      P1_EL_MAIN),
        (P1_EL_LIGHT,     P1_EL_DIST),
        (P1_EL_SOCKET,    P1_EL_LIGHT),
        (P1_VENT_UNIT,    P1_VENT_DUCT),
        (P1_FIRE_SPRINK,  P1_FIRE_DET),
        (P1_FIN_COMMON,   P1_PHASE_MEP),
        (P1_COM_LIFT,     P1_COM_LOBBY),
        (P1_COM_FLOOR,    P1_COM_LOBBY),
        (P1_FIN_FLATS,    P1_PHASE_MEP),
        (P1_FLAT_FLOOR,   P1_FLAT_PLAST),
        (P1_FLAT_TILE,    P1_FLAT_FLOOR),
        (P1_FLAT_PAINT,   P1_FLAT_TILE),
        (P1_FIN_TERR,     P1_PHASE_ENVELOP),
        (P1_TERR_ASPH,    P1_TERR_CURB),
        (P1_TERR_GREEN,   P1_TERR_ASPH),
        (P1_TERR_PLAY,    P1_TERR_GREEN),
        (P1_FIN_HANDOVER, P1_FIN_COMMON),
        (P1_FIN_HANDOVER, P1_FIN_FLATS),
        (P1_FIN_HANDOVER, P1_FIN_TERR),
        (P1_HDO_DOCS,     P1_HDO_INSPECT),
        (P1_HDO_SIGN,     P1_HDO_DOCS),
    ]
    for task_id, depends_on in deps_p1:
        conn.execute(text("""
            INSERT INTO task_dependencies (task_id, depends_on)
            VALUES (:t, :d) ON CONFLICT DO NOTHING
        """), {'t': task_id, 'd': depends_on})

    # ─── Задачи Ганта проекта 2 ───────────────────────────────────────────────
    gantt_p2 = [
        (P2_PHASE_DEMO,   None,            'Демонтаж',                    -20, 12,  0, True,  'project', '#ef4444'),
        (P2_DEMO_ASPH,    P2_PHASE_DEMO,   'Демонтаж асфальта и покрытий',-20,  4,100, False, 'task',    '#fca5a5'),
        (P2_DEMO_STRUCT,  P2_PHASE_DEMO,   'Снос старых конструкций',     -16,  6, 80, False, 'task',    '#fca5a5'),
        (P2_DEMO_UTIL,    P2_PHASE_DEMO,   'Демонтаж коммуникаций',       -14,  4, 60, False, 'task',    '#fca5a5'),

        (P2_PHASE_FOUND,  None,            'Фундамент',                    -8, 20,  0, True,  'project', '#f59e0b'),
        (P2_FND_PILE,     P2_PHASE_FOUND,  'Свайное поле',                 -8, 10, 20, False, 'task',    '#fde68a'),
        (P2_FND_SLAB,     P2_PHASE_FOUND,  'Монолитная плита',              3, 10,  0, False, 'task',    '#fde68a'),

        (P2_PHASE_STRUCT, None,            'Конструкции',                  14, 35,  0, True,  'project', '#8b5cf6'),
        (P2_STR_COL,      P2_PHASE_STRUCT, 'Колонны и несущие стены',      14, 10,  0, False, 'task',    '#c4b5fd'),
        (P2_STR_FLOOR1,   P2_PHASE_STRUCT, 'Перекрытие торгового зала',    25, 12,  0, False, 'task',    '#c4b5fd'),
        (P2_STR_FLOOR2,   P2_PHASE_STRUCT, 'Перекрытие 2-го уровня',       38, 12,  0, False, 'task',    '#c4b5fd'),
        (P2_STR_ROOF,     P2_PHASE_STRUCT, 'Кровельные конструкции',        51, 10,  0, False, 'task',    '#c4b5fd'),

        (P2_PHASE_MEP,    None,            'Инженерные системы',            50, 40,  0, True,  'project', '#0ea5e9'),
        (P2_MEP_HVAC,     P2_PHASE_MEP,    'Вентиляция и климат',           50, 20,  0, False, 'task',    '#7dd3fc'),
        (P2_MEP_ELEC,     P2_PHASE_MEP,    'Электроснабжение',              52, 18,  0, False, 'task',    '#7dd3fc'),
        (P2_MEP_FIRE,     P2_PHASE_MEP,    'Противопожарные системы',       55, 15,  0, False, 'task',    '#7dd3fc'),
        (P2_MEP_IT,       P2_PHASE_MEP,    'Слаботочные системы и IT',      60, 12,  0, False, 'task',    '#7dd3fc'),

        (P2_PHASE_FINISH, None,            'Отделка и открытие',            75, 35,  0, True,  'project', '#10b981'),
        (P2_FIN_FLOOR,    P2_PHASE_FINISH, 'Напольные покрытия',            75, 14,  0, False, 'task',    '#6ee7b7'),
        (P2_FIN_WALLS,    P2_PHASE_FINISH, 'Отделка стен',                  78, 14,  0, False, 'task',    '#6ee7b7'),
        (P2_FIN_FACADE,   P2_PHASE_FINISH, 'Фасадное остекление',           72, 18,  0, False, 'task',    '#6ee7b7'),
        (P2_FIN_SIGNAGE,  P2_PHASE_FINISH, 'Вывески и навигация',           90,  8,  0, False, 'milestone','#6ee7b7'),
    ]

    for i, row in enumerate(gantt_p2):
        tid, parent, name, offset, days, progress, is_group, gtype, color = row
        conn.execute(text("""
            INSERT INTO gantt_tasks
                (id, project_id, parent_id, name, start_date,
                 working_days, progress, is_group, type, color, row_order)
            VALUES (:id, :pid, :parent, :name, :start,
                    :days, :progress, :is_group, :type, :color, :order)
            ON CONFLICT (id) DO NOTHING
        """), {
            'id': tid, 'pid': PROJECT2_ID,
            'parent': parent if parent else None,
            'name': name,
            'start': TODAY + timedelta(days=offset),
            'days': days, 'progress': progress,
            'is_group': bool(is_group),
            'type': gtype, 'color': color,
            'order': (i + 1) * 100,
        })

    deps_p2 = [
        (P2_DEMO_STRUCT,  P2_DEMO_ASPH),
        (P2_DEMO_UTIL,    P2_DEMO_ASPH),
        (P2_PHASE_FOUND,  P2_PHASE_DEMO),
        (P2_FND_SLAB,     P2_FND_PILE),
        (P2_PHASE_STRUCT, P2_PHASE_FOUND),
        (P2_STR_FLOOR1,   P2_STR_COL),
        (P2_STR_FLOOR2,   P2_STR_FLOOR1),
        (P2_STR_ROOF,     P2_STR_FLOOR2),
        (P2_PHASE_MEP,    P2_STR_FLOOR1),
        (P2_MEP_FIRE,     P2_MEP_HVAC),
        (P2_MEP_IT,       P2_MEP_ELEC),
        (P2_PHASE_FINISH, P2_PHASE_MEP),
        (P2_FIN_WALLS,    P2_FIN_FLOOR),
        (P2_FIN_SIGNAGE,  P2_FIN_FACADE),
        (P2_FIN_SIGNAGE,  P2_FIN_WALLS),
    ]
    for task_id, depends_on in deps_p2:
        conn.execute(text("""
            INSERT INTO task_dependencies (task_id, depends_on)
            VALUES (:t, :d) ON CONFLICT DO NOTHING
        """), {'t': task_id, 'd': depends_on})

    # ─── Материалы проекта 1 ──────────────────────────────────────────────────
    materials = [
        (P1_FRM_BEAM,   'Металлопрокат HEA 200',           'т',    28, 'major', 'ordered',  7,  TODAY - timedelta(days=3)),
        (P1_FRM_BRACE,  'Уголок 100×100×10',               'т',     8, 'major', 'ordered',  7,  TODAY + timedelta(days=2)),
        (P1_FL1_POUR,   'Арматура А500С d16',               'т',    18, 'major', 'planned',  5,  TODAY + timedelta(days=4)),
        (P1_FL1_POUR,   'Бетон B25 W6',                    'м³',  210, 'major', 'planned',  3,  TODAY + timedelta(days=6)),
        (P1_FL2_FORM,   'Опалубка щитовая (аренда)',        'м²',  820, 'major', 'planned',  2,  TODAY + timedelta(days=8)),
        (P1_ROOF_INSUL, 'Плиты PIR 150мм',                 'м²',  850, 'major', 'planned', 14,  TODAY + timedelta(days=20)),
        (P1_ROOF_MEMBR, 'Мембрана ПВХ Logicroof V-RP',     'м²',  880, 'major', 'planned', 14,  TODAY + timedelta(days=24)),
        (P1_FAC_INSUL,  'Минвата фасадная 150мм',          'м²', 1680, 'major', 'planned', 21,  TODAY + timedelta(days=28)),
        (P1_WIN_FRAME,  'Оконные блоки ПВХ REHAU',         'шт',   96, 'major', 'planned', 30,  TODAY + timedelta(days=22)),
        (P1_HEAT_BOIL,  'Котёл газовый Viessmann 200кВт',  'шт',    2, 'major', 'planned', 60,  TODAY + timedelta(days=30)),
        (P1_EL_MAIN,    'Кабель ВВГнг-LS 4×35',            'м',  2400, 'major', 'planned', 14,  TODAY + timedelta(days=36)),
        (P1_COM_LIFT,   'Лифт пассажирский Otis 630кг',    'шт',    2, 'major', 'planned', 90,  TODAY + timedelta(days=58)),
        (P1_FLAT_TILE,  'Плитка керамическая 300×600',     'м²',  400, 'small', 'planned',  7,  TODAY + timedelta(days=70)),
        (P1_TERR_ASPH,  'Асфальт горячий м/з',             'т',   180, 'major', 'planned',  5,  TODAY + timedelta(days=80)),
    ]
    for tid, name, unit, qty, mtype, status, lead, delivery in materials:
        conn.execute(text("""
            INSERT INTO materials (id, project_id, task_id, name, unit, quantity,
                type, status, lead_days, delivery_date)
            VALUES (gen_random_uuid(), :pid, :tid, :name, :unit, :qty,
                :type, :status, :lead, :delivery)
        """), {
            'pid': PROJECT1_ID, 'tid': tid, 'name': name,
            'unit': unit, 'qty': qty, 'type': mtype,
            'status': status, 'lead': lead, 'delivery': delivery,
        })

    # ─── Праздники РФ ─────────────────────────────────────────────────────────
    holidays_ru = [
        (date(2025, 1, 1),  'Новый год'),
        (date(2025, 1, 2),  'Новогодние каникулы'),
        (date(2025, 1, 7),  'Рождество'),
        (date(2025, 2, 23), 'День защитника Отечества'),
        (date(2025, 3, 8),  'Международный женский день'),
        (date(2025, 5, 1),  'Праздник Весны и Труда'),
        (date(2025, 5, 9),  'День Победы'),
        (date(2025, 6, 12), 'День России'),
        (date(2025, 11, 4), 'День народного единства'),
        (date(2026, 1, 1),  'Новый год'),
        (date(2026, 1, 7),  'Рождество'),
        (date(2026, 2, 23), 'День защитника Отечества'),
        (date(2026, 3, 9),  'Международный женский день (перенос)'),
        (date(2026, 5, 1),  'Праздник Весны и Труда'),
        (date(2026, 5, 11), 'День Победы (перенос)'),
        (date(2026, 6, 12), 'День России'),
        (date(2026, 11, 4), 'День народного единства'),
    ]
    for hdate, hname in holidays_ru:
        conn.execute(text("""
            INSERT INTO holidays (date, name, country)
            VALUES (:d, :n, 'RU') ON CONFLICT DO NOTHING
        """), {'d': hdate, 'n': hname})

    print("\n✅ Тестовые данные созданы:")
    print("   Логин:  test@test.local")
    print("   Пароль: test123")
    print(f"   Задач ЖК «Сосновый бор»: {len(gantt_p1)} (3 уровня вложенности)")
    print(f"   Задач ТЦ «Меркурий»:     {len(gantt_p2)} (2 уровня вложенности)\n")


def downgrade():
    conn = op.get_bind()

    all_task_ids = [
        P1_PHASE_PREP, P1_PREP_GEODESY, P1_GEO_SURVEY, P1_GEO_MARKS,
        P1_PREP_FENCE, P1_FENCE_INST, P1_FENCE_GATE, P1_FENCE_LIGHT,
        P1_PREP_ROADS, P1_ROAD_PLAN, P1_ROAD_GRAVEL,
        P1_PREP_UTILITY, P1_UTL_POWER, P1_UTL_WATER,
        P1_PHASE_FOUND, P1_FOUND_EXCAV, P1_EXC_STRIP, P1_EXC_BULK, P1_EXC_REFINE,
        P1_FOUND_PILES, P1_PILE_DRILL, P1_PILE_POUR, P1_PILE_TEST,
        P1_FOUND_RAFT, P1_RAFT_FORM, P1_RAFT_REBAR, P1_RAFT_POUR, P1_RAFT_CURE,
        P1_FOUND_WATERP, P1_WP_PREP, P1_WP_COAT, P1_WP_PROTECT,
        P1_PHASE_STRUCT, P1_STRUCT_FRAME, P1_FRM_COL, P1_FRM_BEAM, P1_FRM_BRACE,
        P1_STRUCT_FLOOR1, P1_FL1_FORM, P1_FL1_REBAR, P1_FL1_POUR,
        P1_STRUCT_FLOOR2, P1_FL2_FORM, P1_FL2_REBAR, P1_FL2_POUR,
        P1_STRUCT_FLOOR3, P1_FL3_FORM, P1_FL3_REBAR, P1_FL3_POUR,
        P1_STRUCT_STAIRS,
        P1_PHASE_ENVELOP, P1_ENV_ROOF,
        P1_ROOF_BASE, P1_ROOF_INSUL, P1_ROOF_MEMBR, P1_ROOF_DRAIN,
        P1_ENV_FACADE, P1_FAC_INSUL, P1_FAC_PLASTER, P1_FAC_PAINT,
        P1_ENV_WINDOWS, P1_WIN_FRAME, P1_WIN_GLASS, P1_WIN_SEAL, P1_ENV_ENTRANCE,
        P1_PHASE_MEP,
        P1_MEP_HEAT, P1_HEAT_BOIL, P1_HEAT_PIPES, P1_HEAT_RAD,
        P1_MEP_WATER, P1_WAT_COLD, P1_WAT_HOT, P1_WAT_DRAIN,
        P1_MEP_ELEC, P1_EL_MAIN, P1_EL_DIST, P1_EL_LIGHT, P1_EL_SOCKET,
        P1_MEP_VENT, P1_VENT_DUCT, P1_VENT_UNIT,
        P1_MEP_FIRE, P1_FIRE_DET, P1_FIRE_SPRINK,
        P1_PHASE_FINISH,
        P1_FIN_COMMON, P1_COM_LOBBY, P1_COM_LIFT, P1_COM_FLOOR,
        P1_FIN_FLATS, P1_FLAT_PLAST, P1_FLAT_FLOOR, P1_FLAT_TILE, P1_FLAT_PAINT,
        P1_FIN_TERR, P1_TERR_CURB, P1_TERR_ASPH, P1_TERR_GREEN, P1_TERR_PLAY,
        P1_FIN_HANDOVER, P1_HDO_INSPECT, P1_HDO_DOCS, P1_HDO_SIGN,
        P2_PHASE_DEMO, P2_DEMO_ASPH, P2_DEMO_STRUCT, P2_DEMO_UTIL,
        P2_PHASE_FOUND, P2_FND_PILE, P2_FND_SLAB,
        P2_PHASE_STRUCT, P2_STR_COL, P2_STR_FLOOR1, P2_STR_FLOOR2, P2_STR_ROOF,
        P2_PHASE_MEP, P2_MEP_HVAC, P2_MEP_ELEC, P2_MEP_FIRE, P2_MEP_IT,
        P2_PHASE_FINISH, P2_FIN_FLOOR, P2_FIN_WALLS, P2_FIN_FACADE, P2_FIN_SIGNAGE,
    ]

    ids_str = ','.join(f"'{t}'" for t in all_task_ids)
    conn.execute(text(
        f"DELETE FROM task_dependencies WHERE task_id IN ({ids_str}) OR depends_on IN ({ids_str})"
    ))
    conn.execute(text(f"DELETE FROM gantt_tasks      WHERE id         IN ({ids_str})"))
    conn.execute(text("DELETE FROM materials          WHERE project_id IN (:p1,:p2)"),
                 {'p1': PROJECT1_ID, 'p2': PROJECT2_ID})
    conn.execute(text("DELETE FROM estimates           WHERE project_id IN (:p1,:p2)"),
                 {'p1': PROJECT1_ID, 'p2': PROJECT2_ID})
    conn.execute(text("DELETE FROM project_members     WHERE project_id IN (:p1,:p2)"),
                 {'p1': PROJECT1_ID, 'p2': PROJECT2_ID})
    conn.execute(text("DELETE FROM projects             WHERE id         IN (:p1,:p2)"),
                 {'p1': PROJECT1_ID, 'p2': PROJECT2_ID})
    conn.execute(text("DELETE FROM users                WHERE id = :id"), {'id': USER_ID})
    conn.execute(text("DELETE FROM organizations        WHERE id = :id"), {'id': ORG_ID})
