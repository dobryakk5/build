BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-21';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-21',
    'Е3-21',
    'Разные работы',
    'измерители, указанные в таблице',
    21
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'I'
JOIN enir_chapters ch
  ON ch.collection_id = c.id
 AND ch.source_chapter_id = '1'
WHERE c.code = 'Е3';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT p.id, v.sort_order, NULL, v.text, NULL, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            0,
            'Расценками строк № 17, 19 учтено применение самоходных кранов грузоподъемностью 5 т. При выполнении работ кранами большей грузоподъемности расценки следует пересчитывать в соответствии с разрядом машиниста крана (крановщика), установленного для этого крана.',
            '{"row_nums":[17,19],"requires_operator_rate_recalc_for_heavier_crane":true}'::jsonb
        ),
        (
            1,
            'Нормы строк № 21, 22 предусматривают разовую очистку рабочего места от снега и льда после длительного (более одной смены) перерыва в работе. Затраты труда на периодическую очистку рабочего места и материалов от снега и льда в течение рабочей смены учитываются зимними коэффициентами и дополнительной оплате не подлежат.',
            '{"row_nums":[21,22],"one_time_cleanup_after_break_only":true}'::jsonb
        )
) AS v(sort_order, text, conditions)
ON true
WHERE p.code = 'Е3-21';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT p.id, v.num, v.text, NULL, NULL, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            1,
            'Расценками строк № 17, 19 учтено применение самоходных кранов грузоподъемностью 5 т. При выполнении работ кранами большей грузоподъемности расценки следует пересчитывать в соответствии с разрядом машиниста крана (крановщика), установленного для этого крана.',
            '{"row_nums":[17,19],"requires_operator_rate_recalc_for_heavier_crane":true}'::jsonb
        ),
        (
            2,
            'Нормы строк № 21, 22 предусматривают разовую очистку рабочего места от снега и льда после длительного (более одной смены) перерыва в работе. Затраты труда на периодическую очистку рабочего места и материалов от снега и льда в течение рабочей смены учитываются зимними коэффициентами и дополнительной оплате не подлежат.',
            '{"row_nums":[21,22],"one_time_cleanup_after_break_only":true}'::jsonb
        )
) AS v(num, text, conditions)
ON true
WHERE p.code = 'Е3-21';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-21_table1', 0, 'Нормы времени и расценки на измерители, указанные в таблице', 23
FROM enir_paragraphs p
WHERE p.code = 'Е3-21';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('work_name', 0, 'Наименование работ', NULL),
        ('crew', 1, 'Состав звена', NULL),
        ('unit', 2, 'Единица измерения', NULL),
        ('norm_time', 3, 'Н.вр.', NULL),
        ('price_rub', 4, 'Расц.', NULL)
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-21_table1';

