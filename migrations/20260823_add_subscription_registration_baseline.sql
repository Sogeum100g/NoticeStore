ALTER TABLE user_subscriptions
    ADD COLUMN IF NOT EXISTS registration_completed_at TIMESTAMPTZ;

-- 이미 정상 수집 중인 기존 구독은 읽음 기준(last_synced_at)을 보존합니다.
-- pending/failed/blocked 사이트는 실제 최초 수집이 성공할 때 애플리케이션이
-- registration_completed_at과 last_synced_at을 함께 갱신합니다.
UPDATE user_subscriptions us
SET registration_completed_at = COALESCE(us.created_at, us.last_synced_at),
    last_synced_at = CASE
        -- 구버전이 최초 공지까지 신규로 취급하기 위해 넣던 sentinel입니다.
        WHEN us.last_synced_at < '2001-01-01 00:00:00+00'::TIMESTAMPTZ
        THEN CURRENT_TIMESTAMP
        ELSE us.last_synced_at
    END
FROM sites s
WHERE s.site_id = us.site_id
  AND us.registration_completed_at IS NULL
  AND COALESCE(s.crawl_status, 'active') = 'active';

CREATE INDEX IF NOT EXISTS idx_user_subscriptions_registration_ready
    ON user_subscriptions (user_id, site_id, registration_completed_at);
