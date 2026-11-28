-- 002: platform tables (M7). Idempotent: safe to run on every start (the API and ingest script both do).

CREATE TABLE IF NOT EXISTS users (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email          TEXT        NOT NULL UNIQUE,
    password_hash  TEXT        NOT NULL,                    -- bcrypt, never the password itself
    role           TEXT        NOT NULL DEFAULT 'analyst' CHECK (role IN ('analyst', 'admin')),
    access_levels  TEXT[]      NOT NULL DEFAULT '{public}', -- which documents.access_level values they may read
    entity_type    TEXT,                                     -- default entity filter, e.g. 'nbfcs'
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per question: the raw material for latency / cost / quality dashboards and capacity planning.
CREATE TABLE IF NOT EXISTS query_log (
    id                 BIGSERIAL PRIMARY KEY,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id            UUID,
    question           TEXT        NOT NULL,
    standalone_question TEXT,
    entity             TEXT,
    mode               TEXT,
    cache              TEXT,              -- miss | exact | semantic
    refused            BOOLEAN     NOT NULL DEFAULT false,
    top_score          REAL,
    provider           TEXT,
    model              TEXT,
    prompt_tokens      INT         NOT NULL DEFAULT 0,
    completion_tokens  INT         NOT NULL DEFAULT 0,
    cost_usd           NUMERIC(12, 6) NOT NULL DEFAULT 0,
    retrieval_ms       INT,
    first_token_ms     INT,
    total_ms           INT,
    citation_ok        BOOLEAN
);
CREATE INDEX IF NOT EXISTS query_log_created_at_idx ON query_log (created_at);
