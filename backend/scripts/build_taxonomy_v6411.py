from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'app' / 'data'
SRC = DATA_DIR / 'construction_work_dictionary_v6_4_10.json'
DST = DATA_DIR / 'construction_work_dictionary_v6_4_11.json'

payload = json.loads(SRC.read_text(encoding='utf-8'))
policy = payload.setdefault('operation_object_resolution_policy', {})
policy['version'] = '1.2.0'
ops = policy.setdefault('operations', {})
objects = policy.setdefault('objects', {})
rules = policy.setdefault('rules', [])

new_operations = {
    'site_survey_layout': ['осмотр участка', 'геодезическая разбивка', 'вынос осей', 'обноска'],
    'site_clearing': ['расчистка территории', 'расчистка участка', 'удаление кустарника', 'удаление пней'],
    'topsoil_removal': ['снятие плодородного слоя', 'снятие растительного слоя', 'снятие дернины'],
    'trench_excavation': ['разработка траншеи', 'разработка траншей', 'рытье траншеи', 'копка траншеи'],
    'backfill': ['обратная засыпка', 'засыпка котлована', 'засыпка пазух', 'засыпка траншеи'],
    'pile_layout': ['разметка мест погружения свай', 'разбивка свайного поля', 'разметка свай'],
    'screw_pile_installation': ['погружение винтовых свай', 'вкручивание винтовых свай', 'монтаж винтовых свай'],
    'driven_pile_installation': ['погружение забивных свай', 'забивка железобетонных свай', 'забивка ж/б свай'],
    'pile_cutting': ['обрезка свай', 'срубка оголовков свай', 'срезка свай'],
    'pile_concreting': ['бетонирование полости свай', 'заполнение свай бетоном', 'бетонирование винтовых свай'],
    'pile_head_installation': ['устройство оголовков на сваи', 'монтаж оголовков свай', 'установка оголовков'],
    'formwork_installation': ['монтаж опалубки', 'устройство опалубки', 'установка опалубки'],
    'formwork_sealing': ['герметизация стыков опалубки', 'герметизация опалубочных щитов'],
    'formwork_lubrication': ['смазка опалубки', 'нанесение смазки на опалубку'],
    'formwork_stripping': ['демонтаж опалубки', 'разборка опалубки', 'распалубка'],
    'temporary_support_installation': ['установка телескопических стоек', 'монтаж временных стоек', 'временные подпорки'],
    'rebar_installation': ['установка арматурных каркасов', 'монтаж арматурного каркаса', 'установка арматуры', 'армирование плиты', 'армирование стен'],
    'rebar_tying': ['вязка арматуры', 'вязка арматурных каркасов', 'соединение стержней вязальной проволокой'],
    'rebar_welding': ['сварка арматурных стержней', 'сварка арматуры'],
    'embedded_parts_installation': ['установка закладных деталей', 'монтаж закладных деталей'],
    'protective_layer_spacer_installation': ['установка фиксаторов защитного слоя', 'фиксаторы защитного слоя'],
    'concrete_pumping': ['подача бетонной смеси автобетононасосом', 'подача бетона бетононасосом', 'работа бетононасоса'],
    'concrete_placement': ['укладка бетонной смеси', 'заливка бетона', 'бетонирование ростверка', 'бетонирование плиты', 'бетонирование стен'],
    'concrete_vibration': ['вибрирование бетонной смеси', 'виброуплотнение бетона', 'вибрирование бетона'],
    'concrete_finishing': ['заглаживание бетонной поверхности', 'заглаживание открытых поверхностей бетона', 'затирка бетона'],
    'concrete_joint_installation': ['устройство рабочих швов бетонирования', 'рабочие швы бетонирования'],
    'concrete_curing': ['уход за бетоном', 'укрытие бетона пленкой', 'увлажнение бетона'],
    'brick_masonry': ['кладка стен из кирпича', 'кирпичная кладка', 'кладка кирпича'],
    'sip_panel_installation': ['монтаж сип-панелей', 'монтаж сип панелей', 'устройство обвязки сип', 'устройство замков сип'],
    'lgtk_frame_installation': ['монтаж лстк-каркаса', 'монтаж лстк каркаса', 'устройство перекрытий из лстк', 'стропильная система из лстк'],
    'timber_frame_installation': ['монтаж деревянного каркаса', 'деревянные каркасные стены', 'сборка деревянного каркаса'],
    'fachwerk_frame_installation': ['монтаж несущего фахверкового каркаса', 'фахверковый каркас'],
    'sandwich_panel_installation': ['монтаж сэндвич-панелей', 'установка сэндвич панелей'],
    'slab_installation': ['монтаж плит перекрытия', 'укладка плит перекрытия', 'устройство сборного перекрытия'],
    'monolithic_slab_complete': ['устройство монолитного перекрытия', 'монолитное перекрытие с армированием и опалубкой'],
    'wood_floor_structure': ['устройство деревянных перекрытий', 'монтаж деревянных балок перекрытия', 'монтаж лаг перекрытия'],
    'roof_structure_installation': ['устройство стропильной системы', 'монтаж стропильной системы', 'монтаж стропил', 'устройство кровельного каркаса'],
    'waterproofing': ['гидроизоляция', 'обмазочная гидроизоляция', 'рулонная гидроизоляция', 'наплавляемая гидроизоляция'],
    'thermal_insulation': ['утепление', 'теплоизоляция', 'монтаж утеплителя'],
    'wind_membrane_installation': ['ветрозащита', 'ветрозащитная мембрана', 'монтаж ветрозащиты'],
    'vapor_barrier_installation': ['пароизоляция', 'монтаж пароизоляции', 'укладка пароизоляции'],
    'facade_cladding': ['облицовка фасада', 'монтаж фасадной облицовки', 'монтаж сайдинга', 'монтаж планкена'],
    'facade_plastering': ['штукатурка фасада', 'фасадная штукатурка'],
    'painting': ['покраска', 'окраска поверхности', 'нанесение краски'],
    'wood_protection': ['антисептирование', 'огнебиозащита деревянных элементов', 'защита древесины'],
    'metal_corrosion_protection': ['антикоррозийная обработка металлоконструкций', 'грунтовка металлоконструкций', 'огнезащита металлоконструкций'],
    'natural_stone_paving': ['мощение натуральным камнем', 'укладка плитняка', 'мощение гранитным камнем'],
    'curb_installation': ['укладка бордюрного камня', 'установка бордюрного камня', 'монтаж бордюрного камня'],
    'retaining_wall_construction': ['устройство подпорной стенки', 'строительство подпорной стенки'],
    'gabion_wall_construction': ['подпорная стенка из габионов', 'устройство габионов', 'монтаж габионов'],
    'lawn_installation': ['устройство рулонного газона', 'посев газона', 'укладка рулонного газона'],
    'landscape_grading': ['вертикальная планировка участка', 'планировка участка', 'планировка грунта'],
    'drainage_installation': ['устройство поверхностного дренажа', 'устройство глубинного дренажа', 'монтаж дренажной трубы'],
    'storm_sewer_installation': ['устройство ливневой канализации', 'ливневая канализация', 'ливневый водоотвод'],
    'drainage_well_installation': ['устройство дренажного колодца', 'монтаж дренажного колодца'],
    'radiator_installation': ['установка радиаторов', 'монтаж радиаторов отопления'],
    'underfloor_heating_pipe_installation': ['укладка труб теплого пола', 'монтаж водяного теплого пола', 'трубы теплого пола'],
    'window_installation': ['установка стеклопакетов', 'монтаж окон', 'установка оконных блоков'],
    'door_installation': ['монтаж дверей', 'установка дверных блоков', 'установка дверей'],
    'roof_covering_installation': ['монтаж кровельного покрытия', 'устройство кровельного покрытия', 'монтаж металлочерепицы', 'монтаж гибкой черепицы'],
    'roof_drainage_installation': ['монтаж водосточной системы', 'устройство водостока'],
    'surface_preparation': ['подготовка поверхности', 'шлифовка поверхности', 'заделка швов', 'черновая отделка'],
    'electrical_point_installation': ['монтаж электроточки', 'установка розетки', 'установка выключателя', 'монтаж точки освещения'],
    'plumbing_point_installation': ['монтаж сантехнической точки', 'точка водоснабжения', 'точка канализации'],
}

