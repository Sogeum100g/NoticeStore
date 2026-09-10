import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:http/http.dart' as http;

import '../models/app_settings_model.dart';
import '../models/user_model.dart';
import '../services/preferences_service.dart';

import 'package:flutter_dotenv/flutter_dotenv.dart';

class SettingsProvider with ChangeNotifier {
  static const String _storageKey = 'app_settings_data';
  String? _ipAddress = dotenv.env['IP_ADDRESS'];

  AppSettingsModel _settings = AppSettingsModel(
    isNotificationEnabled: false,
    isDarkMode: false,
    appVersion: "1.0.0",
    globalKeywords: [],
  );

  AppSettingsModel get settings => _settings;

  Future<void> initSettings() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final String? jsonString = prefs.getString(_storageKey);

      if (jsonString != null) {
        final Map<String, dynamic> jsonMap = jsonDecode(jsonString);
        _settings = AppSettingsModel.fromJson(jsonMap);
        notifyListeners();
      }
    } catch (e) {
      debugPrint("Settings 로드 중 오류 발생: $e");
    }
  }

  Future<void> updateSettings({
    bool? isNotificationEnabled,
    bool? isDarkMode,
    List<String>? globalKeywords,
  }) async {
    final previousSettings = _settings;

    _settings = _settings.copyWith(
      isNotificationEnabled: isNotificationEnabled,
      isDarkMode: isDarkMode,
      globalKeywords: globalKeywords,
    );
    notifyListeners();
    await _saveToDisk();

    bool notificationChanged = isNotificationEnabled != null;

    if (notificationChanged) {
      bool isSuccess = await _syncNotificationSettingsWithServer();

      if (!isSuccess) {
        debugPrint("서버 동기화 실패. 이전 상태로 롤백합니다.");
        _settings = previousSettings;
        notifyListeners();
        await _saveToDisk();
      }
    }
  }

  Future<bool> _syncNotificationSettingsWithServer() async {
    try {
      final String? accessToken = await PreferencesService.getAuthToken();

      // 토큰이 없는 경우 (예: 로그아웃 상태) 서버 요청을 보내지 않고 미리 종료
      if (accessToken == null || accessToken.isEmpty) {
        debugPrint("❌ 인증 토큰이 없습니다. 로그인이 필요합니다.");
        return false;
      }

      final response = await http.patch(
        Uri.parse('https://${_ipAddress}/v1/user/notification'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $accessToken',
        },
        body: jsonEncode({
          "is_notification_enabled": _settings.isNotificationEnabled,
        }),
      );

      if (response.statusCode == 200) {
        debugPrint("알림 설정 서버 동기화 성공");
        return true;
      } else {
        debugPrint("알림 설정 서버 동기화 실패: 상태 코드 ${response.statusCode}");
        return false;
      }
    } catch (e) {
      debugPrint("API 통신 중 예외 발생: $e");
      return false;
    }
  }

  Future<void> addKeyword(String keyword) async {
    if (!_settings.globalKeywords.contains(keyword)) {
      final newKeywords = [..._settings.globalKeywords, keyword];
      await updateSettings(globalKeywords: newKeywords);
    }
  }

  Future<void> removeKeyword(String keyword) async {
    final newKeywords = _settings.globalKeywords
        .where((k) => k != keyword)
        .toList();
    await updateSettings(globalKeywords: newKeywords);
  }

  Future<void> _saveToDisk() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final String jsonString = jsonEncode(_settings.toJson());
      await prefs.setString(_storageKey, jsonString);
    } catch (e) {
      debugPrint("Settings 저장 중 오류 발생: $e");
    }
  }

  /// 사용자 ID가 포함된 초대 링크를 공유합니다.
  void shareInviteLink(int userId) {
    final String inviteUrl = 'https://noticestorage.com/invite?ref=$userId';
    final String message =
        '🔔 [공지저장소] 친구가 당신을 초대했습니다!\n\n'
        '원하는 사이트의 공지사항을 실시간으로 받아보세요.\n'
        '아래 링크로 가입하면 저와 친구 모두 구독 한도가 늘어나요! 🎁\n\n'
        '$inviteUrl';

    Share.share(message, subject: '공지저장소 초대장');
  }

  void resetSettings() {
    _settings = AppSettingsModel.fromJson({});
    notifyListeners();
  }

  /// 유저 모델로부터 설정을 동기화 (서버 요청 제외)
  void syncFromUserModel(UserModel user) {
    _settings = _settings.copyWith(
      isNotificationEnabled: user.isNotificationEnabled,
    );

    _saveToDisk();
    notifyListeners();
    debugPrint("🔄 [SettingsProvider] 유저 DB 값으로 설정 동기화 완료");
  }
}
