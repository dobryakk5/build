BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-29';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    NULL,
    'Е3-29',
    'Е3-29',
    'Установка временных металлических печей',
    '1 печь',
    29
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'II'
WHERE c.code = 'Е3';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT
    p.id,
    0,
    '{"condition":"","operations":["1. Выстилка кирпичом основания под печь.","2. Установка временной металлической печи.","3. Подвеска труб.","4. Вставка колена с задвижкой.","5. Обмазка стыков."]}'
FROM enir_paragraphs p
WHERE p.code = 'Е3-29';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, NULL, 0
FROM enir_paragraphs p
WHERE p.code = 'Е3-29';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, '1. Выстилка кирпичом основания под печь.'),
        (1, '2. Установка временной металлической печи.'),
        (2, '3. Подвеска труб.'),
        (3, '4. Вставка колена с задвижкой.'),
        (4, '5. Обмазка стыков.')
    ) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-29';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT
    p.id,
    0,
    'Печник',
    2.0::numeric(4,1),
    1,
    'Печник 2 разр. - 1'
FROM enir_paragraphs p
WHERE p.code = 'Е3-29';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT
    p.id,
    'Печник',
    2.0::numeric(4,1),
    1
FROM enir_paragraphs p
WHERE p.code = 'Е3-29';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT
    p.id,
    0,
    'ПР-1',
    'Нормами предусмотрена навеска до 7 м труб. На каждый следующий 1 м сверх 7 м добавлять Н.вр. 0,1 чел.-ч, Расц. 0-06,4 печника 2 разр. (ПР-1).',
    NULL,
    '{"pipe_hanging_m":{"base":7},"per_unit":"1m_pipe_over_7m","add_n_vr":0.1,"add_rate":0.064,"worker_grade":2}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-29';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT
    p.id,
    1,
    'Нормами предусмотрена навеска до 7 м труб. На каждый следующий 1 м сверх 7 м добавлять Н.вр. 0,1 чел.-ч, Расц. 0-06,4 печника 2 разр. (ПР-1).',
    NULL,
    'ПР-1',
    '{"pipe_hanging_m":{"base":7},"per_unit":"1m_pipe_over_7m","add_n_vr":0.1,"add_rate":0.064,"worker_grade":2}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-29';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-29_table1', 0, 'Нормы времени и расценки на 1 печь', 1
FROM enir_paragraphs p
WHERE p.code = 'Е3-29';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('without_lining', 0, 'Без футеровки', 'а'),
        ('with_inner_lining', 1, 'С футеровкой внутри', 'б')
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-29_table1';

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT
    t.id,
    'Е3-29_r1',
    0,
    1,
    '{"work":"install_temporary_metal_stove"}'::jsonb
FROM enir_norm_tables t
WHERE t.source_table_id = 'Е3-29_table1';

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
        ('without_lining','n_vr','1,2',1.20::numeric),
        ('without_lining','rate','0-76,8',0.768::numeric),
        ('with_inner_lining','n_vr','2',2.00::numeric),
        ('with_inner_lining','rate','1-28',1.28::numeric)
) AS v(source_column_key, value_type, value_text, value_numeric)
ON true
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key
WHERE r.source_row_id = 'Е3-29_r1';

COMMIT;
