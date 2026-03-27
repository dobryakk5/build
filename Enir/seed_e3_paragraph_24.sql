BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-24';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-24',
    'Е3-24',
    'Механизированное гашение извести',
    '1 т негашеной извести',
    24
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'I'
JOIN enir_chapters ch
  ON ch.collection_id = c.id
 AND ch.source_chapter_id = '2'
WHERE c.code = 'Е3';

INSERT INTO enir_paragraph_technical_characteristics (paragraph_id, sort_order, raw_text)
SELECT p.id, v.sort_order, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Нормами предусмотрено гашение извести двумя способами: с применением машин, работающих по принципу мокрого помола извести двухступенчатыми катками.'),
        (1, 'Нормами предусмотрено гашение извести двумя способами: с применением помольно-гасильных машин.')
) AS v(sort_order, raw_text)
ON true
WHERE p.code = 'Е3-24';

INSERT INTO enir_paragraph_application_notes (paragraph_id, sort_order, text)
SELECT p.id, v.sort_order, v.text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Нормами предусмотрено гашение извести двумя способами.'),
        (1, 'С применением машин, работающих по принципу мокрого помола извести двухступенчатыми катками.'),
        (2, 'С применением помольно-гасильных машин.')
) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-24';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT
    p.id,
    0,
    '{"condition":"","operations":["1. Загрузка комовой извести в гасильный барабан при помощи транспортера.","2. Подача в барабан воды от водопровода.","3. Наблюдение за помолом и гашением извести.","4. Выпуск гашеной извести (известковое молоко) через выгрузочное отверстие барабана в желоб (лоток).","5. Наблюдение за поступлением гашеной извести в творильную яму.","6. Очистка барабана и приемного ящика от засорения и от крупных негашеных частиц извести и инертных включений с отброской отходов от 3 м.","7. Уход за установкой."]}'
FROM enir_paragraphs p
WHERE p.code = 'Е3-24';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, NULL, 0
FROM enir_paragraphs p
WHERE p.code = 'Е3-24';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, '1. Загрузка комовой извести в гасильный барабан при помощи транспортера.'),
        (1, '2. Подача в барабан воды от водопровода.'),
        (2, '3. Наблюдение за помолом и гашением извести.'),
        (3, '4. Выпуск гашеной извести (известковое молоко) через выгрузочное отверстие барабана в желоб (лоток).'),
        (4, '5. Наблюдение за поступлением гашеной извести в творильную яму.'),
        (5, '6. Очистка барабана и приемного ящика от засорения и от крупных негашеных частиц извести и инертных включений с отброской отходов от 3 м.'),
        (6, '7. Уход за установкой.')
    ) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-24';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Известегасильщик', 4.0::numeric(4,1), 1, 'Известегасильщик 4 разр. - 1'),
        (1, 'Известегасильщик', 3.0::numeric(4,1), 1, 'Известегасильщик 3 разр. - 1'),
        (2, 'Известегасильщик', 2.0::numeric(4,1), 3, 'Известегасильщик 2 разр. - 3')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-24';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Известегасильщик', 4.0::numeric(4,1), 1),
        ('Известегасильщик', 3.0::numeric(4,1), 1),
        ('Известегасильщик', 2.0::numeric(4,1), 3)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-24';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-24_table1', 0, 'Норма времени и расценка на 1 т негашеной извести', 1
FROM enir_paragraphs p
WHERE p.code = 'Е3-24';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('crew', 0, 'Состав звена', NULL),
        ('norm_time', 1, 'Н.вр.', NULL),
        ('price_rub', 2, 'Расц.', NULL)
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-24_table1';

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT
    t.id,
    'Е3-24_r1',
    0,
    1,
    '{"work":"mechanized_lime_slaking"}'::jsonb
FROM enir_norm_tables t
WHERE t.source_table_id = 'Е3-24_table1';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    r.id,
    c.id,
    'cell',
    v.value_text,
    v.value_numeric
FROM enir_norm_rows r
JOIN enir_norm_tables t
  ON t.id = r.norm_table_id
JOIN (
    VALUES
        ('crew', 'Известегасильщики 4 разр. - 1; 3 разр. - 1; 2 разр. - 3', NULL::numeric),
        ('norm_time', '2,7', 2.70::numeric),
        ('price_rub', '1-84', 1.84::numeric)
) AS v(source_column_key, value_text, value_numeric)
ON true
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key
WHERE r.source_row_id = 'Е3-24_r1';

COMMIT;
