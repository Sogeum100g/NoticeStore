import 'dart:convert';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:google_sign_in/google_sign_in.dart' as official;
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../models/user_model.dart';
import 'notification_service.dart';
import 'preferences_service.dart';

class AuthService {
  String? _ipAddress = dotenv.env['IP_ADDRESS'];
  String get _baseUrl => 'https://${_ipAddress}/v1';
  final storage = const FlutterSecureStorage();

  final official.GoogleSignIn _googleSignInOfficial = official.GoogleSignIn(
    clientId: kIsWeb ? dotenv.env['GOOGLE_WEB_CLIENT_ID'] : null,
    serverClientId: dotenv.env['GOOGLE_WEB_CLIENT_ID'],
    scopes: ['openid', 'email', 'profile'],
  );

  /// 구글 로그인 실행 (윈도우 대응)
  /// [referrerCode] 파라미터를 추가하여 UI 단에서 딥링크를 통해 얻은 초대 코드를 넘겨받습니다.
  Future<UserModel?> signInWithGoogle({String? referrerCode}) async {
    try {
      String? idToken;

      //   debugPrint("📡 [Windows Result] Access: ${result?.accessToken != null}, ID: ${result?.idToken != null}");
        final googleUser = await _googleSignInOfficial.signIn();
        final auth = await googleUser?.authentication;
        idToken = auth?.idToken;

      if (idToken == null) {
        debugPrint("❌ [AuthService] ID 토큰을 가져오지 못했습니다.");
        return null;
      }

      return await _sendTokenToBackend(
        provider: 'google',
        token: idToken,
        referrerCode: referrerCode,
      );
    } catch (e) {
      debugPrint('❌ Google SignIn Error: $e');
      return null;
    }
  }

  /// 앱 실행 시 사용자 개입 없이 로그인 세션 복구
  Future<UserModel?> trySilentSignIn() async {
    try {
      debugPrint("📡 [AuthService] 기존 구글 세션 확인 중...");
      String? idToken;

        final official.GoogleSignInAccount? googleUser = await _googleSignInOfficial.signInSilently();
        if (googleUser == null) return null;

        final official.GoogleSignInAuthentication googleAuth = await googleUser.authentication;
        idToken = googleAuth.idToken;

      if (idToken == null) return null;

      debugPrint("🚀 [AuthService] 서버에 세션 검증 요청...");
      return await _sendTokenToBackend(provider: 'google', token: idToken);
    } catch (e) {
      debugPrint('❌ [AuthService] Silent SignIn 에러: $e');
      return null;
    }
  }

  /// 백엔드 서버와 통신 (토큰 검증 및 세션 발급)
  Future<UserModel?> _sendTokenToBackend({
    required String provider,
    required String token,
    String? referrerCode,
  }) async {
    try {
      final deviceInfo = await NotificationService().getDeviceInfo();

      final Map<String, dynamic> requestBody = {
        'provider': provider,
        'access_token': token,
        'fcm_token': await PreferencesService.getFCMToken(),
        'device_id': deviceInfo['device_id'],
        'device_type': deviceInfo['device_type'],
      };

      if (referrerCode != null && referrerCode.isNotEmpty) {
        requestBody['referrer_code'] = referrerCode;
      }

      final response = await http.post(
        Uri.parse('$_baseUrl/auth/login'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(requestBody),
      ).timeout(const Duration(seconds: 10));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final String? jwtToken = data['access_token'];

        if (jwtToken != null) {
          await storage.write(key: "jwt_token", value: jwtToken);
          debugPrint("✅ JWT 저장 완료");
        }

        return UserModel.fromJson(data['user']);
      } else {
        debugPrint('❌ 로그인 요청 실패: ${response.statusCode} - ${response.body}');
        return null;
      }
    } catch (e) {
      debugPrint('❌ 백엔드 통신 실패: $e');
      return null;
    }
  }

  /// 로그아웃
  Future<void> signOut() async {
    try {
      // 로컬 데이터를 지우기 전에 먼저 호출해야 서버 인증이 가능합니다.
      await NotificationService().deleteTokenOnLogout();

        await _googleSignInOfficial.signOut();

      // 다음 로그인 시 새로운 토큰을 발급받도록 강제합니다.
      await FirebaseMessaging.instance.deleteToken();

      await PreferencesService.clearUserData();
      await storage.delete(key: "jwt_token");
      await PreferencesService.removeAuthToken();

      debugPrint("✅ [AuthService] 모든 인증 세션 및 로컬 토큰 삭제 완료");
    } catch (e) {
      debugPrint("❌ [AuthService] 로그아웃 중 에러 발생: $e");
    }
  }

  /// 서버의 사용자 닉네임 업데이트
  Future<bool> updateNicknameOnServer(String newNickname) async {
    try {
      final String? token = await storage.read(key: "jwt_token");
      if (token == null) return false;

      final response = await http.patch(
        Uri.parse('$_baseUrl/user/nickname'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
        body: jsonEncode({'nickname': newNickname}),
      ).timeout(const Duration(seconds: 7));

      return response.statusCode == 200;
    } catch (e) {
      debugPrint("⚠️ [AuthService] 닉네임 업데이트 중 네트워크 오류: $e");
      return false;
    }
  }

  /// 서버 DB로부터 최신 사용자 프로필 정보 가져오기
  Future<UserModel?> fetchUserProfile() async {
    try {
      final String? token = await storage.read(key: "jwt_token");
      if (token == null) return null;

      final response = await http.get(
        Uri.parse('$_baseUrl/user/profile'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
      ).timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final Map<String, dynamic> data = jsonDecode(utf8.decode(response.bodyBytes));
        if (data['user'] != null) {
          return UserModel.fromJson(data['user']);
        }
      }
      return null;
    } catch (e) {
      debugPrint("⚠️ [AuthService] 프로필 매칭 실패: $e");
      return null;
    }
  }

  /// 서버에 회원탈퇴(계정 및 데이터 삭제) 요청
  Future<bool> deleteAccount() async {
    try {
      final String? token = await storage.read(key: "jwt_token");
      if (token == null) {
        debugPrint("⚠️ [AuthService] 탈퇴 실패: 유효한 로컬 토큰이 없습니다.");
        return false;
      }

      final response = await http.delete(
        Uri.parse('$_baseUrl/user/me'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
      ).timeout(const Duration(seconds: 10));

      if (response.statusCode == 200 || response.statusCode == 204) {
        debugPrint("✅ [AuthService] 서버 회원탈퇴 처리 성공");
        return true;
      } else {
        debugPrint("❌ [AuthService] 서버 회원탈퇴 실패: 상태 코드 ${response.statusCode}");
        return false;
      }
    } catch (e) {
      debugPrint("❌ [AuthService] 회원탈퇴 중 네트워크 오류 발생: $e");
      return false;
    }
  }
}
