BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-17';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-17',
    'Е3-17',
    'Укладка железобетонных, каменных конструктивных элементов и деталей вручную',
    'измерители, указанные в таблице',
    17
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'I'
JOIN enir_chapters ch
  ON ch.collection_id = c.id
 AND ch.source_chapter_id = '1'
WHERE c.code = 'Е3';

INSERT INTO enir_paragraph_technical_characteristics (paragraph_id, sort_order, raw_text)
SELECT
    p.id,
    0,
    'Нормами предусмотрена укладка железобетонных и каменных изделий массой до 100 кг.'
FROM enir_paragraphs p
WHERE p.code = 'Е3-17';

INSERT INTO enir_paragraph_application_notes (paragraph_id, sort_order, text)
SELECT p.id, v.sort_order, v.text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'При длине ступеней до 1,4 м Н.вр. и Расц. умножать на 1,1 (ПР-1), до 1,6 м - на 1,25 (ПР-2) и до 2 м - на 1,5 (ПР-3).'),
        (1, 'При укладке забежных ступеней Н.вр. и Расц. строк № 7-12 умножать на 1,2 (ПР-4).')
) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-17';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT p.id, v.sort_order, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            0,
            '{"condition":"При укладке перемычек, досок подоконных мозаичных и плит (строки № 1-6, 13-15)","operations":["1. Очистка основания со смачиванием его (в необходимых случаях).","2. Укладка элементов и деталей на раствор.","3. Пригонка элементов и деталей по месту.","4. Заполнение швов раствором."]}'
        ),
        (
            1,
            '{"condition":"При укладке ступеней (строки № 7-12)","operations":["1. Установка ступеней на место с подгонкой их.","2. Заделка раствором щелей между проступью и подступенком.","3. Заделка концов ступеней в стену на растворе с частичной разработкой гнезд (при укладке ступеней на один косоур).","4. Подрубка ступеней (при необходимости)."]}'
        )
) AS v(sort_order, raw_text)
ON true
WHERE p.code = 'Е3-17';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, v.condition, v.sort_order
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'При укладке перемычек, досок подоконных мозаичных и плит (строки № 1-6, 13-15)'),
        (1, 'При укладке ступеней (строки № 7-12)')
) AS v(sort_order, condition)
ON true
WHERE p.code = 'Е3-17';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, 0, '1. Очистка основания со смачиванием его (в необходимых случаях).'),
        (0, 1, '2. Укладка элементов и деталей на раствор.'),
        (0, 2, '3. Пригонка элементов и деталей по месту.'),
        (0, 3, '4. Заполнение швов раствором.'),
        (1, 0, '1. Установка ступеней на место с подгонкой их.'),
        (1, 1, '2. Заделка раствором щелей между проступью и подступенком.'),
        (1, 2, '3. Заделка концов ступеней в стену на растворе с частичной разработкой гнезд (при укладке ступеней на один косоур).'),
        (1, 3, '4. Подрубка ступеней (при необходимости).')
    ) AS v(composition_sort_order, sort_order, text)
  ON v.composition_sort_order = wc.sort_order
