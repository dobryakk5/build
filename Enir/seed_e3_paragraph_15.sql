BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-15';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-15',
    'Е3-15',
    'Устройство вентиляционных каналов и труб',
    'измерители, указанные в таблице',
    15
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'I'
JOIN enir_chapters ch
  ON ch.collection_id = c.id
 AND ch.source_chapter_id = '1'
WHERE c.code = 'Е3';

INSERT INTO enir_paragraph_application_notes (paragraph_id, sort_order, text)
SELECT
    p.id,
    0,
    'Нормами учтена установка пробок или заглушек (с последующим их удалением) для защиты каналов от засорения в процессе работы.'
FROM enir_paragraphs p
WHERE p.code = 'Е3-15';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT p.id, v.sort_order, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, '{"condition":"При каналах из кирпича","operations":["1. Подача кирпича.","2. Перелопачивание и расстилание раствора.","3. Кладка каналов с перевязкой с основной кладкой."]}'),
        (1, '{"condition":"При вентиляционных трубах из кирпича","operations":["1. Подача кирпича.","2. Перелопачивание, расстилание и разравнивание раствора.","3. Кладка вентиляционных каналов с выделкой отливов.","4. Швабровка каналов.","5. Укладка пробок в кладку.","6. Расшивка швов.","7. Устройство покрытия каналов из железобетонных плит или кирпича на растворе."]}'),
        (2, '{"condition":"При каналах из кирпича по чердачному перекрытию","operations":["1. Подача кирпича.","2. Перелопачивание и расстилание раствора.","3. Кладка стен каналов толщиной в 1/2 кирпича.","4. Устройство перекрытия каналов.","5. Оштукатуривание каналов с наружной стороны."]}'),
        (3, '{"condition":"При каналах из четырехканальных шлакобетонных блоков","operations":["1. Очистка мест установки блоков.","2. Установка блоков на раствор.","3. Проверка правильности установки.","4. Устройство подмостей."]}'),
        (4, '{"condition":"При каналах из асбоцементных труб","operations":["1. Установка в проектное положение.","2. Выверка труб по отвесу.","3. Закрепление концов труб в гнездах с заливкой раствором."]}')
) AS v(sort_order, raw_text)
ON true
WHERE p.code = 'Е3-15';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, v.condition, v.sort_order
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'При каналах из кирпича'),
        (1, 'При вентиляционных трубах из кирпича'),
        (2, 'При каналах из кирпича по чердачному перекрытию'),
        (3, 'При каналах из четырехканальных шлакобетонных блоков'),
        (4, 'При каналах из асбоцементных труб')
) AS v(sort_order, condition)
ON true
WHERE p.code = 'Е3-15';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, 0, '1. Подача кирпича.'),
        (0, 1, '2. Перелопачивание и расстилание раствора.'),
        (0, 2, '3. Кладка каналов с перевязкой с основной кладкой.'),
        (1, 0, '1. Подача кирпича.'),
        (1, 1, '2. Перелопачивание, расстилание и разравнивание раствора.'),
        (1, 2, '3. Кладка вентиляционных каналов с выделкой отливов.'),
        (1, 3, '4. Швабровка каналов.'),
        (1, 4, '5. Укладка пробок в кладку.'),
        (1, 5, '6. Расшивка швов.'),
        (1, 6, '7. Устройство покрытия каналов из железобетонных плит или кирпича на растворе.'),
        (2, 0, '1. Подача кирпича.'),
        (2, 1, '2. Перелопачивание и расстилание раствора.'),
        (2, 2, '3. Кладка стен каналов толщиной в 1/2 кирпича.'),
        (2, 3, '4. Устройство перекрытия каналов.'),
        (2, 4, '5. Оштукатуривание каналов с наружной стороны.'),
        (3, 0, '1. Очистка мест установки блоков.'),
        (3, 1, '2. Установка блоков на раствор.'),
        (3, 2, '3. Проверка правильности установки.'),
        (3, 3, '4. Устройство подмостей.'),
        (4, 0, '1. Установка в проектное положение.'),
        (4, 1, '2. Выверка труб по отвесу.'),
        (4, 2, '3. Закрепление концов труб в гнездах с заливкой раствором.')
) AS v(composition_sort_order, sort_order, text)
  ON v.composition_sort_order = wc.sort_order
