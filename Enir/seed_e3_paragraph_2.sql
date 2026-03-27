BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-2';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-2',
    'Е3-2',
    'Изоляция фундаментов',
    '100 м2 изоляции',
    1
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
            '{"condition":"При изоляции рулонными материалами","operations":["1. Выравнивание верхней поверхности фундаментов цементным раствором при толщине слоя до 2,5 см.","2. Резка рулонных материалов и промазка их разогретой мастикой.","3. Укладка рулонных материалов."]}'
        ),
        (
            1,
            '{"condition":"При изоляции цементным раствором","operations":["1. Укладка цементного раствора на верхнюю поверхность фундамента.","2. Выравнивание и затирка поверхности."]}'
        )
) AS v(sort_order, raw_text)
ON true
WHERE p.code = 'Е3-2';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, v.condition, v.sort_order
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'При изоляции рулонными материалами'),
        (1, 'При изоляции цементным раствором')
) AS v(sort_order, condition)
ON true
WHERE p.code = 'Е3-2';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, 0, '1. Выравнивание верхней поверхности фундаментов цементным раствором при толщине слоя до 2,5 см.'),
        (0, 1, '2. Резка рулонных материалов и промазка их разогретой мастикой.'),
        (0, 2, '3. Укладка рулонных материалов.'),
        (1, 0, '1. Укладка цементного раствора на верхнюю поверхность фундамента.'),
        (1, 1, '2. Выравнивание и затирка поверхности.')
) AS v(composition_sort_order, sort_order, text)
  ON v.composition_sort_order = wc.sort_order
WHERE p.code = 'Е3-2';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, 0, 'Каменщик', 3.0::numeric(4,1), 1, 'Каменщик 3 разр. - 1'
FROM enir_paragraphs p
WHERE p.code = 'Е3-2';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, 'Каменщик', 3.0::numeric(4,1), 1
FROM enir_paragraphs p
WHERE p.code = 'Е3-2';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT
    p.id,
    0,
    NULL,
    'Варку и разогрев битумной мастики для изоляции фундаментов рулонными материалами и изоляцию боковых поверхностей фундаментов нефтебитумом или смолой нормировать по Е11 "Изоляционные работы".',
    NULL,
    NULL,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-2';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT
    p.id,
    1,
    'Варку и разогрев битумной мастики для изоляции фундаментов рулонными материалами и изоляцию боковых поверхностей фундаментов нефтебитумом или смолой нормировать по Е11 "Изоляционные работы".',
    NULL,
    NULL,
    NULL,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-2';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-2_table1', 0, 'Нормы времени и расценки на 100 м2 изоляции', 3
FROM enir_paragraphs p
WHERE p.code = 'Е3-2';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('work_type', 0, 'Вид изоляции', NULL),
        ('norm_time', 1, 'Н.вр.', NULL),
        ('price_rub', 2, 'Расц.', NULL)
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-2_table1';

CREATE TEMP TABLE tmp_e3_2_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    work_type_title text NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_2_rows
    (source_row_id, sort_order, source_row_num, work_type_title, params)
VALUES
    ('Е3-2_r1', 0, 1, 'Рулонными материалами при укладке в один слой', '{"material":"roll","layers":1}'),
    ('Е3-2_r2', 1, 2, 'Рулонными материалами при укладке в два слоя', '{"material":"roll","layers":2}'),
    ('Е3-2_r3', 2, 3, 'Цементным раствором', '{"material":"cement_mortar"}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_2_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = 'Е3-2_table1';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    nc.id,
    'cell',
    v.value_text,
    v.value_numeric
FROM tmp_e3_2_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-2_r1', 'work_type', 'Рулонными материалами при укладке в один слой', NULL::numeric),
        ('Е3-2_r1', 'norm_time', '7', 7.00::numeric),
        ('Е3-2_r1', 'price_rub', '4-90', 4.90::numeric),
        ('Е3-2_r2', 'work_type', 'Рулонными материалами при укладке в два слоя', NULL::numeric),
        ('Е3-2_r2', 'norm_time', '8,3', 8.30::numeric),
        ('Е3-2_r2', 'price_rub', '5-81', 5.81::numeric),
        ('Е3-2_r3', 'work_type', 'Цементным раствором', NULL::numeric),
        ('Е3-2_r3', 'norm_time', '5,6', 5.60::numeric),
        ('Е3-2_r3', 'price_rub', '3-92', 3.92::numeric)
) AS v(source_row_id, source_column_key, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns nc
  ON nc.norm_table_id = t.id
 AND nc.source_column_key = v.source_column_key;

COMMIT;
