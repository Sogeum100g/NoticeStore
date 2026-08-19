import 'dart:convert';
import 'dart:io';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:google_sign_in/google_sign_in.dart' as official; // 공식 패키지 [cite: 2026-02-15]
import 'package:google_sign_in_all_platforms/google_sign_in_all_platforms.dart' as desktop; // 윈도우용
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart'; // storage 사용을 위해 추가
import '../models/user_model.dart';
import 'notification_service.dart';
import 'preferences_service.dart';

class AuthService {
  String? _ipAddress = dotenv.env['IP_ADDRESS'];
  // 서버 주소 (v1 라우터 대응) [cite: 2025-10-01]
  String get _baseUrl => 'http://${_ipAddress}/v1';
  final storage = const FlutterSecureStorage(); // 보안 저장소 인스턴스

  // 1. 공식 패키지 (모바일/웹) 설정 [cite: 2026-02-15]
  final official.GoogleSignIn _googleSignInOfficial = official.GoogleSignIn(
    clientId: kIsWeb ? dotenv.env['GOOGLE_WEB_CLIENT_ID'] : null,
    serverClientId: dotenv.env['GOOGLE_WEB_CLIENT_ID'],
    // 'openid' 추가 필수
    scopes: ['openid', 'email', 'profile'],
  );

  // 2. 윈도우용 패키지 설정 수정
  final desktop.GoogleSignIn _googleSignInDesktop = desktop.GoogleSignIn(
    params: desktop.GoogleSignInParams(
      clientId: dotenv.env['GOOGLE_WINDOWS_CLIENT_ID']!,
      // 윈도우는 토큰 교환을 위해 Secret이 필요한 경우가 많습니다.
      clientSecret: dotenv.env['GOOGLE_WEB_CLIENT_SECRET'],
      scopes: ['openid', 'email', 'profile'],
      // redirectPort: 8000, // 기본값 8000 (콘솔의 리디렉션 URI와 일치해야 함)
    ),
  );

