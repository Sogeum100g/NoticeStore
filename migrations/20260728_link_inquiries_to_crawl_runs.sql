BEGIN;

ALTER TABLE inquiries
    ADD COLUMN site_id INTEGER,
    ADD COLUMN crawl_run_id BIGINT;

ALTER TABLE inquiries
    ADD CONSTRAINT fk_inquiries_site
        FOREIGN KEY (site_id) REFERENCES sites(site_id) ON DELETE SET NULL,
    ADD CONSTRAINT fk_inquiries_crawl_run
        FOREIGN KEY (crawl_run_id)
        REFERENCES crawl_runs(crawl_run_id) ON DELETE SET NULL;

CREATE INDEX idx_inquiries_site_created_at
    ON inquiries (site_id, created_at DESC)
    WHERE site_id IS NOT NULL;

COMMIT;
