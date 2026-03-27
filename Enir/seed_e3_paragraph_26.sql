BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-26';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    NULL,
    'Е3-26',
    'Е3-26',
    'Кладка дымовых труб',
    '1 м трубы',
    26
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'II'
WHERE c.code = 'Е3';

INSERT INTO enir_paragraph_technical_characteristics (paragraph_id, sort_order, raw_text)
SELECT p.id, v.sort_order, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Швы кладки дымовых труб должны быть заполнены раствором на всю толщину.'),
        (1, 'Для труб, выкладываемых из тугоплавкого или шамотного кирпича, толщина швов допускается не более 3 мм.'),
        (2, 'Для труб на известковом или известково-цементном растворах толщина швов кладки должна быть не более 10 мм.'),
        (3, 'Кладка дымовых отдельно стоящих труб высотой до 20 м выполняется с лесов. Подача материалов для кладки производится на рабочее место каменщиков краном.')
) AS v(sort_order, raw_text)
ON true
WHERE p.code = 'Е3-26';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT p.id, v.sort_order, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            0,
            '{"condition":"А. Печей и очагов","operations":["1. Кладка труб по отвесу и ватерпасу.","2. Устройство горизонтальных разделок.","3. Выделка выдр, отливов и головки.","4. Швабровка каналов (без применения раствора).","5. Оштукатуривание труб с наружной стороны (при кладке с оштукатуриванием)."]}'
        ),
        (
            1,
            '{"condition":"Б. Отдельно стоящих труб прямоугольного сечения","operations":["1. Перелопачивание, расстилание и разравнивание раствора.","2. Кладка трубы с одним каналом.","3. Установка закладных деталей.","4. Расшивка швов."]}'
        )
) AS v(sort_order, raw_text)
ON true
WHERE p.code = 'Е3-26';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, v.condition, v.sort_order
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'А. Печей и очагов'),
        (1, 'Б. Отдельно стоящих труб прямоугольного сечения')
) AS v(sort_order, condition)
ON true
WHERE p.code = 'Е3-26';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, 0, '1. Кладка труб по отвесу и ватерпасу.'),
        (0, 1, '2. Устройство горизонтальных разделок.'),
        (0, 2, '3. Выделка выдр, отливов и головки.'),
        (0, 3, '4. Швабровка каналов (без применения раствора).'),
        (0, 4, '5. Оштукатуривание труб с наружной стороны (при кладке с оштукатуриванием).'),
        (1, 0, '1. Перелопачивание, расстилание и разравнивание раствора.'),
        (1, 1, '2. Кладка трубы с одним каналом.'),
        (1, 2, '3. Установка закладных деталей.'),
        (1, 3, '4. Расшивка швов.')
    ) AS v(composition_sort_order, sort_order, text)
  ON v.composition_sort_order = wc.sort_order
WHERE p.code = 'Е3-26';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Каменщик', 4.0::numeric(4,1), 1, 'Каменщик 4 разр. - 1 (печей и очагов)'),
        (1, 'Каменщик', 3.0::numeric(4,1), 1, 'Каменщик 3 разр. - 1 (печей и очагов)'),
        (2, 'Каменщик', 5.0::numeric(4,1), 1, 'Каменщик 5 разр. - 1 (отдельно стоящих труб)'),
        (3, 'Каменщик', 3.0::numeric(4,1), 1, 'Каменщик 3 разр. - 1 (отдельно стоящих труб)')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-26';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Каменщик', 4.0::numeric(4,1), 1),
        ('Каменщик', 3.0::numeric(4,1), 1),
        ('Каменщик', 5.0::numeric(4,1), 1)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-26';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT p.id, v.sort_order, v.code, v.text, v.coefficient, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'ПР-1', 'При кладке труб без расшивки швов Н.вр. и Расц. умножать на 0,9 (ПР-1).', 0.90::numeric(6,4), '{"table_scope":["Е3-26_table2"],"jointing":false}'::jsonb),
        (1, NULL, 'Кладка футеровки нормами не учтена.', NULL::numeric(6,4), '{"lining_not_included":true}'::jsonb)
) AS v(sort_order, code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-26';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT p.id, v.num, v.text, v.coefficient, v.pr_code, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (1, 'ПР-1', 'При кладке труб без расшивки швов Н.вр. и Расц. умножать на 0,9 (ПР-1).', 0.90::numeric(6,4), '{"table_scope":["Е3-26_table2"],"jointing":false}'::jsonb),
        (2, NULL, 'Кладка футеровки нормами не учтена.', NULL::numeric(6,4), '{"lining_not_included":true}'::jsonb)
) AS v(num, pr_code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-26';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, v.source_table_id, v.sort_order, v.title, v.row_count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Е3-26_table1', 0, 'Нормы времени и расценки на 1 м трубы', 2),
        ('Е3-26_table2', 1, 'Нормы времени и расценки на 1 м3 кладки (за вычетом пустот)', 1)
) AS v(source_table_id, sort_order, title, row_count)
ON true
WHERE p.code = 'Е3-26';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('Е3-26_table1','finish_type',0,'Вид кладки труб',NULL),
        ('Е3-26_table1','half_half_one',1,'1/2×1/2 один канал','а'),
        ('Е3-26_table1','half_half_each_next',2,'1/2×1/2 добавлять на каждый следующий канал','б'),
        ('Е3-26_table1','half_one_one',3,'1/2×1 один канал','в'),
        ('Е3-26_table1','half_one_each_next',4,'1/2×1 добавлять на каждый следующий канал','г'),
        ('Е3-26_table1','one_one_one',5,'1×1 один канал','д'),
        ('Е3-26_table1','one_one_each_next',6,'1×1 добавлять на каждый следующий канал','е'),
        ('Е3-26_table2','thickness_1',0,'Толщина кладки 1 кирпич','а'),
        ('Е3-26_table2','thickness_1_5',1,'Толщина кладки 1 1/2 кирпича','б'),
        ('Е3-26_table2','thickness_2',2,'Толщина кладки 2 кирпича','в')
) AS v(table_key, source_column_key, sort_order, header, label)
  ON v.table_key = t.source_table_id;

