BEGIN;

ALTER TABLE crawl_runs
    ADD COLUMN selection_decision VARCHAR(30),
    ADD COLUMN selection_reason TEXT,
    ADD COLUMN selected_candidate_index INTEGER,
    ADD COLUMN candidate_evidence JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE crawl_runs
    ADD CONSTRAINT ck_crawl_runs_selection_decision CHECK (
        selection_decision IS NULL
        OR selection_decision IN (
            'accept_rule',
            'defer_to_llm',
            'reject_or_observe_more',
            'cached_reuse'
        )
    ),
    ADD CONSTRAINT ck_crawl_runs_selected_candidate_index CHECK (
        selected_candidate_index IS NULL
        OR selected_candidate_index >= -1
    );

COMMIT;
