BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-6';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-6',
    'Е3-6',
    'Кладка стен из бетонных камней',
    '1 м3 кладки',
    5
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'I'
JOIN enir_chapters ch
  ON ch.collection_id = c.id
 AND ch.source_chapter_id = '1'
WHERE c.code = 'Е3';

INSERT INTO enir_paragraph_technical_characteristics (paragraph_id, sort_order, raw_text)
SELECT p.id, v.sort_order, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Нормами предусмотрена кладка из сплошных и пустотелых бетонных камней длиной 390 мм, шириной 190 мм и высотой 188 мм.'),
        (1, 'Отклонения в размерах и положении кладки из бетонных камней от проектных принимаются, как и для кирпичной кладки, по табл. 1 § Е3-3.')
) AS v(sort_order, raw_text)
ON true
WHERE p.code = 'Е3-6';

INSERT INTO enir_paragraph_application_notes (paragraph_id, sort_order, text)
SELECT p.id, v.sort_order, v.text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'А. При кладке стен.'),
        (1, 'Б. При заполнении стен каркасных зданий.')
    ) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-6';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT p.id, v.sort_order, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            0,
            '{"condition":"А. При кладке стен","operations":["1. Натягивание причалки.","2. Подача и раскладка камней.","3. Перелопачивание, расстилание и разравнивание раствора.","4. Кладка стен с выкладкой всех усложнений кладки, подбором, околкой и отеской камней.","5. Заделка балочных гнезд.","6. Установка креплений (при отсутствии перевязки продольных вертикальных швов).","7. Заполнение пустот пустотелых камней.","8. Облицовка стен в 1/2 кирпича с расшивкой швов облицовки (при кладке с облицовкой).","9. Расшивка швов наружных стен с одной стороны (при кладке с расшивкой)."]}'
        ),
        (
            1,
            '{"condition":"Б. При заполнении стен каркасных зданий","operations":["1. Натягивание причалки.","2. Подача и раскладка камней.","3. Перелопачивание, расстилание и разравнивание раствора.","4. Кладка стен с выкладкой всех усложнений кладки, подбором, околкой и отеской камней."]}'
        )
) AS v(sort_order, raw_text)
ON true
WHERE p.code = 'Е3-6';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, v.condition, v.sort_order
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'А. При кладке стен'),
        (1, 'Б. При заполнении стен каркасных зданий')
) AS v(sort_order, condition)
ON true
WHERE p.code = 'Е3-6';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, 0, '1. Натягивание причалки.'),
        (0, 1, '2. Подача и раскладка камней.'),
        (0, 2, '3. Перелопачивание, расстилание и разравнивание раствора.'),
        (0, 3, '4. Кладка стен с выкладкой всех усложнений кладки, подбором, околкой и отеской камней.'),
        (0, 4, '5. Заделка балочных гнезд.'),
        (0, 5, '6. Установка креплений (при отсутствии перевязки продольных вертикальных швов).'),
        (0, 6, '7. Заполнение пустот пустотелых камней.'),
        (0, 7, '8. Облицовка стен в 1/2 кирпича с расшивкой швов облицовки (при кладке с облицовкой).'),
        (0, 8, '9. Расшивка швов наружных стен с одной стороны (при кладке с расшивкой).'),
        (1, 0, '1. Натягивание причалки.'),
        (1, 1, '2. Подача и раскладка камней.'),
        (1, 2, '3. Перелопачивание, расстилание и разравнивание раствора.'),
        (1, 3, '4. Кладка стен с выкладкой всех усложнений кладки, подбором, околкой и отеской камней.')
) AS v(composition_sort_order, sort_order, text)
  ON v.composition_sort_order = wc.sort_order
