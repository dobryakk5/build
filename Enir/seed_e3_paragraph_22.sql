BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-22';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-22',
    'Е3-22',
    'Механизированное приготовление растворов',
    '1 м3 раствора',
    22
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
    'Приготовление растворов на приобъектных растворосмесительных установках, а также вручную допускается лишь при малой потребности в растворе и технико-экономическом обосновании целесообразности такого производства.'
FROM enir_paragraphs p
WHERE p.code = 'Е3-22';

INSERT INTO enir_source_crew_items
    (paragraph_id, sort_order, profession, grade, count, raw_text)
SELECT p.id, v.sort_order, v.profession, v.grade, v.count, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'Машинист растворосмесителя', 3.0::numeric(4,1), 1, 'Машинист растворосмесителя 3 разр. - 1 (до 325 л)'),
        (1, 'Машинист растворосмесителя', 4.0::numeric(4,1), 1, 'Машинист растворосмесителя 4 разр. - 1 (до 750 л)'),
        (2, 'Подсобный рабочий', 2.0::numeric(4,1), 1, 'Подсобный рабочий 2 разр. - 1 (загрузка ковша вручную)'),
        (3, 'Машинист автоматического дозатора', 3.0::numeric(4,1), 1, 'Машинист автоматического дозатора 3 разр. - 1'),
        (4, 'Транспортерщик', 3.0::numeric(4,1), 1, 'Транспортерщик 3 разр. - 1'),
        (5, 'Транспортерщик', 2.0::numeric(4,1), 1, 'Транспортерщик 2 разр. - 1'),
        (6, 'Подсобный рабочий', 2.0::numeric(4,1), 1, 'Подсобный рабочий 2 разр. - 1 (механизированная загрузка бункера)')
) AS v(sort_order, profession, grade, count, raw_text)
ON true
WHERE p.code = 'Е3-22';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Машинист растворосмесителя', 3.0::numeric(4,1), 1),
        ('Машинист растворосмесителя', 4.0::numeric(4,1), 1),
        ('Подсобный рабочий', 2.0::numeric(4,1), 1),
        ('Машинист автоматического дозатора', 3.0::numeric(4,1), 1),
        ('Транспортерщик', 3.0::numeric(4,1), 1),
        ('Транспортерщик', 2.0::numeric(4,1), 1)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-22';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT
    p.id,
    0,
    'ПР-1',
    'При загрузке ковша растворосмесителя готовыми сухими смесями Н.вр. и Расц. строки 1а умножать на 0,7 (ПР-1).',
    0.70::numeric(6,4),
    '{"row_nums":[1],"solution_types":["cement"],"ready_dry_mix":true}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-22';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT
    p.id,
    1,
    'При загрузке ковша растворосмесителя готовыми сухими смесями Н.вр. и Расц. строки 1а умножать на 0,7 (ПР-1).',
    0.70::numeric(6,4),
    'ПР-1',
    '{"row_nums":[1],"solution_types":["cement"],"ready_dry_mix":true}'::jsonb,
    NULL
FROM enir_paragraphs p
WHERE p.code = 'Е3-22';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-22_table1', 0, 'Нормы времени и расценки на 1 м3 раствора', 6
FROM enir_paragraphs p
WHERE p.code = 'Е3-22';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('work_name', 0, 'Наименование работ', NULL),
        ('cement', 1, 'Цементный', 'а'),
        ('lime_heavy', 2, 'Известковый тяжелый', 'б'),
        ('lime_light', 3, 'Известковый легкий', 'в'),
        ('lc_heavy', 4, 'Известково-цементный тяжелый', 'г'),
        ('lc_light', 5, 'Известково-цементный легкий', 'д'),
        ('lc_mineral', 6, 'Известково-цементный с минеральной крошкой', 'е'),
        ('lc_decor', 7, 'Известково-цементный с декоративной смесью', 'ж')
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-22_table1';

