-- ComplianceIQ schema (M0)
-- Runs automatically the FIRST time the Postgres container starts with an empty volume.
-- To re-run after changes:  docker compose down -v && docker compose up --build

CREATE EXTENSION IF NOT EXISTS vector;

-- One row per source document (an RBI circular / master direction PDF)
CREATE TABLE IF NOT EXISTS documents (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_file   TEXT        NOT NULL,
    content_hash  TEXT        NOT NULL UNIQUE,          -- SHA-256 of the file: the same PDF is never ingested twice
    regulator     TEXT        NOT NULL DEFAULT 'RBI',   -- RBI | SEBI
    doc_type      TEXT,                                 -- circular | master_direction | notification
    circular_no   TEXT,                                 -- e.g. "RBI/2023-24/95 DOR.AML.REC.47/14.01.001/2023-24"
    title         TEXT,
    department    TEXT,
    issued_on     DATE,
    status        TEXT        NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'amended', 'superseded')),
    supersedes    TEXT[]      NOT NULL DEFAULT '{}',    -- circular numbers this one replaces (version graph)
    access_level  TEXT        NOT NULL DEFAULT 'public',-- for document-level ACL in M7
    metadata      JSONB       NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS documents_circular_no_idx ON documents (circular_no);
CREATE INDEX IF NOT EXISTS documents_issued_on_idx   ON documents (issued_on);
CREATE INDEX IF NOT EXISTS documents_status_idx      ON documents (status);

-- Parent-child chunks: small "child" chunks are searched, their bigger "parent" is sent to the LLM
CREATE TABLE IF NOT EXISTS chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    parent_id       UUID REFERENCES chunks(id) ON DELETE CASCADE,
    chunk_level     TEXT NOT NULL CHECK (chunk_level IN ('parent', 'child')),
    chunk_index     INT  NOT NULL,
    section_path    TEXT,                     -- e.g. "Chapter VI > Para 38 > (b)" for section-level citations
    page_start      INT,
    page_end        INT,
    context_header  TEXT NOT NULL DEFAULT '', -- "Circular X, dated Y, section Z": added to the chunk before embedding
    content         TEXT NOT NULL,
    token_count     INT,
    content_hash    TEXT NOT NULL,
    embedding       VECTOR(1024),             -- 1024 dims: matches bge-m3 / Titan v2 / Cohere v3 class models
    -- Keyword search column, computed by Postgres. Weights: header (A) > section (B) > body (C)
    tsv             TSVECTOR GENERATED ALWAYS AS (
                        setweight(to_tsvector('english', coalesce(context_header, '')), 'A') ||
                        setweight(to_tsvector('english', coalesce(section_path, '')),   'B') ||
                        setweight(to_tsvector('english', content),                     'C')
                    ) STORED,
    metadata        JSONB       NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_level, chunk_index)
);

-- Vector search: HNSW graph index using cosine distance
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Keyword search: GIN inverted index over the tsvector
CREATE INDEX IF NOT EXISTS chunks_tsv_gin_idx ON chunks USING gin (tsv);

CREATE INDEX IF NOT EXISTS chunks_document_id_idx ON chunks (document_id);
CREATE INDEX IF NOT EXISTS chunks_parent_id_idx   ON chunks (parent_id);