for code, terms in new_operations.items():
    existing = ops.setdefault(code, [])
    for term in terms:
        if term not in existing:
            existing.append(term)

# Additive metadata: every operation gets a record, including legacy operations.
unit_hints = {
    'site_survey_layout': ['site'], 'site_clearing': ['are', 'm2', 'site'], 'topsoil_removal': ['m2', 'm3'],
    'excavation': ['m3', 'm2'], 'trench_excavation': ['m3', 'm'], 'soil_movement': ['m3'], 'soil_disposal': ['m3'],
    'backfill': ['m3'], 'sand_backfill': ['m3', 'm2'], 'gravel_backfill': ['m3', 'm2'], 'compaction': ['m2', 'm3'],
    'pile_layout': ['point', 'pcs'], 'pile_drilling': ['pcs', 'm'], 'screw_pile_installation': ['pcs'],
    'driven_pile_installation': ['pcs'], 'pile_cutting': ['pcs'], 'pile_concreting': ['pcs', 'm3'], 'pile_head_installation': ['pcs'],
    'formwork_installation': ['m2'], 'formwork_sealing': ['m'], 'formwork_lubrication': ['m2'],
    'formwork_stripping': ['m2'], 'temporary_support_installation': ['m2', 'pcs', 'set'],
    'rebar_installation': ['t', 'kg'], 'rebar_tying': ['t', 'kg'], 'rebar_welding': ['t', 'kg'],
    'embedded_parts_installation': ['t', 'kg', 'pcs'], 'protective_layer_spacer_installation': ['pcs'],
    'concrete_pumping': ['m3', 'machine_hour'], 'concrete_placement': ['m3'], 'concrete_vibration': ['m3'],
    'concrete_finishing': ['m2'], 'concrete_joint_installation': ['m'], 'concrete_curing': ['m2'],
    'formwork_rebar_concrete': ['m3', 'm2', 't'], 'block_masonry': ['m3', 'm2'], 'brick_masonry': ['m3', 'm2'],
    'sip_panel_installation': ['m2', 'm'], 'lgtk_frame_installation': ['m2', 't'], 'timber_frame_installation': ['m2', 'm3'],
    'fachwerk_frame_installation': ['t', 'm3'], 'sandwich_panel_installation': ['m2'],
    'slab_installation': ['m2', 'pcs'], 'monolithic_slab_complete': ['m3', 'm2'], 'wood_floor_structure': ['m2'],
    'roof_structure_installation': ['m2', 'm3'], 'waterproofing': ['m2', 'm'], 'thermal_insulation': ['m2', 'm3'],
    'wind_membrane_installation': ['m2'], 'vapor_barrier_installation': ['m2'], 'facade_cladding': ['m2'],
    'facade_plastering': ['m2'], 'painting': ['m2'], 'wood_protection': ['m2', 'm3'], 'metal_corrosion_protection': ['m2', 't'],
    'geotextile_installation': ['m2'], 'membrane_installation': ['m2'], 'paving': ['m2'], 'natural_stone_paving': ['m2'],
    'curb_installation': ['m'], 'retaining_wall_construction': ['m2', 'm3', 'm'], 'gabion_wall_construction': ['m', 'm3'],
    'lawn_installation': ['m2'], 'grading': ['m2', 'are', 'machine_hour'], 'landscape_grading': ['m2', 'are', 'machine_hour'],
    'drainage_installation': ['m'], 'storm_sewer_installation': ['m'], 'drainage_well_installation': ['pcs'],
    'radiator_installation': ['pcs'], 'underfloor_heating_pipe_installation': ['m', 'm2'],
    'window_installation': ['window', 'pcs', 'opening'], 'door_installation': ['pcs', 'opening'],
    'roof_covering_installation': ['m2'], 'roof_drainage_installation': ['m'], 'surface_preparation': ['m2', 'm'],
    'stone_cladding': ['m2'], 'surface_priming': ['m2'], 'reinforcing_mesh_installation': ['m2'],
    'electrical_point_installation': ['point'], 'plumbing_point_installation': ['point'],
}