CREATE TEMP TABLE tmp_e3_21_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_21_rows
    (source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-21_r1', 0, 1, '{"work":"wedge_lintels_on_existing_formwork","jointing":true}'),
    ('Е3-21_r2', 1, 2, '{"work":"brick_posts_under_floor_joists","brick_type":["single","thickened"]}'),
    ('Е3-21_r3', 2, 3, '{"work":"pit_walls","material":"brick","thickness_bricks":0.5}'),
    ('Е3-21_r4', 3, 4, '{"work":"pit_walls","material":"brick","thickness_bricks":1.0}'),
    ('Е3-21_r5', 4, 5, '{"work":"pit_walls","material":"brick","thickness_bricks":1.5}'),
    ('Е3-21_r6', 5, 6, '{"work":"pit_walls","material":"brick","thickness_bricks":2.0}'),
    ('Е3-21_r7', 6, 7, '{"work":"pit_walls","material":"brick","thickness_bricks":2.5}'),
    ('Е3-21_r8', 7, 8, '{"work":"pit_walls","material":"brick","thickness_bricks":3.0,"thickness_rule":"and_more"}'),
    ('Е3-21_r9', 8, 9, '{"work":"pit_walls","material":"rubble_with_brick_facing_one_side"}'),
    ('Е3-21_r10', 9, 10, '{"work":"patching_large_block_walls_with_brick","volume_m3":{"lte":0.1}}'),
    ('Е3-21_r11', 10, 11, '{"work":"patching_large_block_walls_with_brick","volume_m3":{"lte":0.25}}'),
    ('Е3-21_r12', 11, 12, '{"work":"patching_large_block_walls_with_brick","volume_m3":{"lte":0.5}}'),
    ('Е3-21_r13', 12, 13, '{"work":"patching_large_block_walls_with_brick","volume_m3":{"lte":1.0}}'),
    ('Е3-21_r14', 13, 14, '{"work":"filling_nests_grooves_beam_ends_not_during_masonry"}'),
    ('Е3-21_r15', 14, 15, '{"work":"support_walls_under_large_panel_partitions"}'),
    ('Е3-21_r16', 15, 16, '{"work":"brick_facing_of_baths_one_side","thickness_bricks":0.25,"height_mm":{"lte":450}}'),
    ('Е3-21_r17', 16, 17, '{"work":"soaking_brick_on_pallets_or_containers","pallet_count":1,"lift_height_m":{"lte":12},"feed_distance_m":{"lte":50},"role":"crane_operator"}'),
    ('Е3-21_r18', 17, 18, '{"work":"soaking_brick_on_pallets_or_containers","pallet_count":1,"lift_height_m":{"lte":12},"feed_distance_m":{"lte":50},"role":"riggers"}'),
    ('Е3-21_r19', 18, 19, '{"work":"soaking_brick_on_pallets_or_containers","pallet_count":2,"lift_height_m":{"lte":12},"feed_distance_m":{"lte":50},"role":"crane_operator"}'),
    ('Е3-21_r20', 19, 20, '{"work":"soaking_brick_on_pallets_or_containers","pallet_count":2,"lift_height_m":{"lte":12},"feed_distance_m":{"lte":50},"role":"riggers"}'),
    ('Е3-21_r21', 20, 21, '{"work":"cleaning_workplace_from_snow_or_ice","target":["foundations","walls"],"measure":"1m3","ice_thickness_mm":{"lte":150}}'),
    ('Е3-21_r22', 21, 22, '{"work":"cleaning_workplace_from_snow_or_ice","target":["foundations","walls"],"measure":"1m2","ice_thickness_mm":{"lte":150}}'),
    ('Е3-21_r23', 22, 23, '{"work":"spreading_sand_on_workplace","carry_distance_m":{"lte":30}}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_21_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = 'Е3-21_table1';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    c.id,
    'cell',
    v.value_text,
    v.value_numeric
FROM tmp_e3_21_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-21_r1','work_name','Кладка клинчатых перемычек по ранее установленной опалубке с расшивкой швов',NULL::numeric),
        ('Е3-21_r1','crew','Каменщики 5 разр. - 1; 3 разр. - 1',NULL::numeric),
        ('Е3-21_r1','unit','1 м3 кладки',NULL::numeric),
        ('Е3-21_r1','norm_time','10,5',10.50::numeric),
        ('Е3-21_r1','price_rub','8-45',8.45::numeric),
        ('Е3-21_r2','work_name','Кладка кирпичных столбиков из одинарного и утолщенного кирпича под половые лаги',NULL::numeric),
        ('Е3-21_r2','crew','Каменщик 2 разр.',NULL::numeric),
        ('Е3-21_r2','unit','100 шт. кирпича в деле',NULL::numeric),
        ('Е3-21_r2','norm_time','2,1',2.10::numeric),
        ('Е3-21_r2','price_rub','1-34',1.34::numeric),
        ('Е3-21_r3','work_name','Кладка стен приямков с околкой кирпича и перелопачиванием раствора',NULL::numeric),
        ('Е3-21_r3','crew','Каменщик 3 разр.',NULL::numeric),
        ('Е3-21_r3','unit','1 м3 кладки',NULL::numeric),
        ('Е3-21_r3','norm_time','6',6.00::numeric),
        ('Е3-21_r3','price_rub','4-20',4.20::numeric),
        ('Е3-21_r4','work_name','Кладка стен приямков с околкой кирпича и перелопачиванием раствора',NULL::numeric),
        ('Е3-21_r4','crew','Каменщик 3 разр.',NULL::numeric),
        ('Е3-21_r4','unit','1 м3 кладки',NULL::numeric),
        ('Е3-21_r4','norm_time','4,1',4.10::numeric),
        ('Е3-21_r4','price_rub','2-87',2.87::numeric),
        ('Е3-21_r5','work_name','Кладка стен приямков с околкой кирпича и перелопачиванием раствора',NULL::numeric),
        ('Е3-21_r5','crew','Каменщик 3 разр.',NULL::numeric),
        ('Е3-21_r5','unit','1 м3 кладки',NULL::numeric),
        ('Е3-21_r5','norm_time','3,3',3.30::numeric),
        ('Е3-21_r5','price_rub','2-31',2.31::numeric),
        ('Е3-21_r6','work_name','Кладка стен приямков с околкой кирпича и перелопачиванием раствора',NULL::numeric),
        ('Е3-21_r6','crew','Каменщик 3 разр.',NULL::numeric),
        ('Е3-21_r6','unit','1 м3 кладки',NULL::numeric),
        ('Е3-21_r6','norm_time','2,8',2.80::numeric),
        ('Е3-21_r6','price_rub','1-96',1.96::numeric),
        ('Е3-21_r7','work_name','Кладка стен приямков с околкой кирпича и перелопачиванием раствора',NULL::numeric),
        ('Е3-21_r7','crew','Каменщик 3 разр.',NULL::numeric),
        ('Е3-21_r7','unit','1 м3 кладки',NULL::numeric),
        ('Е3-21_r7','norm_time','2,6',2.60::numeric),
        ('Е3-21_r7','price_rub','1-82',1.82::numeric),
        ('Е3-21_r8','work_name','Кладка стен приямков с околкой кирпича и перелопачиванием раствора',NULL::numeric),
        ('Е3-21_r8','crew','Каменщик 3 разр.',NULL::numeric),
        ('Е3-21_r8','unit','1 м3 кладки',NULL::numeric),
        ('Е3-21_r8','norm_time','2,3',2.30::numeric),
        ('Е3-21_r8','price_rub','1-61',1.61::numeric),
        ('Е3-21_r9','work_name','Кладка стен приямков из бутового камня с облицовкой кирпичом с одной стороны',NULL::numeric),
        ('Е3-21_r9','crew','Каменщик 3 разр.',NULL::numeric),
        ('Е3-21_r9','unit','1 м3 кладки',NULL::numeric),
        ('Е3-21_r9','norm_time','4,8',4.80::numeric),
        ('Е3-21_r9','price_rub','3-36',3.36::numeric),
        ('Е3-21_r10','work_name','Заделка кирпичом отдельных мест в крупноблочных стенах на цементном растворе с подбором и околкой кирпича, очисткой кладки от подтеков раствора',NULL::numeric),
        ('Е3-21_r10','crew','Каменщик 3 разр.',NULL::numeric),
        ('Е3-21_r10','unit','1 м3 кладки',NULL::numeric),
        ('Е3-21_r10','norm_time','8,5',8.50::numeric),
        ('Е3-21_r10','price_rub','5-95',5.95::numeric),
        ('Е3-21_r11','work_name','Заделка кирпичом отдельных мест в крупноблочных стенах на цементном растворе с подбором и околкой кирпича, очисткой кладки от подтеков раствора',NULL::numeric),
        ('Е3-21_r11','crew','Каменщик 3 разр.',NULL::numeric),
        ('Е3-21_r11','unit','1 м3 кладки',NULL::numeric),
        ('Е3-21_r11','norm_time','6,6',6.60::numeric),
        ('Е3-21_r11','price_rub','4-62',4.62::numeric),
        ('Е3-21_r12','work_name','Заделка кирпичом отдельных мест в крупноблочных стенах на цементном растворе с подбором и околкой кирпича, очисткой кладки от подтеков раствора',NULL::numeric),
        ('Е3-21_r12','crew','Каменщик 3 разр.',NULL::numeric),
        ('Е3-21_r12','unit','1 м3 кладки',NULL::numeric),
        ('Е3-21_r12','norm_time','5,5',5.50::numeric),
        ('Е3-21_r12','price_rub','3-85',3.85::numeric),
        ('Е3-21_r13','work_name','Заделка кирпичом отдельных мест в крупноблочных стенах на цементном растворе с подбором и околкой кирпича, очисткой кладки от подтеков раствора',NULL::numeric),
        ('Е3-21_r13','crew','Каменщик 3 разр.',NULL::numeric),
        ('Е3-21_r13','unit','1 м3 кладки',NULL::numeric),
        ('Е3-21_r13','norm_time','3,8',3.80::numeric),
        ('Е3-21_r13','price_rub','2-66',2.66::numeric),
        ('Е3-21_r14','work_name','Заделка одинарным и утолщенным кирпичом гнезд, борозд и балочных концов в кирпичных стенах',NULL::numeric),
        ('Е3-21_r14','crew','Каменщик 3 разр.',NULL::numeric),
        ('Е3-21_r14','unit','100 шт. кирпича в деле',NULL::numeric),
        ('Е3-21_r14','norm_time','3,9',3.90::numeric),
        ('Е3-21_r14','price_rub','2-73',2.73::numeric),
        ('Е3-21_r15','work_name','Кладка под крупнопанельные перегородки опорных стенок из кирпича размером 250×120×65 мм ложком, высотой в 1 ряд кирпича',NULL::numeric),
        ('Е3-21_r15','crew','Каменщик 3 разр.',NULL::numeric),
        ('Е3-21_r15','unit','100 м опорной стенки',NULL::numeric),
        ('Е3-21_r15','norm_time','12,5',12.50::numeric),
        ('Е3-21_r15','price_rub','8-75',8.75::numeric),
        ('Е3-21_r16','work_name','Облицовка ванн кирпичом с одной стороны в 1/4 кирпича на высоту до 450 мм на цементном растворе',NULL::numeric),
        ('Е3-21_r16','crew','Каменщик 3 разр.',NULL::numeric),
        ('Е3-21_r16','unit','1 м2 облицовки',NULL::numeric),
        ('Е3-21_r16','norm_time','1,2',1.20::numeric),
        ('Е3-21_r16','price_rub','0-84',0.84::numeric),
        ('Е3-21_r17','work_name','Замачивание кирпича на поддонах или контейнерах в емкостях с подъемом до 12 м и подачей до 50 м на рабочее место при помощи крана',NULL::numeric),
        ('Е3-21_r17','crew','Машинист крана (крановщик) 4 разр.',NULL::numeric),
        ('Е3-21_r17','unit','1000 шт. кирпича',NULL::numeric),
        ('Е3-21_r17','norm_time','0,38',0.38::numeric),
        ('Е3-21_r17','price_rub','0-30',0.30::numeric),
        ('Е3-21_r18','work_name','Замачивание кирпича на поддонах или контейнерах в емкостях с подъемом до 12 м и подачей до 50 м на рабочее место при помощи крана',NULL::numeric),
        ('Е3-21_r18','crew','Такелажники на монтаже 2 разр.',NULL::numeric),
        ('Е3-21_r18','unit','1000 шт. кирпича',NULL::numeric),
        ('Е3-21_r18','norm_time','0,76',0.76::numeric),
        ('Е3-21_r18','price_rub','0-48,6',0.486::numeric),
        ('Е3-21_r19','work_name','Замачивание кирпича на поддонах или контейнерах в емкостях с подъемом до 12 м и подачей до 50 м на рабочее место при помощи крана',NULL::numeric),
        ('Е3-21_r19','crew','Машинист крана (крановщик) 4 разр.',NULL::numeric),
        ('Е3-21_r19','unit','1000 шт. кирпича',NULL::numeric),
        ('Е3-21_r19','norm_time','0,26',0.26::numeric),
        ('Е3-21_r19','price_rub','0-20,5',0.205::numeric),
        ('Е3-21_r20','work_name','Замачивание кирпича на поддонах или контейнерах в емкостях с подъемом до 12 м и подачей до 50 м на рабочее место при помощи крана',NULL::numeric),
        ('Е3-21_r20','crew','Такелажники на монтаже 2 разр.',NULL::numeric),
        ('Е3-21_r20','unit','1000 шт. кирпича',NULL::numeric),
        ('Е3-21_r20','norm_time','0,52',0.52::numeric),
        ('Е3-21_r20','price_rub','0-33,3',0.333::numeric),
        ('Е3-21_r21','work_name','Очистка рабочего места, фундаментов и стен от снега и льда с отбрасыванием их на расстояние до 3 м',NULL::numeric),
        ('Е3-21_r21','crew','Подсобный рабочий 1 разр.',NULL::numeric),
        ('Е3-21_r21','unit','1 м3 по обмеру до очистки',NULL::numeric),
        ('Е3-21_r21','norm_time','0,12',0.12::numeric),
        ('Е3-21_r21','price_rub','0-07,1',0.071::numeric),
        ('Е3-21_r22','work_name','Очистка рабочего места, фундаментов и стен от снега и льда толщиной до 150 мм',NULL::numeric),
        ('Е3-21_r22','crew','Подсобный рабочий 1 разр.',NULL::numeric),
        ('Е3-21_r22','unit','1 м2',NULL::numeric),
        ('Е3-21_r22','norm_time','0,09',0.09::numeric),
        ('Е3-21_r22','price_rub','0-05,3',0.053::numeric),
        ('Е3-21_r23','work_name','Посыпка рабочего места песком с подноской его на расстояние до 30 м',NULL::numeric),
        ('Е3-21_r23','crew','Подсобный рабочий 1 разр.',NULL::numeric),
        ('Е3-21_r23','unit','100 м2',NULL::numeric),
        ('Е3-21_r23','norm_time','0,65',0.65::numeric),
        ('Е3-21_r23','price_rub','0-38,4',0.384::numeric)
) AS v(source_row_id, source_column_key, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key;

COMMIT;
