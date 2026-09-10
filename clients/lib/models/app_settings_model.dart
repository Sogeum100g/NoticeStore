
class AppSettingsModel {
  final bool isNotificationEnabled;
  final bool isDarkMode;
  final String appVersion;
  final List<String> globalKeywords;

  AppSettingsModel({
    required this.isNotificationEnabled,
    required this.isDarkMode,
    required this.appVersion,
    required this.globalKeywords,
  });

  factory AppSettingsModel.fromJson(Map<String, dynamic> json) {
    return AppSettingsModel(
      isNotificationEnabled: json['is_notification_enabled'] ?? false,
      isDarkMode: json['is_dark_mode'] ?? false,
      appVersion: json['app_version'] ?? "1.0.0",
      globalKeywords: List<String>.from(json['global_keywords'] ?? []),
    );
  }

  Map<String, dynamic> toJson() => {
    'is_notification_enabled': isNotificationEnabled,
    'is_dark_mode': isDarkMode,
    'app_version': appVersion,
    'global_keywords': globalKeywords,
  };

  AppSettingsModel copyWith({
    bool? isNotificationEnabled,
    bool? isDarkMode,
    String? appVersion,
    List<String>? globalKeywords,
  }) {
    return AppSettingsModel(
      isNotificationEnabled:
          isNotificationEnabled ?? this.isNotificationEnabled,
      isDarkMode: isDarkMode ?? this.isDarkMode,
      appVersion: appVersion ?? this.appVersion,
      globalKeywords: globalKeywords ?? this.globalKeywords,
    );
  }
}
