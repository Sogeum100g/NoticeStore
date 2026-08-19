class UserModel {
  // 1. 필수(Not Null) 필드 - DB 스키마에서 [v] 체크된 항목들
  final int userId;
  final String socialId;
  final String provider;
  final bool isNotificationEnabled;
  final String notificationTime;
  final int maxSitesLimit;
  final int maxKeywordsLimit;
  final String role;

  // 2. 선택(Nullable) 필드 - DB 스키마에서 [ ] 체크된 항목들
  final String? email;
  final String? nickname;
  final DateTime? createdAt; // 앱 내에서 날짜 계산이 편하도록 DateTime으로 변환


  UserModel({
    // Not Null 필드는 객체 생성 시 반드시 필요하므로 required 적용
    required this.userId,
    required this.socialId,
    required this.provider,
    required this.isNotificationEnabled,
    required this.notificationTime,
    required this.maxSitesLimit,
    required this.maxKeywordsLimit,

    // Nullable 필드
    this.email,
    this.nickname,
    this.createdAt,

    this.role = 'USER',
  });


  // JSON 변환 로직 (서버에서 GET 해올 때 사용)
  factory UserModel.fromJson(Map<String, dynamic> json) {
    return UserModel(
      // 필수 필드라도 서버에서 null이 올 수 있다고 가정하고 방어합니다.
      userId: json['user_id'] ?? 0,
      socialId: json['social_id'] ?? '', // 💡 여기서 에러가 났을 확률이 가장 높습니다.
      provider: json['provider'] ?? 'google',

      isNotificationEnabled: json['is_notification_enabled'] ?? false,
      notificationTime: json['notification_time'] ?? '18:00',

      email: json['email'],
      nickname: json['nickname'],

      createdAt: json['created_at'] != null
          ? DateTime.tryParse(json['created_at'].toString())
          : null,

      maxSitesLimit: json['max_sites_limit'] ?? 5,
      maxKeywordsLimit: json['max_keywords_limit'] ?? 50,
      role: json['role'] ?? 'USER',
    );
  }
}
