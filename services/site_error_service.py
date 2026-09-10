from typing import Optional


SITE_ERROR_MESSAGES = {
    "CRAWL_QUEUE_UNAVAILABLE": (
        "사이트 분석을 시작하지 못했습니다. 잠시 후 다시 시도해 주세요."
    ),
    "ROBOTS_TXT_BLOCKED": (
        "사이트 정책으로 공지 수집이 제한되었습니다."
    ),
    "SITE_VALIDATION_FAILED": (
        "사이트의 정보 목록을 확인하지 못했습니다."
    ),
    "SITE_ACCESS_BLOCKED": (
        "사이트 정책으로 접근이 제한되었습니다."
    ),
    "SITE_UNREACHABLE": (
        "사이트 응답을 받지 못했습니다. 잠시 후 다시 확인해 주세요."
    ),
    "DATABASE_ERROR": (
        "사이트 정보를 저장하는 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
    ),
    "SITE_REGISTRATION_FAILED": (
        "사이트 등록 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
    ),
}


# 세부 원인은 내부 상태와 crawl_runs telemetry에 유지하고, 사용자 API에는
# 동일한 최종 결과 코드만 공개합니다. 기존 DB 값도 마이그레이션 없이
# 일관된 계약으로 응답할 수 있도록 경계에서 정규화합니다.
SITE_ERROR_CODE_ALIASES = {
    "NO_NOTICE_SOURCE": "SITE_VALIDATION_FAILED",
    "NOTICE_EXTRACTION_FAILED": "SITE_VALIDATION_FAILED",
}


def get_public_site_error_code(error_code: Optional[str]) -> Optional[str]:
    if not error_code:
        return None
    return SITE_ERROR_CODE_ALIASES.get(error_code, error_code)


def get_site_error_message(error_code: Optional[str]) -> Optional[str]:
    public_error_code = get_public_site_error_code(error_code)
    if not public_error_code:
        return None
    return SITE_ERROR_MESSAGES.get(
        public_error_code,
        SITE_ERROR_MESSAGES["SITE_REGISTRATION_FAILED"],
    )
