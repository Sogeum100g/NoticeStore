// lib/models/app_settings_model.dart

class AppSettingsModel {
  final bool isNotificationEnabled;
  final bool isDarkMode;
  final String appVersion;
  final List<String> globalKeywords;
  // 💡 새롭게 추가된 필드
  final int notificationHour;   // 알림 시간 (시) [cite: 2026-02-15]
  final int notificationMinute; // 알림 시간 (분) [cite: 2026-02-15]

  AppSettingsModel({
    required this.isNotificationEnabled,
    required this.isDarkMode,
    required this.appVersion,
    required this.globalKeywords,
    required this.notificationHour,
    required this.notificationMinute,
  });

  // 💡 [JSON 변환] 새 필드들에 기본값(18:00)을 부여하여 에러 방지 [cite: 2025-10-01]
  factory AppSettingsModel.fromJson(Map<String, dynamic> json) {
    return AppSettingsModel(
      isNotificationEnabled: json['is_notification_enabled'] ?? true,
      isDarkMode: json['is_dark_mode'] ?? false,
      appVersion: json['app_version'] ?? "1.0.0",
      globalKeywords: List<String>.from(json['global_keywords'] ?? []),
      notificationHour: json['notification_hour'] ?? 18,
      notificationMinute: json['notification_minute'] ?? 0,
    );
  }

  Map<String, dynamic> toJson() => {
    'is_notification_enabled': isNotificationEnabled,
    'is_dark_mode': isDarkMode,
    'app_version': appVersion,
    'global_keywords': globalKeywords,
    'notification_hour': notificationHour,
    'notification_minute': notificationMinute,
  };

  // 💡 [불변성 유지] 필드 확장 [cite: 2025-10-01]
  AppSettingsModel copyWith({
    bool? isNotificationEnabled,
    bool? isDarkMode,
    String? appVersion,
    List<String>? globalKeywords,
    int? notificationHour,
    int? notificationMinute,
  }) {
    return AppSettingsModel(
      isNotificationEnabled: isNotificationEnabled ?? this.isNotificationEnabled,
      isDarkMode: isDarkMode ?? this.isDarkMode,
      appVersion: appVersion ?? this.appVersion,
      globalKeywords: globalKeywords ?? this.globalKeywords,
      notificationHour: notificationHour ?? this.notificationHour,
      notificationMinute: notificationMinute ?? this.notificationMinute,
    );
  }
}