CREATE TEMP TABLE tmp_e3_26_rows (
    table_key text NOT NULL,
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_26_rows
    (table_key, source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-26_table1', 'Е3-26_t1_r1', 0, 1, '{"structure":"chimney_pipe_for_stove","finish":"without_plaster"}'),
    ('Е3-26_table1', 'Е3-26_t1_r2', 1, 2, '{"structure":"chimney_pipe_for_stove","finish":"with_plaster"}'),
    ('Е3-26_table2', 'Е3-26_t2_r1', 0, 1, '{"structure":"freestanding_rectangular_chimney"}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_26_rows r
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
FROM tmp_e3_26_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-26_t1_r1','finish_type','cell','Без оштукатуривания',NULL::numeric),
        ('Е3-26_t1_r1','half_half_one','n_vr','1,3',1.30::numeric),
        ('Е3-26_t1_r1','half_half_one','rate','0-96,8',0.968::numeric),
        ('Е3-26_t1_r1','half_half_each_next','n_vr','0,69',0.69::numeric),
        ('Е3-26_t1_r1','half_half_each_next','rate','0-51,4',0.514::numeric),
        ('Е3-26_t1_r1','half_one_one','n_vr','1,7',1.70::numeric),
        ('Е3-26_t1_r1','half_one_one','rate','1-27',1.27::numeric),
        ('Е3-26_t1_r1','half_one_each_next','n_vr','0,9',0.90::numeric),
        ('Е3-26_t1_r1','half_one_each_next','rate','0-67',0.67::numeric),
        ('Е3-26_t1_r1','one_one_one','n_vr','2,4',2.40::numeric),
        ('Е3-26_t1_r1','one_one_one','rate','1-79',1.79::numeric),
        ('Е3-26_t1_r1','one_one_each_next','n_vr','1,18',1.18::numeric),
        ('Е3-26_t1_r1','one_one_each_next','rate','0-87,9',0.879::numeric),
        ('Е3-26_t1_r2','finish_type','cell','С оштукатуриванием',NULL::numeric),
        ('Е3-26_t1_r2','half_half_one','n_vr','2,2',2.20::numeric),
        ('Е3-26_t1_r2','half_half_one','rate','1-64',1.64::numeric),
        ('Е3-26_t1_r2','half_half_each_next','n_vr','1,04',1.04::numeric),
        ('Е3-26_t1_r2','half_half_each_next','rate','0-77,5',0.775::numeric),
        ('Е3-26_t1_r2','half_one_one','n_vr','2,8',2.80::numeric),
        ('Е3-26_t1_r2','half_one_one','rate','2-09',2.09::numeric),
        ('Е3-26_t1_r2','half_one_each_next','n_vr','1,37',1.37::numeric),
        ('Е3-26_t1_r2','half_one_each_next','rate','1-02',1.02::numeric),
        ('Е3-26_t1_r2','one_one_one','n_vr','3,8',3.80::numeric),
        ('Е3-26_t1_r2','one_one_one','rate','2-83',2.83::numeric),
        ('Е3-26_t1_r2','one_one_each_next','n_vr','1,89',1.89::numeric),
        ('Е3-26_t1_r2','one_one_each_next','rate','1-41',1.41::numeric),
        ('Е3-26_t2_r1','thickness_1','n_vr','4,3',4.30::numeric),
        ('Е3-26_t2_r1','thickness_1','rate','3-46',3.46::numeric),
        ('Е3-26_t2_r1','thickness_1_5','n_vr','3,7',3.70::numeric),
        ('Е3-26_t2_r1','thickness_1_5','rate','2-98',2.98::numeric),
        ('Е3-26_t2_r1','thickness_2','n_vr','2,6',2.60::numeric),
        ('Е3-26_t2_r1','thickness_2','rate','2-09',2.09::numeric)
) AS v(source_row_id, source_column_key, value_type, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key;

COMMIT;
