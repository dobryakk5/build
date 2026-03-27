BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-1';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-1',
    'Е3-1',
    'Устройство фундаментов, стен и столбов из бутового камня, бутобетона и других материалов',
    '1 м3 кладки',
    0
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'I'
JOIN enir_chapters ch
  ON ch.collection_id = c.id
 AND ch.source_chapter_id = '1'
WHERE c.code = 'Е3';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT p.id, v.sort_order, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            0,
            '{"condition":"При кладке фундаментов, стен и столбов под лопатку","operations":["1. Опускание материалов в траншею.","2. Натягивание причалки.","3. Перелопачивание, расстилание и разравнивание раствора.","4. Подбор камней.","5. Кладка верстовых рядов с выкладкой всех усложнений кладки (пилястры, контрфорсы и т. д.) с тщательной приколкой камня стен и столбов.","6. Кладка забутки с грубой приколкой камня.","7. Расщебенка пустот с бойкой щебня.","8. Укладка железобетонных брусковых перемычек с подливкой раствора, пригонкой перемычек по месту и заполнением швов между брусками раствором (при кладке стен с проемами).","9. Кладка облицовки (при кладке стен с облицовкой)."]}'
        ),
        (
            1,
            '{"condition":"При устройстве фундаментов из бутового камня, кирпичного боя или щебня под залив","operations":["1. Опускание материалов в траншею.","2. Укладывание камня или рассыпка кирпичного боя или щебня слоями.","3. Послойная заливка раствором.","4. Трамбование каждого слоя."]}'
        ),
        (
            2,
            '{"condition":"При устройстве бутобетонных фундаментов","operations":["1. Опускание материалов в траншею.","2. Укладка бетона слоями.","3. Втапливание бутовых камней горизонтальными рядами в каждый слой бетона.","4. Уплотнение каждого слоя вибрированием."]}'
        )
) AS v(sort_order, raw_text)
ON true
WHERE p.code = 'Е3-1';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, v.condition, v.sort_order
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'При кладке фундаментов, стен и столбов под лопатку'),
        (1, 'При устройстве фундаментов из бутового камня, кирпичного боя или щебня под залив'),
        (2, 'При устройстве бутобетонных фундаментов')
) AS v(sort_order, condition)
ON true
WHERE p.code = 'Е3-1';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, 0, '1. Опускание материалов в траншею.'),
        (0, 1, '2. Натягивание причалки.'),
        (0, 2, '3. Перелопачивание, расстилание и разравнивание раствора.'),
        (0, 3, '4. Подбор камней.'),
        (0, 4, '5. Кладка верстовых рядов с выкладкой всех усложнений кладки (пилястры, контрфорсы и т. д.) с тщательной приколкой камня стен и столбов.'),
        (0, 5, '6. Кладка забутки с грубой приколкой камня.'),
        (0, 6, '7. Расщебенка пустот с бойкой щебня.'),
        (0, 7, '8. Укладка железобетонных брусковых перемычек с подливкой раствора, пригонкой перемычек по месту и заполнением швов между брусками раствором (при кладке стен с проемами).'),
        (0, 8, '9. Кладка облицовки (при кладке стен с облицовкой).'),
        (1, 0, '1. Опускание материалов в траншею.'),
        (1, 1, '2. Укладывание камня или рассыпка кирпичного боя или щебня слоями.'),
        (1, 2, '3. Послойная заливка раствором.'),
        (1, 3, '4. Трамбование каждого слоя.'),
        (2, 0, '1. Опускание материалов в траншею.'),
        (2, 1, '2. Укладка бетона слоями.'),
        (2, 2, '3. Втапливание бутовых камней горизонтальными рядами в каждый слой бетона.'),
        (2, 3, '4. Уплотнение каждого слоя вибрированием.')
) AS v(composition_sort_order, sort_order, text)
  ON v.composition_sort_order = wc.sort_order
WHERE p.code = 'Е3-1';

