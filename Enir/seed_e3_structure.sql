BEGIN;

INSERT INTO enir_collections (code, title, sort_order)
VALUES ('Е3', 'Каменные работы', 3)
ON CONFLICT (code) DO UPDATE
SET title = EXCLUDED.title,
    sort_order = EXCLUDED.sort_order;

INSERT INTO enir_sections (collection_id, source_section_id, title, sort_order, has_tech)
SELECT c.id, v.source_section_id, v.title, v.sort_order, v.has_tech
FROM enir_collections c
JOIN (
    VALUES
        ('I', 'Каменные конструкции зданий', 0, true),
        ('II', 'Бытовые печи', 1, true)
) AS v(source_section_id, title, sort_order, has_tech)
ON true
WHERE c.code = 'Е3'
ON CONFLICT ON CONSTRAINT uq_enir_section_source_id DO UPDATE
SET title = EXCLUDED.title,
    sort_order = EXCLUDED.sort_order,
    has_tech = EXCLUDED.has_tech;

INSERT INTO enir_chapters (collection_id, section_id, source_chapter_id, title, sort_order, has_tech)
SELECT c.id, s.id, v.source_chapter_id, v.title, v.sort_order, v.has_tech
FROM enir_collections c
JOIN enir_sections s
  ON s.collection_id = c.id
 AND s.source_section_id = 'I'
JOIN (
    VALUES
        ('1', 'Каменная кладка', 0, false),
        ('2', 'Приготовление растворов', 1, false)
) AS v(source_chapter_id, title, sort_order, has_tech)
ON true
WHERE c.code = 'Е3'
ON CONFLICT ON CONSTRAINT uq_enir_chapter_source_id DO UPDATE
SET title = EXCLUDED.title,
    sort_order = EXCLUDED.sort_order,
    has_tech = EXCLUDED.has_tech;

DELETE FROM enir_technical_coefficients
WHERE collection_id = (
    SELECT id FROM enir_collections WHERE code = 'Е3'
);

INSERT INTO enir_technical_coefficients
    (collection_id, code, description, multiplier, conditions, sort_order)
SELECT c.id, v.code, v.description, v.multiplier, v.conditions::jsonb, v.sort_order
FROM enir_collections c
JOIN (
    VALUES
        (
            'ТЧ-1',
            'Кладка стен криволинейного очертания любого радиуса',
            1.10::numeric(8,4),
            '{"wall_shape":"curved"}',
            1
        ),
        (
            'ТЧ-2',
            'Кладка из утолщенного кирпича 250x120x88 мм',
            0.90::numeric(8,4),
            '{"brick_size":"250x120x88"}',
            2
        ),
        (
            'ТЧ-3',
            'Кирпич массой менее 3 т на 1000 шт.',
            0.90::numeric(8,4),
            '{"brick_weight_1000_t":{"lt":3.0}}',
            3
        ),
        (
            'ТЧ-4',
            'Употребление в кладку до 30% кирпичного половняка',
            1.05::numeric(8,4),
            '{"half_brick_pct":{"gt":20,"lte":30}}',
            4
        ),
        (
            'ТЧ-5',
            'Употребление в кладку более 30% кирпичного половняка',
            1.10::numeric(8,4),
            '{"half_brick_pct":{"gt":30}}',
            5
        ),
        (
            'ТЧ-6',
            'Применение известкового или известково-цементного раствора',
            0.87::numeric(8,4),
            '{"mortar_type":"lime"}',
            6
        )
) AS v(code, description, multiplier, conditions, sort_order)
ON true
WHERE c.code = 'Е3';

INSERT INTO enir_technical_coefficients
    (collection_id, code, description, multiplier, conditions, formula, sort_order)
SELECT
    c.id,
    'ТЧ-17',
    'Производство работ на высоте более 15 м: +0.5% за каждый метр сверх 15',
    NULL,
    '{"work_height_m":{"gt":15}}'::jsonb,
    '1 + (work_height_m - 15) * 0.005',
    17
FROM enir_collections c
WHERE c.code = 'Е3';

COMMIT;
