BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-18';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-18',
    'Е3-18',
    'Укладка в стены стальных элементов и деталей',
    'измерители, указанные в таблице',
    18
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
    '{"condition":"","operations":["1. Расчистка места под укладку.","2. Укладка стальных элементов и деталей в кладку.","3. Покрытие связей и анкеров готовым цементным молоком.","4. Установка штырей и подкладок под концы балок с выверкой устанавливаемых элементов и деталей по уровню."]}'
FROM enir_paragraphs p
WHERE p.code = 'Е3-18';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, NULL, 0
FROM enir_paragraphs p
WHERE p.code = 'Е3-18';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, '1. Расчистка места под укладку.'),
        (1, '2. Укладка стальных элементов и деталей в кладку.'),
        (2, '3. Покрытие связей и анкеров готовым цементным молоком.'),
        (3, '4. Установка штырей и подкладок под концы балок с выверкой устанавливаемых элементов и деталей по уровню.')
    ) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-18';

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
WHERE p.code = 'Е3-18';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT
    p.id,
    'Каменщик',
    4.0::numeric(4,1),
    1
FROM enir_paragraphs p
WHERE p.code = 'Е3-18';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT
    p.id,
    0,
    'ПР-1',
    'На обмотку балок проволокой при расстоянии между спиралями не более 50 мм принимать на 1 м балок Н.вр. 0,11 чел.-ч каменщика 2 разр., Расц. 0-07 (ПР-1).',
    NULL,
    '{"beam_wire_wrap":true,"spiral_spacing_mm":{"lte":50},"per_unit":"1m_beam","add_n_vr":0.11,"add_rate":0.07,"worker_grade":2}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-18';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT
    p.id,
    1,
    'На обмотку балок проволокой при расстоянии между спиралями не более 50 мм принимать на 1 м балок Н.вр. 0,11 чел.-ч каменщика 2 разр., Расц. 0-07 (ПР-1).',
    NULL,
    'ПР-1',
    '{"beam_wire_wrap":true,"spiral_spacing_mm":{"lte":50},"per_unit":"1m_beam","add_n_vr":0.11,"add_rate":0.07,"worker_grade":2}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-18';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-18_table1', 0, 'Нормы времени и расценки на измерители, указанные в таблице', 4
FROM enir_paragraphs p
WHERE p.code = 'Е3-18';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('element_name', 0, 'Вид элементов и деталей', NULL),
        ('unit', 1, 'Единица измерения', NULL),
        ('norm_time', 2, 'Н.вр.', NULL),
        ('price_rub', 3, 'Расц.', NULL)
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-18_table1';

CREATE TEMP TABLE tmp_e3_18_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_18_rows
    (source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-18_r1', 0, 1, '{"element":"rebar_and_mesh_for_masonry_reinforcement_or_anchors_or_ties","unit":"100kg"}'),
    ('Е3-18_r2', 1, 2, '{"element":"beams_over_openings_arches_stairwells","unit":"1_beam"}'),
    ('Е3-18_r3', 2, 3, '{"element":"brackets_placed_during_masonry","wall_material":["brick","rubble"],"unit":"100_brackets"}'),
    ('Е3-18_r4', 3, 4, '{"element":"drainpipe_holders_without_hanging_pipes","unit":"100_holders"}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_18_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = 'Е3-18_table1';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    c.id,
    'cell',
    v.value_text,
    v.value_numeric
FROM tmp_e3_18_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-18_r1', 'element_name', 'Арматура и арматурные сетки для усиления кладки, анкеры и связи для крепления стен с перекрытиями', NULL::numeric),
        ('Е3-18_r1', 'unit', '100 кг', NULL::numeric),
        ('Е3-18_r1', 'norm_time', '1,1', 1.10::numeric),
        ('Е3-18_r1', 'price_rub', '0-86,9', 0.869::numeric),
        ('Е3-18_r2', 'element_name', 'Балки над проемами, арками и лестничными клетками', NULL::numeric),
        ('Е3-18_r2', 'unit', '1 балка', NULL::numeric),
        ('Е3-18_r2', 'norm_time', '0,35', 0.35::numeric),
        ('Е3-18_r2', 'price_rub', '0-27,7', 0.277::numeric),
        ('Е3-18_r3', 'element_name', 'Кронштейны, укладываемые по ходу кладки в кирпичные или бутовые стены', NULL::numeric),
        ('Е3-18_r3', 'unit', '100 кронштейнов', NULL::numeric),
        ('Е3-18_r3', 'norm_time', '24,5', 24.50::numeric),
        ('Е3-18_r3', 'price_rub', '19-36', 19.36::numeric),
        ('Е3-18_r4', 'element_name', 'Установка одновременно с кладкой ухватов (без навески водосточных труб)', NULL::numeric),
        ('Е3-18_r4', 'unit', '100 ухватов', NULL::numeric),
        ('Е3-18_r4', 'norm_time', '3,5', 3.50::numeric),
        ('Е3-18_r4', 'price_rub', '2-77', 2.77::numeric)
) AS v(source_row_id, source_column_key, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key;

COMMIT;
