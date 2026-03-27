BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-3';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-3',
    'Е3-3',
    'Кладка стен из кирпича',
    '1 м3 кладки',
    2
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'I'
JOIN enir_chapters ch
  ON ch.collection_id = c.id
 AND ch.source_chapter_id = '1'
WHERE c.code = 'Е3';

INSERT INTO enir_paragraph_application_notes (paragraph_id, sort_order, text)
SELECT p.id, v.sort_order, v.text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Указания по качеству работ.'),
        (1, 'Кладка стен не должна иметь отклонений, превышающих допуски, указанные в табл. 1.'),
        (2, 'Смещение опорных подушек под ригели, фермы и подкрановые балки и другие несущие конструкции в плане от проектного положения в любом направлении не должно превышать 10 мм, если иные требования не оговорены проектом. Отклонения в отметках по высоте этажа (в пределах допуска по табл. 1) должны исправляться в последующих этажах.'),
        (3, 'Толщина горизонтальных швов кирпичной кладки должна быть не менее 10 и не более 15 мм. Для вертикальных швов кладки допускаемая толщина швов должна быть в пределах 8-15 мм. Толщина швов армированной кладки должна превышать диаметр арматуры не менее чем на 4 мм.')
) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-3';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT p.id, v.sort_order, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            0,
            '{"condition":"А. При обычной кладке","operations":["1. Натягивание причалки.","2. Подача и раскладка кирпича.","3. Перелопачивание, расстилание и разравнивание раствора.","4. Кладка стен с выкладкой всех усложнений кладки, подбором, околкой и отеской кирпича.","5. Заделка балочных гнезд.","6. Расшивка швов (при кладке с расшивкой)."]}'
        ),
        (
            1,
            '{"condition":"Б. При кладке с совмещенными вертикальными швами","operations":["1. Натягивание причалки.","2. Подача и раскладка кирпича с подбором кирпича для наружной версты и очисткой от загрязнений (при необходимости).","3. Перелопачивание, расстилание и разравнивание раствора.","4. Кладка стен с выкладкой всех усложнений кладки, с подбором, околкой и отеской кирпича.","5. Расшивка швов стен с одной стороны."]}'
        )
) AS v(sort_order, raw_text)
ON true
WHERE p.code = 'Е3-3';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, v.condition, v.sort_order
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'А. При обычной кладке'),
        (1, 'Б. При кладке с совмещенными вертикальными швами')
) AS v(sort_order, condition)
ON true
WHERE p.code = 'Е3-3';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, 0, '1. Натягивание причалки.'),
        (0, 1, '2. Подача и раскладка кирпича.'),
        (0, 2, '3. Перелопачивание, расстилание и разравнивание раствора.'),
        (0, 3, '4. Кладка стен с выкладкой всех усложнений кладки, подбором, околкой и отеской кирпича.'),
        (0, 4, '5. Заделка балочных гнезд.'),
        (0, 5, '6. Расшивка швов (при кладке с расшивкой).'),
        (1, 0, '1. Натягивание причалки.'),
        (1, 1, '2. Подача и раскладка кирпича с подбором кирпича для наружной версты и очисткой от загрязнений (при необходимости).'),
        (1, 2, '3. Перелопачивание, расстилание и разравнивание раствора.'),
        (1, 3, '4. Кладка стен с выкладкой всех усложнений кладки, с подбором, околкой и отеской кирпича.'),
        (1, 4, '5. Расшивка швов стен с одной стороны.')
) AS v(composition_sort_order, sort_order, text)
  ON v.composition_sort_order = wc.sort_order