WHERE p.code = 'Е3-15';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Каменщик', 4.0::numeric(4,1), 1, 'Каменщик 4 разр. - 1 (прочие виды работ: строки № 1-4, 6-8)'),
        (1, 'Каменщик', 3.0::numeric(4,1), 1, 'Каменщик 3 разр. - 1 (все виды работ)'),
        (2, 'Каменщик', 3.0::numeric(4,1), 1, 'Каменщик 3 разр. - 1 (устройство каналов по чердачному перекрытию из кирпича, строка № 5)')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-15';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Каменщик', 4.0::numeric(4,1), 1),
        ('Каменщик', 3.0::numeric(4,1), 1)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-15';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT
    p.id,
    0,
    NULL,
    'Нормами учтена установка пробок или заглушек (с последующим их удалением) для защиты каналов от засорения в процессе работы.',
    NULL,
    '{"includes_plugs_or_caps":true}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-15';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT
    p.id,
    1,
    'Нормами учтена установка пробок или заглушек (с последующим их удалением) для защиты каналов от засорения в процессе работы.',
    NULL,
    NULL,
    '{"includes_plugs_or_caps":true}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-15';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-15_table2', 0, 'Нормы времени и расценки на измерители, указанные в таблице', 8
FROM enir_paragraphs p
WHERE p.code = 'Е3-15';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('work_type', 0, 'Вид каналов и труб', NULL),
        ('section_desc', 1, 'Сечение каналов в кирпичах', NULL),
        ('layout_desc', 2, 'Расположение каналов / исполнение', NULL),
        ('unit', 3, 'Единица измерения', NULL),
        ('norm_time', 4, 'Н.вр.', NULL),
        ('price_rub', 5, 'Расц.', NULL)
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-15_table2';

