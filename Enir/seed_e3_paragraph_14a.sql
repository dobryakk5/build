BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-14а';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-14а',
    'Е3-14а',
    'Остекление металлических переплетов стеклопакетами',
    '1 м2 остекления',
    14
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
        (0, 'Нормами предусмотрено остекление металлических переплетов стеклопакетами площадью до 5 м2.'),
        (1, 'Стеклопакеты крепятся к металлическим переплетам штампиками на болтах и пластмассовых (металлических) защелках или при помощи резиновых профилей.')
) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-14а';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT
    p.id,
    0,
    '{"condition":"","operations":["1. Распаковка ящиков.","2. Очистка и протирка поверхностей стеклопакетов от пыли и грязи.","3. Снятие штапиков.","4. Очистка фальцев.","5. Установка резиновых прокладок.","6. Нанесение герметика на фальцы.","7. Нарезка и приклеивание резинового профиля (при установке стеклопакетов на резиновый профиль).","8. Установка стеклопакетов.","9. Установка и крепление штапиков.","10. Перестановка подмостей.","11. Перемещение материалов на расстояние до 30 м."]}'
FROM enir_paragraphs p
WHERE p.code = 'Е3-14а';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, NULL, 0
FROM enir_paragraphs p
WHERE p.code = 'Е3-14а';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, '1. Распаковка ящиков.'),
        (1, '2. Очистка и протирка поверхностей стеклопакетов от пыли и грязи.'),
        (2, '3. Снятие штапиков.'),
        (3, '4. Очистка фальцев.'),
        (4, '5. Установка резиновых прокладок.'),
        (5, '6. Нанесение герметика на фальцы.'),
        (6, '7. Нарезка и приклеивание резинового профиля (при установке стеклопакетов на резиновый профиль).'),
        (7, '8. Установка стеклопакетов.'),
        (8, '9. Установка и крепление штапиков.'),
        (9, '10. Перестановка подмостей.'),
        (10, '11. Перемещение материалов на расстояние до 30 м.')
    ) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-14а';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Стекольщик', 4.0::numeric(4,1), 1, 'Стекольщик 4 разр. - 1'),
        (1, 'Стекольщик', 2.0::numeric(4,1), 1, 'Стекольщик 2 разр. - 1'),
        (2, 'Стекольщик', 4.0::numeric(4,1), 2, 'Стекольщик 4 разр. - 2'),
        (3, 'Стекольщик', 2.0::numeric(4,1), 2, 'Стекольщик 2 разр. - 2')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-14а';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Стекольщик', 4.0::numeric(4,1), 1),
        ('Стекольщик', 2.0::numeric(4,1), 1),
        ('Стекольщик', 4.0::numeric(4,1), 2),
        ('Стекольщик', 2.0::numeric(4,1), 2)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-14а';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-14а_table1', 0, 'Нормы времени и расценки на 1 м2 остекления', 8
FROM enir_paragraphs p
WHERE p.code = 'Е3-14а';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('crew', 0, 'Состав звена стекольщиков', NULL),
        ('area_upto_m2', 1, 'Площадь стеклопакетов, м2, до', NULL),
        ('norm_time', 2, 'Н.вр.', NULL),
        ('price_rub', 3, 'Расц.', NULL)
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-14а_table1';