WHERE p.code = 'Е3-6';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Каменщик', 5.0::numeric(4,1), 1, 'Каменщик 5 разр. - 1 (средней сложности с облицовкой)'),
        (1, 'Каменщик', 4.0::numeric(4,1), 1, 'Каменщик 4 разр. - 1 (простые с облицовкой и средней сложности без облицовки)'),
        (2, 'Каменщик', 3.0::numeric(4,1), 2, 'Каменщик 3 разр. - 2 (простые без облицовки)'),
        (3, 'Каменщик', 3.0::numeric(4,1), 1, 'Каменщик 3 разр. - 1 (простые с облицовкой, средней сложности без облицовки и с облицовкой)'),
        (4, 'Каменщик', 3.0::numeric(4,1), 1, 'Каменщик 3 разр. - 1 (при заполнении стен каркасных зданий)')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-6';

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
WHERE p.code = 'Е3-6';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT p.id, v.sort_order, v.code, v.text, v.coefficient, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            0,
            'ПР-1',
            'При кладке стен из пустотелых камней без засыпки пустот Н.вр. и Расц. умножать на 0,85 (ПР-1).',
            0.85::numeric(6,4),
            '{"stone_type":"hollow","fill_voids":false}'::jsonb
        ),
        (
            1,
            NULL,
            'Нормами предусмотрена облицовка стен одинарным или утолщенным кирпичом.',
            NULL,
            NULL
        )
) AS v(sort_order, code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-6';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT p.id, v.num, v.text, v.coefficient, v.pr_code, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            1,
            'ПР-1',
            'При кладке стен из пустотелых камней без засыпки пустот Н.вр. и Расц. умножать на 0,85 (ПР-1).',
            0.85::numeric(6,4),
            '{"stone_type":"hollow","fill_voids":false}'::jsonb
        ),
        (
            2,
            NULL,
            'Нормами предусмотрена облицовка стен одинарным или утолщенным кирпичом.',
            NULL,
            NULL
        )
    ) AS v(num, pr_code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-6';

INSERT INTO enir_technical_coefficients
    (collection_id, code, description, multiplier, conditions, sort_order)
SELECT c.id, v.code, v.description, v.multiplier, v.conditions, v.sort_order
FROM enir_collections c
JOIN (
    VALUES
        ('ТЧ-7', 'Кладка стен зданий с проемностью наружных стен до 5%', 0.90::numeric(8,4), '{"opening_ratio":{"lte":0.05}}'::jsonb, 7),
        ('ТЧ-8', 'Заделка оставленных в процессе кладки разрывов длиной до 2 м', 1.25::numeric(8,4), '{"gap_fill":true}'::jsonb, 8)
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
  AND p.code = 'Е3-6'
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
        ('Е3-6_table2', 0, 'Нормы времени и расценки на 1 м3 кладки', 9),
        ('Е3-6_table3', 1, 'Нормы времени и расценки на 1 м3 кладки', 2)
    ) AS v(source_table_id, sort_order, title, row_count)
ON true
WHERE p.code = 'Е3-6';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('Е3-6_table2', 'thickness_stones', 0, 'Толщина стен в камнях', NULL),
        ('Е3-6_table2', 'finish_type', 1, 'Вид кладки', NULL),
        ('Е3-6_table2', 'simple_hollow', 2, 'Простые, пустотелые', 'а'),
        ('Е3-6_table2', 'simple_solid', 3, 'Простые, сплошные', 'б'),
        ('Е3-6_table2', 'medium_hollow', 4, 'Средней сложности, пустотелые', 'в'),
        ('Е3-6_table2', 'medium_solid', 5, 'Средней сложности, сплошные', 'г'),
        ('Е3-6_table3', 'frame_wall_type', 0, 'Вид каркасных стен', NULL),
        ('Е3-6_table3', 'thickness_0_5', 1, '1/2 камня', 'а'),
        ('Е3-6_table3', 'thickness_1', 2, '1 камень', 'б'),
        ('Е3-6_table3', 'thickness_1_5', 3, '1 1/2 камня', 'в')
    ) AS v(table_key, source_column_key, sort_order, header, label)
  ON v.table_key = t.source_table_id;

