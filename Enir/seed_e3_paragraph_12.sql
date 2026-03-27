BEGIN;

DELETE FROM enir_paragraphs
WHERE code = 'Е3-12';

INSERT INTO enir_paragraphs
    (collection_id, section_id, chapter_id, source_paragraph_id, code, title, unit, sort_order)
SELECT
    c.id,
    s.id,
    ch.id,
    'Е3-12',
    'Е3-12',
    'Устройство перегородок',
    '1 м2 перегородок',
    11
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
        (0, 'При перегородках из кирпича, из пустотелых керамических или бетонных камней.'),
        (1, 'При перегородках из гипсовых, фосфогипсовых, гипсошлаковых, гипсощебеночных и других плит.')
) AS v(sort_order, text)
ON true
WHERE p.code = 'Е3-12';

INSERT INTO enir_source_work_items (paragraph_id, sort_order, raw_text)
SELECT p.id, v.sort_order, v.raw_text
FROM enir_paragraphs p
JOIN (
    VALUES
        (
            0,
            '{"condition":"При перегородках из кирпича, из пустотелых керамических или бетонных камней","operations":["1. Разметка осей перегородки.","2. Натягивание причалки.","3. Подача и раскладка кирпича или камней.","4. Перелопачивание, расстилание и разравнивание раствора.","5. Подбор, околка и отеска кирпича или камней.","6. Кладка перегородок под штукатурку с креплением их к стенам и заделкой мест примыканий."]}'
        ),
        (
            1,
            '{"condition":"При перегородках из гипсовых, фосфогипсовых, гипсошлаковых, гипсощебеночных и других плит","operations":["1. Разметка осей перегородки.","2. Установка направляющих реек.","3. Приготовление гипсового раствора или гипсовой мастики.","4. Установка плит с учетом перевязки вертикальных швов (с перепиливанием и пригонкой плит).","5. Заливка гипсового раствора в пазы плит, расстилание раствора (при установке плит без пазов), нанесение гипсовой мастики на гребни плит (при установке плит с пазогребневой конструкцией стыков).","6. Крепление плит, примыкающих к стенам и потолку с забивкой костылей или установкой металлических уголков с помощью монтажного пистолета.","7. Конопатка и заделка швов в местах примыкания перегородок.","8. Отделка швов."]}'
        )
) AS v(sort_order, raw_text)
ON true
WHERE p.code = 'Е3-12';

INSERT INTO enir_work_compositions (paragraph_id, condition, sort_order)
SELECT p.id, v.condition, v.sort_order
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'При перегородках из кирпича, из пустотелых керамических или бетонных камней'),
        (1, 'При перегородках из гипсовых, фосфогипсовых, гипсошлаковых, гипсощебеночных и других плит')
) AS v(sort_order, condition)
ON true
WHERE p.code = 'Е3-12';

INSERT INTO enir_work_operations (composition_id, text, sort_order)
SELECT wc.id, v.text, v.sort_order
FROM enir_work_compositions wc
JOIN enir_paragraphs p
  ON p.id = wc.paragraph_id
JOIN (
    VALUES
        (0, 0, '1. Разметка осей перегородки.'),
        (0, 1, '2. Натягивание причалки.'),
        (0, 2, '3. Подача и раскладка кирпича или камней.'),
        (0, 3, '4. Перелопачивание, расстилание и разравнивание раствора.'),
        (0, 4, '5. Подбор, околка и отеска кирпича или камней.'),
        (0, 5, '6. Кладка перегородок под штукатурку с креплением их к стенам и заделкой мест примыканий.'),
        (1, 0, '1. Разметка осей перегородки.'),
        (1, 1, '2. Установка направляющих реек.'),
        (1, 2, '3. Приготовление гипсового раствора или гипсовой мастики.'),
        (1, 3, '4. Установка плит с учетом перевязки вертикальных швов (с перепиливанием и пригонкой плит).'),
        (1, 4, '5. Заливка гипсового раствора в пазы плит, расстилание раствора (при установке плит без пазов), нанесение гипсовой мастики на гребни плит (при установке плит с пазогребневой конструкцией стыков).'),
        (1, 5, '6. Крепление плит, примыкающих к стенам и потолку с забивкой костылей или установкой металлических уголков с помощью монтажного пистолета.'),
        (1, 6, '7. Конопатка и заделка швов в местах примыкания перегородок.'),
        (1, 7, '8. Отделка швов.')
) AS v(composition_sort_order, sort_order, text)
  ON v.composition_sort_order = wc.sort_order
