from pydantic import BaseModel
from typing import Optional, List

# --- [인증 관련] ---
class LoginRequest(BaseModel):
    provider: str
    access_token: str
    fcm_token: Optional[str] = None

# --- [유저 관련] ---
class NicknameRequest(BaseModel):
    nickname: str

class NotificationSettingsRequest(BaseModel):
    is_notification_enabled: Optional[bool] = None
    notification_time: Optional[str] = None
    fcm_token: Optional[str] = None

class FCMTokenRequest(BaseModel):
    fcm_token: str

# --- [사이트 및 구독 관련] ---
class SiteRequest(BaseModel):
    url: str
    alias: str

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

class ReplyRequest(BaseModel):
    reply_content: str