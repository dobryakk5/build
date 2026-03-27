BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-16';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-16',
    'Е3-16',
    'Укладка брусков перемычек',
    '1 проем',
    16
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
    '{"condition":"","operations":["1. Укладка при помощи крана оконных и дверных перемычек на растворе.","2. Выверка и исправление положения.","3. Заполнение стыков и швов раствором."]}'
FROM enir_paragraphs p
WHERE p.code = 'Е3-16';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, NULL, 0
FROM enir_paragraphs p
WHERE p.code = 'Е3-16';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, '1. Укладка при помощи крана оконных и дверных перемычек на растворе.'),
        (1, '2. Выверка и исправление положения.'),
        (2, '3. Заполнение стыков и швов раствором.')
    ) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-16';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Каменщик', 4.0::numeric(4,1), 1, 'Каменщик 4 разр. - 1'),
        (1, 'Каменщик', 3.0::numeric(4,1), 1, 'Каменщик 3 разр. - 1'),
        (2, 'Каменщик', 2.0::numeric(4,1), 1, 'Каменщик 2 разр. - 1'),
        (3, 'Машинист крана (крановщик)', 5.0::numeric(4,1), 1, 'Машинист крана (крановщик) 5 разр. - 1')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-16';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Каменщик', 4.0::numeric(4,1), 1),
        ('Каменщик', 3.0::numeric(4,1), 1),
        ('Каменщик', 2.0::numeric(4,1), 1),
        ('Машинист крана (крановщик)', 5.0::numeric(4,1), 1)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-16';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-16_table1', 0, 'Нормы времени и расценки на 1 проем', 3
FROM enir_paragraphs p
WHERE p.code = 'Е3-16';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('mass_upto_t', 0, 'Общая масса брусковых перемычек для одного проема, т, до', NULL),
        ('mason_norm_time', 1, 'Н.вр. для каменщиков', 'а'),
        ('mason_price_rub', 2, 'Расц. для каменщиков', 'а'),
        ('operator_norm_time', 3, 'Н.вр. для машиниста', 'б'),
        ('operator_price_rub', 4, 'Расц. для машиниста', 'б')
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-16_table1';

CREATE TEMP TABLE tmp_e3_16_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_16_rows
    (source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-16_r1', 0, 1, '{"structure":"lintel_bar","mass_for_opening_t":{"lte":0.5}}'),
    ('Е3-16_r2', 1, 2, '{"structure":"lintel_bar","mass_for_opening_t":{"lte":1.0}}'),
    ('Е3-16_r3', 2, 3, '{"structure":"lintel_bar","mass_for_opening_t":{"lte":1.5}}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_16_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = 'Е3-16_table1';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    c.id,
    'cell',
    v.value_text,
    v.value_numeric
FROM tmp_e3_16_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-16_r1', 'mass_upto_t', '0,5', 0.50::numeric),
        ('Е3-16_r1', 'mason_norm_time', '0,45', 0.45::numeric),
        ('Е3-16_r1', 'mason_price_rub', '0-32', 0.32::numeric),
        ('Е3-16_r1', 'operator_norm_time', '0,15', 0.15::numeric),
        ('Е3-16_r1', 'operator_price_rub', '0-13,7', 0.137::numeric),
        ('Е3-16_r2', 'mass_upto_t', '1', 1.00::numeric),
        ('Е3-16_r2', 'mason_norm_time', '0,66', 0.66::numeric),
        ('Е3-16_r2', 'mason_price_rub', '0-46,9', 0.469::numeric),
        ('Е3-16_r2', 'operator_norm_time', '0,22', 0.22::numeric),
        ('Е3-16_r2', 'operator_price_rub', '0-20', 0.20::numeric),
        ('Е3-16_r3', 'mass_upto_t', '1,5', 1.50::numeric),
        ('Е3-16_r3', 'mason_norm_time', '0,83', 0.83::numeric),
        ('Е3-16_r3', 'mason_price_rub', '0-58,9', 0.589::numeric),
        ('Е3-16_r3', 'operator_norm_time', '0,28', 0.28::numeric),
        ('Е3-16_r3', 'operator_price_rub', '0-25,5', 0.255::numeric)
) AS v(source_row_id, source_column_key, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key;

COMMIT;
