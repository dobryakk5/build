BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-25';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    NULL,
    'Е3-25',
    'Е3-25',
    'Кладка печей и очагов',
    '1 м3 кладки печей',
    25
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'II'
WHERE c.code = 'Е3';

INSERT INTO enir_paragraph_technical_characteristics (paragraph_id, sort_order, raw_text)
SELECT p.id, v.sort_order, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Качество работ должно соответствовать требованиям действующего СНиП III-17-78 "Каменные конструкции".'),
        (1, 'Швы кладки должны быть заполнены на всю толщину. Внутренние стенки поверхности дымооборотов печи тщательно прошвабровываются.'),
        (2, 'Вертикальная разделка должна быть прочно укреплена проволокой к перегородке или стене отвесно и не должна быть перевязана с кладкой печи или трубы.'),
        (3, 'Горизонтальная разделка должна быть перевязана с основной кладкой печи и трубы.'),
        (4, 'Приборы должны быть укреплены прочно и действовать исправно.')
) AS v(sort_order, raw_text)
ON true
WHERE p.code = 'Е3-25';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT
    p.id,
    0,
    '{"condition":"","operations":["1. Устройство основания.","2. Кладка печей и очагов с установкой печных приборов.","3. Устройство горизонтальных разделок.","4. Швабровка внутренней поверхности (без применения раствора).","5. Затирка и расшивка швов."]}'
FROM enir_paragraphs p
WHERE p.code = 'Е3-25';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, NULL, 0
FROM enir_paragraphs p
WHERE p.code = 'Е3-25';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, '1. Устройство основания.'),
        (1, '2. Кладка печей и очагов с установкой печных приборов.'),
        (2, '3. Устройство горизонтальных разделок.'),
        (3, '4. Швабровка внутренней поверхности (без применения раствора).'),
        (4, '5. Затирка и расшивка швов.')
    ) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-25';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Печник', 4.0::numeric(4,1), 1, 'Печник 4 разр. - 1'),
        (1, 'Печник', 3.0::numeric(4,1), 1, 'Печник 3 разр. - 1')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-25';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Печник', 4.0::numeric(4,1), 1),
        ('Печник', 3.0::numeric(4,1), 1)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-25';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT p.id, v.sort_order, v.code, v.text, v.coefficient, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'ПР-1', 'При кладке печей и очагов с оштукатуриванием поверхности (с разделкой лузг, усенков и падуг) Н.вр. и Расц. умножать на 1,1 (ПР-1).', 1.10::numeric(6,4), '{"plastered_surface":true}'::jsonb),
        (1, 'ПР-2', 'На устройство вертикальных разделок принимать на 1 м разделки Н.вр. 0,23 чел.-ч., Расц. 0-17,1 (ПР-2).', NULL::numeric(6,4), '{"vertical_division":true,"per_unit":"1m_division","add_n_vr":0.23,"add_rate":0.171,"crew":[{"profession":"Печник","grade":4,"count":1},{"profession":"Печник","grade":3,"count":1}]}'::jsonb),
        (2, 'ПР-3', 'На устройство холодной четверти принимать на 1 м2 холодной четверти Н.вр. 1,18 чел.-ч, Расц. 0-87,9 (ПР-3).', NULL::numeric(6,4), '{"cold_quarter":true,"per_unit":"1m2_cold_quarter","add_n_vr":1.18,"add_rate":0.879,"crew":[{"profession":"Печник","grade":4,"count":1},{"profession":"Печник","grade":3,"count":1}]}'::jsonb)
) AS v(sort_order, code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-25';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT p.id, v.num, v.text, v.coefficient, v.pr_code, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (1, 'ПР-1', 'При кладке печей и очагов с оштукатуриванием поверхности (с разделкой лузг, усенков и падуг) Н.вр. и Расц. умножать на 1,1 (ПР-1).', 1.10::numeric(6,4), '{"plastered_surface":true}'::jsonb),
        (2, 'ПР-2', 'На устройство вертикальных разделок принимать на 1 м разделки Н.вр. 0,23 чел.-ч., Расц. 0-17,1 (ПР-2).', NULL::numeric(6,4), '{"vertical_division":true,"per_unit":"1m_division","add_n_vr":0.23,"add_rate":0.171,"crew":[{"profession":"Печник","grade":4,"count":1},{"profession":"Печник","grade":3,"count":1}]}'::jsonb),
        (3, 'ПР-3', 'На устройство холодной четверти принимать на 1 м2 холодной четверти Н.вр. 1,18 чел.-ч, Расц. 0-87,9 (ПР-3).', NULL::numeric(6,4), '{"cold_quarter":true,"per_unit":"1m2_cold_quarter","add_n_vr":1.18,"add_rate":0.879,"crew":[{"profession":"Печник","grade":4,"count":1},{"profession":"Печник","grade":3,"count":1}]}'::jsonb)
) AS v(num, pr_code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-25';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-25_table2', 0, 'Нормы времени и расценки на 1 м3 кладки печей или очагов', 4
FROM enir_paragraphs p
WHERE p.code = 'Е3-25';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('stove_type', 0, 'Вид печей', NULL),
        ('norm_time', 1, 'Н.вр.', NULL),
        ('price_rub', 2, 'Расц.', NULL)
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-25_table2';

CREATE TEMP TABLE tmp_e3_25_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_25_rows
    (source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-25_r1', 0, 1, '{"stove_type":"kitchen_hearth"}'),
    ('Е3-25_r2', 1, 2, '{"stove_type":"room_stove"}'),
    ('Е3-25_r3', 2, 3, '{"stove_type":"russian_stove"}'),
    ('Е3-25_r4', 3, 4, '{"stove_type":"temporary_heating_calorifier"}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_25_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = 'Е3-25_table2';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    c.id,
    'cell',
    v.value_text,
    v.value_numeric
FROM tmp_e3_25_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-25_r1', 'stove_type', 'Кухонные очаги квартирные и общественного назначения', NULL::numeric),
        ('Е3-25_r1', 'norm_time', '8', 8.00::numeric),
        ('Е3-25_r1', 'price_rub', '5-96', 5.96::numeric),
        ('Е3-25_r2', 'stove_type', 'Комнатные печи', NULL::numeric),
        ('Е3-25_r2', 'norm_time', '7,1', 7.10::numeric),
        ('Е3-25_r2', 'price_rub', '5-29', 5.29::numeric),
        ('Е3-25_r3', 'stove_type', 'Русские печи', NULL::numeric),
        ('Е3-25_r3', 'norm_time', '6,6', 6.60::numeric),
        ('Е3-25_r3', 'price_rub', '4-92', 4.92::numeric),
        ('Е3-25_r4', 'stove_type', 'Калориферы для временного отопления', NULL::numeric),
        ('Е3-25_r4', 'norm_time', '7,4', 7.40::numeric),
        ('Е3-25_r4', 'price_rub', '5-51', 5.51::numeric)
) AS v(source_row_id, source_column_key, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key;

COMMIT;
