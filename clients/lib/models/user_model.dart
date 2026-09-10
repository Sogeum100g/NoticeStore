class UserModel {
  final int userId;
  final String socialId;
  final String provider;
  final bool isNotificationEnabled;
  final int maxSitesLimit;
  final int maxKeywordsLimit;
  final String role;

  final String? email;
  final String? nickname;
  final DateTime? createdAt;

  UserModel({
    required this.userId,
    required this.socialId,
    required this.provider,
    required this.isNotificationEnabled,
    required this.maxSitesLimit,
    required this.maxKeywordsLimit,

    this.email,
    this.nickname,
    this.createdAt,

    this.role = 'USER',
  });

  factory UserModel.fromJson(Map<String, dynamic> json) {
    return UserModel(
      userId: json['user_id'] ?? 0,
      socialId: json['social_id'] ?? '',
      provider: json['provider'] ?? 'google',

      isNotificationEnabled: json['is_notification_enabled'] ?? false,

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
