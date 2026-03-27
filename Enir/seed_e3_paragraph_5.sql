BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-5';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-5',
    'Е3-5',
    'Кладка стен зданий облегченных конструкций из кирпича',
    '1 м3 стены',
    4
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
        (0, 'А. При кладке кирпично-бетонных стен.'),
        (1, 'Б. При кладке колодцевых стен.')
) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-5';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT p.id, v.sort_order, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            0,
            '{"condition":"А. При кладке кирпично-бетонных стен","operations":["1. Натягивание причалки.","2. Подача и раскладка кирпича.","3. Перелопачивание, расстилание и разравнивание раствора.","4. Кладка стен с выкладкой всех усложнений кладки, подбором, отеской и околкой кирпича.","5. Заполнение пустот между кирпичными стенами легким бетоном.","6. Заделка балочных гнезд.","7. Расшивка швов (при кладке с расшивкой)."]}'
        ),
        (
            1,
            '{"condition":"Б. При кладке колодцевых стен","operations":["1. Натягивание причалки.","2. Подача и раскладка кирпича.","3. Перелопачивание, расстилание и разравнивание раствора.","4. Кладка стен с выкладкой всех усложнений кладки, подбором, отеской и околкой кирпича.","5. Заполнение колодцев стен шлаком и легким бетоном с послойным уплотнением и проливкой раствором, а в стенах с узлами жесткости - устройство армированных диафрагм из раствора.","6. Заделка балочных гнезд.","7. Расшивка швов (при кладке с расшивкой)."]}'
        )
) AS v(sort_order, raw_text)
ON true
WHERE p.code = 'Е3-5';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, v.condition, v.sort_order
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'А. При кладке кирпично-бетонных стен'),
        (1, 'Б. При кладке колодцевых стен')
) AS v(sort_order, condition)
ON true
WHERE p.code = 'Е3-5';

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
        (0, 3, '4. Кладка стен с выкладкой всех усложнений кладки, подбором, отеской и околкой кирпича.'),
        (0, 4, '5. Заполнение пустот между кирпичными стенами легким бетоном.'),
        (0, 5, '6. Заделка балочных гнезд.'),
        (0, 6, '7. Расшивка швов (при кладке с расшивкой).'),
        (1, 0, '1. Натягивание причалки.'),
        (1, 1, '2. Подача и раскладка кирпича.'),
        (1, 2, '3. Перелопачивание, расстилание и разравнивание раствора.'),
        (1, 3, '4. Кладка стен с выкладкой всех усложнений кладки, подбором, отеской и околкой кирпича.'),
        (1, 4, '5. Заполнение колодцев стен шлаком и легким бетоном с послойным уплотнением и проливкой раствором, а в стенах с узлами жесткости - устройство армированных диафрагм из раствора.'),
        (1, 5, '6. Заделка балочных гнезд.'),
        (1, 6, '7. Расшивка швов (при кладке с расшивкой).')
) AS v(composition_sort_order, sort_order, text)
  ON v.composition_sort_order = wc.sort_order
WHERE p.code = 'Е3-5';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Каменщик', 5.0::numeric(4,1), 1, 'Каменщик 5 разр. - 1 (стены средней сложности и сложные)'),
        (1, 'Каменщик', 4.0::numeric(4,1), 1, 'Каменщик 4 разр. - 1 (простые стены)'),
        (2, 'Каменщик', 3.0::numeric(4,1), 2, 'Каменщик 3 разр. - 2')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-5';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Каменщик', 5.0::numeric(4,1), 1),
        ('Каменщик', 4.0::numeric(4,1), 1),
        ('Каменщик', 3.0::numeric(4,1), 2)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-5';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT
    p.id,
    0,
    'ПР-1',
    'При кладке колодцевых стен с узлами жесткости Н.вр. и Расц. умножать на 0,9 (ПР-1).',
    0.90::numeric(6,4),
    '{"wall_type":"well_wall","has_stiffness_nodes":true,"table_scope":["Е3-5_table3"]}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-5';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT
    p.id,
    1,
    'При кладке колодцевых стен с узлами жесткости Н.вр. и Расц. умножать на 0,9 (ПР-1).',
    0.90::numeric(6,4),
    'ПР-1',
    '{"wall_type":"well_wall","has_stiffness_nodes":true,"table_scope":["Е3-5_table3"]}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-5';

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
  AND p.code = 'Е3-5'
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
        ('Е3-5_table2', 0, 'Нормы времени и расценки на 1 м3 стены', 4),
        ('Е3-5_table3', 1, 'Нормы времени и расценки на 1 м3 стены', 6)
) AS v(source_table_id, sort_order, title, row_count)
ON true
WHERE p.code = 'Е3-5';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('Е3-5_table2', 'thickness_mm', 0, 'Толщина стен, мм', NULL),
        ('Е3-5_table2', 'finish_type', 1, 'Вид кладки', NULL),
        ('Е3-5_table2', 'simple', 2, 'Простые', 'а'),
        ('Е3-5_table2', 'medium', 3, 'Средней сложности', 'б'),
        ('Е3-5_table2', 'complex', 4, 'Сложные', 'в'),
        ('Е3-5_table3', 'thickness_range', 0, 'Толщина стен, мм', NULL),
        ('Е3-5_table3', 'finish_type', 1, 'Вид кладки', NULL),
        ('Е3-5_table3', 'simple', 2, 'Простые', 'а'),
        ('Е3-5_table3', 'medium', 3, 'Средней сложности', 'б'),
        ('Е3-5_table3', 'complex', 4, 'Сложные', 'в')
    ) AS v(table_key, source_column_key, sort_order, header, label)
  ON v.table_key = t.source_table_id;

