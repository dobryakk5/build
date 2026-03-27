BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-20';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-20',
    'Е3-20',
    'Устройство и разборка инвентарных подмостей для кладки',
    '10 м3 кладки',
    20
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'I'
JOIN enir_chapters ch
  ON ch.collection_id = c.id
 AND ch.source_chapter_id = '1'
WHERE c.code = 'Е3';

INSERT INTO enir_paragraph_technical_characteristics (paragraph_id, sort_order, raw_text)
SELECT p.id, v.sort_order, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Нормами предусмотрено устройство и разборка следующих типов подмостей: блочные подмости размером 4,45×2,25 м; пакетные подмости размером 5,3-5,5×2,5 м; ленточные подмости на стойках с выдвижными штоками при готовых рамах (конвертах).'),
        (1, 'Нормами учтено двухъярусное подмащивание.'),
        (2, 'Подъем и опускание блочных и пакетных подмостей предусмотрен с помощью самоходных кранов грузоподъемностью 5 т.')
) AS v(sort_order, raw_text)
ON true
WHERE p.code = 'Е3-20';

INSERT INTO enir_paragraph_application_notes (paragraph_id, sort_order, text)
SELECT
    p.id,
    0,
    'При выполнении работ кранами с большей грузоподъемностью расценки для машиниста крана (крановщика) следует пересчитывать в соответствии с разрядом машиниста крана (крановщика).'
FROM enir_paragraphs p
WHERE p.code = 'Е3-20';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT p.id, v.sort_order, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            0,
            '{"condition":"При устройстве блочных подмостей","operations":["1. Установка блоков на перекрытии каждого этажа при помощи крана.","2. Устройство ограждений.","3. Подъем блоков краном с раздвижкой опорных рам для установки блоков во второе положение в пределах каждого этажа.","4. Опускание блоков краном с последнего этажа вниз.","5. Установка и перестановка инвентарных стремянок."]}'
        ),
        (
            1,
            '{"condition":"При устройстве пакетных подмостей","operations":["1. Установка на перекрытии каждого этажа пакетов первого, а затем второго ярусов при помощи крана.","2. Устройство ограждений.","3. Опускание краном пакетов с последнего этажа вниз.","4. Установка и перестановка инвентарных стремянок."]}'
        ),
        (
            2,
            '{"condition":"При устройстве подмостей на стойках с выдвижными штоками или на готовых рамах (конвертах)","operations":["1. Сборка подмостей на перекрытии с расшивкой и креплением опор.","2. Устройство настила из готовых щитов.","3. Устройство ограждений.","4. Устройство второго яруса подмостей (выдвижение или наращивание) в пределах каждого этажа.","5. Перестановка подмостей с этажа на этаж с разборкой их и сборкой вновь.","6. Разборка подмостей и опускание их с последнего этажа вниз с укладкой элементов в штабель.","7. Установка и перестановка инвентарных стремянок."]}'
        )
) AS v(sort_order, raw_text)
ON true
WHERE p.code = 'Е3-20';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, v.condition, v.sort_order
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'При устройстве блочных подмостей'),
        (1, 'При устройстве пакетных подмостей'),
        (2, 'При устройстве подмостей на стойках с выдвижными штоками или на готовых рамах (конвертах)')
) AS v(sort_order, condition)
ON true
WHERE p.code = 'Е3-20';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, 0, '1. Установка блоков на перекрытии каждого этажа при помощи крана.'),
        (0, 1, '2. Устройство ограждений.'),
        (0, 2, '3. Подъем блоков краном с раздвижкой опорных рам для установки блоков во второе положение в пределах каждого этажа.'),
        (0, 3, '4. Опускание блоков краном с последнего этажа вниз.'),
        (0, 4, '5. Установка и перестановка инвентарных стремянок.'),
        (1, 0, '1. Установка на перекрытии каждого этажа пакетов первого, а затем второго ярусов при помощи крана.'),
        (1, 1, '2. Устройство ограждений.'),
        (1, 2, '3. Опускание краном пакетов с последнего этажа вниз.'),
        (1, 3, '4. Установка и перестановка инвентарных стремянок.'),
        (2, 0, '1. Сборка подмостей на перекрытии с расшивкой и креплением опор.'),
        (2, 1, '2. Устройство настила из готовых щитов.'),
        (2, 2, '3. Устройство ограждений.'),
        (2, 3, '4. Устройство второго яруса подмостей (выдвижение или наращивание) в пределах каждого этажа.'),
        (2, 4, '5. Перестановка подмостей с этажа на этаж с разборкой их и сборкой вновь.'),
        (2, 5, '6. Разборка подмостей и опускание их с последнего этажа вниз с укладкой элементов в штабель.'),
        (2, 6, '7. Установка и перестановка инвентарных стремянок.')
    ) AS v(composition_sort_order, sort_order, text)
  ON v.composition_sort_order = wc.sort_order
