BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-27';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    NULL,
    'Е3-27',
    'Е3-27',
    'Облицовка печей и очагов изразцами',
    '1 м2 облицованной поверхности',
    27
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'II'
WHERE c.code = 'Е3';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT
    p.id,
    0,
    '{"condition":"","operations":["1. Сортировка изразцов и подбор их по цвету и тону.","2. Распиловка изразцов и выпиливание отверстий для приборов.","3. Постановка изразцов по уровню и отвесу с пригонкой и притиркой их.","4. Укрепление изразцов проволокой.","5. Заполнение рамок готовым глиняным раствором и кирпичной щебенкой.","6. Расшивка швов облицовки с предварительной расчисткой и промывкой их меловым составом, с приготовлением гипсового раствора.","7. Протирка поверхности облицовки."]}'
FROM enir_paragraphs p
WHERE p.code = 'Е3-27';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, NULL, 0
FROM enir_paragraphs p
WHERE p.code = 'Е3-27';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, '1. Сортировка изразцов и подбор их по цвету и тону.'),
        (1, '2. Распиловка изразцов и выпиливание отверстий для приборов.'),
        (2, '3. Постановка изразцов по уровню и отвесу с пригонкой и притиркой их.'),
        (3, '4. Укрепление изразцов проволокой.'),
        (4, '5. Заполнение рамок готовым глиняным раствором и кирпичной щебенкой.'),
        (5, '6. Расшивка швов облицовки с предварительной расчисткой и промывкой их меловым составом, с приготовлением гипсового раствора.'),
        (6, '7. Протирка поверхности облицовки.')
    ) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-27';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT
    p.id,
    0,
    'Печник',
    5.0::numeric(4,1),
    1,
    'Печник 5 разр. - 1'
FROM enir_paragraphs p
WHERE p.code = 'Е3-27';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT
    p.id,
    'Печник',
    5.0::numeric(4,1),
    1
FROM enir_paragraphs p
WHERE p.code = 'Е3-27';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT
    p.id,
    0,
    'ПР-1',
    'На промывку и протирку изразцовых поверхностей после облицовки печи принимать на 1 м2 поверхности Н.вр. 0,17 чел.-ч печника 2 разр. Расц. 0-10,9 (ПР-1).',
    NULL,
    '{"post_wash_and_wipe_tiled_surface":true,"per_unit":"1m2_surface","add_n_vr":0.17,"add_rate":0.109,"worker_grade":2}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-27';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT
    p.id,
    1,
    'На промывку и протирку изразцовых поверхностей после облицовки печи принимать на 1 м2 поверхности Н.вр. 0,17 чел.-ч печника 2 разр. Расц. 0-10,9 (ПР-1).',
    NULL,
    'ПР-1',
    '{"post_wash_and_wipe_tiled_surface":true,"per_unit":"1m2_surface","add_n_vr":0.17,"add_rate":0.109,"worker_grade":2}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-27';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-27_table1', 0, 'Нормы времени и расценки на 1 м2 облицованной поверхности', 1
FROM enir_paragraphs p
WHERE p.code = 'Е3-27';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('direct_corner_upto_220', 0, 'Прямые и угловые до 220×220 мм', 'а'),
        ('direct_corner_gt_220', 1, 'Прямые и угловые более 220×220 мм', 'б'),
        ('rustics_and_others', 2, 'Рустики, уступы, цоколь и др.', 'в')
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-27_table1';

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT
    t.id,
    'Е3-27_r1',
    0,
    1,
    '{"work":"tile_facing_of_stoves_and_hearths"}'::jsonb
FROM enir_norm_tables t
WHERE t.source_table_id = 'Е3-27_table1';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    r.id,
    c.id,
    v.value_type,
    v.value_text,
    v.value_numeric
FROM enir_norm_rows r
JOIN enir_norm_tables t
  ON t.id = r.norm_table_id
JOIN (
    VALUES
        ('direct_corner_upto_220','n_vr','4,6',4.60::numeric),
        ('direct_corner_upto_220','rate','4-19',4.19::numeric),
        ('direct_corner_gt_220','n_vr','3',3.00::numeric),
        ('direct_corner_gt_220','rate','2-73',2.73::numeric),
        ('rustics_and_others','n_vr','5',5.00::numeric),
        ('rustics_and_others','rate','4-55',4.55::numeric)
) AS v(source_column_key, value_type, value_text, value_numeric)
ON true
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key
WHERE r.source_row_id = 'Е3-27_r1';

COMMIT;