CREATE TEMP TABLE tmp_e3_5_rows (
    table_key text NOT NULL,
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_5_rows
    (table_key, source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-5_table2', 'Е3-5_t2_r1', 0, 1, '{"wall_type":"brick_concrete","thickness_mm":380,"finish":"under_plaster"}'),
    ('Е3-5_table2', 'Е3-5_t2_r2', 1, 2, '{"wall_type":"brick_concrete","thickness_mm":380,"finish":"jointing"}'),
    ('Е3-5_table2', 'Е3-5_t2_r3', 2, 3, '{"wall_type":"brick_concrete","thickness_mm":510,"finish":"under_plaster"}'),
    ('Е3-5_table2', 'Е3-5_t2_r4', 3, 4, '{"wall_type":"brick_concrete","thickness_mm":510,"finish":"jointing"}'),
    ('Е3-5_table3', 'Е3-5_t3_r1', 4, 1, '{"wall_type":"well_wall","thickness_mm_to":420,"finish":"under_plaster"}'),
    ('Е3-5_table3', 'Е3-5_t3_r2', 5, 2, '{"wall_type":"well_wall","thickness_mm_to":420,"finish":"jointing"}'),
    ('Е3-5_table3', 'Е3-5_t3_r3', 6, 3, '{"wall_type":"well_wall","thickness_mm_to":580,"finish":"under_plaster"}'),
    ('Е3-5_table3', 'Е3-5_t3_r4', 7, 4, '{"wall_type":"well_wall","thickness_mm_to":580,"finish":"jointing"}'),
    ('Е3-5_table3', 'Е3-5_t3_r5', 8, 5, '{"wall_type":"well_wall","thickness_mm_from":581,"finish":"under_plaster"}'),
    ('Е3-5_table3', 'Е3-5_t3_r6', 9, 6, '{"wall_type":"well_wall","thickness_mm_from":581,"finish":"jointing"}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_5_rows r
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
FROM tmp_e3_5_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-5_t2_r1', 'thickness_mm', 'cell', '380', NULL::numeric),
        ('Е3-5_t2_r1', 'finish_type', 'cell', 'Под штукатурку', NULL::numeric),
        ('Е3-5_t2_r1', 'simple', 'n_vr', '2,6', 2.60::numeric),
        ('Е3-5_t2_r1', 'simple', 'rate', '1-90', 1.90::numeric),
        ('Е3-5_t2_r1', 'medium', 'n_vr', '3,2', 3.20::numeric),
        ('Е3-5_t2_r1', 'medium', 'rate', '2-46', 2.46::numeric),
        ('Е3-5_t2_r1', 'complex', 'n_vr', '3,8', 3.80::numeric),
        ('Е3-5_t2_r1', 'complex', 'rate', '2-93', 2.93::numeric),

        ('Е3-5_t2_r2', 'thickness_mm', 'cell', '380', NULL::numeric),
        ('Е3-5_t2_r2', 'finish_type', 'cell', 'С расшивкой', NULL::numeric),
        ('Е3-5_t2_r2', 'simple', 'n_vr', '3,2', 3.20::numeric),
        ('Е3-5_t2_r2', 'simple', 'rate', '2-34', 2.34::numeric),
        ('Е3-5_t2_r2', 'medium', 'n_vr', '3,7', 3.70::numeric),
        ('Е3-5_t2_r2', 'medium', 'rate', '2-85', 2.85::numeric),
        ('Е3-5_t2_r2', 'complex', 'n_vr', '4,5', 4.50::numeric),
        ('Е3-5_t2_r2', 'complex', 'rate', '3-46', 3.46::numeric),

        ('Е3-5_t2_r3', 'thickness_mm', 'cell', '510', NULL::numeric),
        ('Е3-5_t2_r3', 'finish_type', 'cell', 'Под штукатурку', NULL::numeric),
        ('Е3-5_t2_r3', 'simple', 'n_vr', '2,3', 2.30::numeric),
        ('Е3-5_t2_r3', 'simple', 'rate', '1-68', 1.68::numeric),
        ('Е3-5_t2_r3', 'medium', 'n_vr', '2,6', 2.60::numeric),
        ('Е3-5_t2_r3', 'medium', 'rate', '2-00', 2.00::numeric),
        ('Е3-5_t2_r3', 'complex', 'n_vr', '3', 3.00::numeric),
        ('Е3-5_t2_r3', 'complex', 'rate', '2-31', 2.31::numeric),

        ('Е3-5_t2_r4', 'thickness_mm', 'cell', '510', NULL::numeric),
        ('Е3-5_t2_r4', 'finish_type', 'cell', 'С расшивкой', NULL::numeric),
        ('Е3-5_t2_r4', 'simple', 'n_vr', '2,6', 2.60::numeric),
        ('Е3-5_t2_r4', 'simple', 'rate', '1-90', 1.90::numeric),
        ('Е3-5_t2_r4', 'medium', 'n_vr', '2,9', 2.90::numeric),
        ('Е3-5_t2_r4', 'medium', 'rate', '2-23', 2.23::numeric),
        ('Е3-5_t2_r4', 'complex', 'n_vr', '3,6', 3.60::numeric),
        ('Е3-5_t2_r4', 'complex', 'rate', '2-77', 2.77::numeric),

        ('Е3-5_t3_r1', 'thickness_range', 'cell', 'До 420', NULL::numeric),
        ('Е3-5_t3_r1', 'finish_type', 'cell', 'Под штукатурку', NULL::numeric),
        ('Е3-5_t3_r1', 'simple', 'n_vr', '3,8', 3.80::numeric),
        ('Е3-5_t3_r1', 'simple', 'rate', '2-77', 2.77::numeric),

        ('Е3-5_t3_r2', 'thickness_range', 'cell', 'До 420', NULL::numeric),
        ('Е3-5_t3_r2', 'finish_type', 'cell', 'С расшивкой', NULL::numeric),
        ('Е3-5_t3_r2', 'simple', 'n_vr', '4,5', 4.50::numeric),
        ('Е3-5_t3_r2', 'simple', 'rate', '3-28', 3.28::numeric),

        ('Е3-5_t3_r3', 'thickness_range', 'cell', 'До 580', NULL::numeric),
        ('Е3-5_t3_r3', 'finish_type', 'cell', 'Под штукатурку', NULL::numeric),
        ('Е3-5_t3_r3', 'simple', 'n_vr', '2,8', 2.80::numeric),
        ('Е3-5_t3_r3', 'simple', 'rate', '2-04', 2.04::numeric),
        ('Е3-5_t3_r3', 'medium', 'n_vr', '3,5', 3.50::numeric),
        ('Е3-5_t3_r3', 'medium', 'rate', '2-70', 2.70::numeric),
        ('Е3-5_t3_r3', 'complex', 'n_vr', '4,1', 4.10::numeric),
        ('Е3-5_t3_r3', 'complex', 'rate', '3-16', 3.16::numeric),

        ('Е3-5_t3_r4', 'thickness_range', 'cell', 'До 580', NULL::numeric),
        ('Е3-5_t3_r4', 'finish_type', 'cell', 'С расшивкой', NULL::numeric),
        ('Е3-5_t3_r4', 'simple', 'n_vr', '3,5', 3.50::numeric),
        ('Е3-5_t3_r4', 'simple', 'rate', '2-56', 2.56::numeric),
        ('Е3-5_t3_r4', 'medium', 'n_vr', '3,9', 3.90::numeric),
        ('Е3-5_t3_r4', 'medium', 'rate', '3-00', 3.00::numeric),
        ('Е3-5_t3_r4', 'complex', 'n_vr', '4,8', 4.80::numeric),
        ('Е3-5_t3_r4', 'complex', 'rate', '3-70', 3.70::numeric),

        ('Е3-5_t3_r5', 'thickness_range', 'cell', 'Более 580', NULL::numeric),
        ('Е3-5_t3_r5', 'finish_type', 'cell', 'Под штукатурку', NULL::numeric),
        ('Е3-5_t3_r5', 'simple', 'n_vr', '2,4', 2.40::numeric),
        ('Е3-5_t3_r5', 'simple', 'rate', '1-75', 1.75::numeric),
        ('Е3-5_t3_r5', 'medium', 'n_vr', '2,9', 2.90::numeric),
        ('Е3-5_t3_r5', 'medium', 'rate', '2-23', 2.23::numeric),
        ('Е3-5_t3_r5', 'complex', 'n_vr', '3,6', 3.60::numeric),
        ('Е3-5_t3_r5', 'complex', 'rate', '2-77', 2.77::numeric),

        ('Е3-5_t3_r6', 'thickness_range', 'cell', 'Более 580', NULL::numeric),
        ('Е3-5_t3_r6', 'finish_type', 'cell', 'С расшивкой', NULL::numeric),
        ('Е3-5_t3_r6', 'simple', 'n_vr', '2,9', 2.90::numeric),
        ('Е3-5_t3_r6', 'simple', 'rate', '2-12', 2.12::numeric),
        ('Е3-5_t3_r6', 'medium', 'n_vr', '3,3', 3.30::numeric),
        ('Е3-5_t3_r6', 'medium', 'rate', '2-54', 2.54::numeric),
        ('Е3-5_t3_r6', 'complex', 'n_vr', '4', 4.00::numeric),
        ('Е3-5_t3_r6', 'complex', 'rate', '3-08', 3.08::numeric)
) AS v(source_row_id, source_column_key, value_type, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns nc
  ON nc.norm_table_id = t.id
 AND nc.source_column_key = v.source_column_key;

COMMIT;