packages = {
    'formwork_rebar_concrete': {
        'kind': 'package', 'legacy': True,
        'included_operations': ['formwork_installation', 'rebar_installation', 'concrete_placement', 'concrete_vibration'],
    },
    'monolithic_slab_complete': {
        'kind': 'package', 'legacy': False,
        'included_operations': ['formwork_installation', 'rebar_installation', 'concrete_placement', 'concrete_vibration'],
    },
}
policy['operation_packages'] = packages
metadata = policy.setdefault('operation_metadata', {})
for code in ops:
    meta = metadata.setdefault(code, {})
    meta.setdefault('negative_terms', [])
    meta['unit_hints'] = unit_hints.get(code, meta.get('unit_hints', []))
    meta.setdefault('row_role', 'work')
    meta['kind'] = 'package' if code in packages else 'atomic'
    if code == 'formwork_rebar_concrete':
        meta['legacy'] = True

new_objects = {
    'construction_site': {'title_terms': ['строительная площадка', 'территория участка'], 'description_terms': ['подготовка участка']},
    'pile_foundation': {'title_terms': ['сваи', 'свайное поле', 'винтовые сваи', 'забивные сваи'], 'description_terms': ['свай']},
    'grillage': {'title_terms': ['ростверк', 'оголовки свай'], 'description_terms': ['ростверк']},
    'structural_frame': {'title_terms': ['каркас', 'колонны', 'балки', 'ригели'], 'description_terms': ['несущий каркас']},
    'floor_slab': {'title_terms': ['перекрытие', 'плита перекрытия'], 'description_terms': ['монолитное перекрытие', 'сборное перекрытие']},
    'stair': {'title_terms': ['лестница', 'марш', 'лестничная площадка'], 'description_terms': ['лестниц']},
    'partition': {'title_terms': ['перегородки', 'внутренние перегородки'], 'description_terms': ['ненесущие перегородки']},
    'roof': {'title_terms': ['кровля', 'крыша', 'стропильная система'], 'description_terms': ['кровель']},
    'facade': {'title_terms': ['фасад', 'наружная отделка'], 'description_terms': ['фасад']},
    'wet_area': {'title_terms': ['санузел', 'душевая', 'мокрая зона'], 'description_terms': ['гидроизоляция пола']},
    'landscape_site': {'title_terms': ['ландшафт', 'благоустройство', 'дорожки', 'площадки'], 'description_terms': ['ландшафт']},
    'drainage': {'title_terms': ['дренаж', 'ливневая канализация'], 'description_terms': ['дренаж']},
    'heating': {'title_terms': ['отопление', 'радиаторы', 'теплый пол'], 'description_terms': ['отоплен']},
    'window_opening': {'title_terms': ['окна', 'стеклопакеты', 'оконные блоки'], 'description_terms': ['окон']},
    'door_opening': {'title_terms': ['двери', 'дверные блоки'], 'description_terms': ['двер']},
}
for code, definition in new_objects.items():
    objects.setdefault(code, definition)

