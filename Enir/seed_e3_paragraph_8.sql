BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-8';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-8',
    'Е3-8',
    'Кладка стен из пустотелых керамических камней с облицовкой кирпичом',
    '1 м3 кладки',
    7
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
        (0, 'Нормами предусмотрена кладка наружных стен из керамических камней размером 250x120x138 мм с облицовкой одинарным или утолщенным кирпичом.'),
        (1, 'Отклонения в размерах и положении кладки из керамических камней от проектных принимаются, как и для кирпичной кладки (см. табл. 1 § Е3-3).')
    ) AS v(sort_order, raw_text)
ON true
WHERE p.code = 'Е3-8';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT
    p.id,
    0,
    '{"condition":"","operations":["1. Натягивание причалки.","2. Подача и раскладка камней и кирпича.","3. Перелопачивание, расстилание и разравнивание раствора.","4. Подбор лицевого кирпича.","5. Кладка стен с облицовкой в 1/2 кирпича, с выкладкой всех усложнений кладки, подбором, околкой и отеской кирпича и керамических камней.","6. Заделка балочных гнезд.","7. Расшивка швов облицовки."]}'
FROM enir_paragraphs p
WHERE p.code = 'Е3-8';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, NULL, 0
FROM enir_paragraphs p
WHERE p.code = 'Е3-8';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, '1. Натягивание причалки.'),
        (1, '2. Подача и раскладка камней и кирпича.'),
        (2, '3. Перелопачивание, расстилание и разравнивание раствора.'),
        (3, '4. Подбор лицевого кирпича.'),
        (4, '5. Кладка стен с облицовкой в 1/2 кирпича, с выкладкой всех усложнений кладки, подбором, околкой и отеской кирпича и керамических камней.'),
        (5, '6. Заделка балочных гнезд.'),
        (6, '7. Расшивка швов облицовки.')
) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-8';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Каменщик', 5.0::numeric(4,1), 1, 'Каменщик 5 разр. - 1 (сложные стены)'),
        (1, 'Каменщик', 4.0::numeric(4,1), 1, 'Каменщик 4 разр. - 1 (простые и средней сложности)'),
        (2, 'Каменщик', 3.0::numeric(4,1), 1, 'Каменщик 3 разр. - 1')
    ) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-8';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Каменщик', 5.0::numeric(4,1), 1),
        ('Каменщик', 4.0::numeric(4,1), 1),
        ('Каменщик', 3.0::numeric(4,1), 1)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-8';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT
    p.id,
    0,
    'ПР-1',
    'При кладке стен из пустотелых керамических камней без облицовки кирпичом Н.вр. и Расц. умножать на 0,85 (ПР-1).',
    0.85::numeric(6,4),
    '{"cladding":false,"material":"hollow_ceramic_stone"}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-8';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT
    p.id,
    1,
    'При кладке стен из пустотелых керамических камней без облицовки кирпичом Н.вр. и Расц. умножать на 0,85 (ПР-1).',
    0.85::numeric(6,4),
    'ПР-1',
    '{"cladding":false,"material":"hollow_ceramic_stone"}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-8';

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
  AND p.code = 'Е3-8'
  AND tc.code IN ('ТЧ-7', 'ТЧ-8')
  AND NOT EXISTS (
      SELECT 1
      FROM enir_technical_coefficient_paragraphs tcp
      WHERE tcp.technical_coefficient_id = tc.id
        AND tcp.paragraph_id = p.id
  );

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-8_table2', 0, 'Нормы времени и расценки на 1 м3 кладки', 2
FROM enir_paragraphs p
WHERE p.code = 'Е3-8';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('thickness_mm', 0, 'Толщина стен, мм', NULL),
        ('simple_medium', 1, 'Простые и средней сложности', 'а'),
        ('complex', 2, 'Сложные', 'б')
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-8_table2';

CREATE TEMP TABLE tmp_e3_8_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_8_rows
    (source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-8_r1', 0, 1, '{"structure":"wall","material":"hollow_ceramic_stone","cladding":true,"thickness_mm":510}'),
    ('Е3-8_r2', 1, 2, '{"structure":"wall","material":"hollow_ceramic_stone","cladding":true,"thickness_mm":640}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_8_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = 'Е3-8_table2';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    c.id,
    v.value_type,
    v.value_text,
    v.value_numeric
FROM tmp_e3_8_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-8_r1', 'thickness_mm', 'cell', '510', NULL::numeric),
        ('Е3-8_r1', 'simple_medium', 'n_vr', '3,6', 3.60::numeric),
        ('Е3-8_r1', 'simple_medium', 'rate', '2-68', 2.68::numeric),
        ('Е3-8_r1', 'complex', 'n_vr', '4,3', 4.30::numeric),
        ('Е3-8_r1', 'complex', 'rate', '3-46', 3.46::numeric),
        ('Е3-8_r2', 'thickness_mm', 'cell', '640', NULL::numeric),
        ('Е3-8_r2', 'simple_medium', 'n_vr', '3,1', 3.10::numeric),
        ('Е3-8_r2', 'simple_medium', 'rate', '2-31', 2.31::numeric),
        ('Е3-8_r2', 'complex', 'n_vr', '3,6', 3.60::numeric),
        ('Е3-8_r2', 'complex', 'rate', '2-90', 2.90::numeric)
) AS v(source_row_id, source_column_key, value_type, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key;

COMMIT;
