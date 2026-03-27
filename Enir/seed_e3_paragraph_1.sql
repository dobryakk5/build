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

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Каменщик', 5.0::numeric(4,1), 1, 'Каменщик 5 разр. — 1 (столбы, под лопатку)'),
        (1, 'Каменщик', 3.0::numeric(4,1), 1, 'Каменщик 3 разр. — 1 (столбы, под лопатку)'),
        (2, 'Каменщик', 4.0::numeric(4,1), 1, 'Каменщик 4 разр. — 1 (фундаменты и стены, под лопатку)'),
        (3, 'Каменщик', 3.0::numeric(4,1), 1, 'Каменщик 3 разр. — 1 (фундаменты и стены, под лопатку)'),
        (4, 'Каменщик', 3.0::numeric(4,1), 2, 'Каменщик 3 разр. — 2 (прочие виды)')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-1';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Каменщик', 5.0::numeric(4,1), 1),
        ('Каменщик', 4.0::numeric(4,1), 1),
        ('Каменщик', 3.0::numeric(4,1), 1),
        ('Каменщик', 3.0::numeric(4,1), 2)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-1';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
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

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
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

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-1_table3', 0, 'Нормы времени и расценки на 1 м3 кладки', 7
FROM enir_paragraphs p
WHERE p.code = 'Е3-1';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('work_type', 0, 'Вид кладки', NULL),
        ('thickness_600', 1, 'Толщина кладки до 600 мм', 'а'),
        ('thickness_800', 2, 'Толщина кладки до 800 мм', 'б'),
        ('thickness_1200', 3, 'Толщина кладки до 1200 мм', 'в'),
        ('thickness_2000', 4, 'Толщина кладки до 2000 мм', 'г')
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-1_table3';

CREATE TEMP TABLE tmp_e3_1_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    work_type_title text NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_1_rows
    (source_row_id, sort_order, source_row_num, work_type_title, params)