  /// 🔐 구글 로그인 실행 (윈도우 대응)
  /// [referrerCode] 파라미터를 추가하여 UI 단에서 딥링크를 통해 얻은 초대 코드를 넘겨받습니다.
  Future<UserModel?> signInWithGoogle({String? referrerCode}) async {
    try {
      String? idToken;

      if (!kIsWeb && Platform.isWindows) {
        // 이미 생성자에서 설정을 마쳤으므로 인자 없이 호출합니다.
        final result = await _googleSignInDesktop.signIn();

        // 디버깅용 로그: 어떤 데이터가 오는지 확인해보세요.
        debugPrint("📡 [Windows Result] Access: ${result?.accessToken != null}, ID: ${result?.idToken != null}");

        idToken = result?.idToken;
      } else {
        final googleUser = await _googleSignInOfficial.signIn();
        final auth = await googleUser?.authentication;
        idToken = auth?.idToken;
      }

      if (idToken == null) {
        debugPrint("❌ [AuthService] ID 토큰을 가져오지 못했습니다.");
        return null; // 여기서 null이 반환되면 UI의 로딩바를 꺼주는 처리가 필요합니다.
      }

      // 획득한 토큰과 추천인 코드를 백엔드로 전송
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

  /// 🔄 앱 실행 시 사용자 개입 없이 로그인 세션 복구
  Future<UserModel?> trySilentSignIn() async {
    try {
      debugPrint("📡 [AuthService] 기존 구글 세션 확인 중...");
      String? idToken;

      if (!kIsWeb && Platform.isWindows) {
        // 윈도우는 현재 패키지 구조상 silentSignIn이 지원되지 않을 수 있으므로 null 반환 후 로그인을 유도합니다.
        return null;
      } else {
        // 사진 4 에러 해결: _googleSignIn -> _googleSignInOfficial로 변경
        final official.GoogleSignInAccount? googleUser = await _googleSignInOfficial.signInSilently();
        if (googleUser == null) return null;

        final official.GoogleSignInAuthentication googleAuth = await googleUser.authentication;
        idToken = googleAuth.idToken;
      }

      if (idToken == null) return null;

      debugPrint("🚀 [AuthService] 서버에 세션 검증 요청...");
      return await _sendTokenToBackend(provider: 'google', token: idToken);
    } catch (e) {
      debugPrint('❌ [AuthService] Silent SignIn 에러: $e');
      return null;
    }
  }

  /// 🚀 백엔드 서버와 통신 (토큰 검증 및 세션 발급) [cite: 2026-02-17]
  Future<UserModel?> _sendTokenToBackend({
    required String provider,
    required String token,
    String? referrerCode,
  }) async {
    try {
      // 1. [리팩토링] 공통 함수를 사용하여 기기 정보 추출 [cite: 2026-03-10]
      // NotificationService의 메서드가 static이거나 인스턴스 접근이 가능해야 합니다.
      final deviceInfo = await NotificationService().getDeviceInfo();

      // 2. 서버로 보낼 JSON 데이터를 구성합니다.
      // 이제 백엔드의 social_login 엔드포인트는 이 기기 정보를 함께 처리합니다. [cite: 2026-03-10]
      final Map<String, dynamic> requestBody = {
        'provider': provider,
        'access_token': token,
        'fcm_token': await PreferencesService.getFCMToken(),
        'device_id': deviceInfo['device_id'],     // 추가됨
        'device_type': deviceInfo['device_type'], // 추가됨
      };

      // 추천인 코드가 존재할 경우에만 바디에 추가합니다.
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

        // 기기 정보와 함께 유저 데이터 반환 [cite: 2026-03-10]
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

  /// 🚪 로그아웃
  Future<void> signOut() async {
    try {
      // 💡 1. [추가] 서버에 FCM 토큰 삭제 알림 (인증 토큰이 있을 때 수행)
      // 로컬 데이터를 지우기 전에 먼저 호출해야 서버 인증이 가능합니다.
      await NotificationService().deleteTokenOnLogout();

      // 플랫폼별로 로그아웃 처리
      if (!kIsWeb && Platform.isWindows) {
        await _googleSignInDesktop.signOut();
      } else {
        await _googleSignInOfficial.signOut(); // .disconnect() 대신 범용적인 .signOut() 사용 권장
      }

      // 💡 3. [추가] 기기 내 FCM 토큰 무효화 (Firebase SDK 레벨)
      // 다음 로그인 시 새로운 토큰을 발급받도록 강제합니다.
      await FirebaseMessaging.instance.deleteToken();

      // 2. 서비스 레이어의 모든 데이터 삭제 💡
      await PreferencesService.clearUserData();
      await storage.delete(key: "jwt_token");
      await PreferencesService.removeAuthToken();

      debugPrint("✅ [AuthService] 모든 인증 세션 및 로컬 토큰 삭제 완료");
    } catch (e) {
      debugPrint("❌ [AuthService] 로그아웃 중 에러 발생: $e");
    }
  }

  /// 📝 서버의 사용자 닉네임 업데이트
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

  /// 🔄 서버 DB로부터 최신 사용자 프로필 정보 가져오기
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

  /// 🚨 서버에 회원탈퇴(계정 및 데이터 삭제) 요청
  Future<bool> deleteAccount() async {
    try {
      // 1. 로컬 보안 저장소에서 JWT 토큰 읽기
      final String? token = await storage.read(key: "jwt_token");
      if (token == null) {
        debugPrint("⚠️ [AuthService] 탈퇴 실패: 유효한 로컬 토큰이 없습니다.");
        return false;
      }

      // 2. 백엔드 FastAPI 서버로 DELETE 요청 전송
      final response = await http.delete(
        Uri.parse('$_baseUrl/user/me'), // FastAPI의 회원탈퇴 엔드포인트
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token', // 인증 헤더 필수
        },
      ).timeout(const Duration(seconds: 10)); // 타임아웃 설정

      // 3. 서버 응답 코드 확인 (200 OK 또는 204 No Content를 성공으로 간주)
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