WHERE p.code = 'Е3-3';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Каменщик', 5.0::numeric(4,1), 1, 'Каменщик 5 разр. - 1 (сложные стены)'),
        (1, 'Каменщик', 4.0::numeric(4,1), 1, 'Каменщик 4 разр. - 1 (стены средней сложности)'),
        (2, 'Каменщик', 3.0::numeric(4,1), 2, 'Каменщик 3 разр. - 2 (простые стены)'),
        (3, 'Каменщик', 3.0::numeric(4,1), 1, 'Каменщик 3 разр. - 1 (стены средней сложности, сложные и заполнение стен каркасных зданий)')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-3';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Каменщик', 5.0::numeric(4,1), 1),
        ('Каменщик', 4.0::numeric(4,1), 1),
        ('Каменщик', 3.0::numeric(4,1), 2),
        ('Каменщик', 3.0::numeric(4,1), 1)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-3';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT p.id, v.sort_order, v.code, v.text, v.coefficient, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            0,
            'ПР-1',
            'Кладку стен зданий с проемностью от 40 до 60% нормировать по нормам и расценкам § Е3-3 табл. 3 и 4 с коэффициентом 1,1 (ПР-1).',
            1.10::numeric(6,4),
            '{"opening_ratio":{"gte":0.40,"lte":0.60},"table_scope":["Е3-3_table3","Е3-3_table4"]}'::jsonb
        ),
        (
            1,
            'ПР-2',
            'При заполнении каркасных стен с подкосами Н.вр. и Расц. § Е3-3 табл. 5 умножать на 1,2 (ПР-2).',
            1.20::numeric(6,4),
            '{"structure":"frame_wall_infill","has_braces":true,"table_scope":["Е3-3_table5"]}'::jsonb
        )
) AS v(sort_order, code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-3';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT p.id, v.num, v.text, v.coefficient, v.pr_code, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            1,
            'ПР-1',
            'Кладку стен зданий с проемностью от 40 до 60% нормировать по нормам и расценкам § Е3-3 табл. 3 и 4 с коэффициентом 1,1 (ПР-1).',
            1.10::numeric(6,4),
            '{"opening_ratio":{"gte":0.40,"lte":0.60},"table_scope":["Е3-3_table3","Е3-3_table4"]}'::jsonb
        ),
        (
            2,
            'ПР-2',
            'При заполнении каркасных стен с подкосами Н.вр. и Расц. § Е3-3 табл. 5 умножать на 1,2 (ПР-2).',
            1.20::numeric(6,4),
            '{"structure":"frame_wall_infill","has_braces":true,"table_scope":["Е3-3_table5"]}'::jsonb
        )
) AS v(num, pr_code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-3';

INSERT INTO enir_technical_coefficients
    (collection_id, code, description, multiplier, conditions, sort_order)
SELECT c.id, v.code, v.description, v.multiplier, v.conditions, v.sort_order
FROM enir_collections c
JOIN (
    VALUES
        (
            'ТЧ-7',
            'Кладка стен зданий с проемностью наружных стен до 5%',
            0.90::numeric(8,4),
            '{"opening_ratio":{"lte":0.05}}'::jsonb,
            7
        ),
        (
            'ТЧ-8',
            'Заделка оставленных в процессе кладки разрывов длиной до 2 м',
            1.25::numeric(8,4),
            '{"gap_fill":true}'::jsonb,
            8
        )
) AS v(code, description, multiplier, conditions, sort_order)
ON true
WHERE c.code = 'Е3'
  AND NOT EXISTS (
      SELECT 1
      FROM enir_technical_coefficients tc
      WHERE tc.collection_id = c.id
        AND tc.code = v.code
  );

INSERT INTO enir_technical_coefficient_paragraphs (technical_coefficient_id, paragraph_id)
SELECT tc.id, p.id
FROM enir_technical_coefficients tc
JOIN enir_collections c
  ON c.id = tc.collection_id
JOIN enir_paragraphs p
  ON p.collection_id = c.id
WHERE c.code = 'Е3'
  AND p.code = 'Е3-3'
  AND tc.code IN ('ТЧ-7', 'ТЧ-8')
  AND NOT EXISTS (
      SELECT 1
      FROM enir_technical_coefficient_paragraphs tcp
      WHERE tcp.technical_coefficient_id = tc.id
        AND tcp.paragraph_id = p.id
  );

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, v.source_table_id, v.sort_order, v.title, v.row_count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Е3-3_table3', 0, 'Нормы времени и расценки на 1 м3 кладки', 10),
        ('Е3-3_table4', 1, 'Нормы времени и расценки на 1 м3 кладки', 6),
        ('Е3-3_table5', 2, 'Нормы времени и расценки на 1 м3 заполнения', 2)
) AS v(source_table_id, sort_order, title, row_count)
ON true
WHERE p.code = 'Е3-3';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('Е3-3_table3', 'thickness_bricks', 0, 'Толщина стен в кирпичах', NULL),
        ('Е3-3_table3', 'finish_type', 1, 'Вид кладки', NULL),
        ('Е3-3_table3', 'simple_solid', 2, 'Простые, глухие', 'а'),
        ('Е3-3_table3', 'simple_openings', 3, 'Простые, с проемами', 'б'),
        ('Е3-3_table3', 'medium_openings', 4, 'Средней сложности, с проемами', 'в'),
        ('Е3-3_table3', 'complex_openings', 5, 'Сложные, с проемами', 'г'),
        ('Е3-3_table4', 'thickness_bricks', 0, 'Толщина стен в кирпичах', NULL),
        ('Е3-3_table4', 'simple', 1, 'Простые', 'а'),
        ('Е3-3_table4', 'medium', 2, 'Средней сложности', 'б'),
        ('Е3-3_table4', 'complex', 3, 'Сложные', 'в'),
        ('Е3-3_table5', 'finish_type', 0, 'Вид кладки', NULL),
        ('Е3-3_table5', 'thickness_0_5', 1, '1/2 кирпича', 'а'),
        ('Е3-3_table5', 'thickness_1', 2, '1 кирпич', 'б'),
        ('Е3-3_table5', 'thickness_1_5', 3, '1 1/2 кирпича', 'в'),
        ('Е3-3_table5', 'thickness_2', 4, '2 кирпича', 'г'),
        ('Е3-3_table5', 'thickness_2_5', 5, '2 1/2 кирпича', 'д')
) AS v(table_key, source_column_key, sort_order, header, label)
  ON v.table_key = t.source_table_id;