VALUES
    ('Е3-1_r1', 0, 1, 'Ленточные фундаменты', '{"work_type":"rubble_spade","structure":"strip_foundation"}'),
    ('Е3-1_r2', 1, 2, 'Столбы', '{"work_type":"rubble_spade","structure":"column"}'),
    ('Е3-1_r3', 2, 3, 'Стены без облицовки, глухие', '{"work_type":"rubble_spade","structure":"wall","cladding":false,"openings":false}'),
    ('Е3-1_r4', 3, 4, 'Стены без облицовки, с проемами', '{"work_type":"rubble_spade","structure":"wall","cladding":false,"openings":true}'),
    ('Е3-1_r5', 4, 5, 'Стены с облицовкой кирпичом, глухие', '{"work_type":"rubble_spade","structure":"wall","cladding":true,"openings":false}'),
    ('Е3-1_r6', 5, 6, 'Стены с облицовкой кирпичом, с проемами', '{"work_type":"rubble_spade","structure":"wall","cladding":true,"openings":true}'),
    ('Е3-1_r7', 6, 7, 'Из бутового камня, кирпичного боя или щебня под залив и из бутобетона', '{"work_type":"rubble_pour_or_concrete"}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_1_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = 'Е3-1_table3';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    nc.id,
    v.value_type,
    v.value_text,
    v.value_numeric
FROM tmp_e3_1_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-1_r1', 'work_type', 'cell', 'Ленточные фундаменты', NULL::numeric),
        ('Е3-1_r1', 'thickness_600', 'n_vr', '2,9', 2.90::numeric),
        ('Е3-1_r1', 'thickness_600', 'rate', '2-16', 2.16::numeric),
        ('Е3-1_r1', 'thickness_800', 'n_vr', '2,4', 2.40::numeric),
        ('Е3-1_r1', 'thickness_800', 'rate', '1-79', 1.79::numeric),
        ('Е3-1_r1', 'thickness_1200', 'n_vr', '2,2', 2.20::numeric),
        ('Е3-1_r1', 'thickness_1200', 'rate', '1-64', 1.64::numeric),
        ('Е3-1_r1', 'thickness_2000', 'n_vr', '2,0', 2.00::numeric),
        ('Е3-1_r1', 'thickness_2000', 'rate', '1-49', 1.49::numeric),

        ('Е3-1_r2', 'work_type', 'cell', 'Столбы', NULL::numeric),
        ('Е3-1_r2', 'thickness_600', 'n_vr', '5,4', 5.40::numeric),
        ('Е3-1_r2', 'thickness_600', 'rate', '4-35', 4.35::numeric),
        ('Е3-1_r2', 'thickness_800', 'n_vr', '4,4', 4.40::numeric),
        ('Е3-1_r2', 'thickness_800', 'rate', '3-54', 3.54::numeric),
        ('Е3-1_r2', 'thickness_1200', 'n_vr', '3,6', 3.60::numeric),
        ('Е3-1_r2', 'thickness_1200', 'rate', '2-90', 2.90::numeric),

        ('Е3-1_r3', 'work_type', 'cell', 'Стены без облицовки, глухие', NULL::numeric),
        ('Е3-1_r3', 'thickness_600', 'n_vr', '3,6', 3.60::numeric),
        ('Е3-1_r3', 'thickness_600', 'rate', '2-68', 2.68::numeric),
        ('Е3-1_r3', 'thickness_800', 'n_vr', '3,0', 3.00::numeric),
        ('Е3-1_r3', 'thickness_800', 'rate', '2-24', 2.24::numeric),
        ('Е3-1_r3', 'thickness_1200', 'n_vr', '2,6', 2.60::numeric),
        ('Е3-1_r3', 'thickness_1200', 'rate', '1-94', 1.94::numeric),

        ('Е3-1_r4', 'work_type', 'cell', 'Стены без облицовки, с проемами', NULL::numeric),
        ('Е3-1_r4', 'thickness_600', 'n_vr', '3,9', 3.90::numeric),
        ('Е3-1_r4', 'thickness_600', 'rate', '2-91', 2.91::numeric),
        ('Е3-1_r4', 'thickness_800', 'n_vr', '3,4', 3.40::numeric),
        ('Е3-1_r4', 'thickness_800', 'rate', '2-53', 2.53::numeric),
        ('Е3-1_r4', 'thickness_1200', 'n_vr', '3,0', 3.00::numeric),
        ('Е3-1_r4', 'thickness_1200', 'rate', '2-24', 2.24::numeric),

        ('Е3-1_r5', 'work_type', 'cell', 'Стены с облицовкой кирпичом, глухие', NULL::numeric),
        ('Е3-1_r5', 'thickness_600', 'n_vr', '3,8', 3.80::numeric),
        ('Е3-1_r5', 'thickness_600', 'rate', '2-83', 2.83::numeric),
        ('Е3-1_r5', 'thickness_800', 'n_vr', '3,3', 3.30::numeric),
        ('Е3-1_r5', 'thickness_800', 'rate', '2-46', 2.46::numeric),
        ('Е3-1_r5', 'thickness_1200', 'n_vr', '2,9', 2.90::numeric),
        ('Е3-1_r5', 'thickness_1200', 'rate', '2-16', 2.16::numeric),

        ('Е3-1_r6', 'work_type', 'cell', 'Стены с облицовкой кирпичом, с проемами', NULL::numeric),
        ('Е3-1_r6', 'thickness_600', 'n_vr', '4,3', 4.30::numeric),
        ('Е3-1_r6', 'thickness_600', 'rate', '3-20', 3.20::numeric),
        ('Е3-1_r6', 'thickness_800', 'n_vr', '3,7', 3.70::numeric),
        ('Е3-1_r6', 'thickness_800', 'rate', '2-76', 2.76::numeric),
        ('Е3-1_r6', 'thickness_1200', 'n_vr', '3,2', 3.20::numeric),
        ('Е3-1_r6', 'thickness_1200', 'rate', '2-38', 2.38::numeric),

        ('Е3-1_r7', 'work_type', 'cell', 'Из бутового камня, кирпичного боя или щебня под залив и из бутобетона', NULL::numeric),
        ('Е3-1_r7', 'thickness_600', 'n_vr', '1,2', 1.20::numeric),
        ('Е3-1_r7', 'thickness_600', 'rate', '0-84', 0.84::numeric)
) AS v(row_id, column_key, value_type, value_text, value_numeric)
  ON v.row_id = r.source_row_id
JOIN enir_norm_columns nc
  ON nc.norm_table_id = t.id
 AND nc.source_column_key = v.column_key;

COMMIT;
