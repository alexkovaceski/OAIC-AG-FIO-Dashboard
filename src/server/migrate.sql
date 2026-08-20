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
