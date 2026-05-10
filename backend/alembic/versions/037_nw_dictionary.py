"""
037_nw_dictionary.py
Справочник нормализованных видов работ (NW).

Иерархия:
  fer.nw_work_type   — верхний уровень (11 типов: WT-01..WT-11)
    └─ fer.nw_item   — нормализованные виды работ (87 записей: NW-001..NW-087)

Атрибуты NW (массивы кодов):
  fer.nw_object_type            — типы объектов  (OT-01..OT-12)
  fer.nw_building_technology    — технология здания (BT-01..BT-06)
  fer.nw_location_scope         — зона выполнения работ (LS-01..LS-11)
  fer.nw_stage                  — этапы для КТП (ST-01..ST-12)
  fer.nw_repair_class           — классы ремонта (none/current/capital/reconstruction)

Перенесено из «Нормализация_видов_работ_v5» (09.05.2026).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "037_nw_dictionary"
down_revision = "036_ktp_groups_and_cards"
branch_labels = None
depends_on = None

FER_SCHEMA = "fer"


# ───────────── seed data ─────────────

NW_WORK_TYPES = [
    {"code": "WT-01", "name": "Земляные", "description": "Грунт, котлованы, траншеи, насыпи, обратная засыпка, уплотнение.", "sort_order": 1},
    {"code": "WT-02", "name": "Демонтажные", "description": "Снос, разборка, демонтаж конструкций, покрытий и инженерных систем.", "sort_order": 2},
    {"code": "WT-03", "name": "Фундаментные", "description": "Основания и фундаменты: опалубка, армирование, бетонирование, гидроизоляция.", "sort_order": 3},
    {"code": "WT-04", "name": "Строительство зданий", "description": "Возведение жилых и нежилых зданий без детализации по технологии материала.", "sort_order": 4},
    {"code": "WT-05", "name": "Ремонт и отделка", "description": "Ремонт помещений/зданий, черновые и чистовые отделочные работы.", "sort_order": 5},
    {"code": "WT-06", "name": "Реконструкция", "description": "Изменение параметров здания, усиление/замена несущих конструкций, пристройки и надстройки.", "sort_order": 6},
    {"code": "WT-07", "name": "Внутренняя инженерия", "description": "Системы внутри здания/помещений.", "sort_order": 7},
    {"code": "WT-08", "name": "Наружная инженерия", "description": "Сети и инженерные сооружения вне здания.", "sort_order": 8},
    {"code": "WT-09", "name": "Кровельные", "description": "Кровля, стропила, утепление, водостоки, ремонт кровли.", "sort_order": 9},
    {"code": "WT-10", "name": "Фасадные", "description": "Фасад, утепление, облицовка, штукатурка, ремонт фасада.", "sort_order": 10},
    {"code": "WT-11", "name": "Ландшафт и благоустройство", "description": "Дренаж участка, мощение, озеленение, МАФ, водоемы.", "sort_order": 11},
]

NW_OBJECT_TYPES = [
    {"code": "OT-01", "name": "Жилое здание / ИЖС", "sort_order": 1},
    {"code": "OT-02", "name": "Квартира в новостройке", "sort_order": 2},
    {"code": "OT-03", "name": "Квартира вторичного фонда", "sort_order": 3},
    {"code": "OT-04", "name": "Нежилое промышленное здание", "sort_order": 4},
    {"code": "OT-05", "name": "Коммерческое / торгово-офисное помещение", "sort_order": 5},
    {"code": "OT-06", "name": "Склад / логистический центр", "sort_order": 6},
    {"code": "OT-07", "name": "Общественно-социальный объект", "sort_order": 7},
    {"code": "OT-08", "name": "Гостиничный объект", "sort_order": 8},
    {"code": "OT-09", "name": "Транспортно-гаражный объект", "sort_order": 9},
    {"code": "OT-10", "name": "Земельный участок / территория", "sort_order": 10},
    {"code": "OT-11", "name": "Инженерная трасса / сеть", "sort_order": 11},
    {"code": "OT-12", "name": "Здание любого назначения", "sort_order": 12},
]

NW_BUILDING_TECH = [
    {"code": "BT-01", "name": "Каркас / каркасно-щитовая технология", "sort_order": 1},
    {"code": "BT-02", "name": "СИП-панели", "sort_order": 2},
    {"code": "BT-03", "name": "Брус / бревно", "sort_order": 3},
    {"code": "BT-04", "name": "Пеноблок / газоблок", "sort_order": 4},
    {"code": "BT-05", "name": "Кирпич", "sort_order": 5},
    {"code": "BT-06", "name": "Монолит", "sort_order": 6},
]

NW_LOCATION_SCOPES = [
    {"code": "LS-01", "name": "Участок / территория", "sort_order": 1},
    {"code": "LS-02", "name": "Здание целиком", "sort_order": 2},
    {"code": "LS-03", "name": "Помещение / внутренняя зона", "sort_order": 3},
    {"code": "LS-04", "name": "Внутренние сети", "sort_order": 4},
    {"code": "LS-05", "name": "Наружные сети", "sort_order": 5},
    {"code": "LS-06", "name": "Трасса инженерных сетей", "sort_order": 6},
    {"code": "LS-07", "name": "Кровля", "sort_order": 7},
    {"code": "LS-08", "name": "Фасад", "sort_order": 8},
    {"code": "LS-09", "name": "Фундамент / основание", "sort_order": 9},
    {"code": "LS-10", "name": "Несущие конструкции", "sort_order": 10},
    {"code": "LS-11", "name": "Прилегающая территория / благоустройство", "sort_order": 11},
]

NW_STAGES = [
    {"code": "ST-01", "name": "Обмеры / проектирование / обследование", "sort_order": 1},
    {"code": "ST-02", "name": "Подготовка площадки / помещения", "sort_order": 2},
    {"code": "ST-03", "name": "Демонтаж", "sort_order": 3},
    {"code": "ST-04", "name": "Земляные работы", "sort_order": 4},
    {"code": "ST-05", "name": "Основание и фундамент", "sort_order": 5},
    {"code": "ST-06", "name": "Несущие конструкции / коробка", "sort_order": 6},
    {"code": "ST-07", "name": "Оболочка здания: кровля и фасад", "sort_order": 7},
    {"code": "ST-08", "name": "Инженерный монтаж", "sort_order": 8},
    {"code": "ST-09", "name": "Черновая отделка", "sort_order": 9},
    {"code": "ST-10", "name": "Чистовая отделка", "sort_order": 10},
    {"code": "ST-11", "name": "Пусконаладка / испытания", "sort_order": 11},
    {"code": "ST-12", "name": "Благоустройство / сдача", "sort_order": 12},
]

NW_REPAIR_CLASSES = [
    {"code": "none", "description": "Не ремонтная работа", "sort_order": 1},
    {"code": "current", "description": "Текущий ремонт: восстановление/обновление без изменения ключевых параметров и несущей схемы.", "sort_order": 2},
    {"code": "capital", "description": "Капитальный ремонт: замена/восстановление конструктивных элементов или инженерных систем без перевода в реконструкцию.", "sort_order": 3},
    {"code": "reconstruction", "description": "Реконструкция: изменение параметров объекта или работа с несущими конструкциями, требующая отдельной проверки.", "sort_order": 4},
]

NW_ITEMS = [
    {"code": "NW-001", "unique_label": "Земляные: подготовка строительной площадки", "work_type_code": "WT-01", "subtype": "Подготовка площадки", "object_type_codes": ["OT-10"], "building_technology_codes": [], "location_scope_codes": ["LS-01"], "stage_codes": ["ST-02"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Не путать с подготовкой трасс инженерных сетей и ландшафтной очисткой.", "sort_order": 1},
    {"code": "NW-002", "unique_label": "Земляные: снятие растительного слоя", "work_type_code": "WT-01", "subtype": "Срезка растительного слоя", "object_type_codes": ["OT-10"], "building_technology_codes": [], "location_scope_codes": ["LS-01"], "stage_codes": ["ST-04"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Грунтовая подготовка перед строительством.", "sort_order": 2},
    {"code": "NW-003", "unique_label": "Земляные: разработка котлована", "work_type_code": "WT-01", "subtype": "Котлован", "object_type_codes": ["OT-10", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-01", "LS-09"], "stage_codes": ["ST-04"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Котлован под фундамент/подземную часть.", "sort_order": 3},
    {"code": "NW-004", "unique_label": "Земляные: разработка траншей под сети", "work_type_code": "WT-01", "subtype": "Траншеи", "object_type_codes": ["OT-11"], "building_technology_codes": [], "location_scope_codes": ["LS-06"], "stage_codes": ["ST-04"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Земляная часть траншей, не монтаж труб/кабеля.", "sort_order": 4},
    {"code": "NW-005", "unique_label": "Земляные: планировка грунта до отметок", "work_type_code": "WT-01", "subtype": "Планировка грунта", "object_type_codes": ["OT-10"], "building_technology_codes": [], "location_scope_codes": ["LS-01"], "stage_codes": ["ST-04"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Срезка/подсыпка до проектных отметок.", "sort_order": 5},
    {"code": "NW-006", "unique_label": "Земляные: устройство насыпей и дамб", "work_type_code": "WT-01", "subtype": "Насыпи и дамбы", "object_type_codes": ["OT-10"], "building_technology_codes": [], "location_scope_codes": ["LS-01"], "stage_codes": ["ST-04"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Искусственные грунтовые сооружения.", "sort_order": 6},
    {"code": "NW-007", "unique_label": "Земляные: обратная засыпка пазух", "work_type_code": "WT-01", "subtype": "Обратная засыпка", "object_type_codes": ["OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-09"], "stage_codes": ["ST-04"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Засыпка вокруг фундамента/стен котлована.", "sort_order": 7},
    {"code": "NW-008", "unique_label": "Земляные: уплотнение основания", "work_type_code": "WT-01", "subtype": "Уплотнение основания", "object_type_codes": ["OT-10", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-09"], "stage_codes": ["ST-04"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Подготовка несущего основания.", "sort_order": 8},
    {"code": "NW-009", "unique_label": "Земляные: водопонижение и крепление откосов", "work_type_code": "WT-01", "subtype": "Водопонижение и откосы", "object_type_codes": ["OT-10", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-01", "LS-09"], "stage_codes": ["ST-04"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Отвод грунтовых вод и устойчивость откосов.", "sort_order": 9},
    {"code": "NW-010", "unique_label": "Земляные: вывоз лишнего грунта", "work_type_code": "WT-01", "subtype": "Вывоз грунта", "object_type_codes": ["OT-10"], "building_technology_codes": [], "location_scope_codes": ["LS-01"], "stage_codes": ["ST-04"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Грунт после разработки, не строительный мусор.", "sort_order": 10},
    {"code": "NW-011", "unique_label": "Демонтаж: снос строений на участке", "work_type_code": "WT-02", "subtype": "Снос строений", "object_type_codes": ["OT-10", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-01", "LS-02"], "stage_codes": ["ST-03"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": True, "notes": "Может быть отдельным договором до строительства.", "sort_order": 11},
    {"code": "NW-012", "unique_label": "Демонтаж: разборка внутренних перегородок", "work_type_code": "WT-02", "subtype": "Внутренний демонтаж", "object_type_codes": ["OT-02", "OT-03", "OT-05"], "building_technology_codes": [], "location_scope_codes": ["LS-03", "LS-10"], "stage_codes": ["ST-03"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": True, "notes": "Нужна проверка, если затрагиваются несущие конструкции. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 12},
    {"code": "NW-013", "unique_label": "Демонтаж: снятие старых инженерных сетей", "work_type_code": "WT-02", "subtype": "Демонтаж инженерии", "object_type_codes": ["OT-02", "OT-03", "OT-05", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-04"], "stage_codes": ["ST-03"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Перед заменой внутренних систем. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 13},
    {"code": "NW-014", "unique_label": "Демонтаж: разборка старой кровли", "work_type_code": "WT-02", "subtype": "Демонтаж кровли", "object_type_codes": ["OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-07"], "stage_codes": ["ST-03"], "repair_class_codes": ["capital"], "is_capital_repair": True, "requires_permit_review": False, "notes": "Отдельно от устройства новой кровли.", "sort_order": 14},
    {"code": "NW-015", "unique_label": "Демонтаж: вывоз строительного мусора", "work_type_code": "WT-02", "subtype": "Вывоз мусора", "object_type_codes": ["OT-02", "OT-03", "OT-05", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-01", "LS-03"], "stage_codes": ["ST-03"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Не смешивать с вывозом грунта.", "sort_order": 15},
    {"code": "NW-016", "unique_label": "Фундаменты: устройство основания под фундамент", "work_type_code": "WT-03", "subtype": "Основание под фундамент", "object_type_codes": ["OT-12"], "building_technology_codes": ["BT-01", "BT-02", "BT-03", "BT-04", "BT-05", "BT-06"], "location_scope_codes": ["LS-09"], "stage_codes": ["ST-05"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Подготовка основания после земляных работ.", "sort_order": 16},
    {"code": "NW-017", "unique_label": "Фундаменты: опалубка и армирование", "work_type_code": "WT-03", "subtype": "Опалубка и армирование", "object_type_codes": ["OT-12"], "building_technology_codes": ["BT-04", "BT-05", "BT-06"], "location_scope_codes": ["LS-09"], "stage_codes": ["ST-05"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Для монолитных/железобетонных элементов.", "sort_order": 17},
    {"code": "NW-018", "unique_label": "Фундаменты: бетонирование фундамента", "work_type_code": "WT-03", "subtype": "Бетонирование фундамента", "object_type_codes": ["OT-12"], "building_technology_codes": ["BT-04", "BT-05", "BT-06"], "location_scope_codes": ["LS-09"], "stage_codes": ["ST-05"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Не земляные работы, отдельный строительный процесс.", "sort_order": 18},
    {"code": "NW-019", "unique_label": "Фундаменты: гидроизоляция фундамента", "work_type_code": "WT-03", "subtype": "Гидроизоляция фундамента", "object_type_codes": ["OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-09"], "stage_codes": ["ST-05"], "repair_class_codes": ["none", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Новое строительство или капремонт; уточнять при классификации.", "sort_order": 19},
    {"code": "NW-020", "unique_label": "Фундаменты: утепление и защита фундамента", "work_type_code": "WT-03", "subtype": "Утепление/защита фундамента", "object_type_codes": ["OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-09"], "stage_codes": ["ST-05"], "repair_class_codes": ["none", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Новое строительство или капремонт; уточнять при классификации.", "sort_order": 20},
    {"code": "NW-021", "unique_label": "Строительство: строительство жилого дома", "work_type_code": "WT-04", "subtype": "Жилой дом", "object_type_codes": ["OT-01"], "building_technology_codes": ["BT-01", "BT-02", "BT-03", "BT-04", "BT-05", "BT-06"], "location_scope_codes": ["LS-02"], "stage_codes": ["ST-06"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": True, "notes": "Технология хранится отдельно, не создает новые строки.", "sort_order": 21},
    {"code": "NW-022", "unique_label": "Строительство: строительство нежилого здания", "work_type_code": "WT-04", "subtype": "Нежилое здание", "object_type_codes": ["OT-04", "OT-05", "OT-06", "OT-07", "OT-08", "OT-09"], "building_technology_codes": ["BT-01", "BT-04", "BT-05", "BT-06"], "location_scope_codes": ["LS-02"], "stage_codes": ["ST-06"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": True, "notes": "Тип нежилого объекта хранится в object_type.", "sort_order": 22},
    {"code": "NW-023", "unique_label": "Строительство: монтаж несущего каркаса", "work_type_code": "WT-04", "subtype": "Несущий каркас", "object_type_codes": ["OT-01", "OT-04", "OT-05", "OT-06"], "building_technology_codes": ["BT-01", "BT-06"], "location_scope_codes": ["LS-10"], "stage_codes": ["ST-06"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": True, "notes": "Несущая система здания.", "sort_order": 23},
    {"code": "NW-024", "unique_label": "Строительство: возведение наружных стен", "work_type_code": "WT-04", "subtype": "Наружные стены", "object_type_codes": ["OT-01", "OT-12"], "building_technology_codes": ["BT-03", "BT-04", "BT-05", "BT-06"], "location_scope_codes": ["LS-10", "LS-08"], "stage_codes": ["ST-06"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Материал стены в building_technology/материальном атрибуте.", "sort_order": 24},
    {"code": "NW-025", "unique_label": "Строительство: устройство перекрытий", "work_type_code": "WT-04", "subtype": "Перекрытия", "object_type_codes": ["OT-01", "OT-12"], "building_technology_codes": ["BT-04", "BT-05", "BT-06"], "location_scope_codes": ["LS-10"], "stage_codes": ["ST-06"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": True, "notes": "Несущие элементы.", "sort_order": 25},
    {"code": "NW-026", "unique_label": "Строительство: монтаж внутренних перегородок", "work_type_code": "WT-04", "subtype": "Перегородки", "object_type_codes": ["OT-01", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-03"], "stage_codes": ["ST-06"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Не путать с демонтажом перегородок.", "sort_order": 26},
    {"code": "NW-027", "unique_label": "Ремонт: ремонт квартиры", "work_type_code": "WT-05", "subtype": "Ремонт квартиры", "object_type_codes": ["OT-02", "OT-03"], "building_technology_codes": [], "location_scope_codes": ["LS-03"], "stage_codes": ["ST-09", "ST-10"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Новостройка/вторичка хранится в object_type. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 27},
    {"code": "NW-028", "unique_label": "Ремонт: ремонт жилого дома", "work_type_code": "WT-05", "subtype": "Ремонт жилого дома", "object_type_codes": ["OT-01"], "building_technology_codes": ["BT-01", "BT-02", "BT-03", "BT-04", "BT-05", "BT-06"], "location_scope_codes": ["LS-02", "LS-03"], "stage_codes": ["ST-09", "ST-10"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Технология дома отдельным атрибутом. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 28},
    {"code": "NW-029", "unique_label": "Ремонт: ремонт нежилого помещения", "work_type_code": "WT-05", "subtype": "Ремонт нежилого помещения", "object_type_codes": ["OT-05", "OT-06", "OT-07", "OT-08", "OT-09"], "building_technology_codes": [], "location_scope_codes": ["LS-03"], "stage_codes": ["ST-09", "ST-10"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Тип нежилого помещения хранится в object_type. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 29},
    {"code": "NW-030", "unique_label": "Ремонт: черновая отделка", "work_type_code": "WT-05", "subtype": "Черновая отделка", "object_type_codes": ["OT-02", "OT-03", "OT-05", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-03"], "stage_codes": ["ST-09"], "repair_class_codes": ["current"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Штукатурка, стяжка, подготовка оснований и т.п.", "sort_order": 30},
    {"code": "NW-031", "unique_label": "Ремонт: чистовая отделка", "work_type_code": "WT-05", "subtype": "Чистовая отделка", "object_type_codes": ["OT-02", "OT-03", "OT-05", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-03"], "stage_codes": ["ST-10"], "repair_class_codes": ["current"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Плитка, покраска, покрытия, финишные работы.", "sort_order": 31},
    {"code": "NW-032", "unique_label": "Ремонт: устройство и ремонт полов", "work_type_code": "WT-05", "subtype": "Полы", "object_type_codes": ["OT-02", "OT-03", "OT-05", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-03"], "stage_codes": ["ST-09", "ST-10"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Черновые и чистовые процессы различать stage. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 32},
    {"code": "NW-033", "unique_label": "Ремонт: ремонт потолков", "work_type_code": "WT-05", "subtype": "Потолки", "object_type_codes": ["OT-02", "OT-03", "OT-05", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-03"], "stage_codes": ["ST-10"], "repair_class_codes": ["current"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Отделочный ремонт.", "sort_order": 33},
    {"code": "NW-034", "unique_label": "Ремонт: ремонт стен", "work_type_code": "WT-05", "subtype": "Стены", "object_type_codes": ["OT-02", "OT-03", "OT-05", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-03"], "stage_codes": ["ST-09", "ST-10"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": True, "notes": "Если несущие стены - проверка разрешений. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 34},
    {"code": "NW-035", "unique_label": "Ремонт: капитальный ремонт конструкций", "work_type_code": "WT-05", "subtype": "Капремонт конструкций", "object_type_codes": ["OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-10"], "stage_codes": ["ST-06"], "repair_class_codes": ["capital"], "is_capital_repair": True, "requires_permit_review": True, "notes": "Отдельно от реконструкции, но требует проверки.", "sort_order": 35},
    {"code": "NW-036", "unique_label": "Ремонт: текущий косметический ремонт", "work_type_code": "WT-05", "subtype": "Косметический ремонт", "object_type_codes": ["OT-02", "OT-03", "OT-05"], "building_technology_codes": [], "location_scope_codes": ["LS-03"], "stage_codes": ["ST-10"], "repair_class_codes": ["current"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Быстрые работы без изменения конструкций.", "sort_order": 36},
    {"code": "NW-037", "unique_label": "Реконструкция: изменение площади здания", "work_type_code": "WT-06", "subtype": "Изменение площади", "object_type_codes": ["OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-02"], "stage_codes": ["ST-06"], "repair_class_codes": ["reconstruction"], "is_capital_repair": None, "requires_permit_review": True, "notes": "Общая запись: меняется площадь без способа. Если указана боковая новая часть — NW-039.", "sort_order": 37},
    {"code": "NW-038", "unique_label": "Реконструкция: изменение высоты здания", "work_type_code": "WT-06", "subtype": "Изменение высоты", "object_type_codes": ["OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-02"], "stage_codes": ["ST-06"], "repair_class_codes": ["reconstruction"], "is_capital_repair": None, "requires_permit_review": True, "notes": "Общая запись: меняется высота/этажность без способа. Если указана новая часть сверху — NW-040.", "sort_order": 38},
    {"code": "NW-039", "unique_label": "Реконструкция: пристройка к зданию", "work_type_code": "WT-06", "subtype": "Пристройка", "object_type_codes": ["OT-12"], "building_technology_codes": ["BT-01", "BT-04", "BT-05", "BT-06"], "location_scope_codes": ["LS-02", "LS-10"], "stage_codes": ["ST-06"], "repair_class_codes": ["reconstruction"], "is_capital_repair": None, "requires_permit_review": True, "notes": "Новая боковая/периметральная часть существующего здания; выбирать вместо NW-037.", "sort_order": 39},
    {"code": "NW-040", "unique_label": "Реконструкция: надстройка здания", "work_type_code": "WT-06", "subtype": "Надстройка", "object_type_codes": ["OT-12"], "building_technology_codes": ["BT-01", "BT-04", "BT-05", "BT-06"], "location_scope_codes": ["LS-02", "LS-10"], "stage_codes": ["ST-06"], "repair_class_codes": ["reconstruction"], "is_capital_repair": None, "requires_permit_review": True, "notes": "Новая часть сверху: этаж, мансарда, техуровень; выбирать вместо NW-038.", "sort_order": 40},
    {"code": "NW-041", "unique_label": "Реконструкция: перепрофилирование помещений", "work_type_code": "WT-06", "subtype": "Перепрофилирование", "object_type_codes": ["OT-04", "OT-05", "OT-06", "OT-07", "OT-08", "OT-09"], "building_technology_codes": [], "location_scope_codes": ["LS-02", "LS-03"], "stage_codes": ["ST-01", "ST-06"], "repair_class_codes": ["reconstruction"], "is_capital_repair": None, "requires_permit_review": True, "notes": "Смена функционального назначения может менять требования.", "sort_order": 41},
    {"code": "NW-042", "unique_label": "Реконструкция: замена несущих конструкций", "work_type_code": "WT-06", "subtype": "Замена несущих конструкций", "object_type_codes": ["OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-10"], "stage_codes": ["ST-06"], "repair_class_codes": ["reconstruction"], "is_capital_repair": None, "requires_permit_review": True, "notes": "Отдельно от обычного ремонта.", "sort_order": 42},
    {"code": "NW-043", "unique_label": "Реконструкция: усиление несущих конструкций", "work_type_code": "WT-06", "subtype": "Усиление несущих конструкций", "object_type_codes": ["OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-10"], "stage_codes": ["ST-06"], "repair_class_codes": ["reconstruction"], "is_capital_repair": None, "requires_permit_review": True, "notes": "Каркасы, стены, перекрытия.", "sort_order": 43},
    {"code": "NW-044", "unique_label": "Реконструкция: усиление фундамента", "work_type_code": "WT-06", "subtype": "Усиление фундамента", "object_type_codes": ["OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-09", "LS-10"], "stage_codes": ["ST-05", "ST-06"], "repair_class_codes": ["reconstruction"], "is_capital_repair": None, "requires_permit_review": True, "notes": "Если это не обычный ремонт фундамента.", "sort_order": 44},
    {"code": "NW-045", "unique_label": "Внутренняя инженерия: монтаж отопления", "work_type_code": "WT-07", "subtype": "Отопление", "object_type_codes": ["OT-01", "OT-02", "OT-03", "OT-05", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-04"], "stage_codes": ["ST-08"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Внутри здания. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 45},
    {"code": "NW-046", "unique_label": "Внутренняя инженерия: монтаж водоснабжения", "work_type_code": "WT-07", "subtype": "Водоснабжение", "object_type_codes": ["OT-01", "OT-02", "OT-03", "OT-05", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-04"], "stage_codes": ["ST-08"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Внутренние сети ХВС/ГВС. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 46},
    {"code": "NW-047", "unique_label": "Внутренняя инженерия: монтаж канализации", "work_type_code": "WT-07", "subtype": "Канализация", "object_type_codes": ["OT-01", "OT-02", "OT-03", "OT-05", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-04"], "stage_codes": ["ST-08"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Внутренние канализационные сети. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 47},
    {"code": "NW-048", "unique_label": "Внутренняя инженерия: вентиляция и кондиционирование", "work_type_code": "WT-07", "subtype": "Вентиляция/кондиционирование", "object_type_codes": ["OT-01", "OT-02", "OT-03", "OT-05", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-04"], "stage_codes": ["ST-08"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Внутренние системы воздуха. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 48},
    {"code": "NW-049", "unique_label": "Внутренняя инженерия: электрообеспечение", "work_type_code": "WT-07", "subtype": "Электрика", "object_type_codes": ["OT-01", "OT-02", "OT-03", "OT-05", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-04"], "stage_codes": ["ST-08"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Щиты, кабель, розетки, освещение внутри. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 49},
    {"code": "NW-050", "unique_label": "Внутренняя инженерия: газоснабжение", "work_type_code": "WT-07", "subtype": "Газоснабжение", "object_type_codes": ["OT-01", "OT-05", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-04"], "stage_codes": ["ST-08"], "repair_class_codes": ["capital"], "is_capital_repair": True, "requires_permit_review": True, "notes": "Нужна отдельная проверка требований.", "sort_order": 50},
    {"code": "NW-051", "unique_label": "Внутренняя инженерия: СКС и ЛВС", "work_type_code": "WT-07", "subtype": "СКС/ЛВС", "object_type_codes": ["OT-05", "OT-06", "OT-07", "OT-08", "OT-09", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-04"], "stage_codes": ["ST-08"], "repair_class_codes": ["current"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Слаботочные сети данных.", "sort_order": 51},
    {"code": "NW-052", "unique_label": "Внутренняя инженерия: видеонаблюдение", "work_type_code": "WT-07", "subtype": "CCTV", "object_type_codes": ["OT-05", "OT-06", "OT-07", "OT-08", "OT-09", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-04", "LS-05", "LS-11"], "stage_codes": ["ST-08"], "repair_class_codes": ["current"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Внутренние и наружные камеры, серверы, мониторы, периметр/территория.", "sort_order": 52},
    {"code": "NW-053", "unique_label": "Внутренняя инженерия: охранно-пожарная сигнализация", "work_type_code": "WT-07", "subtype": "ОПС", "object_type_codes": ["OT-05", "OT-06", "OT-07", "OT-08", "OT-09", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-04"], "stage_codes": ["ST-08", "ST-11"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": True, "notes": "Сигнализация и оповещение. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 53},
    {"code": "NW-054", "unique_label": "Внутренняя инженерия: контроль доступа", "work_type_code": "WT-07", "subtype": "СКУД", "object_type_codes": ["OT-05", "OT-06", "OT-07", "OT-08", "OT-09", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-04"], "stage_codes": ["ST-08"], "repair_class_codes": ["current"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Домофония, замки, турникеты, считыватели.", "sort_order": 54},
    {"code": "NW-055", "unique_label": "Внутренняя инженерия: телевидение и радиосети", "work_type_code": "WT-07", "subtype": "ТВ/радиосети", "object_type_codes": ["OT-05", "OT-07", "OT-08", "OT-09", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-04"], "stage_codes": ["ST-08"], "repair_class_codes": ["current"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Кабельное/эфирное/спутниковое ТВ, радиосети.", "sort_order": 55},
    {"code": "NW-056", "unique_label": "Внутренняя инженерия: диспетчеризация и умный дом", "work_type_code": "WT-07", "subtype": "Диспетчеризация", "object_type_codes": ["OT-01", "OT-05", "OT-06", "OT-07", "OT-08", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-04"], "stage_codes": ["ST-08", "ST-11"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Интеграция инженерных систем. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 56},
    {"code": "NW-057", "unique_label": "Наружная инженерия: геодезическая разбивка трасс", "work_type_code": "WT-08", "subtype": "Разбивка трасс", "object_type_codes": ["OT-11"], "building_technology_codes": [], "location_scope_codes": ["LS-06"], "stage_codes": ["ST-01"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Подготовка наружных сетей.", "sort_order": 57},
    {"code": "NW-058", "unique_label": "Наружная инженерия: подготовка трасс сетей", "work_type_code": "WT-08", "subtype": "Подготовка трасс", "object_type_codes": ["OT-11"], "building_technology_codes": [], "location_scope_codes": ["LS-06"], "stage_codes": ["ST-02"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Уникализирует повтор с земляной расчисткой.", "sort_order": 58},
    {"code": "NW-059", "unique_label": "Наружная инженерия: устройство скважины водоснабжения", "work_type_code": "WT-08", "subtype": "Скважина", "object_type_codes": ["OT-10", "OT-11"], "building_technology_codes": [], "location_scope_codes": ["LS-05"], "stage_codes": ["ST-08"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": True, "notes": "Источник водоснабжения.", "sort_order": 59},
    {"code": "NW-060", "unique_label": "Наружная инженерия: наружный водопровод", "work_type_code": "WT-08", "subtype": "Наружный водопровод", "object_type_codes": ["OT-11"], "building_technology_codes": [], "location_scope_codes": ["LS-05", "LS-06"], "stage_codes": ["ST-08"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Прокладка трубопроводов ХВС/ГВС вне здания.", "sort_order": 60},
    {"code": "NW-061", "unique_label": "Наружная инженерия: бытовая канализация и септики", "work_type_code": "WT-08", "subtype": "Наружная канализация", "object_type_codes": ["OT-10", "OT-11"], "building_technology_codes": [], "location_scope_codes": ["LS-05", "LS-06"], "stage_codes": ["ST-08"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Канализация, септики, очистные сооружения.", "sort_order": 61},
    {"code": "NW-062", "unique_label": "Наружная инженерия: ливневая канализация", "work_type_code": "WT-08", "subtype": "Ливневка", "object_type_codes": ["OT-10", "OT-11"], "building_technology_codes": [], "location_scope_codes": ["LS-05", "LS-06"], "stage_codes": ["ST-08"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Инженерная ливневая сеть, не ландшафтный дренаж.", "sort_order": 62},
    {"code": "NW-063", "unique_label": "Наружная инженерия: тепловые сети", "work_type_code": "WT-08", "subtype": "Теплосети", "object_type_codes": ["OT-11"], "building_technology_codes": [], "location_scope_codes": ["LS-05", "LS-06"], "stage_codes": ["ST-08"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": True, "notes": "Магистрали и подключение к источнику тепла.", "sort_order": 63},
    {"code": "NW-064", "unique_label": "Наружная инженерия: кабельные линии и подстанции", "work_type_code": "WT-08", "subtype": "КЛ/ТП", "object_type_codes": ["OT-11"], "building_technology_codes": [], "location_scope_codes": ["LS-05", "LS-06"], "stage_codes": ["ST-08"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": True, "notes": "Кабельные линии, ТП, подключение.", "sort_order": 64},
    {"code": "NW-065", "unique_label": "Наружная инженерия: наружное освещение", "work_type_code": "WT-08", "subtype": "Наружное освещение", "object_type_codes": ["OT-10", "OT-11"], "building_technology_codes": [], "location_scope_codes": ["LS-05", "LS-11"], "stage_codes": ["ST-08"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Опоры, светильники, кабельные линии освещения.", "sort_order": 65},
    {"code": "NW-066", "unique_label": "Наружная инженерия: внешний газопровод", "work_type_code": "WT-08", "subtype": "Газопровод", "object_type_codes": ["OT-10", "OT-11"], "building_technology_codes": [], "location_scope_codes": ["LS-05", "LS-06"], "stage_codes": ["ST-08"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": True, "notes": "Нужна отдельная проверка требований.", "sort_order": 66},
    {"code": "NW-067", "unique_label": "Наружная инженерия: кабели связи", "work_type_code": "WT-08", "subtype": "Связь", "object_type_codes": ["OT-11"], "building_technology_codes": [], "location_scope_codes": ["LS-05", "LS-06"], "stage_codes": ["ST-08"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Наружные линии связи.", "sort_order": 67},
    {"code": "NW-068", "unique_label": "Кровля: устройство стропильной системы", "work_type_code": "WT-09", "subtype": "Стропильная система", "object_type_codes": ["OT-01", "OT-12"], "building_technology_codes": ["BT-01", "BT-02", "BT-03", "BT-04", "BT-05"], "location_scope_codes": ["LS-07"], "stage_codes": ["ST-07"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Конструктив скатной кровли; применимо и для СИП-домов.", "sort_order": 68},
    {"code": "NW-069", "unique_label": "Кровля: монтаж кровельного покрытия", "work_type_code": "WT-09", "subtype": "Кровельное покрытие", "object_type_codes": ["OT-01", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-07"], "stage_codes": ["ST-07"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Черепица, металл, мягкая кровля и т.д. как материал отдельно.", "sort_order": 69},
    {"code": "NW-070", "unique_label": "Кровля: утепление кровли", "work_type_code": "WT-09", "subtype": "Утепление кровли", "object_type_codes": ["OT-01", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-07"], "stage_codes": ["ST-07"], "repair_class_codes": ["none", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Новое строительство или капремонт; уточнять при классификации.", "sort_order": 70},
    {"code": "NW-071", "unique_label": "Кровля: водосточная система", "work_type_code": "WT-09", "subtype": "Водосток", "object_type_codes": ["OT-01", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-07", "LS-08"], "stage_codes": ["ST-07"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Желоба, трубы, узлы отвода воды. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 71},
    {"code": "NW-072", "unique_label": "Кровля: ремонт кровли", "work_type_code": "WT-09", "subtype": "Ремонт кровли", "object_type_codes": ["OT-01", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-07"], "stage_codes": ["ST-07"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Отдельно от демонтажа старой кровли. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 72},
    {"code": "NW-073", "unique_label": "Фасад: утепление фасада", "work_type_code": "WT-10", "subtype": "Утепление фасада", "object_type_codes": ["OT-01", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-08"], "stage_codes": ["ST-07"], "repair_class_codes": ["none", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Новое строительство или капремонт; уточнять при классификации. Выделено отдельно от общей отделки.", "sort_order": 73},
    {"code": "NW-074", "unique_label": "Фасад: штукатурный фасад", "work_type_code": "WT-10", "subtype": "Штукатурный фасад", "object_type_codes": ["OT-01", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-08"], "stage_codes": ["ST-07"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Мокрый фасад/штукатурные системы. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 74},
    {"code": "NW-075", "unique_label": "Фасад: вентилируемый фасад", "work_type_code": "WT-10", "subtype": "Вентфасад", "object_type_codes": ["OT-01", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-08"], "stage_codes": ["ST-07"], "repair_class_codes": ["none", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Новое строительство или капремонт; уточнять при классификации. Каркас, облицовка, утеплитель.", "sort_order": 75},
    {"code": "NW-076", "unique_label": "Фасад: облицовка фасада", "work_type_code": "WT-10", "subtype": "Облицовка фасада", "object_type_codes": ["OT-01", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-08"], "stage_codes": ["ST-07"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Панели, плитка, камень и т.п. как материал отдельно. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 76},
    {"code": "NW-077", "unique_label": "Фасад: ремонт фасада", "work_type_code": "WT-10", "subtype": "Ремонт фасада", "object_type_codes": ["OT-01", "OT-12"], "building_technology_codes": [], "location_scope_codes": ["LS-08"], "stage_codes": ["ST-07"], "repair_class_codes": ["current", "capital"], "is_capital_repair": None, "requires_permit_review": False, "notes": "Отдельно от внутреннего ремонта и наружных сетей. Класс ремонта уточняется при классификации; is_capital_repair=null до уточнения.", "sort_order": 77},
    {"code": "NW-078", "unique_label": "Ландшафт: проект благоустройства участка", "work_type_code": "WT-11", "subtype": "Проект благоустройства", "object_type_codes": ["OT-10"], "building_technology_codes": [], "location_scope_codes": ["LS-11"], "stage_codes": ["ST-01"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Эскизы, генплан, дендроплан, инженерные схемы.", "sort_order": 78},
    {"code": "NW-079", "unique_label": "Ландшафт: дренаж участка", "work_type_code": "WT-11", "subtype": "Дренаж участка", "object_type_codes": ["OT-10"], "building_technology_codes": [], "location_scope_codes": ["LS-11"], "stage_codes": ["ST-12"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Ландшафтный дренаж, не наружная ливневая сеть.", "sort_order": 79},
    {"code": "NW-080", "unique_label": "Ландшафт: автополив и освещение участка", "work_type_code": "WT-11", "subtype": "Автополив/освещение", "object_type_codes": ["OT-10"], "building_technology_codes": [], "location_scope_codes": ["LS-11"], "stage_codes": ["ST-12"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Инженерия благоустройства участка.", "sort_order": 80},
    {"code": "NW-081", "unique_label": "Ландшафт: очистка территории под благоустройство", "work_type_code": "WT-11", "subtype": "Очистка территории", "object_type_codes": ["OT-10"], "building_technology_codes": [], "location_scope_codes": ["LS-11"], "stage_codes": ["ST-02"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Уникализирует повтор с земляными.", "sort_order": 81},
    {"code": "NW-082", "unique_label": "Ландшафт: выравнивание участка под озеленение", "work_type_code": "WT-11", "subtype": "Выравнивание под озеленение", "object_type_codes": ["OT-10"], "building_technology_codes": [], "location_scope_codes": ["LS-11"], "stage_codes": ["ST-12"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Не проектные отметки строительства, а благоустройство.", "sort_order": 82},
    {"code": "NW-083", "unique_label": "Ландшафт: мощение дорожек и площадок", "work_type_code": "WT-11", "subtype": "Мощение", "object_type_codes": ["OT-10"], "building_technology_codes": [], "location_scope_codes": ["LS-11"], "stage_codes": ["ST-12"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Дорожки, площадки, отмостки при благоустройстве.", "sort_order": 83},
    {"code": "NW-084", "unique_label": "Ландшафт: подпорные стенки и малые формы", "work_type_code": "WT-11", "subtype": "Подпорные стенки/МАФ", "object_type_codes": ["OT-10"], "building_technology_codes": [], "location_scope_codes": ["LS-11"], "stage_codes": ["ST-12"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Беседки, перголы, террасы, мостики.", "sort_order": 84},
    {"code": "NW-085", "unique_label": "Ландшафт: посадка деревьев и кустарников", "work_type_code": "WT-11", "subtype": "Посадки", "object_type_codes": ["OT-10"], "building_technology_codes": [], "location_scope_codes": ["LS-11"], "stage_codes": ["ST-12"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Деревья, кустарники, живые изгороди.", "sort_order": 85},
    {"code": "NW-086", "unique_label": "Ландшафт: устройство газона и цветников", "work_type_code": "WT-11", "subtype": "Газон/цветники", "object_type_codes": ["OT-10"], "building_technology_codes": [], "location_scope_codes": ["LS-11"], "stage_codes": ["ST-12"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Рулонный/посевной газон, цветники, рокарии.", "sort_order": 86},
    {"code": "NW-087", "unique_label": "Ландшафт: водоемы и фонтаны", "work_type_code": "WT-11", "subtype": "Водоемы/фонтаны", "object_type_codes": ["OT-10"], "building_technology_codes": [], "location_scope_codes": ["LS-11"], "stage_codes": ["ST-12"], "repair_class_codes": ["none"], "is_capital_repair": False, "requires_permit_review": False, "notes": "Пруды, ручьи, фонтаны, водопады.", "sort_order": 87},
]


# ───────────── DDL ─────────────

def _simple_ref(name, with_description=False, code_len=10):
    """code (PK) + name + sort_order [+ description]."""
    cols = [
        sa.Column("code", sa.String(length=code_len), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
    ]
    if with_description:
        cols.append(sa.Column("description", sa.Text(), nullable=True))
    return op.create_table(name, *cols, schema=FER_SCHEMA)


def upgrade():
    # ── reference tables ──
    op.create_table(
        "nw_work_type",
        sa.Column("code", sa.String(length=10), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
        schema=FER_SCHEMA,
    )
    op.create_table(
        "nw_object_type",
        sa.Column("code", sa.String(length=10), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
        schema=FER_SCHEMA,
    )
    op.create_table(
        "nw_building_technology",
        sa.Column("code", sa.String(length=10), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
        schema=FER_SCHEMA,
    )
    op.create_table(
        "nw_location_scope",
        sa.Column("code", sa.String(length=10), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
        schema=FER_SCHEMA,
    )
    op.create_table(
        "nw_stage",
        sa.Column("code", sa.String(length=10), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
        schema=FER_SCHEMA,
    )
    op.create_table(
        "nw_repair_class",
        sa.Column("code", sa.String(length=20), primary_key=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
        schema=FER_SCHEMA,
    )

    # ── main: nw_item ──
    op.create_table(
        "nw_item",
        sa.Column("code", sa.String(length=10), primary_key=True),
        sa.Column("unique_label", sa.Text(), nullable=False),
        sa.Column(
            "work_type_code",
            sa.String(length=10),
            sa.ForeignKey(f"{FER_SCHEMA}.nw_work_type.code", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("subtype", sa.Text(), nullable=True),
        sa.Column("object_type_codes", postgresql.ARRAY(sa.String(length=10)), nullable=False, server_default="{}"),
        sa.Column("building_technology_codes", postgresql.ARRAY(sa.String(length=10)), nullable=False, server_default="{}"),
        sa.Column("location_scope_codes", postgresql.ARRAY(sa.String(length=10)), nullable=False, server_default="{}"),
        sa.Column("stage_codes", postgresql.ARRAY(sa.String(length=10)), nullable=False, server_default="{}"),
        sa.Column("repair_class_codes", postgresql.ARRAY(sa.String(length=20)), nullable=False, server_default="{}"),
        sa.Column("is_capital_repair", sa.Boolean(), nullable=True),
        sa.Column("requires_permit_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.UniqueConstraint("unique_label", name="uq_nw_item_unique_label"),
        schema=FER_SCHEMA,
    )
    op.create_index(
        "ix_nw_item_work_type_code",
        "nw_item",
        ["work_type_code"],
        schema=FER_SCHEMA,
    )

    # ── seed ──
    bind = op.get_bind()

    def _table(name, *cols):
        return sa.table(name, *cols, schema=FER_SCHEMA)

    op.bulk_insert(
        _table(
            "nw_work_type",
            sa.column("code", sa.String),
            sa.column("name", sa.Text),
            sa.column("description", sa.Text),
            sa.column("sort_order", sa.SmallInteger),
        ),
        NW_WORK_TYPES,
    )
    op.bulk_insert(
        _table(
            "nw_object_type",
            sa.column("code", sa.String),
            sa.column("name", sa.Text),
            sa.column("sort_order", sa.SmallInteger),
        ),
        NW_OBJECT_TYPES,
    )
    op.bulk_insert(
        _table(
            "nw_building_technology",
            sa.column("code", sa.String),
            sa.column("name", sa.Text),
            sa.column("sort_order", sa.SmallInteger),
        ),
        NW_BUILDING_TECH,
    )
    op.bulk_insert(
        _table(
            "nw_location_scope",
            sa.column("code", sa.String),
            sa.column("name", sa.Text),
            sa.column("sort_order", sa.SmallInteger),
        ),
        NW_LOCATION_SCOPES,
    )
    op.bulk_insert(
        _table(
            "nw_stage",
            sa.column("code", sa.String),
            sa.column("name", sa.Text),
            sa.column("sort_order", sa.SmallInteger),
        ),
        NW_STAGES,
    )
    op.bulk_insert(
        _table(
            "nw_repair_class",
            sa.column("code", sa.String),
            sa.column("description", sa.Text),
            sa.column("sort_order", sa.SmallInteger),
        ),
        NW_REPAIR_CLASSES,
    )

    # nw_item — массивы передаём как Python list, диалект сам сериализует
    op.bulk_insert(
        _table(
            "nw_item",
            sa.column("code", sa.String),
            sa.column("unique_label", sa.Text),
            sa.column("work_type_code", sa.String),
            sa.column("subtype", sa.Text),
            sa.column("object_type_codes", postgresql.ARRAY(sa.String)),
            sa.column("building_technology_codes", postgresql.ARRAY(sa.String)),
            sa.column("location_scope_codes", postgresql.ARRAY(sa.String)),
            sa.column("stage_codes", postgresql.ARRAY(sa.String)),
            sa.column("repair_class_codes", postgresql.ARRAY(sa.String)),
            sa.column("is_capital_repair", sa.Boolean),
            sa.column("requires_permit_review", sa.Boolean),
            sa.column("notes", sa.Text),
            sa.column("sort_order", sa.SmallInteger),
        ),
        NW_ITEMS,
    )


def downgrade():
    op.drop_index("ix_nw_item_work_type_code", table_name="nw_item", schema=FER_SCHEMA)
    op.drop_table("nw_item", schema=FER_SCHEMA)
    op.drop_table("nw_repair_class", schema=FER_SCHEMA)
    op.drop_table("nw_stage", schema=FER_SCHEMA)
    op.drop_table("nw_location_scope", schema=FER_SCHEMA)
    op.drop_table("nw_building_technology", schema=FER_SCHEMA)
    op.drop_table("nw_object_type", schema=FER_SCHEMA)
    op.drop_table("nw_work_type", schema=FER_SCHEMA)
