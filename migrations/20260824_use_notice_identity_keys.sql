-- 제목이 같더라도 외부 ID나 상세 URL이 다르면 서로 다른 공지입니다.
ALTER TABLE notices
    DROP CONSTRAINT IF EXISTS uq_notices_site_title;

-- external_id와 detail_url의 partial unique index는 기존 스키마에 이미 있습니다.
-- 둘 다 제공되지 않는 공지만 record_hash를 최후 식별자로 사용합니다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_notices_site_fallback_hash
    ON notices (site_id, record_hash)
    WHERE external_id IS NULL
      AND detail_url IS NULL
      AND record_hash IS NOT NULL;
