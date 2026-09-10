BEGIN;

ALTER TABLE crawl_runs
    ADD COLUMN agent_stage_telemetry JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN rule_activation_status VARCHAR(20),
    ADD COLUMN rule_activation_reason TEXT,
    ADD COLUMN evaluator_decision VARCHAR(10),
    ADD COLUMN evaluator_confidence NUMERIC(5, 4);

ALTER TABLE crawl_runs
    ADD CONSTRAINT ck_crawl_runs_rule_activation_status CHECK (
        rule_activation_status IS NULL
        OR rule_activation_status IN ('approved', 'rejected', 'failed', 'reused')
    ),
    ADD CONSTRAINT ck_crawl_runs_evaluator_decision CHECK (
        evaluator_decision IS NULL OR evaluator_decision IN ('pass', 'fail')
    ),
    ADD CONSTRAINT ck_crawl_runs_evaluator_confidence CHECK (
        evaluator_confidence IS NULL
        OR evaluator_confidence BETWEEN 0 AND 1
    );

COMMIT;
