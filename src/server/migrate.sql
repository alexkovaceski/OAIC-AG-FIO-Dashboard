CREATE SCHEMA IF NOT EXISTS horizon;

CREATE TABLE IF NOT EXISTS horizon.foi_datasets (
    id             BIGSERIAL PRIMARY KEY,
    period_label   TEXT NOT NULL,
    window_mode    TEXT NOT NULL CHECK (window_mode IN ('single_quarter','cumulative','fy')),
    source_files   JSONB NOT NULL,
    normaliser_ver TEXT NOT NULL,
    canonical_hash TEXT NOT NULL,
    fact_count     INT NOT NULL,
    superseded_by  BIGINT REFERENCES horizon.foi_datasets(id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS horizon.foi_facts (
    id            BIGSERIAL PRIMARY KEY,
    dataset_id    BIGINT NOT NULL REFERENCES horizon.foi_datasets(id),
    agency_key    TEXT NOT NULL,
    agency_name   TEXT NOT NULL,
    fy            TEXT NOT NULL,
    quarter       INT,
    measure_group TEXT NOT NULL,
    measure       TEXT NOT NULL,
    bucket        TEXT NOT NULL CHECK (bucket IN ('personal','other','total')),
    value         NUMERIC NOT NULL,
    derived       BOOLEAN NOT NULL DEFAULT FALSE,
    row_hash      TEXT NOT NULL,
    UNIQUE (dataset_id, agency_key, fy, quarter, measure_group, measure, bucket)
);
CREATE INDEX IF NOT EXISTS idx_foi_facts_measure ON horizon.foi_facts (dataset_id, measure, bucket);

-- Stage 1 (portfolio dimension): source-file portfolio per fact. Existing
-- rows default to ''; new ingests write the banner-row portfolio.
ALTER TABLE horizon.foi_facts
  ADD COLUMN IF NOT EXISTS portfolio TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS horizon.lineage_artifacts (
    id            BIGSERIAL PRIMARY KEY,
    artifact_type TEXT NOT NULL,
    artifact_key  TEXT NOT NULL,
    user_id       BIGINT,
    dataset_id    BIGINT NOT NULL REFERENCES horizon.foi_datasets(id),
    request_text  TEXT NOT NULL,
    spec_json     JSONB NOT NULL,
    model         TEXT NOT NULL,
    status        TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS horizon.lineage_ops (
    id           BIGSERIAL PRIMARY KEY,
    artifact_id  BIGINT NOT NULL REFERENCES horizon.lineage_artifacts(id),
    dataset_id   BIGINT NOT NULL REFERENCES horizon.foi_datasets(id),
    kind         TEXT NOT NULL,
    op           TEXT NOT NULL,
    params       JSONB NOT NULL,
    row_count    INT,
    rows_hash    TEXT,
    result_value JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lineage_ops_artifact ON horizon.lineage_ops (artifact_id);

CREATE TABLE IF NOT EXISTS horizon.lineage_tool_calls (
    id          BIGSERIAL PRIMARY KEY,
    artifact_id BIGINT NOT NULL REFERENCES horizon.lineage_artifacts(id),
    seq         INT NOT NULL,
    tool        TEXT NOT NULL,
    op          TEXT NOT NULL,
    input_json  JSONB NOT NULL,
    output_json JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lineage_tool_calls_artifact ON horizon.lineage_tool_calls (artifact_id);

CREATE TABLE IF NOT EXISTS horizon.foi_chat_users (
    id           BIGSERIAL PRIMARY KEY,
    username     TEXT NOT NULL UNIQUE,
    pw_hash      TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Task 1 (role access tier): access tier on foi_chat_users. Existing rows
-- default to 'viewer'; the CHECK confines role to the two known tiers.
ALTER TABLE horizon.foi_chat_users
  ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'viewer'
  CHECK (role IN ('viewer','internal'));

CREATE TABLE IF NOT EXISTS horizon.foi_chat_messages (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES horizon.foi_chat_users(id),
    role       TEXT NOT NULL CHECK (role IN ('user','assistant','report')),
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_foi_chat_messages_user ON horizon.foi_chat_messages (user_id);