CREATE TEMP TABLE tmp_e3_15_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_15_rows
    (source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-15_r1', 0, 1, '{"structure":"ventilation_channel","material":"brick","orientation":"vertical","unit":"100m_channel"}'),
    ('Е3-15_r2', 1, 2, '{"structure":"ventilation_pipe_above_roof","material":"brick","section_bricks":"1/2x1/2","layout":"single_row","unit":"1m_channel"}'),
    ('Е3-15_r3', 2, 3, '{"structure":"ventilation_pipe_above_roof","material":"brick","section_bricks":"1/2x1/2","layout":"double_row","unit":"1m_channel"}'),
    ('Е3-15_r4', 3, 4, '{"structure":"ventilation_pipe_above_roof","material":"brick","section_bricks":"1x1/2","layout":"single_row","unit":"1m_channel"}'),
    ('Е3-15_r5', 4, 5, '{"structure":"horizontal_ventilation_channel","material":"brick","section_bricks":"1x1","location":"attic_floor","unit":"1m_channel"}'),
    ('Е3-15_r6', 5, 6, '{"structure":"vertical_ventilation_channel","material":"slag_concrete_block","block_type":"BV-4","block_size_cm":"92x26x20","reinforcement":false,"unit":"1_block"}'),
    ('Е3-15_r7', 6, 7, '{"structure":"vertical_ventilation_channel","material":"slag_concrete_block","block_type":"BV-4","block_size_cm":"92x26x20","reinforcement":true,"unit":"1_block"}'),
    ('Е3-15_r8', 7, 8, '{"structure":"ventilation_channel","material":"asbestos_cement_pipe","unit":"100m_channel"}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_15_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = 'Е3-15_table2';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    c.id,
    'cell',
    v.value_text,
    v.value_numeric
FROM tmp_e3_15_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-15_r1', 'work_type', 'Вентиляционные каналы из кирпича', NULL::numeric),
        ('Е3-15_r1', 'section_desc', NULL, NULL::numeric),
        ('Е3-15_r1', 'layout_desc', NULL, NULL::numeric),
        ('Е3-15_r1', 'unit', '100 м канала', NULL::numeric),
        ('Е3-15_r1', 'norm_time', '12,5', 12.50::numeric),
        ('Е3-15_r1', 'price_rub', '9-31', 9.31::numeric),
        ('Е3-15_r2', 'work_type', 'Вентиляционные трубы из кирпича сверх крыши', NULL::numeric),
        ('Е3-15_r2', 'section_desc', '1/2×1/2', NULL::numeric),
        ('Е3-15_r2', 'layout_desc', 'Однорядное', NULL::numeric),
        ('Е3-15_r2', 'unit', '1 м канала', NULL::numeric),
        ('Е3-15_r2', 'norm_time', '0,54', 0.54::numeric),
        ('Е3-15_r2', 'price_rub', '0-40,2', 0.402::numeric),
        ('Е3-15_r3', 'work_type', 'Вентиляционные трубы из кирпича сверх крыши', NULL::numeric),
        ('Е3-15_r3', 'section_desc', '1/2×1/2', NULL::numeric),
        ('Е3-15_r3', 'layout_desc', 'Двухрядное', NULL::numeric),
        ('Е3-15_r3', 'unit', '1 м канала', NULL::numeric),
        ('Е3-15_r3', 'norm_time', '0,44', 0.44::numeric),
        ('Е3-15_r3', 'price_rub', '0-32,8', 0.328::numeric),
        ('Е3-15_r4', 'work_type', 'Вентиляционные трубы из кирпича сверх крыши', NULL::numeric),
        ('Е3-15_r4', 'section_desc', '1×1/2', NULL::numeric),
        ('Е3-15_r4', 'layout_desc', 'Однорядное', NULL::numeric),
        ('Е3-15_r4', 'unit', '1 м канала', NULL::numeric),
        ('Е3-15_r4', 'norm_time', '0,83', 0.83::numeric),
        ('Е3-15_r4', 'price_rub', '0-61,8', 0.618::numeric),
        ('Е3-15_r5', 'work_type', 'Горизонтальные вентиляционные каналы по чердачному перекрытию', NULL::numeric),
        ('Е3-15_r5', 'section_desc', '1×1', NULL::numeric),
        ('Е3-15_r5', 'layout_desc', NULL, NULL::numeric),
        ('Е3-15_r5', 'unit', '1 м канала', NULL::numeric),
        ('Е3-15_r5', 'norm_time', '1,2', 1.20::numeric),
        ('Е3-15_r5', 'price_rub', '0-84', 0.84::numeric),
        ('Е3-15_r6', 'work_type', 'Вертикальные вентиляционные каналы из четырехканальных шлакобетонных блоков типа БВ-4 размером 92×26×20 см', NULL::numeric),
        ('Е3-15_r6', 'section_desc', NULL, NULL::numeric),
        ('Е3-15_r6', 'layout_desc', 'Без армирования', NULL::numeric),
        ('Е3-15_r6', 'unit', '1 блок', NULL::numeric),
        ('Е3-15_r6', 'norm_time', '0,27', 0.27::numeric),
        ('Е3-15_r6', 'price_rub', '0-20,1', 0.201::numeric),
        ('Е3-15_r7', 'work_type', 'Вертикальные вентиляционные каналы из четырехканальных шлакобетонных блоков типа БВ-4 размером 92×26×20 см', NULL::numeric),
        ('Е3-15_r7', 'section_desc', NULL, NULL::numeric),
        ('Е3-15_r7', 'layout_desc', 'С армированием', NULL::numeric),
        ('Е3-15_r7', 'unit', '1 блок', NULL::numeric),
        ('Е3-15_r7', 'norm_time', '0,29', 0.29::numeric),
        ('Е3-15_r7', 'price_rub', '0-21,6', 0.216::numeric),
        ('Е3-15_r8', 'work_type', 'Вентиляционные каналы из асбоцементных труб', NULL::numeric),
        ('Е3-15_r8', 'section_desc', NULL, NULL::numeric),
        ('Е3-15_r8', 'layout_desc', NULL, NULL::numeric),
        ('Е3-15_r8', 'unit', '100 м канала', NULL::numeric),
        ('Е3-15_r8', 'norm_time', '7,8', 7.80::numeric),
        ('Е3-15_r8', 'price_rub', '5-81', 5.81::numeric)
) AS v(source_row_id, source_column_key, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key;

COMMIT;