CREATE TEMP TABLE tmp_e3_6_rows (
    table_key text NOT NULL,
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_6_rows
    (table_key, source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-6_table2', 'Е3-6_t2_r1', 0, 1, '{"structure":"wall","stone_type":"any","thickness_stones":0.5,"cladding":false,"finish":"no_jointing"}'),
    ('Е3-6_table2', 'Е3-6_t2_r2', 1, 2, '{"structure":"wall","stone_type":"any","thickness_stones":0.5,"cladding":false,"finish":"jointing"}'),
    ('Е3-6_table2', 'Е3-6_t2_r3', 2, 3, '{"structure":"wall","stone_type":"any","thickness_stones":0.5,"cladding":true}'),
    ('Е3-6_table2', 'Е3-6_t2_r4', 3, 4, '{"structure":"wall","stone_type":"any","thickness_stones":1.0,"cladding":false,"finish":"no_jointing"}'),
    ('Е3-6_table2', 'Е3-6_t2_r5', 4, 5, '{"structure":"wall","stone_type":"any","thickness_stones":1.0,"cladding":false,"finish":"jointing"}'),
    ('Е3-6_table2', 'Е3-6_t2_r6', 5, 6, '{"structure":"wall","stone_type":"any","thickness_stones":1.0,"cladding":true}'),
    ('Е3-6_table2', 'Е3-6_t2_r7', 6, 7, '{"structure":"wall","stone_type":"any","thickness_stones":1.5,"cladding":false,"finish":"no_jointing"}'),
    ('Е3-6_table2', 'Е3-6_t2_r8', 7, 8, '{"structure":"wall","stone_type":"any","thickness_stones":1.5,"cladding":false,"finish":"jointing"}'),
    ('Е3-6_table2', 'Е3-6_t2_r9', 8, 9, '{"structure":"wall","stone_type":"any","thickness_stones":1.5,"cladding":true}'),
    ('Е3-6_table3', 'Е3-6_t3_r1', 9, 1, '{"structure":"frame_wall_infill","has_braces":false}'),
    ('Е3-6_table3', 'Е3-6_t3_r2', 10, 2, '{"structure":"frame_wall_infill","has_braces":true}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_6_rows r
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
FROM tmp_e3_6_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-6_t2_r1', 'thickness_stones', 'cell', '1/2', NULL::numeric),
        ('Е3-6_t2_r1', 'finish_type', 'cell', 'Без облицовки без расшивки', NULL::numeric),
        ('Е3-6_t2_r1', 'simple_hollow', 'n_vr', '2,8', 2.80::numeric),
        ('Е3-6_t2_r1', 'simple_hollow', 'rate', '1-96', 1.96::numeric),
        ('Е3-6_t2_r1', 'simple_solid', 'n_vr', '2,3', 2.30::numeric),
        ('Е3-6_t2_r1', 'simple_solid', 'rate', '1-61', 1.61::numeric),

        ('Е3-6_t2_r2', 'thickness_stones', 'cell', '1/2', NULL::numeric),
        ('Е3-6_t2_r2', 'finish_type', 'cell', 'С расшивкой', NULL::numeric),
        ('Е3-6_t2_r2', 'simple_hollow', 'n_vr', '3,2', 3.20::numeric),
        ('Е3-6_t2_r2', 'simple_hollow', 'rate', '2-24', 2.24::numeric),
        ('Е3-6_t2_r2', 'simple_solid', 'n_vr', '2,7', 2.70::numeric),
        ('Е3-6_t2_r2', 'simple_solid', 'rate', '1-89', 1.89::numeric),

        ('Е3-6_t2_r3', 'thickness_stones', 'cell', '1/2', NULL::numeric),
        ('Е3-6_t2_r3', 'finish_type', 'cell', 'С облицовкой', NULL::numeric),
        ('Е3-6_t2_r3', 'simple_hollow', 'n_vr', '4', 4.00::numeric),
        ('Е3-6_t2_r3', 'simple_hollow', 'rate', '2-98', 2.98::numeric),
        ('Е3-6_t2_r3', 'simple_solid', 'n_vr', '3,2', 3.20::numeric),
        ('Е3-6_t2_r3', 'simple_solid', 'rate', '2-38', 2.38::numeric),

        ('Е3-6_t2_r4', 'thickness_stones', 'cell', '1', NULL::numeric),
        ('Е3-6_t2_r4', 'finish_type', 'cell', 'Без облицовки без расшивки', NULL::numeric),
        ('Е3-6_t2_r4', 'simple_hollow', 'n_vr', '2,4', 2.40::numeric),
        ('Е3-6_t2_r4', 'simple_hollow', 'rate', '1-68', 1.68::numeric),
        ('Е3-6_t2_r4', 'simple_solid', 'n_vr', '1,8', 1.80::numeric),
        ('Е3-6_t2_r4', 'simple_solid', 'rate', '1-26', 1.26::numeric),
        ('Е3-6_t2_r4', 'medium_hollow', 'n_vr', '2,5', 2.50::numeric),
        ('Е3-6_t2_r4', 'medium_hollow', 'rate', '1-86', 1.86::numeric),
        ('Е3-6_t2_r4', 'medium_solid', 'n_vr', '2,2', 2.20::numeric),
        ('Е3-6_t2_r4', 'medium_solid', 'rate', '1-64', 1.64::numeric),

        ('Е3-6_t2_r5', 'thickness_stones', 'cell', '1', NULL::numeric),
        ('Е3-6_t2_r5', 'finish_type', 'cell', 'С расшивкой', NULL::numeric),
        ('Е3-6_t2_r5', 'simple_hollow', 'n_vr', '2,6', 2.60::numeric),
        ('Е3-6_t2_r5', 'simple_hollow', 'rate', '1-82', 1.82::numeric),
        ('Е3-6_t2_r5', 'simple_solid', 'n_vr', '2,1', 2.10::numeric),
        ('Е3-6_t2_r5', 'simple_solid', 'rate', '1-47', 1.47::numeric),
        ('Е3-6_t2_r5', 'medium_hollow', 'n_vr', '2,9', 2.90::numeric),
        ('Е3-6_t2_r5', 'medium_hollow', 'rate', '2-16', 2.16::numeric),
        ('Е3-6_t2_r5', 'medium_solid', 'n_vr', '2,5', 2.50::numeric),
        ('Е3-6_t2_r5', 'medium_solid', 'rate', '1-86', 1.86::numeric),

        ('Е3-6_t2_r6', 'thickness_stones', 'cell', '1', NULL::numeric),
        ('Е3-6_t2_r6', 'finish_type', 'cell', 'С облицовкой', NULL::numeric),
        ('Е3-6_t2_r6', 'simple_hollow', 'n_vr', '3,3', 3.30::numeric),
        ('Е3-6_t2_r6', 'simple_hollow', 'rate', '2-46', 2.46::numeric),
        ('Е3-6_t2_r6', 'simple_solid', 'n_vr', '2,6', 2.60::numeric),
        ('Е3-6_t2_r6', 'simple_solid', 'rate', '1-94', 1.94::numeric),
        ('Е3-6_t2_r6', 'medium_hollow', 'n_vr', '3,7', 3.70::numeric),
        ('Е3-6_t2_r6', 'medium_hollow', 'rate', '2-98', 2.98::numeric),
        ('Е3-6_t2_r6', 'medium_solid', 'n_vr', '3,1', 3.10::numeric),
        ('Е3-6_t2_r6', 'medium_solid', 'rate', '2-50', 2.50::numeric),

        ('Е3-6_t2_r7', 'thickness_stones', 'cell', '1 1/2', NULL::numeric),
        ('Е3-6_t2_r7', 'finish_type', 'cell', 'Без облицовки без расшивки', NULL::numeric),
        ('Е3-6_t2_r7', 'simple_hollow', 'n_vr', '2,1', 2.10::numeric),
        ('Е3-6_t2_r7', 'simple_hollow', 'rate', '1-47', 1.47::numeric),
        ('Е3-6_t2_r7', 'simple_solid', 'n_vr', '1,6', 1.60::numeric),
        ('Е3-6_t2_r7', 'simple_solid', 'rate', '1-12', 1.12::numeric),
        ('Е3-6_t2_r7', 'medium_hollow', 'n_vr', '2,4', 2.40::numeric),
        ('Е3-6_t2_r7', 'medium_hollow', 'rate', '1-79', 1.79::numeric),
        ('Е3-6_t2_r7', 'medium_solid', 'n_vr', '1,8', 1.80::numeric),
        ('Е3-6_t2_r7', 'medium_solid', 'rate', '1-34', 1.34::numeric),

        ('Е3-6_t2_r8', 'thickness_stones', 'cell', '1 1/2', NULL::numeric),
        ('Е3-6_t2_r8', 'finish_type', 'cell', 'С расшивкой', NULL::numeric),
        ('Е3-6_t2_r8', 'simple_hollow', 'n_vr', '2,2', 2.20::numeric),
        ('Е3-6_t2_r8', 'simple_hollow', 'rate', '1-54', 1.54::numeric),
        ('Е3-6_t2_r8', 'simple_solid', 'n_vr', '1,7', 1.70::numeric),
        ('Е3-6_t2_r8', 'simple_solid', 'rate', '1-19', 1.19::numeric),
        ('Е3-6_t2_r8', 'medium_hollow', 'n_vr', '2,5', 2.50::numeric),
        ('Е3-6_t2_r8', 'medium_hollow', 'rate', '1-86', 1.86::numeric),
        ('Е3-6_t2_r8', 'medium_solid', 'n_vr', '2,1', 2.10::numeric),
        ('Е3-6_t2_r8', 'medium_solid', 'rate', '1-56', 1.56::numeric),

        ('Е3-6_t2_r9', 'thickness_stones', 'cell', '1 1/2', NULL::numeric),
        ('Е3-6_t2_r9', 'finish_type', 'cell', 'С облицовкой', NULL::numeric),
        ('Е3-6_t2_r9', 'simple_hollow', 'n_vr', '2,8', 2.80::numeric),
        ('Е3-6_t2_r9', 'simple_hollow', 'rate', '2-09', 2.09::numeric),
        ('Е3-6_t2_r9', 'simple_solid', 'n_vr', '2,3', 2.30::numeric),
        ('Е3-6_t2_r9', 'simple_solid', 'rate', '1-71', 1.71::numeric),
        ('Е3-6_t2_r9', 'medium_hollow', 'n_vr', '3,2', 3.20::numeric),
        ('Е3-6_t2_r9', 'medium_hollow', 'rate', '2-58', 2.58::numeric),
        ('Е3-6_t2_r9', 'medium_solid', 'n_vr', '2,5', 2.50::numeric),
        ('Е3-6_t2_r9', 'medium_solid', 'rate', '2-01', 2.01::numeric),

        ('Е3-6_t3_r1', 'frame_wall_type', 'cell', 'Без подкосов', NULL::numeric),
        ('Е3-6_t3_r1', 'thickness_0_5', 'n_vr', '2,6', 2.60::numeric),
        ('Е3-6_t3_r1', 'thickness_0_5', 'rate', '1-82', 1.82::numeric),
        ('Е3-6_t3_r1', 'thickness_1', 'n_vr', '2,1', 2.10::numeric),
        ('Е3-6_t3_r1', 'thickness_1', 'rate', '1-47', 1.47::numeric),
        ('Е3-6_t3_r1', 'thickness_1_5', 'n_vr', '1,7', 1.70::numeric),
        ('Е3-6_t3_r1', 'thickness_1_5', 'rate', '1-19', 1.19::numeric),

        ('Е3-6_t3_r2', 'frame_wall_type', 'cell', 'С подкосами', NULL::numeric),
        ('Е3-6_t3_r2', 'thickness_0_5', 'n_vr', '3,1', 3.10::numeric),
        ('Е3-6_t3_r2', 'thickness_0_5', 'rate', '2-17', 2.17::numeric),
        ('Е3-6_t3_r2', 'thickness_1', 'n_vr', '2,5', 2.50::numeric),
        ('Е3-6_t3_r2', 'thickness_1', 'rate', '1-75', 1.75::numeric),
        ('Е3-6_t3_r2', 'thickness_1_5', 'n_vr', '2,2', 2.20::numeric),
        ('Е3-6_t3_r2', 'thickness_1_5', 'rate', '1-54', 1.54::numeric)
) AS v(source_row_id, source_column_key, value_type, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns nc
  ON nc.norm_table_id = t.id
 AND nc.source_column_key = v.source_column_key;

COMMIT;
