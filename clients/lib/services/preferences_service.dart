import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

class PreferencesService {
  static const String _keyNotices = 'all_notices_data';
  static const String _keySiteMetadata = 'subscription_site_metadata';
  static const String _keySubscriptionOrder = 'subscription_site_order';
  static const String _keyFolders = 'favorite_folders';
  static const String _keyKeywords = 'folder_keywords';
  static const String _keyDisplayLimits = 'subscription_display_limits';

  static const String _keyAuthToken = 'jwt_token';
  static const String _keyFCMToken = 'firebase_fcm_token';

  static const String _referrerKey = 'referrer_code';

  static SharedPreferences? _prefs;
  static const _secureStorage = FlutterSecureStorage();

  static Future<void> init() async {
    _prefs ??= await SharedPreferences.getInstance();
    debugPrint("✅ PreferencesService 초기화 완료");
  }

  static Future<SharedPreferences> _getOrInitPrefs() async {
    _prefs ??= await SharedPreferences.getInstance();
    return _prefs!;
  }

  /// 서버에서 받은 JWT 토큰을 보안 저장소에 암호화하여 저장
  static Future<void> setAuthToken(String token) async {
    await _secureStorage.write(key: _keyAuthToken, value: token);
    debugPrint("✅ [SecureStorage] JWT 저장 완료");
  }

  /// 저장된 JWT 토큰 불러오기
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

    // 앱 설정(다크모드 등)은 유지하고 싶을 때 사용합니다.
    await Future.wait([
      prefs.remove(_keyNotices),
      prefs.remove(_keySiteMetadata),
      prefs.remove(_keySubscriptionOrder),
      prefs.remove(_keyFolders),
      prefs.remove(_keyKeywords),
      prefs.remove(_keyDisplayLimits),
      prefs.remove(_keyFCMToken), // 계정별 푸시 토큰이 다를 수 있음
      _secureStorage.delete(key: _keyAuthToken),
    ]);

    debugPrint("🧹 [PreferencesService] 모든 사용자 데이터 초기화 완료");
  }

  static Future<void> saveNotices(
      Map<String, List<Map<String, dynamic>>> notices,
      ) async {
    final prefs = await _getOrInitPrefs();
    await prefs.setString(_keyNotices, jsonEncode(notices));
  }

  static Future<Map<String, List<Map<String, dynamic>>>> loadNotices() async {
    final prefs = await _getOrInitPrefs();
    final String? jsonStr = prefs.getString(_keyNotices);
    if (jsonStr == null || jsonStr.isEmpty) return {};
    try {
      final Map<String, dynamic> decoded = jsonDecode(jsonStr);
      return decoded.map(
            (key, value) => MapEntry(
          key,
          (value as List).map((e) => Map<String, dynamic>.from(e)).toList(),
        ),
      );
    } catch (e) {
      return {};
    }
  }

  static Future<void> saveSiteMetadata(
      Map<String, Map<String, dynamic>> metadata,
      ) async {
    final prefs = await _getOrInitPrefs();
    await prefs.setString(_keySiteMetadata, jsonEncode(metadata));
  }

  static Future<Map<String, Map<String, dynamic>>> loadSiteMetadata() async {
    final prefs = await _getOrInitPrefs();
    final String? jsonStr = prefs.getString(_keySiteMetadata);
    if (jsonStr == null || jsonStr.isEmpty) return {};

    try {
      final Map<String, dynamic> decoded = jsonDecode(jsonStr);
      return decoded.map(
            (key, value) => MapEntry(key, Map<String, dynamic>.from(value as Map)),
      );
    } catch (e) {
      return {};
    }
  }

  /// 구독 폴더의 사용자 지정 순서를 별명 대신 변경되지 않는 site_id로 보관합니다.
  static Future<void> saveSubscriptionOrder(List<int> siteIds) async {
    final prefs = await _getOrInitPrefs();
    await prefs.setString(_keySubscriptionOrder, jsonEncode(siteIds));
  }

  static Future<List<int>> loadSubscriptionOrder() async {
    final prefs = await _getOrInitPrefs();
    final String? jsonStr = prefs.getString(_keySubscriptionOrder);
    if (jsonStr == null || jsonStr.isEmpty) return [];

    try {
      final dynamic decoded = jsonDecode(jsonStr);
      if (decoded is! List) return [];
      return decoded
          .map((value) => int.tryParse(value.toString()))
          .whereType<int>()
          .toList();
    } catch (_) {
      return [];
    }
  }

  /// 구독 폴더별 표시 개수/날짜 제한 설정 (알림 폴더에 공지가 과도하게 쌓였을 때 사용)
  static Future<void> saveDisplayLimits(
      Map<String, Map<String, dynamic>> limits,
      ) async {
    final prefs = await _getOrInitPrefs();
    await prefs.setString(_keyDisplayLimits, jsonEncode(limits));
  }

  static Future<Map<String, Map<String, dynamic>>> loadDisplayLimits() async {
    final prefs = await _getOrInitPrefs();
    final String? jsonStr = prefs.getString(_keyDisplayLimits);
    if (jsonStr == null || jsonStr.isEmpty) return {};

    try {
      final Map<String, dynamic> decoded = jsonDecode(jsonStr);
      return decoded.map(
            (key, value) => MapEntry(key, Map<String, dynamic>.from(value as Map)),
      );
    } catch (e) {
      return {};
    }
  }

  static Future<void> saveFavorites({
    required Map<String, List<Map<String, dynamic>>> folders,
    required Map<String, List<String>> keywords,
  }) async {
    final prefs = await _getOrInitPrefs();
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
      folders = decoded.map(
            (key, value) => MapEntry(
          key,
          (value as List).map((e) => Map<String, dynamic>.from(e)).toList(),
        ),
      );
    }

    if (keywordsJson != null && keywordsJson.isNotEmpty) {
      final Map<String, dynamic> decoded = jsonDecode(keywordsJson);
      keywords = decoded.map(
            (key, value) => MapEntry(key, List<String>.from(value)),
      );
    }

    return {'folders': folders, 'keywords': keywords};
  }

  static Future<void> saveAlias(String url, String alias) async {
    final prefs = await _getOrInitPrefs();
    await prefs.setString(url, alias);
  }

  static Future<String?> getAlias(String url) async {
    final prefs = await _getOrInitPrefs();
    return prefs.getString(url);
  }

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

  static Future<void> saveReferrerCode(String code) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_referrerKey, code);
  }

  static Future<String?> getReferrerCode() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_referrerKey);
  }

  static Future<void> clearReferrerCode() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_referrerKey);
  }
}
