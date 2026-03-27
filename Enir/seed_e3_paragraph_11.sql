BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-11';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-11',
    'Е3-11',
    'Кладка столбов из кирпича',
    '1 м2 кладки',
    10
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
    'Кладка не должна иметь отклонений, превышающих допуски, указанные в табл. 1.'
FROM enir_paragraphs p
WHERE p.code = 'Е3-11';

INSERT INTO enir_paragraph_application_notes (paragraph_id, sort_order, text)
SELECT p.id, v.sort_order, v.text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Указания по качеству работ.'),
        (1, 'Кладка не должна иметь отклонений, превышающих допуски, указанные в табл. 1.')
) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-11';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT
    p.id,
    0,
    '{"condition":"","operations":["1. Перелопачивание, расстилание и разравнивание раствора.","2. Кладка столбов с подбором и околкой кирпича.","3. Теска кирпича (при кладке столбов круглого сечения)."]}'
FROM enir_paragraphs p
WHERE p.code = 'Е3-11';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, NULL, 0
FROM enir_paragraphs p
WHERE p.code = 'Е3-11';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, '1. Перелопачивание, расстилание и разравнивание раствора.'),
        (1, '2. Кладка столбов с подбором и околкой кирпича.'),
        (2, '3. Теска кирпича (при кладке столбов круглого сечения).')
    ) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-11';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Каменщик', 6.0::numeric(4,1), 1, 'Каменщик 6 разр. - 1 (круглые столбы)'),
        (1, 'Каменщик', 5.0::numeric(4,1), 1, 'Каменщик 5 разр. - 1 (прямоугольные столбы)'),
        (2, 'Каменщик', 3.0::numeric(4,1), 1, 'Каменщик 3 разр. - 1')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-11';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Каменщик', 6.0::numeric(4,1), 1),
        ('Каменщик', 5.0::numeric(4,1), 1),
        ('Каменщик', 3.0::numeric(4,1), 1)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-11';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT p.id, v.sort_order, v.code, v.text, v.coefficient, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            0,
            'ПР-1',
            'Нормами предусмотрена кладка столбов без армирования. При кладке столбов с армированием сетками добавлять на 1 место Н.вр. 0,03 чел.-ч, каменщика 3 разр., Расц. 0-02,1 (ПР-1).',
            NULL::numeric(6,4),
            '{"mesh_reinforcement":true,"per_unit":"1_place","add_n_vr":0.03,"add_rate":0.021,"worker_grade":3}'::jsonb
        ),
        (
            1,
            'ПР-2',
            'При кладке прямоугольных столбов с одновременной расшивкой швов Н.вр. и Расц. умножать на 1,3 (ПР-2).',
            1.30::numeric(6,4),
            '{"shape":"rectangular","jointing":true}'::jsonb
        )
) AS v(sort_order, code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-11';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT p.id, v.num, v.text, v.coefficient, v.pr_code, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            1,
            'ПР-1',
            'Нормами предусмотрена кладка столбов без армирования. При кладке столбов с армированием сетками добавлять на 1 место Н.вр. 0,03 чел.-ч, каменщика 3 разр., Расц. 0-02,1 (ПР-1).',
            NULL::numeric(6,4),
            '{"mesh_reinforcement":true,"per_unit":"1_place","add_n_vr":0.03,"add_rate":0.021,"worker_grade":3}'::jsonb
        ),
        (
            2,
            'ПР-2',
            'При кладке прямоугольных столбов с одновременной расшивкой швов Н.вр. и Расц. умножать на 1,3 (ПР-2).',
            1.30::numeric(6,4),
            '{"shape":"rectangular","jointing":true}'::jsonb
        )
) AS v(num, pr_code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-11';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-11_table3', 0, 'Нормы времени и расценки на 1 м2 кладки', 2
FROM enir_paragraphs p
WHERE p.code = 'Е3-11';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('shape', 0, 'Форма столбов', NULL),
        ('size_metric', 1, 'Размер столбов', NULL),
        ('rect_upto_1520', 2, 'до 1520', 'а'),
        ('rect_upto_2040', 3, 'до 2040', 'б'),
        ('rect_upto_2560', 4, 'до 2560', 'в'),
        ('rect_upto_3340', 5, 'до 3340', 'г'),
        ('rect_gt_3340', 6, 'более 3340', 'д'),
        ('round_upto_380', 7, 'до 380', 'е'),
        ('round_upto_510', 8, 'до 510', 'ж'),
        ('round_upto_640', 9, 'до 640', 'з'),
        ('round_upto_770', 10, 'до 770', 'и'),
        ('round_upto_900', 11, 'до 900', 'к'),
        ('round_gt_900', 12, 'более 900', 'л')
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-11_table3';

CREATE TEMP TABLE tmp_e3_11_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_11_rows
    (source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-11_r1', 0, 1, '{"structure":"column","material":"brick","shape":"rectangular","size_metric":"perimeter_mm"}'),
    ('Е3-11_r2', 1, 2, '{"structure":"column","material":"brick","shape":"round","size_metric":"diameter_mm"}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_11_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = 'Е3-11_table3';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    c.id,
    v.value_type,
    v.value_text,
    v.value_numeric
FROM tmp_e3_11_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-11_r1', 'shape', 'cell', 'Прямоугольные', NULL::numeric),
        ('Е3-11_r1', 'size_metric', 'cell', 'Периметр, мм', NULL::numeric),
        ('Е3-11_r1', 'rect_upto_1520', 'n_vr', '7,4', 7.40::numeric),
        ('Е3-11_r1', 'rect_upto_1520', 'rate', '5-96', 5.96::numeric),
        ('Е3-11_r1', 'rect_upto_2040', 'n_vr', '5,3', 5.30::numeric),
        ('Е3-11_r1', 'rect_upto_2040', 'rate', '4-27', 4.27::numeric),
        ('Е3-11_r1', 'rect_upto_2560', 'n_vr', '4,1', 4.10::numeric),
        ('Е3-11_r1', 'rect_upto_2560', 'rate', '3-30', 3.30::numeric),
        ('Е3-11_r1', 'rect_upto_3340', 'n_vr', '3,1', 3.10::numeric),
        ('Е3-11_r1', 'rect_upto_3340', 'rate', '2-50', 2.50::numeric),
        ('Е3-11_r1', 'rect_gt_3340', 'n_vr', '2,6', 2.60::numeric),
        ('Е3-11_r1', 'rect_gt_3340', 'rate', '2-09', 2.09::numeric),
        ('Е3-11_r2', 'shape', 'cell', 'Круглые', NULL::numeric),
        ('Е3-11_r2', 'size_metric', 'cell', 'Диаметр, мм', NULL::numeric),
        ('Е3-11_r2', 'round_upto_380', 'n_vr', '11,4', 11.40::numeric),
        ('Е3-11_r2', 'round_upto_380', 'rate', '10-03', 10.03::numeric),
        ('Е3-11_r2', 'round_upto_510', 'n_vr', '9,9', 9.90::numeric),
        ('Е3-11_r2', 'round_upto_510', 'rate', '8-71', 8.71::numeric),
        ('Е3-11_r2', 'round_upto_640', 'n_vr', '8,2', 8.20::numeric),
        ('Е3-11_r2', 'round_upto_640', 'rate', '7-22', 7.22::numeric),
        ('Е3-11_r2', 'round_upto_770', 'n_vr', '5,9', 5.90::numeric),
        ('Е3-11_r2', 'round_upto_770', 'rate', '5-19', 5.19::numeric),
        ('Е3-11_r2', 'round_upto_900', 'n_vr', '4,4', 4.40::numeric),
        ('Е3-11_r2', 'round_upto_900', 'rate', '3-87', 3.87::numeric),
        ('Е3-11_r2', 'round_gt_900', 'n_vr', '3', 3.00::numeric),
        ('Е3-11_r2', 'round_gt_900', 'rate', '2-64', 2.64::numeric)
) AS v(source_row_id, source_column_key, value_type, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key;

COMMIT;
