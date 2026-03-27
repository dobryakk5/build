BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-28';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    NULL,
    'Е3-28',
    'Е3-28',
    'Устройство металлических кухонных очагов',
    '1 очаг',
    28
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'II'
WHERE c.code = 'Е3';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT
    p.id,
    0,
    '{"condition":"","operations":["1. Расчистка отверстий дымоходов.","2. Установка металлического кухонного очага с присоединением патрубка, зачистка места присоединения и очистка поверхности.","3. Обмазка духового шкафа раствором.","4. Обделка топки кирпичом.","5. Швабровка дымохода вокруг шкафа.","6. Установка и заделка топочной решетки.","7. Швабровка поверхности кладки."]}'
FROM enir_paragraphs p
WHERE p.code = 'Е3-28';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, NULL, 0
FROM enir_paragraphs p
WHERE p.code = 'Е3-28';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, '1. Расчистка отверстий дымоходов.'),
        (1, '2. Установка металлического кухонного очага с присоединением патрубка, зачистка места присоединения и очистка поверхности.'),
        (2, '3. Обмазка духового шкафа раствором.'),
        (3, '4. Обделка топки кирпичом.'),
        (4, '5. Швабровка дымохода вокруг шкафа.'),
        (5, '6. Установка и заделка топочной решетки.'),
        (6, '7. Швабровка поверхности кладки.')
    ) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-28';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Печник', 4.0::numeric(4,1), 1, 'Печник 4 разр. - 1'),
        (1, 'Печник', 2.0::numeric(4,1), 1, 'Печник 2 разр. - 1')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-28';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Печник', 4.0::numeric(4,1), 1),
        ('Печник', 2.0::numeric(4,1), 1)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-28';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-28_table1', 0, 'Нормы времени и расценки на 1 очаг', 1
FROM enir_paragraphs p
WHERE p.code = 'Е3-28';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('size_upto_1100x550', 0, 'До 1100×550', 'а'),
        ('size_gt_1100x550', 1, 'Более 1100×550', 'б')
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-28_table1';

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT
    t.id,
    'Е3-28_r1',
    0,
    1,
    '{"work":"install_metal_kitchen_hearth"}'::jsonb
FROM enir_norm_tables t
WHERE t.source_table_id = 'Е3-28_table1';

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
        ('size_upto_1100x550','n_vr','2,6',2.60::numeric),
        ('size_upto_1100x550','rate','1-86',1.86::numeric),
        ('size_gt_1100x550','n_vr','3,3',3.30::numeric),
        ('size_gt_1100x550','rate','2-36',2.36::numeric)
) AS v(source_column_key, value_type, value_text, value_numeric)
ON true
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key
WHERE r.source_row_id = 'Е3-28_r1';

COMMIT;
