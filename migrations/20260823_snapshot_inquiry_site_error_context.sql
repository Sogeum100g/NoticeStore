ALTER TABLE inquiries
    ADD COLUMN IF NOT EXISTS site_alias VARCHAR(100),
    ADD COLUMN IF NOT EXISTS site_url TEXT,
    ADD COLUMN IF NOT EXISTS site_error_code VARCHAR(100);

CREATE INDEX IF NOT EXISTS idx_inquiries_site_error_code
    ON inquiries (site_error_code, created_at DESC)
    WHERE site_error_code IS NOT NULL;