CREATE TEMP TABLE tmp_e3_22_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_22_rows
    (source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-22_r1', 0, 1, '{"work":"manual_loading_of_mixer_bucket"}'),
    ('Е3-22_r2', 1, 2, '{"work":"mechanized_loading_of_mixer_hopper","mixer_capacity_l":750}'),
    ('Е3-22_r3', 2, 3, '{"work":"mixing_mortar","mixer_capacity_l":80}'),
    ('Е3-22_r4', 3, 4, '{"work":"mixing_mortar","mixer_capacity_l":150}'),
    ('Е3-22_r5', 4, 5, '{"work":"mixing_mortar","mixer_capacity_l":325}'),
    ('Е3-22_r6', 5, 6, '{"work":"mixing_mortar","mixer_capacity_l":750}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_22_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = 'Е3-22_table1';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    c.id,
    v.value_type,
    v.value_text,
    v.value_numeric
FROM tmp_e3_22_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-22_r1','work_name','cell','Загрузка ковша растворосмесителя составляющими с дозировкой их и подноской вручную',NULL::numeric),
        ('Е3-22_r1','cement','n_vr','1',1.00::numeric),
        ('Е3-22_r1','cement','rate','0-64',0.64::numeric),
        ('Е3-22_r1','lime_heavy','n_vr','1,4',1.40::numeric),
        ('Е3-22_r1','lime_heavy','rate','0-89,6',0.896::numeric),
        ('Е3-22_r1','lime_light','n_vr','1,1',1.10::numeric),
        ('Е3-22_r1','lime_light','rate','0-70,4',0.704::numeric),
        ('Е3-22_r1','lc_heavy','n_vr','1,1',1.10::numeric),
        ('Е3-22_r1','lc_heavy','rate','0-70,4',0.704::numeric),
        ('Е3-22_r1','lc_light','n_vr','0,71',0.71::numeric),
        ('Е3-22_r1','lc_light','rate','0-45,4',0.454::numeric),
        ('Е3-22_r1','lc_mineral','n_vr','1,3',1.30::numeric),
        ('Е3-22_r1','lc_mineral','rate','0-83,2',0.832::numeric),
        ('Е3-22_r1','lc_decor','n_vr','0,72',0.72::numeric),
        ('Е3-22_r1','lc_decor','rate','0-46,1',0.461::numeric),
        ('Е3-22_r2','work_name','cell','Механизированная загрузка приемного бункера растворосмесителя вместимостью 750 л',NULL::numeric),
        ('Е3-22_r2','cement','n_vr','0,27',0.27::numeric),
        ('Е3-22_r2','cement','rate','0-18,1',0.181::numeric),
        ('Е3-22_r2','lc_heavy','n_vr','0,27',0.27::numeric),
        ('Е3-22_r2','lc_heavy','rate','0-18,1',0.181::numeric),
        ('Е3-22_r3','work_name','cell','Приготовление раствора в растворосмесителе вместимостью 80 л, до',NULL::numeric),
        ('Е3-22_r3','cement','n_vr','0,6',0.60::numeric),
        ('Е3-22_r3','cement','rate','0-42',0.42::numeric),
        ('Е3-22_r3','lime_heavy','n_vr','0,6',0.60::numeric),
        ('Е3-22_r3','lime_heavy','rate','0-42',0.42::numeric),
        ('Е3-22_r3','lime_light','n_vr','0,98',0.98::numeric),
        ('Е3-22_r3','lime_light','rate','0-68,6',0.686::numeric),
        ('Е3-22_r3','lc_heavy','n_vr','0,6',0.60::numeric),
        ('Е3-22_r3','lc_heavy','rate','0-42',0.42::numeric),
        ('Е3-22_r3','lc_light','n_vr','0,98',0.98::numeric),
        ('Е3-22_r3','lc_light','rate','0-68,6',0.686::numeric),
        ('Е3-22_r3','lc_mineral','n_vr','1,3',1.30::numeric),
        ('Е3-22_r3','lc_mineral','rate','0-91',0.91::numeric),
        ('Е3-22_r3','lc_decor','n_vr','1,6',1.60::numeric),
        ('Е3-22_r3','lc_decor','rate','1-12',1.12::numeric),
        ('Е3-22_r4','work_name','cell','Приготовление раствора в растворосмесителе вместимостью 150 л, до',NULL::numeric),
        ('Е3-22_r4','cement','n_vr','0,29',0.29::numeric),
        ('Е3-22_r4','cement','rate','0-20,3',0.203::numeric),
        ('Е3-22_r4','lime_heavy','n_vr','0,29',0.29::numeric),
        ('Е3-22_r4','lime_heavy','rate','0-20,3',0.203::numeric),
        ('Е3-22_r4','lime_light','n_vr','0,49',0.49::numeric),
        ('Е3-22_r4','lime_light','rate','0-34,3',0.343::numeric),
        ('Е3-22_r4','lc_heavy','n_vr','0,29',0.29::numeric),
        ('Е3-22_r4','lc_heavy','rate','0-20,3',0.203::numeric),
        ('Е3-22_r4','lc_light','n_vr','0,49',0.49::numeric),
        ('Е3-22_r4','lc_light','rate','0-34,3',0.343::numeric),
        ('Е3-22_r4','lc_mineral','n_vr','0,67',0.67::numeric),
        ('Е3-22_r4','lc_mineral','rate','0-46,9',0.469::numeric),
        ('Е3-22_r4','lc_decor','n_vr','0,79',0.79::numeric),
        ('Е3-22_r4','lc_decor','rate','0-55,3',0.553::numeric),
        ('Е3-22_r5','work_name','cell','Приготовление раствора в растворосмесителе вместимостью 325 л, до',NULL::numeric),
        ('Е3-22_r5','cement','n_vr','0,13',0.13::numeric),
        ('Е3-22_r5','cement','rate','0-09,1',0.091::numeric),
        ('Е3-22_r5','lime_heavy','n_vr','0,13',0.13::numeric),
        ('Е3-22_r5','lime_heavy','rate','0-09,1',0.091::numeric),
        ('Е3-22_r5','lime_light','n_vr','0,2',0.20::numeric),
        ('Е3-22_r5','lime_light','rate','0-14',0.14::numeric),
        ('Е3-22_r5','lc_heavy','n_vr','0,13',0.13::numeric),
        ('Е3-22_r5','lc_heavy','rate','0-09,1',0.091::numeric),
        ('Е3-22_r5','lc_light','n_vr','0,2',0.20::numeric),
        ('Е3-22_r5','lc_light','rate','0-14',0.14::numeric),
        ('Е3-22_r5','lc_mineral','n_vr','0,26',0.26::numeric),
        ('Е3-22_r5','lc_mineral','rate','0-18,2',0.182::numeric),
        ('Е3-22_r5','lc_decor','n_vr','0,34',0.34::numeric),
        ('Е3-22_r5','lc_decor','rate','0-23,8',0.238::numeric),
        ('Е3-22_r6','work_name','cell','Приготовление раствора в растворосмесителе вместимостью 750 л, до',NULL::numeric),
        ('Е3-22_r6','cement','n_vr','0,07',0.07::numeric),
        ('Е3-22_r6','cement','rate','0-05,5',0.055::numeric),
        ('Е3-22_r6','lc_heavy','n_vr','0,07',0.07::numeric),
        ('Е3-22_r6','lc_heavy','rate','0-05,5',0.055::numeric)
) AS v(source_row_id, source_column_key, value_type, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key;

COMMIT;
