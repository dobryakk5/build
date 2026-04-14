# FER Vector Index Schema

`fer.vector_index` is a separate storage table for embeddings over the FER hierarchy.

Current source tables remain unchanged:
- `fer.collections`
- `fer.sections`
- `fer.subsections`
- `fer.fer_tables`
- `fer.fer_rows`

## Purpose

The table stores search-ready embeddings without adding `embedding` columns into the existing FER tables.

Primary target for the first pilot is `fer_rows.clarification`, but the schema supports indexing any FER level:
- `collection`
- `section`
- `subsection`
- `table`
- `row`

## Table Shape

Schema: `fer`

Table: `vector_index`

Columns:
- `id bigint generated always as identity primary key`
- `entity_kind varchar(32) not null`
- `entity_id bigint not null`
- `parent_entity_kind varchar(32) null`
- `parent_entity_id bigint null`
- `collection_id smallint not null`
- `section_id smallint null`
- `subsection_id smallint null`
- `table_id smallint null`
- `row_id integer null`
- `source_field varchar(32) not null`
- `source_text text not null`
- `search_text text not null`
- `fts_document tsvector null`
- `embedding fer.vector(1536) not null`
- `provider varchar(32) not null`
- `model varchar(128) not null`
- `text_checksum varchar(64) not null`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

## Constraints and Indexes

- Unique: `(entity_kind, entity_id, source_field, model)`
- B-tree: `(entity_kind, entity_id)`
- B-tree: `(collection_id, section_id, subsection_id, table_id, row_id)`
- GIN: `(fts_document)`
- Vector index: `hnsw (embedding fer.vector_cosine_ops)`

Note:
- In the current database `pgvector` is installed into schema `fer`, so SQL uses explicit `fer.vector` and `fer.vector_cosine_ops`.

## Row-Level Pilot Strategy

For pilot row embeddings:
- `entity_kind = 'row'`
- `entity_id = fer.fer_rows.id`
- `parent_entity_kind = 'table'`
- `parent_entity_id = fer.fer_tables.id`
- `source_field = 'clarification'`
- `source_text = fer.fer_rows.clarification`

`search_text` is built from hierarchy plus clarification:

1. `Сборник {num} {name}`
2. `Раздел: ...`
3. `Подраздел: ...`
4. `Таблица: {common_work_name || table_title}`
5. `Уточнение: {clarification}`

This keeps the exact clarification as the target text while preserving FER context for retrieval.

## Hybrid Search

`fts_document` stores a Russian full-text index built from the same enriched retrieval text used for embeddings.

Hybrid matching combines:

1. vector similarity over `embedding`
2. full-text rank over `fts_document`

Default score formula in the matcher:

- `0.65 * vec_score`
- `0.35 * fts_score`
