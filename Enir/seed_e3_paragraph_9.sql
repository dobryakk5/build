BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-9';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-9',
    'Е3-9',
    'Кладка парапета из кирпича',
    '1 м3 кладки',
    8
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'I'
JOIN enir_chapters ch
  ON ch.collection_id = c.id
 AND ch.source_chapter_id = '1'
WHERE c.code = 'Е3';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT
    p.id,
    0,
    '{"condition":"","operations":["1. Натягивание причалки.","2. Подача и раскладка кирпича.","3. Перелопачивание и расстилание раствора.","4. Кладка парапета с подбором, околкой и отеской кирпича.","5. Устройство цементного отлива.","6. Укладка закладных деталей в кладку (при необходимости).","7. Расшивка швов."]}'
FROM enir_paragraphs p
WHERE p.code = 'Е3-9';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, NULL, 0
FROM enir_paragraphs p
WHERE p.code = 'Е3-9';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, '1. Натягивание причалки.'),
        (1, '2. Подача и раскладка кирпича.'),
        (2, '3. Перелопачивание и расстилание раствора.'),
        (3, '4. Кладка парапета с подбором, околкой и отеской кирпича.'),
        (4, '5. Устройство цементного отлива.'),
        (5, '6. Укладка закладных деталей в кладку (при необходимости).'),
        (6, '7. Расшивка швов.')
    ) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-9';

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
WHERE p.code = 'Е3-9';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Каменщик', 4.0::numeric(4,1), 1),
        ('Каменщик', 3.0::numeric(4,1), 1)
    ) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-9';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT p.id, v.sort_order, v.code, v.text, NULL, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            0,
            'ПР-1',
            'При укладке закладных деталей из деревянных брусков или досок в кладку (для образования паза, в который будет заводиться рубероид при устройстве кровли) принимать на 1 м детали Н.вр. 0,01 чел.-ч, каменщика 3 разр., Расц. 0-00,7 (ПР-1).',
            '{"embedded_wood_detail":true,"per_unit":"1m_detail","add_n_vr":0.01,"add_rate":0.007,"worker_grade":3}'::jsonb
        ),
        (
            1,
            NULL,
            'Нормами предусмотрена кладка парапета с выкладкой рисунка.',
            NULL
        )
    ) AS v(sort_order, code, text, conditions)
ON true
WHERE p.code = 'Е3-9';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT p.id, v.num, v.text, NULL, v.pr_code, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            1,
            'ПР-1',
            'При укладке закладных деталей из деревянных брусков или досок в кладку (для образования паза, в который будет заводиться рубероид при устройстве кровли) принимать на 1 м детали Н.вр. 0,01 чел.-ч, каменщика 3 разр., Расц. 0-00,7 (ПР-1).',
            '{"embedded_wood_detail":true,"per_unit":"1m_detail","add_n_vr":0.01,"add_rate":0.007,"worker_grade":3}'::jsonb
        ),
        (
            2,
            NULL,
            'Нормами предусмотрена кладка парапета с выкладкой рисунка.',
            NULL
        )
    ) AS v(num, pr_code, text, conditions)
ON true
WHERE p.code = 'Е3-9';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-9_table1', 0, 'Нормы времени и расценки на 1 м3 кладки', 5
FROM enir_paragraphs p
WHERE p.code = 'Е3-9';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('bonding_system', 0, 'Система перевязки кладки', NULL),
        ('thickness_bricks', 1, 'Толщина кладки парапета в кирпичах', NULL),
        ('norm_time', 2, 'Н.вр.', NULL),
        ('price_rub', 3, 'Расц.', NULL)
    ) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-9_table1';

CREATE TEMP TABLE tmp_e3_9_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_9_rows
    (source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-9_r1', 0, 1, '{"structure":"parapet","bonding_system":"ordinary","thickness_bricks":1.0}'),
    ('Е3-9_r2', 1, 2, '{"structure":"parapet","bonding_system":"ordinary","thickness_bricks":1.5}'),
    ('Е3-9_r3', 2, 3, '{"structure":"parapet","bonding_system":"ordinary","thickness_bricks":2.0}'),
    ('Е3-9_r4', 3, 4, '{"structure":"parapet","bonding_system":"ordinary","thickness_bricks":2.5}'),
    ('Е3-9_r5', 4, 5, '{"structure":"parapet","bonding_system":"combined_vertical_joints","thickness_bricks":1.5}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_9_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = 'Е3-9_table1';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    c.id,
    'cell',
    v.value_text,
    v.value_numeric
FROM tmp_e3_9_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-9_r1', 'bonding_system', 'Обычная', NULL::numeric),
        ('Е3-9_r1', 'thickness_bricks', '1', NULL::numeric),
        ('Е3-9_r1', 'norm_time', '4,7', 4.70::numeric),
        ('Е3-9_r1', 'price_rub', '3-50', 3.50::numeric),
        ('Е3-9_r2', 'bonding_system', 'Обычная', NULL::numeric),
        ('Е3-9_r2', 'thickness_bricks', '1 1/2', NULL::numeric),
        ('Е3-9_r2', 'norm_time', '3,9', 3.90::numeric),
        ('Е3-9_r2', 'price_rub', '2-91', 2.91::numeric),
        ('Е3-9_r3', 'bonding_system', 'Обычная', NULL::numeric),
        ('Е3-9_r3', 'thickness_bricks', '2', NULL::numeric),
        ('Е3-9_r3', 'norm_time', '3,5', 3.50::numeric),
        ('Е3-9_r3', 'price_rub', '2-61', 2.61::numeric),
        ('Е3-9_r4', 'bonding_system', 'Обычная', NULL::numeric),
        ('Е3-9_r4', 'thickness_bricks', '2 1/2', NULL::numeric),
        ('Е3-9_r4', 'norm_time', '3,3', 3.30::numeric),
        ('Е3-9_r4', 'price_rub', '2-46', 2.46::numeric),
        ('Е3-9_r5', 'bonding_system', 'С совмещенными вертикальными швами', NULL::numeric),
        ('Е3-9_r5', 'thickness_bricks', '1 1/2', NULL::numeric),
        ('Е3-9_r5', 'norm_time', '5,1', 5.10::numeric),
        ('Е3-9_r5', 'price_rub', '3-80', 3.80::numeric)
    ) AS v(source_row_id, source_column_key, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key;

COMMIT;