INSERT INTO enir_source_crew_items (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, 0, 'Каменщик', 5.0, 1, 'Каменщик 5 разр. - 1'
FROM enir_paragraphs p
WHERE p.code = 'Е3-1';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, 'Каменщик', 5.0, 1
FROM enir_paragraphs p
WHERE p.code = 'Е3-1';

INSERT INTO enir_source_notes (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT p.id, v.sort_order, v.code, v.text, v.coefficient, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            0,
            'ПР-1',
            'Нормами предусмотрена кладка как выше уровня земли, так и на глубине до 1,2 м. При глубине более 1,2 м Н.вр. и Расц. умножать на 1,15 (ПР-1).',
            1.15::numeric(6,4),
            '{"depth_m":{"gt":1.2}}'::jsonb
        ),
        (
            1,
            'ПР-2',
            'Нормами предусмотрена кладка в траншеях и котлованах без распор. При наличии распор Н.вр. и Расц. умножать на 1,1 (ПР-2).',
            1.10::numeric(6,4),
            '{"has_struts":true}'::jsonb
        ),
        (
            2,
            NULL,
            'Расшивку швов кладки бутовых стен нормировать по § Е3-19.',
            NULL,
            NULL
        ),
        (
            3,
            NULL,
            'Устройство опалубки следует нормировать дополнительно.',
            NULL,
            NULL
        )
) AS v(sort_order, code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-1';

INSERT INTO enir_notes (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT p.id, v.num, v.text, v.coefficient, v.pr_code, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            1,
            'ПР-1',
            'Нормами предусмотрена кладка как выше уровня земли, так и на глубине до 1,2 м. При глубине более 1,2 м Н.вр. и Расц. умножать на 1,15 (ПР-1).',
            1.15::numeric(6,4),
            '{"depth_m":{"gt":1.2}}'::jsonb
        ),
        (
            2,
            'ПР-2',
            'Нормами предусмотрена кладка в траншеях и котлованах без распор. При наличии распор Н.вр. и Расц. умножать на 1,1 (ПР-2).',
            1.10::numeric(6,4),
            '{"has_struts":true}'::jsonb
        ),
        (
            3,
            NULL,
            'Расшивку швов кладки бутовых стен нормировать по § Е3-19.',
            NULL,
            NULL
        ),
        (
            4,
            NULL,
            'Устройство опалубки следует нормировать дополнительно.',
            NULL,
            NULL
        )
) AS v(num, pr_code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-1';

INSERT INTO enir_norm_tables (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-1__T1', 0, 'Нормы времени и расценки на 1 м3 кладки', 20
FROM enir_paragraphs p
WHERE p.code = 'Е3-1';

INSERT INTO enir_norm_columns (norm_table_id, source_column_key, sort_order, header, label)
SELECT nt.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables nt
JOIN (
    VALUES
        ('row_num', 0, '№', NULL),
        ('work_type', 1, 'Вид кладки', NULL),
        ('condition', 2, 'Характеристика', NULL),
        ('thickness_mm', 3, 'Толщина кладки, мм', NULL),
        ('column_label', 4, 'Графа', NULL),
        ('norm_time', 5, 'Н.вр.', NULL),
        ('price_rub', 6, 'Расц.', NULL)
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE nt.source_table_id = 'Е3-1__T1';

CREATE TEMP TABLE tmp_e3_1_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    row_num smallint NOT NULL,
    work_type text NOT NULL,
    condition text NOT NULL,
    thickness_mm integer,
    column_label text NOT NULL,
    norm_time numeric(10,4) NOT NULL,
    price_rub numeric(12,4) NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_1_rows
    (source_row_id, sort_order, source_row_num, row_num, work_type, condition, thickness_mm, column_label, norm_time, price_rub, params)
VALUES
    ('Е3-1__T1__R1',  0, 1, 1, 'Из бутового камня под лопатку', 'Ленточные фундаменты', 600,  'а', 2.90, 2.16, '{"work_type":"rubble_spade","structure":"strip_foundation","thickness_mm":600}'),
    ('Е3-1__T1__R2',  1, 1, 1, 'Из бутового камня под лопатку', 'Ленточные фундаменты', 800,  'б', 2.40, 1.79, '{"work_type":"rubble_spade","structure":"strip_foundation","thickness_mm":800}'),
    ('Е3-1__T1__R3',  2, 1, 1, 'Из бутового камня под лопатку', 'Ленточные фундаменты', 1200, 'в', 2.20, 1.64, '{"work_type":"rubble_spade","structure":"strip_foundation","thickness_mm":1200}'),
    ('Е3-1__T1__R4',  3, 1, 1, 'Из бутового камня под лопатку', 'Ленточные фундаменты', 2000, 'г', 2.00, 1.49, '{"work_type":"rubble_spade","structure":"strip_foundation","thickness_mm":2000}'),
    ('Е3-1__T1__R5',  4, 2, 2, 'Из бутового камня под лопатку', 'Столбы', 600,  'а', 5.40, 4.35, '{"work_type":"rubble_spade","structure":"column","thickness_mm":600}'),
    ('Е3-1__T1__R6',  5, 2, 2, 'Из бутового камня под лопатку', 'Столбы', 800,  'б', 4.40, 3.54, '{"work_type":"rubble_spade","structure":"column","thickness_mm":800}'),
    ('Е3-1__T1__R7',  6, 2, 2, 'Из бутового камня под лопатку', 'Столбы', 1200, 'в', 3.60, 2.90, '{"work_type":"rubble_spade","structure":"column","thickness_mm":1200}'),
    ('Е3-1__T1__R8',  7, 3, 3, 'Из бутового камня под лопатку', 'Стены без облицовки, глухие', 600,  'а', 3.60, 2.68, '{"work_type":"rubble_spade","structure":"wall","cladding":false,"openings":false,"thickness_mm":600}'),
    ('Е3-1__T1__R9',  8, 3, 3, 'Из бутового камня под лопатку', 'Стены без облицовки, глухие', 800,  'б', 3.00, 2.24, '{"work_type":"rubble_spade","structure":"wall","cladding":false,"openings":false,"thickness_mm":800}'),
    ('Е3-1__T1__R10', 9, 3, 3, 'Из бутового камня под лопатку', 'Стены без облицовки, глухие', 1200, 'в', 2.60, 1.94, '{"work_type":"rubble_spade","structure":"wall","cladding":false,"openings":false,"thickness_mm":1200}'),
    ('Е3-1__T1__R11', 10, 4, 4, 'Из бутового камня под лопатку', 'Стены без облицовки, с проемами', 600,  'а', 3.90, 2.91, '{"work_type":"rubble_spade","structure":"wall","cladding":false,"openings":true,"thickness_mm":600}'),
    ('Е3-1__T1__R12', 11, 4, 4, 'Из бутового камня под лопатку', 'Стены без облицовки, с проемами', 800,  'б', 3.40, 2.53, '{"work_type":"rubble_spade","structure":"wall","cladding":false,"openings":true,"thickness_mm":800}'),
    ('Е3-1__T1__R13', 12, 4, 4, 'Из бутового камня под лопатку', 'Стены без облицовки, с проемами', 1200, 'в', 3.00, 2.24, '{"work_type":"rubble_spade","structure":"wall","cladding":false,"openings":true,"thickness_mm":1200}'),
    ('Е3-1__T1__R14', 13, 5, 5, 'Из бутового камня под лопатку', 'Стены с облицовкой кирпичом, глухие', 600,  'а', 3.80, 2.83, '{"work_type":"rubble_spade","structure":"wall","cladding":true,"openings":false,"thickness_mm":600}'),
    ('Е3-1__T1__R15', 14, 5, 5, 'Из бутового камня под лопатку', 'Стены с облицовкой кирпичом, глухие', 800,  'б', 3.30, 2.46, '{"work_type":"rubble_spade","structure":"wall","cladding":true,"openings":false,"thickness_mm":800}'),
    ('Е3-1__T1__R16', 15, 5, 5, 'Из бутового камня под лопатку', 'Стены с облицовкой кирпичом, глухие', 1200, 'в', 2.90, 2.16, '{"work_type":"rubble_spade","structure":"wall","cladding":true,"openings":false,"thickness_mm":1200}'),
    ('Е3-1__T1__R17', 16, 6, 6, 'Из бутового камня под лопатку', 'Стены с облицовкой кирпичом, с проемами', 600,  'а', 4.30, 3.20, '{"work_type":"rubble_spade","structure":"wall","cladding":true,"openings":true,"thickness_mm":600}'),
    ('Е3-1__T1__R18', 17, 6, 6, 'Из бутового камня под лопатку', 'Стены с облицовкой кирпичом, с проемами', 800,  'б', 3.70, 2.76, '{"work_type":"rubble_spade","structure":"wall","cladding":true,"openings":true,"thickness_mm":800}'),
    ('Е3-1__T1__R19', 18, 6, 6, 'Из бутового камня под лопатку', 'Стены с облицовкой кирпичом, с проемами', 1200, 'в', 3.20, 2.38, '{"work_type":"rubble_spade","structure":"wall","cladding":true,"openings":true,"thickness_mm":1200}'),
    ('Е3-1__T1__R20', 19, 7, 7, 'Из бутового камня, кирпичного боя или щебня под залив и из бутобетона', 'Под залив и бутобетон', NULL, 'а', 1.20, 0.84, '{"work_type":"rubble_pour_or_concrete"}');

INSERT INTO enir_norm_rows (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT nt.id, t.source_row_id, t.sort_order, t.source_row_num, t.params
FROM tmp_e3_1_rows t
JOIN enir_norm_tables nt
  ON nt.source_table_id = 'Е3-1__T1';

INSERT INTO enir_norm_values (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT nr.id, nc.id, v.value_type, v.value_text, v.value_numeric
FROM (
    SELECT source_row_id, 'row_num' AS column_key, 'cell' AS value_type, row_num::text AS value_text, row_num::numeric AS value_numeric
    FROM tmp_e3_1_rows
    UNION ALL
    SELECT source_row_id, 'work_type', 'cell', work_type, NULL
    FROM tmp_e3_1_rows
    UNION ALL
    SELECT source_row_id, 'condition', 'cell', condition, NULL
    FROM tmp_e3_1_rows
    UNION ALL
    SELECT source_row_id, 'thickness_mm', 'cell', thickness_mm::text, thickness_mm::numeric
    FROM tmp_e3_1_rows
    WHERE thickness_mm IS NOT NULL
    UNION ALL
    SELECT source_row_id, 'column_label', 'cell', column_label, NULL
    FROM tmp_e3_1_rows
    UNION ALL
    SELECT source_row_id, 'norm_time', 'cell', trim(to_char(norm_time, 'FM999999990.00')), norm_time
    FROM tmp_e3_1_rows
    UNION ALL
    SELECT source_row_id, 'price_rub', 'cell', trim(to_char(price_rub, 'FM999999990.00')), price_rub
    FROM tmp_e3_1_rows
) AS v
JOIN enir_norm_rows nr
  ON nr.source_row_id = v.source_row_id
JOIN enir_norm_columns nc
  ON nc.norm_table_id = nr.norm_table_id
 AND nc.source_column_key = v.column_key;

COMMIT;