# Validate target codes before adding rules.
valid_codes = {
    f"{section['id']}/{subtype['id']}"
    for section in payload.get('sections', [])
    for subtype in section.get('subtypes', [])
}
existing_rule_keys = {
    (r.get('operation'), r.get('object'), r.get('section_id'), r.get('subtype_id'))
    for r in rules if isinstance(r, dict)
}

def add_rule(operation, obj, taxonomy_code, stage=None):
    assert taxonomy_code in valid_codes, taxonomy_code
    section_id, subtype_id = taxonomy_code.split('/', 1)
    key = (operation, obj, section_id, subtype_id)
    if key in existing_rule_keys:
        return
    row = {'operation': operation, 'object': obj, 'section_id': section_id, 'subtype_id': subtype_id}
    if stage:
        row['preferred_stage_number'] = stage
    rules.append(row)
    existing_rule_keys.add(key)

# Site and earthworks.
add_rule('site_survey_layout', 'construction_site', 'mobilization/survey_geology_geodesy')
add_rule('site_clearing', 'construction_site', 'earthworks/site_clearing')
add_rule('site_clearing', 'landscape_site', 'landscape/site_clearing')
add_rule('topsoil_removal', 'construction_site', 'earthworks/site_clearing')
add_rule('trench_excavation', 'foundation', 'earthworks/excavation_pit_trench')
add_rule('trench_excavation', 'construction_site', 'earthworks/excavation_pit_trench')
add_rule('backfill', 'foundation', 'earthworks/backfill')
add_rule('backfill', 'construction_site', 'earthworks/backfill')