CREATE TEMP TABLE tmp_e3_14a_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_14a_rows
    (source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-14а_r1', 0, 1, '{"crew":[{"profession":"Стекольщик","grade":4,"count":1},{"profession":"Стекольщик","grade":2,"count":1}],"glass_unit_area_m2":{"lte":0.5}}'),
    ('Е3-14а_r2', 1, 2, '{"crew":[{"profession":"Стекольщик","grade":4,"count":1},{"profession":"Стекольщик","grade":2,"count":1}],"glass_unit_area_m2":{"lte":1.0}}'),
    ('Е3-14а_r3', 2, 3, '{"crew":[{"profession":"Стекольщик","grade":4,"count":1},{"profession":"Стекольщик","grade":2,"count":1}],"glass_unit_area_m2":{"lte":1.5}}'),
    ('Е3-14а_r4', 3, 4, '{"crew":[{"profession":"Стекольщик","grade":4,"count":1},{"profession":"Стекольщик","grade":2,"count":2}],"glass_unit_area_m2":{"lte":2.0}}'),
    ('Е3-14а_r5', 4, 5, '{"crew":[{"profession":"Стекольщик","grade":4,"count":1},{"profession":"Стекольщик","grade":2,"count":2}],"glass_unit_area_m2":{"lte":2.5}}'),
    ('Е3-14а_r6', 5, 6, '{"crew":[{"profession":"Стекольщик","grade":4,"count":2},{"profession":"Стекольщик","grade":2,"count":2}],"glass_unit_area_m2":{"lte":3.0}}'),
    ('Е3-14а_r7', 6, 7, '{"crew":[{"profession":"Стекольщик","grade":4,"count":2},{"profession":"Стекольщик","grade":2,"count":2}],"glass_unit_area_m2":{"lte":4.0}}'),
    ('Е3-14а_r8', 7, 8, '{"crew":[{"profession":"Стекольщик","grade":4,"count":2},{"profession":"Стекольщик","grade":2,"count":2}],"glass_unit_area_m2":{"lte":5.0}}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_14a_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = 'Е3-14а_table1';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    c.id,
    'cell',
    v.value_text,
    v.value_numeric
FROM tmp_e3_14a_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-14а_r1', 'crew', '4 разр. - 1; 2 разр. - 1', NULL::numeric),
        ('Е3-14а_r1', 'area_upto_m2', '0,5', 0.50::numeric),
        ('Е3-14а_r1', 'norm_time', '1,9', 1.90::numeric),
        ('Е3-14а_r1', 'price_rub', '1-36', 1.36::numeric),
        ('Е3-14а_r2', 'crew', '4 разр. - 1; 2 разр. - 1', NULL::numeric),
        ('Е3-14а_r2', 'area_upto_m2', '1', 1.00::numeric),
        ('Е3-14а_r2', 'norm_time', '1,4', 1.40::numeric),
        ('Е3-14а_r2', 'price_rub', '1-00', 1.00::numeric),
        ('Е3-14а_r3', 'crew', '4 разр. - 1; 2 разр. - 1', NULL::numeric),
        ('Е3-14а_r3', 'area_upto_m2', '1,5', 1.50::numeric),
        ('Е3-14а_r3', 'norm_time', '1,2', 1.20::numeric),
        ('Е3-14а_r3', 'price_rub', '0-82,8', 0.828::numeric),
        ('Е3-14а_r4', 'crew', '4 разр. - 1; 2 разр. - 2', NULL::numeric),
        ('Е3-14а_r4', 'area_upto_m2', '2', 2.00::numeric),
        ('Е3-14а_r4', 'norm_time', '0,93', 0.93::numeric),
        ('Е3-14а_r4', 'price_rub', '0-64,9', 0.649::numeric),
        ('Е3-14а_r5', 'crew', '4 разр. - 1; 2 разр. - 2', NULL::numeric),
        ('Е3-14а_r5', 'area_upto_m2', '2,5', 2.50::numeric),
        ('Е3-14а_r5', 'norm_time', '0,88', 0.88::numeric),
        ('Е3-14а_r5', 'price_rub', '0-62,9', 0.629::numeric),
        ('Е3-14а_r6', 'crew', '4 разр. - 2; 2 разр. - 2', NULL::numeric),
        ('Е3-14а_r6', 'area_upto_m2', '3', 3.00::numeric),
        ('Е3-14а_r6', 'norm_time', '0,79', 0.79::numeric),
        ('Е3-14а_r6', 'price_rub', '0-56,5', 0.565::numeric),
        ('Е3-14а_r7', 'crew', '4 разр. - 2; 2 разр. - 2', NULL::numeric),
        ('Е3-14а_r7', 'area_upto_m2', '4', 4.00::numeric),
        ('Е3-14а_r7', 'norm_time', '0,72', 0.72::numeric),
        ('Е3-14а_r7', 'price_rub', '0-51,5', 0.515::numeric),
        ('Е3-14а_r8', 'crew', '4 разр. - 2; 2 разр. - 2', NULL::numeric),
        ('Е3-14а_r8', 'area_upto_m2', '5', 5.00::numeric),
        ('Е3-14а_r8', 'norm_time', '0,59', 0.59::numeric),
        ('Е3-14а_r8', 'price_rub', '0-42,2', 0.422::numeric)
) AS v(source_row_id, source_column_key, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key;

COMMIT;
