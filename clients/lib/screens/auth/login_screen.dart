import 'package:clients/providers/settings_provider.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/auth_provider.dart';
import '../../providers/notice_provider.dart';
import '../../services/preferences_service.dart';

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
              Image.asset(
                'assets/images/pigeon_cutout.png',
                width: 80,
                height: 80,
                fit: BoxFit.contain,
              ),
              const SizedBox(height: 24),
              Text(
                '공지저장소',
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 24),

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

  /// 로그인 처리 로직
  Future<void> _handleLogin(BuildContext context, String provider) async {
    bool success = false;
    final messenger = ScaffoldMessenger.of(context);

    if (provider == 'google') {
      final authProv = context.read<AuthProvider>();
      final noticeProv = context.read<NoticeProvider>();
      final settingsProv = context.read<SettingsProvider>();

      String? inviteCode = await PreferencesService.getReferrerCode();

      success = await authProv.signInWithGoogle(noticeProv, settingsProv, referrerCode: inviteCode);

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
