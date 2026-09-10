enum SiteCrawlStatus {
  pending,
  active,
  paused,
  failed,
  blocked,
  unknown;

  static SiteCrawlStatus fromApi(dynamic value) {
    return switch (value?.toString().toLowerCase()) {
      'pending' => SiteCrawlStatus.pending,
      'active' => SiteCrawlStatus.active,
      'paused' => SiteCrawlStatus.paused,
      'failed' => SiteCrawlStatus.failed,
      'blocked' => SiteCrawlStatus.blocked,
      _ => SiteCrawlStatus.unknown,
    };
  }

  bool get shouldShowInSubscription {
    return this != SiteCrawlStatus.active &&
        this != SiteCrawlStatus.unknown;
  }

  String get label {
    return switch (this) {
      SiteCrawlStatus.pending => '분석 중',
      SiteCrawlStatus.active => '정상',
      SiteCrawlStatus.paused => '일시 중지',
      SiteCrawlStatus.failed => '수집 실패',
      SiteCrawlStatus.blocked => '수집 제한',
      SiteCrawlStatus.unknown => '상태 확인 중',
    };
  }

  String get userMessage {
    return switch (this) {
      SiteCrawlStatus.pending =>
      '사이트 구조를 분석하고 있습니다. 잠시 후 새로고침해 주세요.',
      SiteCrawlStatus.active => '',
      SiteCrawlStatus.paused => '정보 수집이 일시 중지된 사이트입니다.',
      SiteCrawlStatus.failed =>
      '정보를 가져오지 못했습니다. 도움말의 문의하기를 통해 알려주세요.',
      SiteCrawlStatus.blocked =>
      '사이트 정책으로 정보 수집이 제한되었습니다.',
      SiteCrawlStatus.unknown => '',
    };
  }

  static String errorMessageFor(String? errorCode) {
    return switch (errorCode) {
      'CRAWL_QUEUE_UNAVAILABLE' =>
      '사이트 분석을 시작하지 못했습니다. 잠시 후 다시 시도해 주세요.',
      'ROBOTS_TXT_BLOCKED' => '사이트 정책으로 접근이 제한되었습니다.',
      'SITE_VALIDATION_FAILED' => '사이트의 정보 목록을 확인하지 못했습니다.',
      'SITE_ACCESS_BLOCKED' => '사이트 정책으로 접근이 제한되었습니다.',
      'SITE_UNREACHABLE' => '사이트 응답을 받지 못했습니다. 잠시 후 다시 확인해 주세요.',
      'DATABASE_ERROR' =>
      '사이트 정보를 저장하는 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.',
      'SITE_REGISTRATION_FAILED' =>
      '사이트 등록 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.',
      _ => '',
    };
  }
}