WHERE p.code = 'Е3-20';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Машинист крана (крановщик)', 4.0::numeric(4,1), 1, 'Машинист крана (крановщик) 4 разр. - 1 (блочные и пакетные)'),
        (1, 'Плотник', 4.0::numeric(4,1), 1, 'Плотник 4 разр. - 1'),
        (2, 'Плотник', 2.0::numeric(4,1), 2, 'Плотник 2 разр. - 2 (блочные и пакетные)'),
        (3, 'Плотник', 2.0::numeric(4,1), 1, 'Плотник 2 разр. - 1 (на стойках / конвертах)'),
        (4, 'Подсобный рабочий', 1.0::numeric(4,1), 1, 'Подсобный рабочий 1 разр. - 1 (на стойках / конвертах)')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-20';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Машинист крана (крановщик)', 4.0::numeric(4,1), 1),
        ('Плотник', 4.0::numeric(4,1), 1),
        ('Плотник', 2.0::numeric(4,1), 2),
        ('Плотник', 2.0::numeric(4,1), 1),
        ('Подсобный рабочий', 1.0::numeric(4,1), 1)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-20';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT p.id, v.sort_order, v.code, v.text, v.coefficient, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            0,
            NULL,
            'При выполнении работ кранами с большей грузоподъемностью расценки для машиниста крана (крановщика) следует пересчитывать в соответствии с разрядом машиниста крана (крановщика).',
            NULL::numeric(6,4),
            '{"requires_operator_rate_recalc_for_heavier_crane":true}'::jsonb
        ),
        (
            1,
            NULL,
            'Нормами и расценками учтено ленточное подмащивание.',
            NULL::numeric(6,4),
            '{"table_scope":["Е3-20_table2"],"includes_strip_scaffolding":true}'::jsonb
        )
) AS v(sort_order, code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-20';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT p.id, v.num, v.text, v.coefficient, NULL, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            1,
            'При выполнении работ кранами с большей грузоподъемностью расценки для машиниста крана (крановщика) следует пересчитывать в соответствии с разрядом машиниста крана (крановщика).',
            NULL::numeric(6,4),
            '{"requires_operator_rate_recalc_for_heavier_crane":true}'::jsonb
        ),
        (
            2,
            'Нормами и расценками учтено ленточное подмащивание.',
            NULL::numeric(6,4),
            '{"table_scope":["Е3-20_table2"],"includes_strip_scaffolding":true}'::jsonb
        )
) AS v(num, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-20';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, v.source_table_id, v.sort_order, v.title, v.row_count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Е3-20_table2', 0, 'Нормы времени и расценки на 10 м3 кладки', 4),
        ('Е3-20_table3', 1, 'Нормы времени и расценки на 10 м3 кладки', 1)
) AS v(source_table_id, sort_order, title, row_count)
ON true
WHERE p.code = 'Е3-20';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('Е3-20_table2', 'wall_thickness_mm', 0, 'Толщина наружных стен, мм', NULL),
        ('Е3-20_table2', 'operator_norm_time', 1, 'Н.вр. для машиниста', 'а'),
        ('Е3-20_table2', 'operator_price_rub', 2, 'Расц. для машиниста', 'а'),
        ('Е3-20_table2', 'worker_norm_time', 3, 'Н.вр. для рабочих', 'б'),
        ('Е3-20_table2', 'worker_price_rub', 4, 'Расц. для рабочих', 'б'),
        ('Е3-20_table3', 'thickness_380_460', 0, '380-460', 'а'),
        ('Е3-20_table3', 'thickness_510_590', 1, '510-590', 'б'),
        ('Е3-20_table3', 'thickness_640_720', 2, '640-720', 'в'),
        ('Е3-20_table3', 'thickness_770_900', 3, '770-900', 'г')
) AS v(table_key, source_column_key, sort_order, header, label)
  ON v.table_key = t.source_table_id;

