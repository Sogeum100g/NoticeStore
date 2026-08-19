import 'package:clients/providers/settings_provider.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/auth_provider.dart';
import '../../providers/notice_provider.dart';
import '../../services/preferences_service.dart'; // 💡 추가: 저장된 추천인 코드를 가져오기 위해 임포트

class LoginScreen extends StatelessWidget {
  const LoginScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final authProvider = context.watch<AuthProvider>();

    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // 1. 앱 로고 및 환영 메시지
              Image.asset(
                'assets/images/pigeon_cutout.png',
                width: 80,
                height: 80,
                fit: BoxFit.contain,
              ),
              const SizedBox(height: 24),
              Text(
                '센트리피전',
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 24),

              // 2. 구글 소셜 로그인 버튼
              SizedBox(
                height: 48,
                child: OutlinedButton(
                  onPressed: authProvider.isLoading
                      ? null
                      : () => _handleLogin(context, 'google'),
                  style: OutlinedButton.styleFrom(
                    backgroundColor: Colors.white,
                    foregroundColor: const Color(0xFF3C4043),
                    side: const BorderSide(color: Color(0xFFDADCE0)),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(4),
                    ),
                    elevation: 0,
                    padding: EdgeInsets.zero,
                  ),
                  child: Stack(
                    alignment: Alignment.centerLeft,
                    children: [
                      Padding(
                        padding: const EdgeInsets.only(left: 12.0),
                        child: Image.asset(
                          'assets/signin-assets/Android/png@4x/light/android_light_rd_na@4x.png',
                          height: 24,
                          width: 24,
                        ),
                      ),
                      const Center(
                        child: Text(
                          'Continue with Google',
                          style: TextStyle(
                            color: Color(0xFF3C4043),
                            fontSize: 16,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),

              // 3. 로딩 인디케이터
              if (authProvider.isLoading)
                const Padding(
                  padding: EdgeInsets.only(top: 20),
                  child: Center(child: CircularProgressIndicator()),
                ),
            ],
          ),
        ),
      ),
    );
  }

  /// 🔐 로그인 처리 로직
  Future<void> _handleLogin(BuildContext context, String provider) async {
    bool success = false;
    final messenger = ScaffoldMessenger.of(context);

    if (provider == 'google') {
      final authProv = context.read<AuthProvider>();
      final noticeProv = context.read<NoticeProvider>();
      final settingsProv = context.read<SettingsProvider>();

      // 1. 딥링크를 통해 임시 저장해둔 추천인 코드를 불러옵니다.
      String? inviteCode = await PreferencesService.getReferrerCode();

      // 2. AuthProvider의 로그인 함수 호출 시 추천인 코드를 함께 넘깁니다.
      success = await authProv.signInWithGoogle(noticeProv, settingsProv, referrerCode: inviteCode);

      // 3. 로그인이 성공적으로 완료되면 중복 사용을 막기 위해 코드를 지워줍니다.
      if (success) {
        await PreferencesService.clearReferrerCode();
      }
    }

    if (!success && context.mounted) {
      messenger.clearSnackBars();
      messenger.showSnackBar(
        const SnackBar(content: Text('로그인에 실패했습니다. 다시 시도해주세요.')),
      );
    }
  }
}