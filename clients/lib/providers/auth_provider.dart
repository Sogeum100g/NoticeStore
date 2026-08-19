import 'package:clients/providers/settings_provider.dart';
import 'package:flutter/material.dart';
import '../models/user_model.dart';
import '../services/auth_service.dart';
import '../services/notification_service.dart';
import '../services/preferences_service.dart';
import 'notice_provider.dart';

class AuthProvider with ChangeNotifier {
  final AuthService _authService = AuthService();
  UserModel? _user;
  bool _isLoading = true;

  UserModel? get user => _user;
  bool get isLoading => _isLoading;
  bool get isAuthenticated => _user != null;


  String get nickname {
    // 1. 유저 정보가 없으면 즉시 반환 (앱 크래시 방지) [cite: 2026-02-15]
    if (_user == null) return '로그인 필요';

    // 2. 닉네임이 존재하고 비어있지 않다면 닉네임 반환 [cite: 2026-02-20]
    if (_user!.nickname != null && _user!.nickname!.trim().isNotEmpty) {
      return _user!.nickname!;
    }

    // 3. 닉네임이 없으면 이메일 앞부분 반환 [cite: 2026-02-20]
    if (_user!.email != null && _user!.email!.contains('@')) {
      return _user!.email!.split('@')[0];
    }

    // 4. 정말 만약의 상황을 위한 최후의 텍스트 [cite: 2025-09-10]
    return '사용자';
  }

  /// 🔐 구글 로그인 실행 및 데이터 동기화
  Future<bool> signInWithGoogle(NoticeProvider noticeProv, SettingsProvider settingsProv, {String? referrerCode}) async {
    _setLoading(true);

    try {
      final user = await _authService.signInWithGoogle(referrerCode: referrerCode);

      if (user != null) {
        _user = user;

        // 알림 설정 동기화 💡 (DB 값을 UI 상태로 주입)
        settingsProv.syncFromUserModel(user);

        // 💡 [추가] 로그인 성공 직후, 발급받은 JWT를 사용해 FCM 토큰을 서버에 등록합니다.
        await NotificationService().syncTokenAfterLogin();

        await noticeProv.fetchNoticesFromServer();
        return true;
      }
      return false;
    } catch (e) {
      debugPrint("❌ 로그인 에러: $e");
      return false;
    } finally {
      _setLoading(false);
    }
  }

  /// 🔄 앱 실행 시 자동 로그인 체크
  Future<void> checkAutoLogin(NoticeProvider noticeProv) async {
    Future.microtask(() => _setLoading(true));

    try {
      final user = await _authService.trySilentSignIn();

      if (user != null) {
        final latestUser = await _authService.fetchUserProfile();
        _user = latestUser ?? user;
        notifyListeners();

        // 💡 [추가] 자동 로그인 성공 시에도 토큰이 서버와 맞지 않을 수 있으므로 갱신해 줍니다.
        await NotificationService().syncTokenAfterLogin();

        await noticeProv.fetchNoticesFromServer();
      }
    } catch (e) {
      debugPrint("❌ 자동 로그인 중 오류: $e");
    } finally {
      _setLoading(false);
    }
  }

  void _setLoading(bool value) {
    if (_isLoading == value) return; // 불필요한 알림 방지
    _isLoading = value;
    notifyListeners();
  }


  Future<void> signOut(SettingsProvider settingsProv) async {
    _setLoading(true);
    try {
      // 1. AuthService를 통해 구글 및 서버 세션 종료
      await _authService.signOut();

      // 💡 메모리에 상주하는 설정 데이터 즉시 초기화
      settingsProv.resetSettings();

      // 2. 로컬 유저 정보 초기화
      _user = null;
      debugPrint("✅ 로그아웃 완료 및 유저 정보 초기화");
    } catch (e) {
      debugPrint("❌ 로그아웃 중 오류 발생: $e");
    } finally {
      _setLoading(false);
      notifyListeners(); // 💡 isAuthenticated가 false가 되어 MainWrapper가 LoginScreen으로 전환됨
    }
  }

  /// 🔄 닉네임 업데이트 (서버 저장 및 로컬 상태 갱신)
  Future<void> updateNickname(String newName) async {
    if (_user == null) return;

    // 1. 서버 API 호출 [cite: 2026-02-17]
    final bool isSuccess = await _authService.updateNicknameOnServer(newName);

    if (isSuccess) {
      // 2. 서버 저장 성공 시, 로컬 UserModel 객체 교체 [cite: 2026-02-20]
      _user = UserModel(
        userId: _user!.userId,
        email: _user!.email,
        nickname: newName, // 새 닉네임 반영
        socialId: _user!.socialId,
        provider: _user!.provider,
        isNotificationEnabled: _user!.isNotificationEnabled,
        notificationTime: _user!.notificationTime,
        maxSitesLimit: _user!.maxSitesLimit,
        maxKeywordsLimit: _user!.maxKeywordsLimit
      );

      // 3. UI 갱신 알림 [cite: 2026-02-17]
      notifyListeners();
      debugPrint("✅ 닉네임 서버 동기화 완료: $newName");
    } else {
      throw Exception("서버 통신 실패로 닉네임을 변경하지 못했습니다.");
    }
  }

  /// 🚨 회원탈퇴 실행
  Future<bool> deleteAccount() async {
    _setLoading(true);
    try {
      // 1. AuthService를 통해 서버에 회원탈퇴 API 요청
      // (주의: AuthService에 deleteAccount() 메서드가 구현되어 있어야 합니다)
      final bool isSuccess = await _authService.deleteAccount();

      if (isSuccess) {
        // 2. 서버 탈퇴 성공 시, 구글 소셜 로그인 세션도 함께 종료
        await _authService.signOut();

        // 3. 로컬 유저 상태 초기화
        _user = null;
        debugPrint("✅ 회원탈퇴 완료 및 로컬 데이터 초기화");
        return true;
      }
      return false;
    } catch (e) {
      debugPrint("❌ 회원탈퇴 중 오류 발생: $e");
      return false;
    } finally {
      _setLoading(false);
      notifyListeners(); // 상태 변경을 UI에 알림
    }
  }

}