CREATE TEMP TABLE tmp_e3_3_rows (
    table_key text NOT NULL,
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_3_rows
    (table_key, source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-3_table3', 'Е3-3_t3_r1', 0, 1, '{"structure":"wall","brickwork_type":"ordinary","thickness_bricks":1.0,"finish":"under_plaster"}'),
    ('Е3-3_table3', 'Е3-3_t3_r2', 1, 2, '{"structure":"wall","brickwork_type":"ordinary","thickness_bricks":1.0,"finish":"jointing"}'),
    ('Е3-3_table3', 'Е3-3_t3_r3', 2, 3, '{"structure":"wall","brickwork_type":"ordinary","thickness_bricks":1.5,"finish":"under_plaster"}'),
    ('Е3-3_table3', 'Е3-3_t3_r4', 3, 4, '{"structure":"wall","brickwork_type":"ordinary","thickness_bricks":1.5,"finish":"jointing"}'),
    ('Е3-3_table3', 'Е3-3_t3_r5', 4, 5, '{"structure":"wall","brickwork_type":"ordinary","thickness_bricks":2.0,"finish":"under_plaster"}'),
    ('Е3-3_table3', 'Е3-3_t3_r6', 5, 6, '{"structure":"wall","brickwork_type":"ordinary","thickness_bricks":2.0,"finish":"jointing"}'),
    ('Е3-3_table3', 'Е3-3_t3_r7', 6, 7, '{"structure":"wall","brickwork_type":"ordinary","thickness_bricks":2.5,"finish":"under_plaster"}'),
    ('Е3-3_table3', 'Е3-3_t3_r8', 7, 8, '{"structure":"wall","brickwork_type":"ordinary","thickness_bricks":2.5,"finish":"jointing"}'),
    ('Е3-3_table3', 'Е3-3_t3_r9', 8, 9, '{"structure":"wall","brickwork_type":"ordinary","thickness_bricks_min":3.0,"finish":"under_plaster"}'),
    ('Е3-3_table3', 'Е3-3_t3_r10', 9, 10, '{"structure":"wall","brickwork_type":"ordinary","thickness_bricks_min":3.0,"finish":"jointing"}'),
    ('Е3-3_table4', 'Е3-3_t4_r1', 10, 1, '{"structure":"wall","brickwork_type":"combined_vertical_joints","thickness_bricks":1.0}'),
    ('Е3-3_table4', 'Е3-3_t4_r2', 11, 2, '{"structure":"wall","brickwork_type":"combined_vertical_joints","thickness_bricks":1.5}'),
    ('Е3-3_table4', 'Е3-3_t4_r3', 12, 3, '{"structure":"wall","brickwork_type":"combined_vertical_joints","thickness_bricks":2.0}'),
    ('Е3-3_table4', 'Е3-3_t4_r4', 13, 4, '{"structure":"wall","brickwork_type":"combined_vertical_joints","thickness_bricks":2.5}'),
    ('Е3-3_table4', 'Е3-3_t4_r5', 14, 5, '{"structure":"wall","brickwork_type":"combined_vertical_joints","thickness_bricks":3.0}'),
    ('Е3-3_table4', 'Е3-3_t4_r6', 15, 6, '{"structure":"wall","brickwork_type":"combined_vertical_joints","thickness_bricks":3.5}'),
    ('Е3-3_table5', 'Е3-3_t5_r1', 16, 1, '{"structure":"frame_wall_infill","finish":"under_plaster"}'),
    ('Е3-3_table5', 'Е3-3_t5_r2', 17, 2, '{"structure":"frame_wall_infill","finish":"jointing"}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_3_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = r.table_key;

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    nc.id,
    v.value_type,
    v.value_text,
    v.value_numeric
FROM tmp_e3_3_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-3_t3_r1', 'thickness_bricks', 'cell', '1', NULL::numeric),
        ('Е3-3_t3_r1', 'finish_type', 'cell', 'Под штукатурку', NULL::numeric),
        ('Е3-3_t3_r1', 'simple_solid', 'n_vr', '3,2', 3.20::numeric),
        ('Е3-3_t3_r1', 'simple_solid', 'rate', '2-24', 2.24::numeric),
        ('Е3-3_t3_r1', 'simple_openings', 'n_vr', '3,7', 3.70::numeric),
        ('Е3-3_t3_r1', 'simple_openings', 'rate', '2-59', 2.59::numeric),

        ('Е3-3_t3_r2', 'thickness_bricks', 'cell', '1', NULL::numeric),
        ('Е3-3_t3_r2', 'finish_type', 'cell', 'С расшивкой', NULL::numeric),
        ('Е3-3_t3_r2', 'simple_solid', 'n_vr', '4', 4.00::numeric),
        ('Е3-3_t3_r2', 'simple_solid', 'rate', '2-80', 2.80::numeric),
        ('Е3-3_t3_r2', 'simple_openings', 'n_vr', '4,6', 4.60::numeric),
        ('Е3-3_t3_r2', 'simple_openings', 'rate', '3-22', 3.22::numeric),

        ('Е3-3_t3_r3', 'thickness_bricks', 'cell', '1 1/2', NULL::numeric),
        ('Е3-3_t3_r3', 'finish_type', 'cell', 'Под штукатурку', NULL::numeric),
        ('Е3-3_t3_r3', 'simple_solid', 'n_vr', '2,6', 2.60::numeric),
        ('Е3-3_t3_r3', 'simple_solid', 'rate', '1-82', 1.82::numeric),
        ('Е3-3_t3_r3', 'simple_openings', 'n_vr', '3,2', 3.20::numeric),
        ('Е3-3_t3_r3', 'simple_openings', 'rate', '2-24', 2.24::numeric),
        ('Е3-3_t3_r3', 'medium_openings', 'n_vr', '3,7', 3.70::numeric),
        ('Е3-3_t3_r3', 'medium_openings', 'rate', '2-76', 2.76::numeric),
        ('Е3-3_t3_r3', 'complex_openings', 'n_vr', '4,3', 4.30::numeric),
        ('Е3-3_t3_r3', 'complex_openings', 'rate', '3-46', 3.46::numeric),

        ('Е3-3_t3_r4', 'thickness_bricks', 'cell', '1 1/2', NULL::numeric),
        ('Е3-3_t3_r4', 'finish_type', 'cell', 'С расшивкой', NULL::numeric),
        ('Е3-3_t3_r4', 'simple_solid', 'n_vr', '3,2', 3.20::numeric),
        ('Е3-3_t3_r4', 'simple_solid', 'rate', '2-24', 2.24::numeric),
        ('Е3-3_t3_r4', 'simple_openings', 'n_vr', '3,7', 3.70::numeric),
        ('Е3-3_t3_r4', 'simple_openings', 'rate', '2-59', 2.59::numeric),
        ('Е3-3_t3_r4', 'medium_openings', 'n_vr', '4,1', 4.10::numeric),
        ('Е3-3_t3_r4', 'medium_openings', 'rate', '3-05', 3.05::numeric),
        ('Е3-3_t3_r4', 'complex_openings', 'n_vr', '5,2', 5.20::numeric),
        ('Е3-3_t3_r4', 'complex_openings', 'rate', '4-19', 4.19::numeric),

        ('Е3-3_t3_r5', 'thickness_bricks', 'cell', '2', NULL::numeric),
        ('Е3-3_t3_r5', 'finish_type', 'cell', 'Под штукатурку', NULL::numeric),
        ('Е3-3_t3_r5', 'simple_solid', 'n_vr', '2,3', 2.30::numeric),
        ('Е3-3_t3_r5', 'simple_solid', 'rate', '1-61', 1.61::numeric),
        ('Е3-3_t3_r5', 'simple_openings', 'n_vr', '2,8', 2.80::numeric),
        ('Е3-3_t3_r5', 'simple_openings', 'rate', '1-96', 1.96::numeric),
        ('Е3-3_t3_r5', 'medium_openings', 'n_vr', '3,2', 3.20::numeric),
        ('Е3-3_t3_r5', 'medium_openings', 'rate', '2-38', 2.38::numeric),
        ('Е3-3_t3_r5', 'complex_openings', 'n_vr', '3,7', 3.70::numeric),
        ('Е3-3_t3_r5', 'complex_openings', 'rate', '2-98', 2.98::numeric),

        ('Е3-3_t3_r6', 'thickness_bricks', 'cell', '2', NULL::numeric),
        ('Е3-3_t3_r6', 'finish_type', 'cell', 'С расшивкой', NULL::numeric),
        ('Е3-3_t3_r6', 'simple_solid', 'n_vr', '2,8', 2.80::numeric),
        ('Е3-3_t3_r6', 'simple_solid', 'rate', '1-96', 1.96::numeric),
        ('Е3-3_t3_r6', 'simple_openings', 'n_vr', '3,2', 3.20::numeric),
        ('Е3-3_t3_r6', 'simple_openings', 'rate', '2-24', 2.24::numeric),
        ('Е3-3_t3_r6', 'medium_openings', 'n_vr', '3,7', 3.70::numeric),
        ('Е3-3_t3_r6', 'medium_openings', 'rate', '2-76', 2.76::numeric),
        ('Е3-3_t3_r6', 'complex_openings', 'n_vr', '4,3', 4.30::numeric),
        ('Е3-3_t3_r6', 'complex_openings', 'rate', '3-46', 3.46::numeric),

        ('Е3-3_t3_r7', 'thickness_bricks', 'cell', '2 1/2', NULL::numeric),
        ('Е3-3_t3_r7', 'finish_type', 'cell', 'Под штукатурку', NULL::numeric),
        ('Е3-3_t3_r7', 'simple_solid', 'n_vr', '2,2', 2.20::numeric),
        ('Е3-3_t3_r7', 'simple_solid', 'rate', '1-54', 1.54::numeric),
        ('Е3-3_t3_r7', 'simple_openings', 'n_vr', '2,5', 2.50::numeric),
        ('Е3-3_t3_r7', 'simple_openings', 'rate', '1-75', 1.75::numeric),
        ('Е3-3_t3_r7', 'medium_openings', 'n_vr', '2,9', 2.90::numeric),
        ('Е3-3_t3_r7', 'medium_openings', 'rate', '2-16', 2.16::numeric),
        ('Е3-3_t3_r7', 'complex_openings', 'n_vr', '3,2', 3.20::numeric),
        ('Е3-3_t3_r7', 'complex_openings', 'rate', '2-58', 2.58::numeric),

        ('Е3-3_t3_r8', 'thickness_bricks', 'cell', '2 1/2', NULL::numeric),
        ('Е3-3_t3_r8', 'finish_type', 'cell', 'С расшивкой', NULL::numeric),
        ('Е3-3_t3_r8', 'simple_solid', 'n_vr', '2,5', 2.50::numeric),
        ('Е3-3_t3_r8', 'simple_solid', 'rate', '1-75', 1.75::numeric),
        ('Е3-3_t3_r8', 'simple_openings', 'n_vr', '2,9', 2.90::numeric),
        ('Е3-3_t3_r8', 'simple_openings', 'rate', '2-03', 2.03::numeric),
        ('Е3-3_t3_r8', 'medium_openings', 'n_vr', '3,2', 3.20::numeric),
        ('Е3-3_t3_r8', 'medium_openings', 'rate', '2-38', 2.38::numeric),
        ('Е3-3_t3_r8', 'complex_openings', 'n_vr', '3,7', 3.70::numeric),
        ('Е3-3_t3_r8', 'complex_openings', 'rate', '2-98', 2.98::numeric),

        ('Е3-3_t3_r9', 'thickness_bricks', 'cell', '3 и более', NULL::numeric),
        ('Е3-3_t3_r9', 'finish_type', 'cell', 'Под штукатурку', NULL::numeric),
        ('Е3-3_t3_r9', 'simple_solid', 'n_vr', '1,8', 1.80::numeric),
        ('Е3-3_t3_r9', 'simple_solid', 'rate', '1-26', 1.26::numeric),
        ('Е3-3_t3_r9', 'simple_openings', 'n_vr', '2,2', 2.20::numeric),
        ('Е3-3_t3_r9', 'simple_openings', 'rate', '1-54', 1.54::numeric),
        ('Е3-3_t3_r9', 'medium_openings', 'n_vr', '2,5', 2.50::numeric),
        ('Е3-3_t3_r9', 'medium_openings', 'rate', '1-86', 1.86::numeric),
        ('Е3-3_t3_r9', 'complex_openings', 'n_vr', '3', 3.00::numeric),
        ('Е3-3_t3_r9', 'complex_openings', 'rate', '2-42', 2.42::numeric),

        ('Е3-3_t3_r10', 'thickness_bricks', 'cell', '3 и более', NULL::numeric),
        ('Е3-3_t3_r10', 'finish_type', 'cell', 'С расшивкой', NULL::numeric),
        ('Е3-3_t3_r10', 'simple_solid', 'n_vr', '2,2', 2.20::numeric),
        ('Е3-3_t3_r10', 'simple_solid', 'rate', '1-54', 1.54::numeric),
        ('Е3-3_t3_r10', 'simple_openings', 'n_vr', '2,5', 2.50::numeric),
        ('Е3-3_t3_r10', 'simple_openings', 'rate', '1-75', 1.75::numeric),
        ('Е3-3_t3_r10', 'medium_openings', 'n_vr', '3', 3.00::numeric),
        ('Е3-3_t3_r10', 'medium_openings', 'rate', '2-24', 2.24::numeric),
        ('Е3-3_t3_r10', 'complex_openings', 'n_vr', '3,3', 3.30::numeric),
        ('Е3-3_t3_r10', 'complex_openings', 'rate', '2-66', 2.66::numeric),

        ('Е3-3_t4_r1', 'thickness_bricks', 'cell', '1', NULL::numeric),
        ('Е3-3_t4_r1', 'simple', 'n_vr', '6,2', 6.20::numeric),
        ('Е3-3_t4_r1', 'simple', 'rate', '4-34', 4.34::numeric),

        ('Е3-3_t4_r2', 'thickness_bricks', 'cell', '1 1/2', NULL::numeric),
        ('Е3-3_t4_r2', 'simple', 'n_vr', '5,2', 5.20::numeric),
        ('Е3-3_t4_r2', 'simple', 'rate', '3-64', 3.64::numeric),
        ('Е3-3_t4_r2', 'medium', 'n_vr', '5,2', 5.20::numeric),
        ('Е3-3_t4_r2', 'medium', 'rate', '3-87', 3.87::numeric),
        ('Е3-3_t4_r2', 'complex', 'n_vr', '6,6', 6.60::numeric),
        ('Е3-3_t4_r2', 'complex', 'rate', '5-31', 5.31::numeric),

        ('Е3-3_t4_r3', 'thickness_bricks', 'cell', '2', NULL::numeric),
        ('Е3-3_t4_r3', 'simple', 'n_vr', '4,1', 4.10::numeric),
        ('Е3-3_t4_r3', 'simple', 'rate', '2-87', 2.87::numeric),
        ('Е3-3_t4_r3', 'medium', 'n_vr', '4,8', 4.80::numeric),
        ('Е3-3_t4_r3', 'medium', 'rate', '3-58', 3.58::numeric),
        ('Е3-3_t4_r3', 'complex', 'n_vr', '5,6', 5.60::numeric),
        ('Е3-3_t4_r3', 'complex', 'rate', '4-51', 4.51::numeric),

        ('Е3-3_t4_r4', 'thickness_bricks', 'cell', '2 1/2', NULL::numeric),
        ('Е3-3_t4_r4', 'simple', 'n_vr', '3,8', 3.80::numeric),
        ('Е3-3_t4_r4', 'simple', 'rate', '2-66', 2.66::numeric),
        ('Е3-3_t4_r4', 'medium', 'n_vr', '4,3', 4.30::numeric),
        ('Е3-3_t4_r4', 'medium', 'rate', '3-20', 3.20::numeric),
        ('Е3-3_t4_r4', 'complex', 'n_vr', '4,9', 4.90::numeric),
        ('Е3-3_t4_r4', 'complex', 'rate', '3-94', 3.94::numeric),

        ('Е3-3_t4_r5', 'thickness_bricks', 'cell', '3', NULL::numeric),
        ('Е3-3_t4_r5', 'simple', 'n_vr', '3,3', 3.30::numeric),
        ('Е3-3_t4_r5', 'simple', 'rate', '2-31', 2.31::numeric),
        ('Е3-3_t4_r5', 'medium', 'n_vr', '3,8', 3.80::numeric),
        ('Е3-3_t4_r5', 'medium', 'rate', '2-83', 2.83::numeric),
        ('Е3-3_t4_r5', 'complex', 'n_vr', '4,4', 4.40::numeric),
        ('Е3-3_t4_r5', 'complex', 'rate', '3-54', 3.54::numeric),

        ('Е3-3_t4_r6', 'thickness_bricks', 'cell', '3 1/2', NULL::numeric),
        ('Е3-3_t4_r6', 'simple', 'n_vr', '3,1', 3.10::numeric),
        ('Е3-3_t4_r6', 'simple', 'rate', '2-17', 2.17::numeric),
        ('Е3-3_t4_r6', 'medium', 'n_vr', '3,7', 3.70::numeric),
        ('Е3-3_t4_r6', 'medium', 'rate', '2-76', 2.76::numeric),
        ('Е3-3_t4_r6', 'complex', 'n_vr', '4,1', 4.10::numeric),
        ('Е3-3_t4_r6', 'complex', 'rate', '3-30', 3.30::numeric),

        ('Е3-3_t5_r1', 'finish_type', 'cell', 'Под штукатурку', NULL::numeric),
        ('Е3-3_t5_r1', 'thickness_0_5', 'n_vr', '5,4', 5.40::numeric),
        ('Е3-3_t5_r1', 'thickness_0_5', 'rate', '3-78', 3.78::numeric),
        ('Е3-3_t5_r1', 'thickness_1', 'n_vr', '3,7', 3.70::numeric),
        ('Е3-3_t5_r1', 'thickness_1', 'rate', '2-59', 2.59::numeric),
        ('Е3-3_t5_r1', 'thickness_1_5', 'n_vr', '3', 3.00::numeric),
        ('Е3-3_t5_r1', 'thickness_1_5', 'rate', '2-10', 2.10::numeric),
        ('Е3-3_t5_r1', 'thickness_2', 'n_vr', '2,5', 2.50::numeric),
        ('Е3-3_t5_r1', 'thickness_2', 'rate', '1-75', 1.75::numeric),
        ('Е3-3_t5_r1', 'thickness_2_5', 'n_vr', '2,4', 2.40::numeric),
        ('Е3-3_t5_r1', 'thickness_2_5', 'rate', '1-68', 1.68::numeric),

        ('Е3-3_t5_r2', 'finish_type', 'cell', 'С расшивкой', NULL::numeric),
        ('Е3-3_t5_r2', 'thickness_0_5', 'n_vr', '7,4', 7.40::numeric),
        ('Е3-3_t5_r2', 'thickness_0_5', 'rate', '5-18', 5.18::numeric),
        ('Е3-3_t5_r2', 'thickness_1', 'n_vr', '4,6', 4.60::numeric),
        ('Е3-3_t5_r2', 'thickness_1', 'rate', '3-22', 3.22::numeric),
        ('Е3-3_t5_r2', 'thickness_1_5', 'n_vr', '3,7', 3.70::numeric),
        ('Е3-3_t5_r2', 'thickness_1_5', 'rate', '2-59', 2.59::numeric),
        ('Е3-3_t5_r2', 'thickness_2', 'n_vr', '3,1', 3.10::numeric),
        ('Е3-3_t5_r2', 'thickness_2', 'rate', '2-17', 2.17::numeric),
        ('Е3-3_t5_r2', 'thickness_2_5', 'n_vr', '2,9', 2.90::numeric),
        ('Е3-3_t5_r2', 'thickness_2_5', 'rate', '2-03', 2.03::numeric)
) AS v(source_row_id, source_column_key, value_type, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns nc
  ON nc.norm_table_id = t.id
 AND nc.source_column_key = v.source_column_key;

COMMIT;
