BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-7';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-7',
    'Е3-7',
    'Кладка простых стен из сплошных продольных полнотелых половинок бетонных камней с облицовкой кирпичом',
    '1 м3 кладки',
    6
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'I'
JOIN enir_chapters ch
  ON ch.collection_id = c.id
 AND ch.source_chapter_id = '1'
WHERE c.code = 'Е3';

INSERT INTO enir_paragraph_technical_characteristics (paragraph_id, sort_order, raw_text)
SELECT p.id, 0, 'Нормой предусмотрена кладка наружных стен толщиной в один камень из сплошных продольных половинок бетонных камней размером 390x90x188 мм с облицовкой утолщенным кирпичом.'
FROM enir_paragraphs p
WHERE p.code = 'Е3-7';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT
    p.id,
    0,
    '{"condition":"","operations":["1. Натягивание причалки.","2. Подача и раскладка камней и кирпича.","3. Перелопачивание, расстилание и разравнивание раствора.","4. Кладка стен с подбором и приколкой камней.","5. Заделка балочных гнезд.","6. Укладка железобетонных брусковых перемычек с подливкой раствора, подгонкой перемычек по месту и заполнением швов между брусками раствором.","7. Облицовка стен в 1/2 кирпича с расшивкой швов облицовки."]}'
FROM enir_paragraphs p
WHERE p.code = 'Е3-7';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, NULL, 0
FROM enir_paragraphs p
WHERE p.code = 'Е3-7';

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
        (3, '4. Кладка стен с подбором и приколкой камней.'),
        (4, '5. Заделка балочных гнезд.'),
        (5, '6. Укладка железобетонных брусковых перемычек с подливкой раствора, подгонкой перемычек по месту и заполнением швов между брусками раствором.'),
        (6, '7. Облицовка стен в 1/2 кирпича с расшивкой швов облицовки.')
) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-7';

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
WHERE p.code = 'Е3-7';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Каменщик', 4.0::numeric(4,1), 1),
        ('Каменщик', 3.0::numeric(4,1), 1)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-7';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-7_table1', 0, 'Норма времени и расценка на 1 м3 кладки', 1
FROM enir_paragraphs p
WHERE p.code = 'Е3-7';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('work_scope', 0, 'Состав работы', NULL),
        ('norm_time', 1, 'Н.вр.', NULL),
        ('price_rub', 2, 'Расц.', NULL)
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-7_table1';

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT
    t.id,
    'Е3-7_r1',
    0,
    1,
    '{"structure":"wall","stone_type":"solid_longitudinal_half_block","cladding":"brick","thickness_stones":1.0}'::jsonb
FROM enir_norm_tables t
WHERE t.source_table_id = 'Е3-7_table1';

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
        ('work_scope', 'cell', 'Кладка простых стен из сплошных продольных полнотелых половинок бетонных камней с облицовкой кирпичом', NULL::numeric),
        ('norm_time', 'cell', '4', 4.00::numeric),
        ('price_rub', 'cell', '2-98', 2.98::numeric)
) AS v(source_column_key, value_type, value_text, value_numeric)
  ON true
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key
WHERE r.source_row_id = 'Е3-7_r1';

COMMIT;
