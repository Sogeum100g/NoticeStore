import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:http/http.dart' as http; // HTTP 통신 패키지 추가
import '../models/app_settings_model.dart';
import '../models/user_model.dart';
import '../services/preferences_service.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

class SettingsProvider with ChangeNotifier {
  static const String _storageKey = 'app_settings_data';
  // 💡 실제 백엔드 서버 주소로 변경 필요
  String? _ipAddress = dotenv.env['IP_ADDRESS'];

  AppSettingsModel _settings = AppSettingsModel(
    isNotificationEnabled: true,
    isDarkMode: false,
    appVersion: "1.0.0",
    globalKeywords: [],
    notificationHour: 18,
    notificationMinute: 0,
  );

  AppSettingsModel get settings => _settings;

  // 1️⃣ [초기화] 앱 시작 시 로컬 설정 로드 (이후 서버 상태와 동기화하는 로직을 추가하는 것을 권장)
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

  // 2️⃣ [상태 업데이트] 로컬 상태 변경 및 서버 동기화
  Future<void> updateSettings({
    bool? isNotificationEnabled,
    bool? isDarkMode,
    List<String>? globalKeywords,
    int? notificationHour,
    int? notificationMinute,
  }) async {
    // 변경 전 상태 백업 (서버 통신 실패 시 롤백용)
    final previousSettings = _settings;

    // 1. UI 즉각 반영을 위해 로컬 상태 먼저 업데이트
    _settings = _settings.copyWith(
      isNotificationEnabled: isNotificationEnabled,
      isDarkMode: isDarkMode,
      globalKeywords: globalKeywords,
      notificationHour: notificationHour,
      notificationMinute: notificationMinute,
    );
    notifyListeners();
    await _saveToDisk();

    // 2. 알림 관련 설정이 변경되었다면 백엔드 서버로 동기화 요청
    bool notificationChanged = isNotificationEnabled != null ||
        notificationHour != null ||
        notificationMinute != null;

    if (notificationChanged) {
      bool isSuccess = await _syncNotificationSettingsWithServer();

      // 서버 동기화 실패 시 로컬 상태 롤백
      if (!isSuccess) {
        debugPrint("서버 동기화 실패. 이전 상태로 롤백합니다.");
        _settings = previousSettings;
        notifyListeners();
        await _saveToDisk();
      }
    }
  }

  // 3️⃣ [서버 동기화] FastAPI로 PATCH 요청 전송
  Future<bool> _syncNotificationSettingsWithServer() async {
    try {
      // 시간 포맷을 FastAPI에서 요구하는 "HH:MM" 형식의 문자열로 변환
      final String timeString =
          '${_settings.notificationHour.toString().padLeft(2, '0')}:${_settings.notificationMinute.toString().padLeft(2, '0')}';

      // 💡 실제 구현 시에는 AuthProvider 등에서 로그인한 유저의 JWT 액세스 토큰을 가져와야 합니다.
      final String? accessToken = await PreferencesService.getAuthToken();

      // 💡 토큰이 없는 경우 (예: 로그아웃 상태) 서버 요청을 보내지 않고 미리 종료
      if (accessToken == null || accessToken.isEmpty) {
        debugPrint("❌ 인증 토큰이 없습니다. 로그인이 필요합니다.");
        return false;
      }

      final response = await http.patch(
        Uri.parse('http://${_ipAddress}/v1/user/notification'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $accessToken',
        },
        body: jsonEncode({
          "is_notification_enabled": _settings.isNotificationEnabled,
          "notification_time": timeString,
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

  // 4️⃣ [키워드 관리] 기존 유지
  Future<void> addKeyword(String keyword) async {
    if (!_settings.globalKeywords.contains(keyword)) {
      final newKeywords = [..._settings.globalKeywords, keyword];
      await updateSettings(globalKeywords: newKeywords);
    }
  }

  Future<void> removeKeyword(String keyword) async {
    final newKeywords = _settings.globalKeywords.where((k) => k != keyword).toList();
    await updateSettings(globalKeywords: newKeywords);
  }

  // 5️⃣ [영속화] 기존 유지
  Future<void> _saveToDisk() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final String jsonString = jsonEncode(_settings.toJson());
      await prefs.setString(_storageKey, jsonString);
    } catch (e) {
      debugPrint("Settings 저장 중 오류 발생: $e");
    }
  }

  /// 초대 링크를 생성하고 공유창을 실행합니다.
  /// 특정 유저의 ID를 받아 고유 URL을 구성합니다.
  /// 초대 링크를 생성하고 공유창을 실행합니다.
  void shareInviteLink(int userId) {
    // 도메인 및 메시지 구성
    final String inviteUrl = 'https://noticestorage.com/invite?ref=$userId';
    final String message = '🔔 [센트리피전] 친구가 당신을 초대했습니다!\n\n'
        '원하는 사이트의 공지사항을 실시간으로 받아보세요.\n'
        '아래 링크로 가입하면 저와 친구 모두 구독 한도가 늘어나요! 🎁\n\n'
        '$inviteUrl';

    // 가이드에 따라 최신 API 방식으로 호출
    // 버전 상수에 따라 Share.share가 그대로 쓰이기도 하나, 경고가 뜬다면 아래 형식을 따릅니다.
    Share.share(
      message,
      subject: '센트리피전 초대장',
    );
  }

  void resetSettings() {
    // factory에서 정의한 기본값들을 그대로 재활용합니다.
    _settings = AppSettingsModel.fromJson({});
    notifyListeners();
  }

  /// 💡 유저 모델로부터 설정을 동기화 (서버 요청 제외)
  void syncFromUserModel(UserModel user) {
    // 예: "19:00" -> hour: 19, minute: 0 분리
    int hour = 18;
    int minute = 0;

    if (user.notificationTime.contains(':')) {
      final parts = user.notificationTime.split(':');
      hour = int.tryParse(parts[0]) ?? 18;
      minute = int.tryParse(parts[1]) ?? 0;
    }

    // 로컬 상태 갱신 및 디스크 저장만 수행 (서버 API 호출 X)
    _settings = _settings.copyWith(
      isNotificationEnabled: user.isNotificationEnabled,
      notificationHour: hour,
      notificationMinute: minute,
      // 필요시 닉네임이나 기타 글로벌 키워드 등도 포함
    );

    _saveToDisk();
    notifyListeners();
    debugPrint("🔄 [SettingsProvider] 유저 DB 값으로 설정 동기화 완료");
  }
}