CREATE TEMP TABLE tmp_e3_20_rows (
    table_key text NOT NULL,
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_20_rows
    (table_key, source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-20_table2', 'Е3-20_t2_r1', 0, 1, '{"scaffold_type":["block","package"],"wall_thickness_mm":{"min":380,"max":460}}'),
    ('Е3-20_table2', 'Е3-20_t2_r2', 1, 2, '{"scaffold_type":["block","package"],"wall_thickness_mm":{"min":510,"max":590}}'),
    ('Е3-20_table2', 'Е3-20_t2_r3', 2, 3, '{"scaffold_type":["block","package"],"wall_thickness_mm":{"min":640,"max":720}}'),
    ('Е3-20_table2', 'Е3-20_t2_r4', 3, 4, '{"scaffold_type":["block","package"],"wall_thickness_mm":{"min":770,"max":900}}'),
    ('Е3-20_table3', 'Е3-20_t3_r1', 0, 1, '{"scaffold_type":"strip_on_posts_or_ready_frames"}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_20_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = r.table_key;

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    c.id,
    v.value_type,
    v.value_text,
    v.value_numeric
FROM tmp_e3_20_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-20_t2_r1', 'wall_thickness_mm', 'cell', '380-460', NULL::numeric),
        ('Е3-20_t2_r1', 'operator_norm_time', 'cell', '0,48', 0.48::numeric),
        ('Е3-20_t2_r1', 'operator_price_rub', 'cell', '0-37,9', 0.379::numeric),
        ('Е3-20_t2_r1', 'worker_norm_time', 'cell', '1,44', 1.44::numeric),
        ('Е3-20_t2_r1', 'worker_price_rub', 'cell', '0-99,4', 0.994::numeric),
        ('Е3-20_t2_r2', 'wall_thickness_mm', 'cell', '510-590', NULL::numeric),
        ('Е3-20_t2_r2', 'operator_norm_time', 'cell', '0,38', 0.38::numeric),
        ('Е3-20_t2_r2', 'operator_price_rub', 'cell', '0-30', 0.30::numeric),
        ('Е3-20_t2_r2', 'worker_norm_time', 'cell', '1,14', 1.14::numeric),
        ('Е3-20_t2_r2', 'worker_price_rub', 'cell', '0-78,7', 0.787::numeric),
        ('Е3-20_t2_r3', 'wall_thickness_mm', 'cell', '640-720', NULL::numeric),
        ('Е3-20_t2_r3', 'operator_norm_time', 'cell', '0,31', 0.31::numeric),
        ('Е3-20_t2_r3', 'operator_price_rub', 'cell', '0-24,5', 0.245::numeric),
        ('Е3-20_t2_r3', 'worker_norm_time', 'cell', '0,93', 0.93::numeric),
        ('Е3-20_t2_r3', 'worker_price_rub', 'cell', '0-64,2', 0.642::numeric),
        ('Е3-20_t2_r4', 'wall_thickness_mm', 'cell', '770-900', NULL::numeric),
        ('Е3-20_t2_r4', 'operator_norm_time', 'cell', '0,25', 0.25::numeric),
        ('Е3-20_t2_r4', 'operator_price_rub', 'cell', '0-19,8', 0.198::numeric),
        ('Е3-20_t2_r4', 'worker_norm_time', 'cell', '0,75', 0.75::numeric),
        ('Е3-20_t2_r4', 'worker_price_rub', 'cell', '0-51,8', 0.518::numeric),
        ('Е3-20_t3_r1', 'thickness_380_460', 'n_vr', '7,3', 7.30::numeric),
        ('Е3-20_t3_r1', 'thickness_380_460', 'rate', '4-92', 4.92::numeric),
        ('Е3-20_t3_r1', 'thickness_510_590', 'n_vr', '5,5', 5.50::numeric),
        ('Е3-20_t3_r1', 'thickness_510_590', 'rate', '3-70', 3.70::numeric),
        ('Е3-20_t3_r1', 'thickness_640_720', 'n_vr', '4,5', 4.50::numeric),
        ('Е3-20_t3_r1', 'thickness_640_720', 'rate', '3-03', 3.03::numeric),
        ('Е3-20_t3_r1', 'thickness_770_900', 'n_vr', '3,6', 3.60::numeric),
        ('Е3-20_t3_r1', 'thickness_770_900', 'rate', '2-42', 2.42::numeric)
) AS v(source_row_id, source_column_key, value_type, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key;

COMMIT;
