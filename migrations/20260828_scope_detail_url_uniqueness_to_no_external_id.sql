-- external_id가 있는 공지는 그것만으로 식별한다(_find_notice_by_identity와
-- deterministic_extractor._notice_identity의 우선순위와 동일). detail_url이
-- 레코드마다 고유하지 않은 사이트(예: 기관 홈페이지 하나를 여러 공고가
-- 공유)에서, external_id가 서로 다른 정상적인 공지들이 detail_url unique
-- 제약에 걸려 저장에 실패하는 문제를 막기 위해 이 제약을 external_id가
-- 없는 공지끼리만 적용하도록 좁힌다.
DROP INDEX IF EXISTS uq_notices_site_detail_url;

CREATE UNIQUE INDEX IF NOT EXISTS uq_notices_site_detail_url
    ON notices (site_id, detail_url)
    WHERE detail_url IS NOT NULL AND external_id IS NULL;
