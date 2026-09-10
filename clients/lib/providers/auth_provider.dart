import 'package:clients/providers/settings_provider.dart';
import 'package:flutter/material.dart';

import '../models/user_model.dart';
import '../services/auth_service.dart';
import '../services/notification_service.dart';
import 'notice_provider.dart';

class AuthProvider with ChangeNotifier {
  final AuthService _authService = AuthService();
  UserModel? _user;
  bool _isLoading = true;

  UserModel? get user => _user;
  bool get isLoading => _isLoading;
  bool get isAuthenticated => _user != null;

  String get nickname {
    if (_user == null) return '로그인 필요';

    if (_user!.nickname != null && _user!.nickname!.trim().isNotEmpty) {
      return _user!.nickname!;
    }

    if (_user!.email != null && _user!.email!.contains('@')) {
      return _user!.email!.split('@')[0];
    }

    return '사용자';
  }

  /// 구글 로그인 실행 및 데이터 동기화
  Future<bool> signInWithGoogle(
    NoticeProvider noticeProv,
    SettingsProvider settingsProv, {
    String? referrerCode,
  }) async {
    _setLoading(true);

    try {
      final user = await _authService.signInWithGoogle(
        referrerCode: referrerCode,
      );

      if (user != null) {
        _user = user;

        settingsProv.syncFromUserModel(user);

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

  /// 앱 실행 시 자동 로그인 체크
  Future<void> checkAutoLogin(
    NoticeProvider noticeProv,
    SettingsProvider settingsProv,
  ) async {
    Future.microtask(() => _setLoading(true));

    try {
      final user = await _authService.trySilentSignIn();

      if (user != null) {
        final latestUser = await _authService.fetchUserProfile();
        _user = latestUser ?? user;
        settingsProv.syncFromUserModel(_user!);
        notifyListeners();

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
    if (_isLoading == value) return;
    _isLoading = value;
    notifyListeners();
  }

  Future<void> signOut(SettingsProvider settingsProv) async {
    _setLoading(true);
    try {
      await _authService.signOut();

      settingsProv.resetSettings();

      _user = null;
      debugPrint("✅ 로그아웃 완료 및 유저 정보 초기화");
    } catch (e) {
      debugPrint("❌ 로그아웃 중 오류 발생: $e");
    } finally {
      _setLoading(false);
      notifyListeners();
    }
  }

  /// 닉네임 업데이트 (서버 저장 및 로컬 상태 갱신)
  Future<void> updateNickname(String newName) async {
    if (_user == null) return;

    final bool isSuccess = await _authService.updateNicknameOnServer(newName);

    if (isSuccess) {
      _user = UserModel(
        userId: _user!.userId,
        email: _user!.email,
        nickname: newName,
        socialId: _user!.socialId,
        provider: _user!.provider,
        isNotificationEnabled: _user!.isNotificationEnabled,
        maxSitesLimit: _user!.maxSitesLimit,
        maxKeywordsLimit: _user!.maxKeywordsLimit,
      );

      notifyListeners();
      debugPrint("✅ 닉네임 서버 동기화 완료: $newName");
    } else {
      throw Exception("서버 통신 실패로 닉네임을 변경하지 못했습니다.");
    }
  }

  /// 회원탈퇴 실행
  Future<bool> deleteAccount() async {
    _setLoading(true);
    try {
      final bool isSuccess = await _authService.deleteAccount();

      if (isSuccess) {
        await _authService.signOut();

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
      notifyListeners();
    }
  }
}
