BEGIN;

ALTER TABLE crawl_runs
    ADD COLUMN review_label VARCHAR(30),
    ADD COLUMN review_notes TEXT,
    ADD COLUMN reviewed_by INTEGER,
    ADD COLUMN reviewed_at TIMESTAMPTZ;

ALTER TABLE crawl_runs
    ADD CONSTRAINT fk_crawl_runs_reviewer
        FOREIGN KEY (reviewed_by) REFERENCES users(user_id) ON DELETE SET NULL,
    ADD CONSTRAINT ck_crawl_runs_review_label CHECK (
        review_label IS NULL
        OR review_label IN (
            'correct',
            'incorrect',
            'no_valid_candidate',
            'needs_more_observation'
        )
    );

CREATE INDEX idx_crawl_runs_review_queue
    ON crawl_runs (started_at DESC)
    WHERE review_label IS NULL;

COMMIT;
