BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-10';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-10',
    'Е3-10',
    'Кладка сводов и арок из кирпича',
    '1 м3 кладки',
    9
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
    '{"condition":"","operations":["1. Подбор, околка и отеска кирпича.","2. Разметка рядов по опалубке.","3. Кладка сводов и арок.","4. Заливка жидким раствором верхней поверхности сводов и арок или затирка поверхности сводов двоякой кривизны слоем раствора толщиной 5 мм."]}'
FROM enir_paragraphs p
WHERE p.code = 'Е3-10';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, NULL, 0
FROM enir_paragraphs p
WHERE p.code = 'Е3-10';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, '1. Подбор, околка и отеска кирпича.'),
        (1, '2. Разметка рядов по опалубке.'),
        (2, '3. Кладка сводов и арок.'),
        (3, '4. Заливка жидким раствором верхней поверхности сводов и арок или затирка поверхности сводов двоякой кривизны слоем раствора толщиной 5 мм.')
    ) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-10';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Каменщик', 6.0::numeric(4,1), 1, 'Каменщик 6 разр. - 1'),
        (1, 'Каменщик', 3.0::numeric(4,1), 1, 'Каменщик 3 разр. - 1')
    ) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-10';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Каменщик', 6.0::numeric(4,1), 1),
        ('Каменщик', 3.0::numeric(4,1), 1)
    ) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-10';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT
    p.id,
    0,
    'ПР-1',
    'На опускание опалубки на клиньях добавлять на 1 м2 горизонтальной проекции сводов и арок Н.вр. 0,55 чел.-ч, Расц. 0-48,4 (каменщики 6 разр. - 1, 3 разр. - 1) (ПР-1).',
    NULL,
    '{"lower_formwork_on_wedges":true,"per_unit":"1m2_horizontal_projection","add_n_vr":0.55,"add_rate":0.484,"crew":[{"profession":"Каменщик","grade":6,"count":1},{"profession":"Каменщик","grade":3,"count":1}]}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-10';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT
    p.id,
    1,
    'На опускание опалубки на клиньях добавлять на 1 м2 горизонтальной проекции сводов и арок Н.вр. 0,55 чел.-ч, Расц. 0-48,4 (каменщики 6 разр. - 1, 3 разр. - 1) (ПР-1).',
    NULL,
    'ПР-1',
    '{"lower_formwork_on_wedges":true,"per_unit":"1m2_horizontal_projection","add_n_vr":0.55,"add_rate":0.484,"crew":[{"profession":"Каменщик","grade":6,"count":1},{"profession":"Каменщик","grade":3,"count":1}]}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-10';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-10_table1', 0, 'Нормы времени и расценки на 1 м3 кладки', 3
FROM enir_paragraphs p
WHERE p.code = 'Е3-10';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('vault_double_curvature', 0, 'Своды двоякой кривизны в 1/4 кирпича', 'а'),
        ('cylindrical_half_brick', 1, 'Цилиндрические своды и арки в 1/2 кирпича', 'б'),
        ('cylindrical_one_plus', 2, 'Цилиндрические своды и арки в 1 кирпич и более', 'в')
    ) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-10_table1';

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, 'Е3-10_r1', 0, 1, '{"structure":"vault_or_arch"}'::jsonb
FROM enir_norm_tables t
WHERE t.source_table_id = 'Е3-10_table1';

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
        ('vault_double_curvature', 'n_vr', '7,7', 7.70::numeric),
        ('vault_double_curvature', 'rate', '6-78', 6.78::numeric),
        ('cylindrical_half_brick', 'n_vr', '5,9', 5.90::numeric),
        ('cylindrical_half_brick', 'rate', '5-19', 5.19::numeric),
        ('cylindrical_one_plus', 'n_vr', '3,8', 3.80::numeric),
        ('cylindrical_one_plus', 'rate', '3-34', 3.34::numeric)
    ) AS v(source_column_key, value_type, value_text, value_numeric)
ON true
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key
WHERE r.source_row_id = 'Е3-10_r1';

COMMIT;