WHERE p.code = 'Е3-12';

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
WHERE p.code = 'Е3-12';

INSERT INTO enir_crew_members (paragraph_id, profession, grade, count)
SELECT p.id, v.profession, v.grade, v.count
FROM enir_paragraphs p
JOIN (
    VALUES
        ('Каменщик', 4.0::numeric(4,1), 1),
        ('Каменщик', 2.0::numeric(4,1), 1)
) AS v(profession, grade, count)
ON true
WHERE p.code = 'Е3-12';

INSERT INTO enir_source_notes
    (paragraph_id, sort_order, code, text, coefficient, conditions, formula)
SELECT p.id, v.sort_order, v.code, v.text, v.coefficient, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (0, 'ПР-1', 'При устройстве двухслойных перегородок к Н.вр. и Расц. применять коэффициент 2 (ПР-1).', 2.00::numeric(6,4), '{"layer_count":2}'::jsonb),
        (1, 'ПР-2', 'Нормами, кроме строки № 3, предусмотрены глухие перегородки. При перегородках с проемами Н.вр. и Расц. умножать на 1,2 (ПР-2), площадь перегородок определять за вычетом проемов.', 1.20::numeric(6,4), '{"has_openings":true,"exclude_row_nums":[3]}'::jsonb),
        (2, 'ПР-3', 'При устройстве перегородок между помещениями площадью до 5 м2 Н.вр. и Расц. умножать на 1,25 (ПР-3).', 1.25::numeric(6,4), '{"room_area_m2":{"lte":5}}'::jsonb),
        (3, 'ПР-4', 'При укладке в перегородках перемычек над проемами Н.вр. и Расц. умножать на 1,1 (ПР-4).', 1.10::numeric(6,4), '{"has_lintel_over_opening":true}'::jsonb),
        (4, 'ПР-5', 'На установку готовой арматуры добавлять на 1 м2 перегородки Н.вр. 0,2 чел.-ч, Расц. 0-14,3 (ПР-5).', NULL::numeric(6,4), '{"ready_rebar":true,"per_unit":"1m2_partition","add_n_vr":0.2,"add_rate":0.143}'::jsonb),
        (5, NULL, 'На установку готовой арматуры коэффициенты, приведенные в примечаниях 2, 3, 4, не распространяются.', NULL::numeric(6,4), '{"ready_rebar":true,"ignore_pr_codes":["ПР-2","ПР-3","ПР-4"]}'::jsonb),
        (6, 'ТЧ-2', 'На кладку перегородок в 1/4 кирпича размером 250×120×88 мм коэффициент 0,9 (ТЧ-2) не распространяется.', NULL::numeric(6,4), '{"tc_code":"ТЧ-2","tc_excluded":true,"brick_size":"250x120x88","thickness_bricks":0.25}'::jsonb)
) AS v(sort_order, code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-12';

INSERT INTO enir_notes
    (paragraph_id, num, text, coefficient, pr_code, conditions, formula)
SELECT p.id, v.num, v.text, v.coefficient, v.pr_code, v.conditions, NULL
FROM enir_paragraphs p
JOIN (
    VALUES
        (1, 'ПР-1', 'При устройстве двухслойных перегородок к Н.вр. и Расц. применять коэффициент 2 (ПР-1).', 2.00::numeric(6,4), '{"layer_count":2}'::jsonb),
        (2, 'ПР-2', 'Нормами, кроме строки № 3, предусмотрены глухие перегородки. При перегородках с проемами Н.вр. и Расц. умножать на 1,2 (ПР-2), площадь перегородок определять за вычетом проемов.', 1.20::numeric(6,4), '{"has_openings":true,"exclude_row_nums":[3]}'::jsonb),
        (3, 'ПР-3', 'При устройстве перегородок между помещениями площадью до 5 м2 Н.вр. и Расц. умножать на 1,25 (ПР-3).', 1.25::numeric(6,4), '{"room_area_m2":{"lte":5}}'::jsonb),
        (4, 'ПР-4', 'При укладке в перегородках перемычек над проемами Н.вр. и Расц. умножать на 1,1 (ПР-4).', 1.10::numeric(6,4), '{"has_lintel_over_opening":true}'::jsonb),
        (5, 'ПР-5', 'На установку готовой арматуры добавлять на 1 м2 перегородки Н.вр. 0,2 чел.-ч, Расц. 0-14,3 (ПР-5).', NULL::numeric(6,4), '{"ready_rebar":true,"per_unit":"1m2_partition","add_n_vr":0.2,"add_rate":0.143}'::jsonb),
        (6, NULL, 'На установку готовой арматуры коэффициенты, приведенные в примечаниях 2, 3, 4, не распространяются.', NULL::numeric(6,4), '{"ready_rebar":true,"ignore_pr_codes":["ПР-2","ПР-3","ПР-4"]}'::jsonb),
        (7, 'ТЧ-2', 'На кладку перегородок в 1/4 кирпича размером 250×120×88 мм коэффициент 0,9 (ТЧ-2) не распространяется.', NULL::numeric(6,4), '{"tc_code":"ТЧ-2","tc_excluded":true,"brick_size":"250x120x88","thickness_bricks":0.25}'::jsonb)
) AS v(num, pr_code, text, coefficient, conditions)
ON true
WHERE p.code = 'Е3-12';

INSERT INTO enir_norm_tables
    (paragraph_id, source_table_id, sort_order, title, row_count)
SELECT p.id, 'Е3-12_table1', 0, 'Нормы времени и расценки на 1 м2 перегородок', 6
FROM enir_paragraphs p
WHERE p.code = 'Е3-12';

INSERT INTO enir_norm_columns
    (norm_table_id, source_column_key, sort_order, header, label)
SELECT t.id, v.source_column_key, v.sort_order, v.header, v.label
FROM enir_norm_tables t
JOIN (
    VALUES
        ('material', 0, 'Вид перегородок', NULL),
        ('thickness', 1, 'Толщина', NULL),
        ('subtype', 2, 'Характеристика', NULL),
        ('norm_time', 3, 'Н.вр.', NULL),
        ('price_rub', 4, 'Расц.', NULL)
) AS v(source_column_key, sort_order, header, label)
ON true
WHERE t.source_table_id = 'Е3-12_table1';

CREATE TEMP TABLE tmp_e3_12_rows (
    source_row_id text PRIMARY KEY,
    sort_order integer NOT NULL,
    source_row_num smallint NOT NULL,
    params jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_e3_12_rows
    (source_row_id, sort_order, source_row_num, params)
VALUES
    ('Е3-12_r1', 0, 1, '{"material":"brick","thickness_bricks":0.25,"subtype":"solid"}'),
    ('Е3-12_r2', 1, 2, '{"material":"brick","thickness_bricks":0.5,"subtype":"solid"}'),
    ('Е3-12_r3', 2, 3, '{"material":"brick","thickness_bricks":0.5,"subtype":"lattice"}'),
    ('Е3-12_r4', 3, 4, '{"material":"hollow_ceramic_or_concrete_block","block_sizes":["250x120x138","390x90x188"]}'),
    ('Е3-12_r5', 4, 5, '{"material":"gypsum_or_similar_plates","length_mm":"600-800","height_mm":"300-400","thickness_mm_max":100}'),
    ('Е3-12_r6', 5, 6, '{"material":"phosphogypsum_or_similar_plates","size_mm":"900x300x80","joint_type":"tongue_groove"}');

INSERT INTO enir_norm_rows
    (norm_table_id, source_row_id, sort_order, source_row_num, params)
SELECT t.id, r.source_row_id, r.sort_order, r.source_row_num, r.params
FROM tmp_e3_12_rows r
JOIN enir_norm_tables t
  ON t.source_table_id = 'Е3-12_table1';

INSERT INTO enir_norm_values
    (norm_row_id, norm_column_id, value_type, value_text, value_numeric)
SELECT
    nr.id,
    c.id,
    'cell',
    v.value_text,
    v.value_numeric
FROM tmp_e3_12_rows r
JOIN enir_norm_rows nr
  ON nr.source_row_id = r.source_row_id
JOIN enir_norm_tables t
  ON t.id = nr.norm_table_id
JOIN (
    VALUES
        ('Е3-12_r1', 'material', 'Кирпичные', NULL::numeric),
        ('Е3-12_r1', 'thickness', '1/4 кирпича', NULL::numeric),
        ('Е3-12_r1', 'subtype', 'Глухие', NULL::numeric),
        ('Е3-12_r1', 'norm_time', '0,53', 0.53::numeric),
        ('Е3-12_r1', 'price_rub', '0-37,9', 0.379::numeric),
        ('Е3-12_r2', 'material', 'Кирпичные', NULL::numeric),
        ('Е3-12_r2', 'thickness', '1/2 кирпича', NULL::numeric),
        ('Е3-12_r2', 'subtype', 'Глухие', NULL::numeric),
        ('Е3-12_r2', 'norm_time', '0,66', 0.66::numeric),
        ('Е3-12_r2', 'price_rub', '0-47,2', 0.472::numeric),
        ('Е3-12_r3', 'material', 'Кирпичные', NULL::numeric),
        ('Е3-12_r3', 'thickness', '1/2 кирпича', NULL::numeric),
        ('Е3-12_r3', 'subtype', 'Решетчатые', NULL::numeric),
        ('Е3-12_r3', 'norm_time', '0,51', 0.51::numeric),
        ('Е3-12_r3', 'price_rub', '0-36,5', 0.365::numeric),
        ('Е3-12_r4', 'material', 'Из пустотелых керамических камней 250×120×138 мм и из продольных половинок бетонных камней 390×90×188 мм', NULL::numeric),
        ('Е3-12_r4', 'thickness', NULL, NULL::numeric),
        ('Е3-12_r4', 'subtype', NULL, NULL::numeric),
        ('Е3-12_r4', 'norm_time', '0,47', 0.47::numeric),
        ('Е3-12_r4', 'price_rub', '0-33,6', 0.336::numeric),
        ('Е3-12_r5', 'material', 'Из гипсовых, гипсошлаковых, гипсощебеночных и других плит', NULL::numeric),
        ('Е3-12_r5', 'thickness', 'длина 600-800 мм, высота 300-400 мм, толщина до 100 мм', NULL::numeric),
        ('Е3-12_r5', 'subtype', NULL, NULL::numeric),
        ('Е3-12_r5', 'norm_time', '0,59', 0.59::numeric),
        ('Е3-12_r5', 'price_rub', '0-42,2', 0.422::numeric),
        ('Е3-12_r6', 'material', 'Из фосфогипсовых и других плит', NULL::numeric),
        ('Е3-12_r6', 'thickness', 'размер 900×300×80 мм', NULL::numeric),
        ('Е3-12_r6', 'subtype', 'Пазогребневая конструкция стыков', NULL::numeric),
        ('Е3-12_r6', 'norm_time', '0,77', 0.77::numeric),
        ('Е3-12_r6', 'price_rub', '0-55,1', 0.551::numeric)
) AS v(source_row_id, source_column_key, value_text, value_numeric)
  ON v.source_row_id = r.source_row_id
JOIN enir_norm_columns c
  ON c.norm_table_id = t.id
 AND c.source_column_key = v.source_column_key;

COMMIT;
