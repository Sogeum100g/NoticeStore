-- =====================================================================================
-- 프로젝트 초기 데이터베이스 스키마 설정 스크립트 (init.sql)
-- =====================================================================================

-- 도커 환경에서는 환경변수(POSTGRES_DB)를 통해 기본 DB가 생성되지만,
-- 명시적으로 스키마를 구성하기 전 기본 세팅을 점검합니다.

-- 1. users 테이블 (최상위 부모)
CREATE TABLE users (
    user_id SERIAL PRIMARY KEY,
    social_id VARCHAR(255) NOT NULL,
    provider VARCHAR(20) NOT NULL,
    email VARCHAR(255),
    fcm_token TEXT,
    max_sites_limit INT DEFAULT 5,
    max_keywords_limit INT DEFAULT 10,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- ERD 반영 추가 컬럼
    nickname VARCHAR(100),
    is_notification_enabled BOOLEAN DEFAULT TRUE,
    notification_time VARCHAR(50),
    role VARCHAR(20) DEFAULT 'USER',

    CONSTRAINT uq_social_provider UNIQUE (social_id, provider)
);

-- 2. sites 테이블 (최상위 부모)
CREATE TABLE sites (
    site_id SERIAL PRIMARY KEY,
    site_url TEXT NOT NULL UNIQUE,
    site_name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_viewed_at TIMESTAMP WITH TIME ZONE DEFAULT '1970-01-01 00:00:00+00'
);

-- 3. api 테이블 (sites 참조)
-- ERD의 명명 규칙(api_id, method_type)을 따르고 누락된 컬럼을 추가했습니다.
CREATE TABLE api (
    api_id SERIAL PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES sites(site_id) ON DELETE CASCADE,
    api_url TEXT NOT NULL,
    method_type VARCHAR(10) DEFAULT 'GET',
    headers JSONB DEFAULT '{}',
    payload JSONB DEFAULT '{}',
    last_hash TEXT,
    scraped_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. notices 테이블 (sites 참조)
CREATE TABLE notices (
    notice_id SERIAL PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES sites(site_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    content_preview TEXT,
    author TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    published_at TIMESTAMP WITH TIME ZONE,
    scraped_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT notices_unique_identity UNIQUE (site_id, title, published_at)
);

-- 성능 최적화를 위한 인덱스
CREATE INDEX idx_notices_site_id ON notices(site_id);
CREATE INDEX idx_notices_published_at ON notices(published_at DESC);

-- 5. user_subscriptions 테이블 (users, sites 참조)
CREATE TABLE user_subscriptions (
    subscription_id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    site_id INT NOT NULL REFERENCES sites(site_id) ON DELETE CASCADE,
    alias VARCHAR(100),
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_user_site UNIQUE (user_id, site_id)
);

-- 6. user_notice_logs 테이블 (users, notices 참조)
CREATE TABLE user_notice_logs (
    log_id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(user_id) ON DELETE CASCADE,
    notice_id INT REFERENCES notices(notice_id) ON DELETE CASCADE,
    clicked_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. user_hidden_notices 테이블 (users, notices 참조)
CREATE TABLE user_hidden_notices (
    hidden_id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(user_id) ON DELETE CASCADE,
    notice_id INT REFERENCES notices(notice_id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(user_id, notice_id)
);

-- 8. user_keywords 테이블 (users 참조)
CREATE TABLE user_keywords (
    keyword_id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    keyword_text VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_user_keyword UNIQUE (user_id, keyword_text)
);

-- 9. favorite_folders 테이블 (users 참조, 자기 참조)
CREATE TABLE favorite_folders (
    folder_id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    parent_folder_id INT REFERENCES favorite_folders(folder_id) ON DELETE CASCADE,
    folder_name VARCHAR(100) NOT NULL,
    sort_order INT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 10. favorite_notices 테이블 (favorite_folders, notices 참조)
CREATE TABLE favorite_notices (
    favorite_id SERIAL PRIMARY KEY,
    folder_id INT NOT NULL REFERENCES favorite_folders(folder_id) ON DELETE CASCADE,
    notice_id INT NOT NULL REFERENCES notices(notice_id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (folder_id, notice_id)
);

-- 11. folder_keywords 테이블 (favorite_folders 참조)
CREATE TABLE folder_keywords (
    keyword_id SERIAL PRIMARY KEY,
    folder_id INT NOT NULL REFERENCES favorite_folders(folder_id) ON DELETE CASCADE,
    keyword VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (folder_id, keyword)
);

-- 12. inquiries 테이블 (users 참조)
CREATE TABLE inquiries (
    inquiry_id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    category VARCHAR(50) NOT NULL,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'PENDING',
    reply_content TEXT,
    replied_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================================================
-- 초기 데이터 세팅 (Seed Data)
-- =====================================================================================
-- 도커 초기화 시 최초의 관리자 권한을 부여할 계정이 있다면 이 부분에 추가할 수 있습니다.
-- 예시: 가입이 되어있다는 전제 하에 업데이트를 진행합니다.
-- (실제 환경에서는 회원가입 로직 후 처리하거나 초기 INSERT를 작성해야 합니다)
-- UPDATE users SET role = 'ADMIN' WHERE email = 'kmkmkmkh9@gmail.com';