# Piles and grillage.
for op in ['pile_layout', 'screw_pile_installation', 'driven_pile_installation', 'pile_cutting', 'pile_concreting']:
    add_rule(op, 'pile_foundation', 'foundation/pile_foundation')
add_rule('pile_head_installation', 'pile_foundation', 'foundation/grillage_and_pile_caps')

# Atomic monolithic operations by object.
for op in ['formwork_installation', 'formwork_sealing', 'formwork_lubrication', 'formwork_stripping',
           'rebar_installation', 'rebar_tying', 'rebar_welding', 'embedded_parts_installation',
           'protective_layer_spacer_installation', 'concrete_pumping', 'concrete_placement',
           'concrete_vibration', 'concrete_finishing', 'concrete_joint_installation', 'concrete_curing']:
    add_rule(op, 'foundation', 'foundation/foundation_rebar_formwork_concrete')
    add_rule(op, 'grillage', 'foundation/foundation_rebar_formwork_concrete')
    add_rule(op, 'structural_frame', 'structural_frame/rc_monolithic_frame')
    add_rule(op, 'floor_slab', 'floor_slabs/monolithic_slab')
add_rule('temporary_support_installation', 'floor_slab', 'reconstruction_works/temporary_shoring_propping')
add_rule('temporary_support_installation', 'structural_frame', 'reconstruction_works/temporary_shoring_propping')
add_rule('formwork_installation', 'stair', 'monolithic_stairs/stair_formwork_rebar')
add_rule('rebar_installation', 'stair', 'monolithic_stairs/stair_formwork_rebar')
add_rule('concrete_placement', 'stair', 'monolithic_stairs/stair_concreting')
add_rule('concrete_vibration', 'stair', 'monolithic_stairs/stair_concreting')
add_rule('monolithic_slab_complete', 'floor_slab', 'floor_slabs/monolithic_slab')

# Walls, panels, frame and slabs.
add_rule('brick_masonry', 'building_wall', 'load_bearing_walls/brick_masonry')
add_rule('brick_masonry', 'partition', 'partitions/brick_partitions')
add_rule('block_masonry', 'building_wall', 'load_bearing_walls/block_walls')
add_rule('block_masonry', 'partition', 'partitions/block_partitions')
add_rule('sip_panel_installation', 'building_wall', 'load_bearing_walls/wood_frame_walls')
add_rule('sip_panel_installation', 'partition', 'partitions/wood_frame_partitions')
add_rule('lgtk_frame_installation', 'building_wall', 'load_bearing_walls/frame_lstk_walls')
add_rule('lgtk_frame_installation', 'structural_frame', 'structural_frame/metal_frame')
add_rule('timber_frame_installation', 'building_wall', 'load_bearing_walls/wood_frame_walls')
add_rule('fachwerk_frame_installation', 'structural_frame', 'structural_frame/metal_frame')
add_rule('sandwich_panel_installation', 'structural_frame', 'structural_frame/sandwich_panel_envelope')
add_rule('sandwich_panel_installation', 'partition', 'partitions/sandwich_panel_partitions')
add_rule('slab_installation', 'floor_slab', 'floor_slabs/precast_rc_slabs')
add_rule('wood_floor_structure', 'floor_slab', 'floor_slabs/timber_floor')