WHERE p.code = 'Е3-17';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Каменщик', 4.0::numeric(4,1), 1, 'Каменщик 4 разр. - 1'),
        (1, 'Каменщик', 3.0::numeric(4,1), 1, 'Каменщик 3 разр. - 1')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-17';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Каменщик', 4.0::numeric(4,1), 1),
        ('Каменщик', 3.0::numeric(4,1), 1)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-17';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT p.id, v.sort_order, v.code, v.text, v.coefficient, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'ПР-1', 'При длине ступеней до 1,4 м Н.вр. и Расц. строк № 7-12 умножать на 1,1 (ПР-1).', 1.10::numeric(6,4), '{"row_range":[7,12],"step_length_m":{"lte":1.4}}'::jsonb),
        (1, 'ПР-2', 'При длине ступеней до 1,6 м Н.вр. и Расц. строк № 7-12 умножать на 1,25 (ПР-2).', 1.25::numeric(6,4), '{"row_range":[7,12],"step_length_m":{"lte":1.6}}'::jsonb),
        (2, 'ПР-3', 'При длине ступеней до 2 м Н.вр. и Расц. строк № 7-12 умножать на 1,5 (ПР-3).', 1.50::numeric(6,4), '{"row_range":[7,12],"step_length_m":{"lte":2.0}}'::jsonb),
        (3, 'ПР-4', 'При укладке забежных ступеней Н.вр. и Расц. строк № 7-12 умножать на 1,2 (ПР-4).', 1.20::numeric(6,4), '{"row_range":[7,12],"step_type":"winder"}'::jsonb),
        (4, NULL, 'Нормами предусмотрена укладка железобетонных и каменных изделий массой до 100 кг.', NULL::numeric(6,4), '{"max_item_weight_kg":100}'::jsonb)
) AS v(sort_order, code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-17';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT p.id, v.num, v.text, v.coefficient, v.pr_code, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (1, 'ПР-1', 'При длине ступеней до 1,4 м Н.вр. и Расц. строк № 7-12 умножать на 1,1 (ПР-1).', 1.10::numeric(6,4), '{"row_range":[7,12],"step_length_m":{"lte":1.4}}'::jsonb),
        (2, 'ПР-2', 'При длине ступеней до 1,6 м Н.вр. и Расц. строк № 7-12 умножать на 1,25 (ПР-2).', 1.25::numeric(6,4), '{"row_range":[7,12],"step_length_m":{"lte":1.6}}'::jsonb),
        (3, 'ПР-3', 'При длине ступеней до 2 м Н.вр. и Расц. строк № 7-12 умножать на 1,5 (ПР-3).', 1.50::numeric(6,4), '{"row_range":[7,12],"step_length_m":{"lte":2.0}}'::jsonb),
        (4, 'ПР-4', 'При укладке забежных ступеней Н.вр. и Расц. строк № 7-12 умножать на 1,2 (ПР-4).', 1.20::numeric(6,4), '{"row_range":[7,12],"step_type":"winder"}'::jsonb),
        (5, NULL, 'Нормами предусмотрена укладка железобетонных и каменных изделий массой до 100 кг.', NULL::numeric(6,4), '{"max_item_weight_kg":100}'::jsonb)
) AS v(num, pr_code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-17';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-17_table1', 0, 'Нормы времени и расценки на измерители, указанные в таблице', 15
FROM enir_paragraphs p
WHERE p.code = 'Е3-17';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('element_name', 0, 'Наименование элементов и деталей', NULL),
        ('detail', 1, 'Характеристика', NULL),
        ('placement', 2, 'Укладка / исполнение', NULL),
        ('unit', 3, 'Единица измерения', NULL),
        ('norm_time', 4, 'Н.вр.', NULL),
        ('price_rub', 5, 'Расц.', NULL)
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-17_table1';

CREATE TEMP TABLE tmp_e3_17_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_17_rows
    (source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-17_r1', 0, 1, '{"element":"reinforced_concrete_lintel","unit":"1_opening"}'),
    ('Е3-17_r2', 1, 2, '{"element":"reinforced_concrete_parapet_slab","area_m2":{"lte":0.5},"unit":"1_slab"}'),
    ('Е3-17_r3', 2, 3, '{"element":"reinforced_concrete_slab","area_m2":{"lte":0.8},"placement":"ibeam_lower_flange","joint_filling":false,"unit":"1_slab"}'),
    ('Е3-17_r4', 3, 4, '{"element":"reinforced_concrete_slab","area_m2":{"lte":0.8},"placement":"ibeam_lower_flange","joint_filling":true,"unit":"1_slab"}'),
    ('Е3-17_r5', 4, 5, '{"element":"slab","joint_filling":true,"groove_filling":true,"slab_type":"bearing_under_beam_ends","unit":"1m2_slab"}'),
    ('Е3-17_r6', 5, 6, '{"element":"slab","joint_filling":true,"groove_filling":true,"slab_type":"cornice_window_sill_landing","unit":"1m2_slab"}'),
    ('Е3-17_r7', 6, 7, '{"element":"step","material":"hollow_reinforced_concrete_or_mosaic","placement":"on_stringers","unit":"1_step"}'),
    ('Е3-17_r8', 7, 8, '{"element":"step","material":"hollow_reinforced_concrete_or_mosaic","placement":"on_solid_base","unit":"1_step"}'),
    ('Е3-17_r9', 8, 9, '{"element":"step","material":"solid_reinforced_concrete_or_mosaic","placement":"on_stringers","unit":"1_step"}'),
    ('Е3-17_r10', 9, 10, '{"element":"step","material":"solid_reinforced_concrete_or_mosaic","placement":"on_solid_base","unit":"1_step"}'),
    ('Е3-17_r11', 10, 11, '{"element":"step","material":"stone","placement":"on_stringers","unit":"1_step"}'),
    ('Е3-17_r12', 11, 12, '{"element":"step","material":"stone","placement":"on_solid_base","unit":"1_step"}'),
    ('Е3-17_r13', 12, 13, '{"element":"mosaic_window_sill_board","area_m2":{"lte":0.35},"unit":"1_board"}'),
    ('Е3-17_r14', 13, 14, '{"element":"mosaic_window_sill_board","area_m2":{"lte":0.65},"unit":"1_board"}'),
    ('Е3-17_r15', 14, 15, '{"element":"mosaic_window_sill_board","area_m2":{"lte":1.0},"unit":"1_board"}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_17_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = 'Е3-17_table1';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    c.id,
    'cell',
    v.value_text,
    v.value_numeric
FROM tmp_e3_17_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-17_r1', 'element_name', 'Железобетонные перемычки', NULL::numeric),
        ('Е3-17_r1', 'detail', NULL, NULL::numeric),
        ('Е3-17_r1', 'placement', NULL, NULL::numeric),
        ('Е3-17_r1', 'unit', '1 проем', NULL::numeric),
        ('Е3-17_r1', 'norm_time', '0,57', 0.57::numeric),
        ('Е3-17_r1', 'price_rub', '0-42,5', 0.425::numeric),
        ('Е3-17_r2', 'element_name', 'Железобетонные парапетные плиты', NULL::numeric),
        ('Е3-17_r2', 'detail', 'Площадью до 0,5 м2', NULL::numeric),
        ('Е3-17_r2', 'placement', NULL, NULL::numeric),
        ('Е3-17_r2', 'unit', '1 плита', NULL::numeric),
        ('Е3-17_r2', 'norm_time', '0,32', 0.32::numeric),
        ('Е3-17_r2', 'price_rub', '0-23,8', 0.238::numeric),
        ('Е3-17_r3', 'element_name', 'Железобетонные плиты, укладываемые по нижним полкам двутавровых балок', NULL::numeric),
        ('Е3-17_r3', 'detail', 'Площадью до 0,8 м2', NULL::numeric),
        ('Е3-17_r3', 'placement', 'Без заделки швов', NULL::numeric),
        ('Е3-17_r3', 'unit', '1 плита', NULL::numeric),
        ('Е3-17_r3', 'norm_time', '0,11', 0.11::numeric),
        ('Е3-17_r3', 'price_rub', '0-08,2', 0.082::numeric),
        ('Е3-17_r4', 'element_name', 'Железобетонные плиты, укладываемые по нижним полкам двутавровых балок', NULL::numeric),
        ('Е3-17_r4', 'detail', 'Площадью до 0,8 м2', NULL::numeric),
        ('Е3-17_r4', 'placement', 'С заделкой швов', NULL::numeric),
        ('Е3-17_r4', 'unit', '1 плита', NULL::numeric),
        ('Е3-17_r4', 'norm_time', '0,13', 0.13::numeric),
        ('Е3-17_r4', 'price_rub', '0-09,7', 0.097::numeric),
        ('Е3-17_r5', 'element_name', 'Плиты с заделкой швов и борозд', NULL::numeric),
        ('Е3-17_r5', 'detail', 'Прокладные под концы балок в стенах и столбах', NULL::numeric),
        ('Е3-17_r5', 'placement', NULL, NULL::numeric),
        ('Е3-17_r5', 'unit', '1 м2 плиты', NULL::numeric),
        ('Е3-17_r5', 'norm_time', '0,38', 0.38::numeric),
        ('Е3-17_r5', 'price_rub', '0-28,3', 0.283::numeric),
        ('Е3-17_r6', 'element_name', 'Плиты с заделкой швов и борозд', NULL::numeric),
        ('Е3-17_r6', 'detail', 'Карнизные, подоконные и для лестничных площадок', NULL::numeric),
        ('Е3-17_r6', 'placement', NULL, NULL::numeric),
        ('Е3-17_r6', 'unit', '1 м2 плиты', NULL::numeric),
        ('Е3-17_r6', 'norm_time', '0,85', 0.85::numeric),
        ('Е3-17_r6', 'price_rub', '0-63,3', 0.633::numeric),
        ('Е3-17_r7', 'element_name', 'Ступени', NULL::numeric),
        ('Е3-17_r7', 'detail', 'Пустотелые железобетонные и мозаичные', NULL::numeric),
        ('Е3-17_r7', 'placement', 'На косоуры', NULL::numeric),
        ('Е3-17_r7', 'unit', '1 ступень', NULL::numeric),
        ('Е3-17_r7', 'norm_time', '0,33', 0.33::numeric),
        ('Е3-17_r7', 'price_rub', '0-24,6', 0.246::numeric),
        ('Е3-17_r8', 'element_name', 'Ступени', NULL::numeric),
        ('Е3-17_r8', 'detail', 'Пустотелые железобетонные и мозаичные', NULL::numeric),
        ('Е3-17_r8', 'placement', 'На сплошное основание', NULL::numeric),
        ('Е3-17_r8', 'unit', '1 ступень', NULL::numeric),
        ('Е3-17_r8', 'norm_time', '0,39', 0.39::numeric),
        ('Е3-17_r8', 'price_rub', '0-29,1', 0.291::numeric),
        ('Е3-17_r9', 'element_name', 'Ступени', NULL::numeric),
        ('Е3-17_r9', 'detail', 'Сплошные железобетонные и мозаичные', NULL::numeric),
        ('Е3-17_r9', 'placement', 'На косоуры', NULL::numeric),
        ('Е3-17_r9', 'unit', '1 ступень', NULL::numeric),
        ('Е3-17_r9', 'norm_time', '0,49', 0.49::numeric),
        ('Е3-17_r9', 'price_rub', '0-36,5', 0.365::numeric),
        ('Е3-17_r10', 'element_name', 'Ступени', NULL::numeric),
        ('Е3-17_r10', 'detail', 'Сплошные железобетонные и мозаичные', NULL::numeric),
        ('Е3-17_r10', 'placement', 'На сплошное основание', NULL::numeric),
        ('Е3-17_r10', 'unit', '1 ступень', NULL::numeric),
        ('Е3-17_r10', 'norm_time', '0,78', 0.78::numeric),
        ('Е3-17_r10', 'price_rub', '0-58,1', 0.581::numeric),
        ('Е3-17_r11', 'element_name', 'Каменные ступени', NULL::numeric),
        ('Е3-17_r11', 'detail', NULL, NULL::numeric),
        ('Е3-17_r11', 'placement', 'На косоуры', NULL::numeric),
        ('Е3-17_r11', 'unit', '1 ступень', NULL::numeric),
        ('Е3-17_r11', 'norm_time', '0,6', 0.60::numeric),
        ('Е3-17_r11', 'price_rub', '0-44,7', 0.447::numeric),
        ('Е3-17_r12', 'element_name', 'Каменные ступени', NULL::numeric),
        ('Е3-17_r12', 'detail', NULL, NULL::numeric),
        ('Е3-17_r12', 'placement', 'На сплошное основание', NULL::numeric),
        ('Е3-17_r12', 'unit', '1 ступень', NULL::numeric),
        ('Е3-17_r12', 'norm_time', '1', 1.00::numeric),
        ('Е3-17_r12', 'price_rub', '0-74,5', 0.745::numeric),
        ('Е3-17_r13', 'element_name', 'Доски подоконные мозаичные', NULL::numeric),
        ('Е3-17_r13', 'detail', 'Площадью до 0,35 м2', NULL::numeric),
        ('Е3-17_r13', 'placement', NULL, NULL::numeric),
        ('Е3-17_r13', 'unit', '1 доска', NULL::numeric),
        ('Е3-17_r13', 'norm_time', '0,29', 0.29::numeric),
        ('Е3-17_r13', 'price_rub', '0-21,6', 0.216::numeric),
        ('Е3-17_r14', 'element_name', 'Доски подоконные мозаичные', NULL::numeric),
        ('Е3-17_r14', 'detail', 'Площадью до 0,65 м2', NULL::numeric),
        ('Е3-17_r14', 'placement', NULL, NULL::numeric),
        ('Е3-17_r14', 'unit', '1 доска', NULL::numeric),
        ('Е3-17_r14', 'norm_time', '0,4', 0.40::numeric),
        ('Е3-17_r14', 'price_rub', '0-29,8', 0.298::numeric),
        ('Е3-17_r15', 'element_name', 'Доски подоконные мозаичные', NULL::numeric),
        ('Е3-17_r15', 'detail', 'Площадью до 1 м2', NULL::numeric),
        ('Е3-17_r15', 'placement', NULL, NULL::numeric),
        ('Е3-17_r15', 'unit', '1 доска', NULL::numeric),
        ('Е3-17_r15', 'norm_time', '0,75', 0.75::numeric),
        ('Е3-17_r15', 'price_rub', '0-55,9', 0.559::numeric)
) AS v(source_row_id, source_column_key, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key;

COMMIT;
