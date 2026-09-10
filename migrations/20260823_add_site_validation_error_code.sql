ALTER TABLE sites
    ADD COLUMN IF NOT EXISTS validation_error_code VARCHAR(100);

UPDATE sites
SET validation_error_code = CASE
    WHEN crawl_status = 'blocked' THEN 'ROBOTS_TXT_BLOCKED'
    WHEN validation_error LIKE '%대기열%' THEN 'CRAWL_QUEUE_UNAVAILABLE'
    WHEN validation_error LIKE '%수집된 API 후보가 없습니다%'
        THEN 'NO_NOTICE_SOURCE'
    WHEN validation_error LIKE '%API 후보 사전 검증%'
        THEN 'SITE_VALIDATION_FAILED'
    WHEN validation_error LIKE '%검증 API 저장%'
        THEN 'DATABASE_ERROR'
    WHEN crawl_status = 'failed' THEN 'SITE_REGISTRATION_FAILED'
    ELSE NULL
END
WHERE validation_error_code IS NULL
  AND crawl_status IN ('failed', 'blocked');

CREATE INDEX IF NOT EXISTS idx_sites_validation_error_code
    ON sites (validation_error_code)
    WHERE validation_error_code IS NOT NULL;
