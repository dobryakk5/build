BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-19';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-19',
    'Е3-19',
    'Расшивка швов',
    '1 м2 расшиваемой поверхности',
    19
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
        (0, 'А. Ранее выложенной кладки.'),
        (1, 'Б. Одновременно с кладкой.')
) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-19';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT
    p.id,
    0,
    '{"condition":"","operations":["1. Расчистка швов.","2. Приготовление раствора вручную.","3. Смачивание швов водой.","4. Расшивка швов кладки по заданному профилю.","5. Удаление лишнего раствора."]}'
FROM enir_paragraphs p
WHERE p.code = 'Е3-19';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, NULL, 0
FROM enir_paragraphs p
WHERE p.code = 'Е3-19';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, '1. Расчистка швов.'),
        (1, '2. Приготовление раствора вручную.'),
        (2, '3. Смачивание швов водой.'),
        (3, '4. Расшивка швов кладки по заданному профилю.'),
        (4, '5. Удаление лишнего раствора.')
    ) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-19';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT
    p.id,
    0,
    'Каменщик',
    4.0::numeric(4,1),
    1,
    'Каменщик 4 разр. - 1'
FROM enir_paragraphs p
WHERE p.code = 'Е3-19';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT
    p.id,
    'Каменщик',
    4.0::numeric(4,1),
    1
FROM enir_paragraphs p
WHERE p.code = 'Е3-19';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, v.source_table_id, v.sort_order, v.title, v.row_count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Е3-19_table1', 0, 'Нормы времени и расценки на 1 м2 расшиваемой поверхности', 3),
        ('Е3-19_table2', 1, 'Нормы времени и расценки на 1 м2 расшиваемой поверхности', 1)
) AS v(source_table_id, sort_order, title, row_count)
ON true
WHERE p.code = 'Е3-19';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('Е3-19_table1', 'surface_type', 0, 'Вид расшиваемой поверхности', NULL),
        ('Е3-19_table1', 'norm_time', 1, 'Н.вр.', NULL),
        ('Е3-19_table1', 'price_rub', 2, 'Расц.', NULL),
        ('Е3-19_table2', 'brick_250x120x65', 0, 'Кирпич одинарный 250×120×65 мм', 'а'),
        ('Е3-19_table2', 'brick_250x120x88', 1, 'Кирпич утолщенный 250×120×88 мм', 'б'),
        ('Е3-19_table2', 'hollow_ceramic_250x120x138', 2, 'Пустотелые керамические камни 250×120×138 мм', 'в'),
        ('Е3-19_table2', 'concrete_390x190x188', 3, 'Бетонные камни 390×190×188 мм', 'г')
) AS v(table_key, source_column_key, sort_order, header, label)
  ON v.table_key = t.source_table_id;

CREATE TEMP TABLE tmp_e3_19_rows (
    table_key text NOT NULL,
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_19_rows
    (table_key, source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-19_table1', 'Е3-19_t1_r1', 0, 1, '{"jointing_timing":"after_masonry","surface_type":"brick_masonry"}'),
    ('Е3-19_table1', 'Е3-19_t1_r2', 1, 2, '{"jointing_timing":"after_masonry","surface_type":"other_masonry","joint_length_m2":{"lte":3}}'),
    ('Е3-19_table1', 'Е3-19_t1_r3', 2, 3, '{"jointing_timing":"after_masonry","surface_type":"other_masonry","add_per_next_joint_length_m":1}'),
    ('Е3-19_table2', 'Е3-19_t2_r1', 0, 1, '{"jointing_timing":"simultaneous_with_masonry"}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_19_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = r.table_key;

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    c.id,
    v.value_type,
    v.value_text,
    v.value_numeric
FROM tmp_e3_19_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-19_t1_r1', 'surface_type', 'cell', 'Кирпичная кладка', NULL::numeric),
        ('Е3-19_t1_r1', 'norm_time', 'cell', '0,55', 0.55::numeric),
        ('Е3-19_t1_r1', 'price_rub', 'cell', '0-43,5', 0.435::numeric),
        ('Е3-19_t1_r2', 'surface_type', 'cell', 'Прочие виды кладок при суммарной длине швов на 1 м2 поверхности до 3 м', NULL::numeric),
        ('Е3-19_t1_r2', 'norm_time', 'cell', '0,23', 0.23::numeric),
        ('Е3-19_t1_r2', 'price_rub', 'cell', '0-18,2', 0.182::numeric),
        ('Е3-19_t1_r3', 'surface_type', 'cell', 'Добавлять за каждый следующий 1 м швов на 1 м2 поверхности', NULL::numeric),
        ('Е3-19_t1_r3', 'norm_time', 'cell', '0,05', 0.05::numeric),
        ('Е3-19_t1_r3', 'price_rub', 'cell', '0-04', 0.04::numeric),
        ('Е3-19_t2_r1', 'brick_250x120x65', 'n_vr', '0,25', 0.25::numeric),
        ('Е3-19_t2_r1', 'brick_250x120x65', 'rate', '0-19,8', 0.198::numeric),
        ('Е3-19_t2_r1', 'brick_250x120x88', 'n_vr', '0,21', 0.21::numeric),
        ('Е3-19_t2_r1', 'brick_250x120x88', 'rate', '0-16,6', 0.166::numeric),
        ('Е3-19_t2_r1', 'hollow_ceramic_250x120x138', 'n_vr', '0,16', 0.16::numeric),
        ('Е3-19_t2_r1', 'hollow_ceramic_250x120x138', 'rate', '0-12,6', 0.126::numeric),
        ('Е3-19_t2_r1', 'concrete_390x190x188', 'n_vr', '0,1', 0.10::numeric),
        ('Е3-19_t2_r1', 'concrete_390x190x188', 'rate', '0-07,9', 0.079::numeric)
) AS v(source_row_id, source_column_key, value_type, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key;

COMMIT;
