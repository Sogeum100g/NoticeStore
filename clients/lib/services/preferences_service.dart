import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

class PreferencesService {
  // --- 1. Keys (일관성 있게 통일) ---
  static const String _keyNotices = 'all_notices_data';
  static const String _keyFolders = 'favorite_folders';
  static const String _keyKeywords = 'folder_keywords';

  // 💡 중요: 모든 파일에서 이 키만 사용하도록 정의합니다. [cite: 2025-10-01]
  static const String _keyAuthToken = 'jwt_token';
  static const String _keyFCMToken = 'firebase_fcm_token';

  static const String _referrerKey = 'referrer_code';

  static SharedPreferences? _prefs;
  // 💡 보안 저장소 인스턴스 생성 [cite: 2025-10-01]
  static const _secureStorage = FlutterSecureStorage();

  static Future<void> init() async {
    _prefs ??= await SharedPreferences.getInstance();
    debugPrint("✅ PreferencesService 초기화 완료");
  }

  static Future<SharedPreferences> _getOrInitPrefs() async {
    _prefs ??= await SharedPreferences.getInstance();
    return _prefs!;
  }

  // --- 2. 인증(Authentication) 관련 - 보안 저장소 사용 [cite: 2025-10-01] ---

  /// 서버에서 받은 JWT 토큰을 보안 저장소에 암호화하여 저장 [cite: 2025-10-01]
  static Future<void> setAuthToken(String token) async {
    await _secureStorage.write(key: _keyAuthToken, value: token);
    debugPrint("✅ [SecureStorage] JWT 저장 완료");
  }

  /// 저장된 JWT 토큰 불러오기 [cite: 2026-02-15]
  static Future<String?> getAuthToken() async {
    final token = await _secureStorage.read(key: _keyAuthToken);
    return token;
  }

  /// 로그아웃 시 토큰 삭제
  static Future<void> removeAuthToken() async {
    await _secureStorage.delete(key: _keyAuthToken);
  }

  /// 로그아웃 시 유저 데이터 삭제
  static Future<void> clearUserData() async {
    final prefs = await _getOrInitPrefs();

    // 💡 방법 A: 특정 사용자 데이터 키만 선택해서 삭제 (권장)
    // 앱 설정(다크모드 등)은 유지하고 싶을 때 사용합니다.
    await Future.wait([
      prefs.remove(_keyNotices),
      prefs.remove(_keyFolders),
      prefs.remove(_keyKeywords),
      prefs.remove(_keyFCMToken), // 계정별 푸시 토큰이 다를 수 있음
      _secureStorage.delete(key: _keyAuthToken),
    ]);

    // 💡 방법 B: 전체 초기화
    // 모든 로컬 데이터를 깨끗이 비웁니다.
    // await prefs.clear();
    // await _secureStorage.deleteAll();

    debugPrint("🧹 [PreferencesService] 모든 사용자 데이터 초기화 완료");
  }

  // --- 3. 일반 설정 및 데이터 - SharedPreferences 사용 ---

  static Future<void> saveNotices(Map<String, List<Map<String, dynamic>>> notices) async {
    final prefs = await _getOrInitPrefs();
    await prefs.setString(_keyNotices, jsonEncode(notices));
  }

  static Future<Map<String, List<Map<String, dynamic>>>> loadNotices() async {
    final prefs = await _getOrInitPrefs();
    final String? jsonStr = prefs.getString(_keyNotices);
    if (jsonStr == null || jsonStr.isEmpty) return {};
    try {
      final Map<String, dynamic> decoded = jsonDecode(jsonStr);
      return decoded.map((key, value) => MapEntry(key, (value as List).map((e) => Map<String, dynamic>.from(e)).toList()));
    } catch (e) { return {}; }
  }

  // --- 4. 즐겨찾기(Favorite) 관련 ---
  static Future<void> saveFavorites({
    required Map<String, List<Map<String, dynamic>>> folders,
    required Map<String, List<String>> keywords,
  }) async {
    final prefs = await _getOrInitPrefs();
    // 여러 데이터를 동시에 저장할 때 효율적
    await Future.wait([
      prefs.setString(_keyFolders, jsonEncode(folders)),
      prefs.setString(_keyKeywords, jsonEncode(keywords)),
    ]);
  }

  static Future<Map<String, dynamic>> loadFavorites() async {
    final prefs = await _getOrInitPrefs();
    final String? foldersJson = prefs.getString(_keyFolders);
    final String? keywordsJson = prefs.getString(_keyKeywords);

    Map<String, List<Map<String, dynamic>>> folders = {};
    Map<String, List<String>> keywords = {};

    if (foldersJson != null && foldersJson.isNotEmpty) {
      final Map<String, dynamic> decoded = jsonDecode(foldersJson);
      folders = decoded.map((key, value) => MapEntry(
          key,
          (value as List).map((e) => Map<String, dynamic>.from(e)).toList()
      ));
    }

    if (keywordsJson != null && keywordsJson.isNotEmpty) {
      final Map<String, dynamic> decoded = jsonDecode(keywordsJson);
      keywords = decoded.map((key, value) => MapEntry(key, List<String>.from(value)));
    }

    return {'folders': folders, 'keywords': keywords};
  }

  // --- 5. 기타 설정 (별명 등) ---
  static Future<void> saveAlias(String url, String alias) async {
    final prefs = await _getOrInitPrefs();
    await prefs.setString(url, alias);
  }

  static Future<String?> getAlias(String url) async {
    final prefs = await _getOrInitPrefs();
    return prefs.getString(url);
  }


  // --- 7. FCM 푸시 토큰 관련 추가 (ERD 연동용) [cite: 2026-02-17] ---

  /// 기기 고유의 FCM 토큰 저장
  static Future<void> setFCMToken(String token) async {
    final prefs = await _getOrInitPrefs();
    await prefs.setString(_keyFCMToken, token);
  }

  /// 저장된 FCM 토큰 불러오기
  static Future<String?> getFCMToken() async {
    final prefs = await _getOrInitPrefs();
    return prefs.getString(_keyFCMToken);
  }

  // 추천인 코드 임시 저장
  static Future<void> saveReferrerCode(String code) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_referrerKey, code);
  }

  // 추천인 코드 가져오기
  static Future<String?> getReferrerCode() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_referrerKey);
  }

  // 사용 후 지우기 (회원가입 완료 시 호출)
  static Future<void> clearReferrerCode() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_referrerKey);
  }
}