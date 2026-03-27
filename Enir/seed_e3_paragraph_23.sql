BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-23';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-23',
    'Е3-23',
    'Ручное приготовление растворов',
    '1 м3 раствора',
    23
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'I'
JOIN enir_chapters ch
  ON ch.collection_id = c.id
 AND ch.source_chapter_id = '2'
WHERE c.code = 'Е3';

INSERT INTO enir_paragraph_application_notes (paragraph_id, sort_order, text)
SELECT
    p.id,
    0,
    'Нормами предусмотрено транспортирование цемента, глины и воды на расстояние до 10 м, песка или крошки - до 20 м. Транспортирование материалов на расстояния, превышающие указанные, следует нормировать по сб. Е1 "Внутрипостроечные транспортные работы".'
FROM enir_paragraphs p
WHERE p.code = 'Е3-23';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT
    p.id,
    0,
    'Каменщик',
    2.0::numeric(4,1),
    1,
    'Каменщик 2 разр. - 1'
FROM enir_paragraphs p
WHERE p.code = 'Е3-23';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT
    p.id,
    'Каменщик',
    2.0::numeric(4,1),
    1
FROM enir_paragraphs p
WHERE p.code = 'Е3-23';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT p.id, v.sort_order, v.code, v.text, v.coefficient, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            0,
            'ПР-1',
            'При приготовлении растворов из готовых сухих смесей Н.вр. и Расц. строки № 1 умножать на 0,7 (ПР-1).',
            0.70::numeric(6,4),
            '{"row_nums":[1],"ready_dry_mix":true}'::jsonb
        ),
        (
            1,
            NULL,
            'Нормами предусмотрено транспортирование цемента, глины и воды на расстояние до 10 м, песка или крошки - до 20 м. Транспортирование материалов на расстояния, превышающие указанные, следует нормировать по сб. Е1 "Внутрипостроечные транспортные работы".',
            NULL::numeric(6,4),
            '{"transport_limits":{"cement_m":10,"clay_m":10,"water_m":10,"sand_or_crumb_m":20}}'::jsonb
        )
) AS v(sort_order, code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-23';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT p.id, v.num, v.text, v.coefficient, v.pr_code, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            1,
            'ПР-1',
            'При приготовлении растворов из готовых сухих смесей Н.вр. и Расц. строки № 1 умножать на 0,7 (ПР-1).',
            0.70::numeric(6,4),
            '{"row_nums":[1],"ready_dry_mix":true}'::jsonb
        ),
        (
            2,
            NULL,
            'Нормами предусмотрено транспортирование цемента, глины и воды на расстояние до 10 м, песка или крошки - до 20 м. Транспортирование материалов на расстояния, превышающие указанные, следует нормировать по сб. Е1 "Внутрипостроечные транспортные работы".',
            NULL::numeric(6,4),
            '{"transport_limits":{"cement_m":10,"clay_m":10,"water_m":10,"sand_or_crumb_m":20}}'::jsonb
        )
) AS v(num, pr_code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-23';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-23_table1', 0, 'Нормы времени и расценки на 1 м3 раствора', 9
FROM enir_paragraphs p
WHERE p.code = 'Е3-23';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('work_name', 0, 'Состав работ', NULL),
        ('solution_type', 1, 'Раствор', NULL),
        ('detail', 2, 'Характеристика', NULL),
        ('norm_time', 3, 'Н.вр.', NULL),
        ('price_rub', 4, 'Расц.', NULL)
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-23_table1';

CREATE TEMP TABLE tmp_e3_23_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_23_rows
    (source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-23_r1', 0, 1, '{"solution_type":"cement"}'),
    ('Е3-23_r2', 1, 2, '{"solution_type":"lime","detail":"heavy"}'),
    ('Е3-23_r3', 2, 3, '{"solution_type":"lime","detail":"light"}'),
    ('Е3-23_r4', 3, 4, '{"solution_type":"lime_cement","detail":"heavy"}'),
    ('Е3-23_r5', 4, 5, '{"solution_type":"lime_cement","detail":"light"}'),
    ('Е3-23_r6', 5, 6, '{"solution_type":"lime_cement","detail":"with_mineral_crumb"}'),
    ('Е3-23_r7', 6, 7, '{"solution_type":"lime_cement","detail":"with_decorative_mix"}'),
    ('Е3-23_r8', 7, 8, '{"solution_type":"clay"}'),
    ('Е3-23_r9', 8, 9, '{"solution_type":"lime_clay"}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_23_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = 'Е3-23_table1';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    c.id,
    'cell',
    v.value_text,
    v.value_numeric
FROM tmp_e3_23_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-23_r1','work_name','1. Дозировка составляющих. 2. Перемешивание (гарцовка) песка или крошки с цементом. 3. Приготовление цементного прыска или известкового молока. 4. Затворение составляющих водой или известковым молоком.',NULL::numeric),
        ('Е3-23_r1','solution_type','Цементный',NULL::numeric),
        ('Е3-23_r1','detail',NULL,NULL::numeric),
        ('Е3-23_r1','norm_time','2,1',2.10::numeric),
        ('Е3-23_r1','price_rub','1-34',1.34::numeric),
        ('Е3-23_r2','work_name','1. Дозировка составляющих. 2. Перемешивание (гарцовка) песка или крошки с цементом. 3. Приготовление цементного прыска или известкового молока. 4. Затворение составляющих водой или известковым молоком.',NULL::numeric),
        ('Е3-23_r2','solution_type','Известковый',NULL::numeric),
        ('Е3-23_r2','detail','Тяжелый',NULL::numeric),
        ('Е3-23_r2','norm_time','2,3',2.30::numeric),
        ('Е3-23_r2','price_rub','1-47',1.47::numeric),
        ('Е3-23_r3','work_name','1. Дозировка составляющих. 2. Перемешивание (гарцовка) песка или крошки с цементом. 3. Приготовление цементного прыска или известкового молока. 4. Затворение составляющих водой или известковым молоком.',NULL::numeric),
        ('Е3-23_r3','solution_type','Известковый',NULL::numeric),
        ('Е3-23_r3','detail','Легкий',NULL::numeric),
        ('Е3-23_r3','norm_time','1,9',1.90::numeric),
        ('Е3-23_r3','price_rub','1-22',1.22::numeric),
        ('Е3-23_r4','work_name','1. Дозировка составляющих. 2. Перемешивание (гарцовка) песка или крошки с цементом. 3. Приготовление цементного прыска или известкового молока. 4. Затворение составляющих водой или известковым молоком.',NULL::numeric),
        ('Е3-23_r4','solution_type','Известково-цементный',NULL::numeric),
        ('Е3-23_r4','detail','Тяжелый',NULL::numeric),
        ('Е3-23_r4','norm_time','2,3',2.30::numeric),
        ('Е3-23_r4','price_rub','1-47',1.47::numeric),
        ('Е3-23_r5','work_name','1. Дозировка составляющих. 2. Перемешивание (гарцовка) песка или крошки с цементом. 3. Приготовление цементного прыска или известкового молока. 4. Затворение составляющих водой или известковым молоком.',NULL::numeric),
        ('Е3-23_r5','solution_type','Известково-цементный',NULL::numeric),
        ('Е3-23_r5','detail','Легкий',NULL::numeric),
        ('Е3-23_r5','norm_time','1,7',1.70::numeric),
        ('Е3-23_r5','price_rub','1-09',1.09::numeric),
        ('Е3-23_r6','work_name','1. Дозировка составляющих. 2. Перемешивание (гарцовка) песка или крошки с цементом. 3. Приготовление цементного прыска или известкового молока. 4. Затворение составляющих водой или известковым молоком.',NULL::numeric),
        ('Е3-23_r6','solution_type','Известково-цементный',NULL::numeric),
        ('Е3-23_r6','detail','С минеральной крошкой',NULL::numeric),
        ('Е3-23_r6','norm_time','2,6',2.60::numeric),
        ('Е3-23_r6','price_rub','1-66',1.66::numeric),
        ('Е3-23_r7','work_name','1. Дозировка составляющих. 2. Перемешивание (гарцовка) песка или крошки с цементом. 3. Приготовление цементного прыска или известкового молока. 4. Затворение составляющих водой или известковым молоком.',NULL::numeric),
        ('Е3-23_r7','solution_type','Известково-цементный',NULL::numeric),
        ('Е3-23_r7','detail','С декоративной смесью',NULL::numeric),
        ('Е3-23_r7','norm_time','3,5',3.50::numeric),
        ('Е3-23_r7','price_rub','2-24',2.24::numeric),
        ('Е3-23_r8','work_name','1. Приготовление известкового молока. 2. Приготовление раствора из глины с добавлением песка и поливкой водой или известковым молоком.',NULL::numeric),
        ('Е3-23_r8','solution_type','Глиняный',NULL::numeric),
        ('Е3-23_r8','detail',NULL,NULL::numeric),
        ('Е3-23_r8','norm_time','2,7',2.70::numeric),
        ('Е3-23_r8','price_rub','1-73',1.73::numeric),
        ('Е3-23_r9','work_name','1. Приготовление известкового молока. 2. Приготовление раствора из глины с добавлением песка и поливкой водой или известковым молоком.',NULL::numeric),
        ('Е3-23_r9','solution_type','Известково-глиняный',NULL::numeric),
        ('Е3-23_r9','detail',NULL,NULL::numeric),
        ('Е3-23_r9','norm_time','2,9',2.90::numeric),
        ('Е3-23_r9','price_rub','1-86',1.86::numeric)
) AS v(source_row_id, source_column_key, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key;

COMMIT;
