from pydantic import BaseModel, Field
from typing import Literal, Optional, List

# --- [인증 관련] ---
class LoginRequest(BaseModel):
    """소셜 로그인 요청 스키마: 계정 정보와 기기 정보를 동시에 받습니다."""
    provider: str
    access_token: str
    fcm_token: Optional[str] = None
    device_id: str                          # 기기 식별자 (필수) [cite: 2026-03-10]
    device_type: Optional[str] = "unknown" # 'android', 'ios' 등 [cite: 2026-03-10]
    referrer_code: Optional[str] = None    # 초대자 코드 (선택)

# --- [유저 관련] ---
class NicknameRequest(BaseModel):
    nickname: str

class NotificationSettingsRequest(BaseModel):
    is_notification_enabled: Optional[bool] = None

class SubscriptionNotificationRequest(BaseModel):
    notification_enabled: bool

class FCMTokenRequest(BaseModel):
    fcm_token: str
    device_id: str      # 필수값으로 설정
    device_type: str    # 'android', 'ios' 등

class FCMDeleteRequest(BaseModel):
    device_id: str

# --- [사이트 및 구독 관련] ---
class SiteRequest(BaseModel):
    url: str
    alias: str

class SiteResponse(BaseModel):
    status: str  # "success" 반환용
    message: str
    site_id: int
    crawl_status: str
    registration_completed: bool

# --- [즐겨찾기 폴더 및 공지 관련] ---
class FolderCreateRequest(BaseModel):
    folder_name: str
    parent_folder_id: Optional[int] = None

class FolderRenameRequest(BaseModel):
    new_folder_name: str

class FavoriteNoticeRequest(BaseModel):
    notice_id: int

class FolderReorderRequest(BaseModel):
    ordered_folder_ids: List[int]

class KeywordRequest(BaseModel):
    keyword: str

# --- [문의하기 관련] ---
class InquiryRequest(BaseModel):
    category: str
    title: str
    content: str
    site_id: Optional[int] = Field(default=None, ge=1)

class ReplyRequest(BaseModel):
    reply_content: str


class CrawlRunReviewRequest(BaseModel):
    label: Literal[
        "correct",
        "incorrect",
        "no_valid_candidate",
        "needs_more_observation",
    ]
    review_notes: Optional[str] = Field(default=None, max_length=2000)
