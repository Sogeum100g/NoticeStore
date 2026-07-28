ALTER TABLE sites
    ADD COLUMN submitted_url TEXT,
    ADD COLUMN crawl_status VARCHAR(20),
    ADD COLUMN validation_status VARCHAR(20),
    ADD COLUMN validation_error TEXT,
    ADD COLUMN last_validated_at TIMESTAMPTZ;

ALTER TABLE api
    ADD COLUMN extractor_config JSONB,
    ADD COLUMN schema_hash TEXT,
    ADD COLUMN last_observed_hash TEXT,
    ADD COLUMN last_processed_hash TEXT,
    ADD COLUMN processing_status VARCHAR(20),
    ADD COLUMN retry_count INTEGER,
    ADD COLUMN next_retry_at TIMESTAMPTZ,
    ADD COLUMN last_error TEXT,
    ADD COLUMN extractor_confidence DOUBLE PRECISION;

ALTER TABLE notices
    ADD COLUMN detail_url TEXT,
    ADD COLUMN external_id TEXT,
    ADD COLUMN published_at TIMESTAMPTZ,
    ADD COLUMN content_type VARCHAR(30),
    ADD COLUMN record_hash TEXT;

CREATE TABLE crawl_runs (
    crawl_run_id BIGSERIAL PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES sites(site_id) ON DELETE CASCADE,
    api_id INTEGER REFERENCES api(api_id) ON DELETE SET NULL,

    status VARCHAR(20) NOT NULL,
    selection_mode VARCHAR(30),
    processing_mode VARCHAR(30),

    observed_hash TEXT,
    processed_hash TEXT,
    schema_hash TEXT,

    candidate_count INTEGER,
    extracted_notice_count INTEGER,

    llm_used BOOLEAN NOT NULL DEFAULT FALSE,
    llm_input_tokens INTEGER,
    llm_output_tokens INTEGER,
    llm_cost NUMERIC(12, 6),

    error_code VARCHAR(100),
    error_message TEXT,

    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ
);
