-- UI 열람 상태를 알림 발송 기준선과 분리합니다.
-- last_synced_at은 최초 수집 직후 알림을 보내지 않기 위한 기준선으로도
-- 사용되므로, 폴더/공지의 NEW 표시는 last_viewed_at을 기준으로 계산합니다.
ALTER TABLE user_subscriptions
    ADD COLUMN IF NOT EXISTS last_viewed_at TIMESTAMPTZ;

-- 기존 사용자의 읽음 상태와 현재 신규 표시를 그대로 이어받습니다.
UPDATE user_subscriptions
SET last_viewed_at = COALESCE(last_synced_at, created_at, CURRENT_TIMESTAMP)
WHERE last_viewed_at IS NULL;

ALTER TABLE user_subscriptions
    ALTER COLUMN last_viewed_at SET DEFAULT CURRENT_TIMESTAMP,
    ALTER COLUMN last_viewed_at SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_user_subscriptions_unread_notices
    ON user_subscriptions (user_id, site_id, last_viewed_at);
