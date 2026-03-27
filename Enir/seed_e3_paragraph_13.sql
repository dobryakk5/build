BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-13';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-13',
    'Е3-13',
    'Устройство каркасных стен, перегородок из пустотелых стеклянных блоков и заполнение проемов',
    '1 м2 кладки',
    12
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
    '{"condition":"","operations":["1. Подача стеклоблоков.","2. Перелопачивание, расстилание и разравнивание раствора.","3. Укладка арматуры.","4. Кладка стеклоблоков.","5. Расшивка швов кладки с двух сторон.","6. Очистка поверхности кладки."]}'
FROM enir_paragraphs p
WHERE p.code = 'Е3-13';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, NULL, 0
FROM enir_paragraphs p
WHERE p.code = 'Е3-13';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, '1. Подача стеклоблоков.'),
        (1, '2. Перелопачивание, расстилание и разравнивание раствора.'),
        (2, '3. Укладка арматуры.'),
        (3, '4. Кладка стеклоблоков.'),
        (4, '5. Расшивка швов кладки с двух сторон.'),
        (5, '6. Очистка поверхности кладки.')
    ) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-13';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Каменщик', 4.0::numeric(4,1), 1, 'Каменщик 4 разр. - 1 (каркасные стены и перегородки; проемы)'),
        (1, 'Каменщик', 3.0::numeric(4,1), 1, 'Каменщик 3 разр. - 1 (каркасные стены и перегородки)')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-13';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Каменщик', 4.0::numeric(4,1), 1),
        ('Каменщик', 3.0::numeric(4,1), 1)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-13';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-13_table2', 0, 'Нормы времени и расценки на 1 м2 кладки', 2
FROM enir_paragraphs p
WHERE p.code = 'Е3-13';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('block_size', 0, 'Стеклянные блоки размером, мм', NULL),
        ('walls_partitions', 1, 'Каркасные стены и перегородки', 'а'),
        ('openings', 2, 'Проемы', 'б')
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-13_table2';

CREATE TEMP TABLE tmp_e3_13_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_13_rows
    (source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-13_r1', 0, 1, '{"material":"glass_block","block_size_mm":"194x194x98"}'),
    ('Е3-13_r2', 1, 2, '{"material":"glass_block","block_size_mm":"244x244x98"}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_13_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = 'Е3-13_table2';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    c.id,
    v.value_type,
    v.value_text,
    v.value_numeric
FROM tmp_e3_13_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-13_r1', 'block_size', 'cell', '194×194×98', NULL::numeric),
        ('Е3-13_r1', 'walls_partitions', 'n_vr', '0,96', 0.96::numeric),
        ('Е3-13_r1', 'walls_partitions', 'rate', '0-71,5', 0.715::numeric),
        ('Е3-13_r1', 'openings', 'n_vr', '1,1', 1.10::numeric),
        ('Е3-13_r1', 'openings', 'rate', '0-86,9', 0.869::numeric),
        ('Е3-13_r2', 'block_size', 'cell', '244×244×98', NULL::numeric),
        ('Е3-13_r2', 'walls_partitions', 'n_vr', '0,82', 0.82::numeric),
        ('Е3-13_r2', 'walls_partitions', 'rate', '0-61,1', 0.611::numeric)
) AS v(source_row_id, source_column_key, value_type, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key;

COMMIT;