# Roof and protection.
add_rule('roof_structure_installation', 'roof', 'rafters/rafters_installation')
add_rule('roof_covering_installation', 'roof', 'roofing/pitched_roof_covering')
add_rule('roof_drainage_installation', 'roof', 'roofing/roof_drainage_and_safety')
add_rule('waterproofing', 'foundation', 'waterproofing/underground_structure_waterproofing')
add_rule('waterproofing', 'wet_area', 'waterproofing/wet_area_waterproofing')
add_rule('waterproofing', 'roof', 'roofing/flat_roll_membrane_roof')
add_rule('thermal_insulation', 'foundation', 'insulation/foundation_plinth_insulation')
add_rule('thermal_insulation', 'facade', 'insulation/facade_wall_insulation')
add_rule('thermal_insulation', 'roof', 'insulation/roof_attic_insulation')
add_rule('thermal_insulation', 'floor_slab', 'insulation/floor_slab_insulation')
add_rule('wind_membrane_installation', 'building_wall', 'insulation/facade_wall_insulation')
add_rule('vapor_barrier_installation', 'roof', 'roofing/roof_insulation_vapor_barrier')
add_rule('facade_cladding', 'facade', 'interior_finishing/facade_finishing')
add_rule('facade_plastering', 'facade', 'interior_finishing/facade_finishing')
add_rule('painting', 'facade', 'interior_finishing/facade_finishing')
add_rule('painting', 'building_wall', 'interior_finishing/painting')
add_rule('wood_protection', 'roof', 'rafters/wood_treatment')
add_rule('wood_protection', 'building_wall', 'rafters/wood_treatment')
add_rule('metal_corrosion_protection', 'structural_frame', 'structural_frame/steel_protection_coatings')
add_rule('surface_preparation', 'building_wall', 'interior_finishing/surface_preparation')

# Existing landscape operation rules required by the rate catalogue.
add_rule('curb_installation', 'landscape_site', 'landscape/curbs_edging')
add_rule('paving', 'landscape_site', 'landscape/paving')
add_rule('stone_cladding', 'retaining_wall', 'landscape/natural_stone_cladding')
add_rule('surface_priming', 'stone_cladding', 'landscape/natural_stone_cladding')
add_rule('reinforcing_mesh_installation', 'stone_cladding', 'landscape/natural_stone_cladding')

# Landscape and external systems.
add_rule('natural_stone_paving', 'landscape_site', 'landscape/large_format_stone_paving')
add_rule('retaining_wall_construction', 'landscape_site', 'landscape/retaining_planter_walls')
add_rule('gabion_wall_construction', 'landscape_site', 'landscape/retaining_planter_walls')
add_rule('lawn_installation', 'landscape_site', 'landscape/lawn')
add_rule('landscape_grading', 'landscape_site', 'landscape/landscape_grading')
add_rule('drainage_installation', 'drainage', 'landscape/site_drainage_stormwater')
add_rule('storm_sewer_installation', 'drainage', 'mep_external/stormwater_drainage')
add_rule('drainage_well_installation', 'drainage', 'landscape/site_drainage_stormwater')

# MEP and openings.
add_rule('radiator_installation', 'heating', 'mep_internal/heating')
add_rule('underfloor_heating_pipe_installation', 'heating', 'mep_internal/heating')
add_rule('window_installation', 'window_opening', 'windows_doors/windows')
add_rule('door_installation', 'door_opening', 'windows_doors/interior_doors')
add_rule('electrical_point_installation', 'building_wall', 'mep_internal/electrical')
add_rule('plumbing_point_installation', 'building_wall', 'mep_internal/water_supply')

payload['dictionary_version'] = 'construction_work_dictionary_v6_4_11@1.8.0'
payload.setdefault('meta', {})['dictionary_version'] = 'construction_work_dictionary_v6_4_11@1.8.0'
payload['meta']['source_file'] = 'construction_work_dictionary_v6_4_10.json + work-rate operation registry v1.2.0'
notes = payload['meta'].setdefault('notes', [])
note = 'v6.4.11: added additive operation_metadata/operation_packages and atomic operation registry for the work-rate catalogue; legacy rule fields operation/object are preserved.'
if note not in notes:
    notes.append(note)

DST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
print(DST)
print('operations', len(ops), 'objects', len(objects), 'rules', len(rules))
