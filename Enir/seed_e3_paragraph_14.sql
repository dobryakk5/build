BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-14';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-14',
    'Е3-14',
    'Устройство перегородок из коробчатого профильного строительного стекла сечением 244×50 мм',
    '1 м2 перегородок',
    13
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
    '{"condition":"","operations":["1. Подноска профильного стекла на расстояние до 20 м.","2. Очистка профильного стекла.","3. Наклейка эластичных прокладок из губчатой резины или пороизола на профильное стекло и на металлические рамы с нарезкой прокладок.","4. Установка профильного стекла с прирезкой (при необходимости) и закреплением его металлическими уголками.","5. Устройство и разборка легких подмостей."]}'
FROM enir_paragraphs p
WHERE p.code = 'Е3-14';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, NULL, 0
FROM enir_paragraphs p
WHERE p.code = 'Е3-14';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, '1. Подноска профильного стекла на расстояние до 20 м.'),
        (1, '2. Очистка профильного стекла.'),
        (2, '3. Наклейка эластичных прокладок из губчатой резины или пороизола на профильное стекло и на металлические рамы с нарезкой прокладок.'),
        (3, '4. Установка профильного стекла с прирезкой (при необходимости) и закреплением его металлическими уголками.'),
        (4, '5. Устройство и разборка легких подмостей.')
    ) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-14';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Каменщик', 4.0::numeric(4,1), 1, 'Каменщик 4 разр. - 1'),
        (1, 'Каменщик', 2.0::numeric(4,1), 1, 'Каменщик 2 разр. - 1')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-14';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Каменщик', 4.0::numeric(4,1), 1),
        ('Каменщик', 2.0::numeric(4,1), 1)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-14';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT
    p.id,
    0,
    NULL,
    'Нормой предусмотрено устройство перегородок высотой до 3,5 м.',
    NULL,
    '{"max_height_m":3.5}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-14';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT
    p.id,
    1,
    'Нормой предусмотрено устройство перегородок высотой до 3,5 м.',
    NULL,
    NULL,
    '{"max_height_m":3.5}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-14';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-14_table1', 0, 'Норма времени и расценка на 1 м2 перегородок', 1
FROM enir_paragraphs p
WHERE p.code = 'Е3-14';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('work_scope', 0, 'Вид работ', NULL),
        ('norm_time', 1, 'Н.вр.', NULL),
        ('price_rub', 2, 'Расц.', NULL)
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-14_table1';

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT
    t.id,
    'Е3-14_r1',
    0,
    1,
    '{"material":"profile_glass","section_mm":"244x50"}'::jsonb
FROM enir_norm_tables t
WHERE t.source_table_id = 'Е3-14_table1';

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
        ('work_scope', 'Устройство перегородок из коробчатого профильного строительного стекла сечением 244×50 мм', NULL::numeric),
        ('norm_time', '0,62', 0.62::numeric),
        ('price_rub', '0-44,3', 0.443::numeric)
) AS v(source_column_key, value_text, value_numeric)
ON true
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key
WHERE r.source_row_id = 'Е3-14_r1';

COMMIT;
