BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-4';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-4',
    'Е3-4',
    'Кладка армированных стен из кирпича в условиях сейсмических районов',
    '1 м3 кладки',
    3
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'I'
JOIN enir_chapters ch
  ON ch.collection_id = c.id
 AND ch.source_chapter_id = '1'
WHERE c.code = 'Е3';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT p.id, 0, '{"condition":"","operations":["1. Натягивание причалки.","2. Подача и раскладка кирпича.","3. Перелопачивание, расстилание и разравнивание раствора.","4. Кладка стен с выкладкой всех усложнений.","5. Укладка арматуры.","6. Расшивка швов кладки (при кладке с расшивкой)."]}'
FROM enir_paragraphs p
WHERE p.code = 'Е3-4';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, NULL, 0
FROM enir_paragraphs p
WHERE p.code = 'Е3-4';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, '1. Натягивание причалки.'),
        (1, '2. Подача и раскладка кирпича.'),
        (2, '3. Перелопачивание, расстилание и разравнивание раствора.'),
        (3, '4. Кладка стен с выкладкой всех усложнений.'),
        (4, '5. Укладка арматуры.'),
        (5, '6. Расшивка швов кладки (при кладке с расшивкой).')
) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-4';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Каменщик', 4.0::numeric(4,1), 1, 'Каменщик 4 разр. - 1 (средней сложности)'),
        (1, 'Каменщик', 3.0::numeric(4,1), 2, 'Каменщик 3 разр. - 2 (простые)'),
        (2, 'Каменщик', 3.0::numeric(4,1), 1, 'Каменщик 3 разр. - 1 (средней сложности)')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-4';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Каменщик', 4.0::numeric(4,1), 1),
        ('Каменщик', 3.0::numeric(4,1), 2),
        ('Каменщик', 3.0::numeric(4,1), 1)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-4';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT
    p.id,
    0,
    NULL,
    'Нормами учтена укладка горизонтальной и вертикальной арматуры в количестве до 10 кг на 1 м3 кладки.',
    NULL,
    NULL,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-4';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT
    p.id,
    1,
    'Нормами учтена укладка горизонтальной и вертикальной арматуры в количестве до 10 кг на 1 м3 кладки.',
    NULL,
    NULL,
    NULL,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-4';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-4_table2', 0, 'Нормы времени и расценки на 1 м3 кладки', 6
FROM enir_paragraphs p
WHERE p.code = 'Е3-4';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('thickness_bricks', 0, 'Толщина наружных стен в кирпичах', NULL),
        ('finish_type', 1, 'Вид кладки', NULL),
        ('simple', 2, 'Простые', 'а'),
        ('medium', 3, 'Средней сложности', 'б')
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-4_table2';

CREATE TEMP TABLE tmp_e3_4_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_4_rows
    (source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-4_r1', 0, 1, '{"structure":"reinforced_wall","region":"seismic","thickness_bricks":1.0,"finish":"under_plaster"}'),
    ('Е3-4_r2', 1, 2, '{"structure":"reinforced_wall","region":"seismic","thickness_bricks":1.0,"finish":"jointing"}'),
    ('Е3-4_r3', 2, 3, '{"structure":"reinforced_wall","region":"seismic","thickness_bricks":1.5,"finish":"under_plaster"}'),
    ('Е3-4_r4', 3, 4, '{"structure":"reinforced_wall","region":"seismic","thickness_bricks":1.5,"finish":"jointing"}'),
    ('Е3-4_r5', 4, 5, '{"structure":"reinforced_wall","region":"seismic","thickness_bricks":2.0,"finish":"under_plaster"}'),
    ('Е3-4_r6', 5, 6, '{"structure":"reinforced_wall","region":"seismic","thickness_bricks":2.0,"finish":"jointing"}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_4_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = 'Е3-4_table2';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    nc.id,
    v.value_type,
    v.value_text,
    v.value_numeric
FROM tmp_e3_4_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-4_r1', 'thickness_bricks', 'cell', '1', NULL::numeric),
        ('Е3-4_r1', 'finish_type', 'cell', 'Под штукатурку', NULL::numeric),
        ('Е3-4_r1', 'simple', 'n_vr', '4,7', 4.70::numeric),
        ('Е3-4_r1', 'simple', 'rate', '3-29', 3.29::numeric),

        ('Е3-4_r2', 'thickness_bricks', 'cell', '1', NULL::numeric),
        ('Е3-4_r2', 'finish_type', 'cell', 'С расшивкой', NULL::numeric),
        ('Е3-4_r2', 'simple', 'n_vr', '5,2', 5.20::numeric),
        ('Е3-4_r2', 'simple', 'rate', '3-64', 3.64::numeric),

        ('Е3-4_r3', 'thickness_bricks', 'cell', '1 1/2', NULL::numeric),
        ('Е3-4_r3', 'finish_type', 'cell', 'Под штукатурку', NULL::numeric),
        ('Е3-4_r3', 'simple', 'n_vr', '3,9', 3.90::numeric),
        ('Е3-4_r3', 'simple', 'rate', '2-73', 2.73::numeric),
        ('Е3-4_r3', 'medium', 'n_vr', '4,4', 4.40::numeric),
        ('Е3-4_r3', 'medium', 'rate', '3-28', 3.28::numeric),

        ('Е3-4_r4', 'thickness_bricks', 'cell', '1 1/2', NULL::numeric),
        ('Е3-4_r4', 'finish_type', 'cell', 'С расшивкой', NULL::numeric),
        ('Е3-4_r4', 'simple', 'n_vr', '4,3', 4.30::numeric),
        ('Е3-4_r4', 'simple', 'rate', '3-01', 3.01::numeric),
        ('Е3-4_r4', 'medium', 'n_vr', '4,8', 4.80::numeric),
        ('Е3-4_r4', 'medium', 'rate', '3-58', 3.58::numeric),

        ('Е3-4_r5', 'thickness_bricks', 'cell', '2', NULL::numeric),
        ('Е3-4_r5', 'finish_type', 'cell', 'Под штукатурку', NULL::numeric),
        ('Е3-4_r5', 'simple', 'n_vr', '3,2', 3.20::numeric),
        ('Е3-4_r5', 'simple', 'rate', '2-24', 2.24::numeric),
        ('Е3-4_r5', 'medium', 'n_vr', '3,7', 3.70::numeric),
        ('Е3-4_r5', 'medium', 'rate', '2-76', 2.76::numeric),

        ('Е3-4_r6', 'thickness_bricks', 'cell', '2', NULL::numeric),
        ('Е3-4_r6', 'finish_type', 'cell', 'С расшивкой', NULL::numeric),
        ('Е3-4_r6', 'simple', 'n_vr', '3,6', 3.60::numeric),
        ('Е3-4_r6', 'simple', 'rate', '2-52', 2.52::numeric),
        ('Е3-4_r6', 'medium', 'n_vr', '4,1', 4.10::numeric),
        ('Е3-4_r6', 'medium', 'rate', '3-05', 3.05::numeric)
) AS v(source_row_id, source_column_key, value_type, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns nc
  ON nc.norm_table_id = t.id
 AND nc.source_column_key = v.source_column_key;

COMMIT;
