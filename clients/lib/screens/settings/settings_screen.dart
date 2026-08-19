import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../../providers/auth_provider.dart';
import 'help/help_manager_screen.dart';
import 'keyword/keyword_manager_screen.dart';
import 'notification/notification_manager_screen.dart';

// 새롭게 추가된 Provider 및 모델 임포트
import '../../providers/settings_provider.dart';
import '../../providers/notice_provider.dart';
import '../../providers/favorite_provider.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});


  Future<void> _navigateToSubScreen(BuildContext context, Widget screen) async {
    final int? targetIndex = await Navigator.push<int>(
      context,
      PageRouteBuilder(
        transitionDuration: const Duration(milliseconds: 100),
        reverseTransitionDuration: const Duration(milliseconds: 100),
        pageBuilder: (context, animation, secondaryAnimation) => screen,
        transitionsBuilder: (context, animation, secondaryAnimation, child) {
          return FadeTransition(opacity: animation, child: child);
        },
      ),
    );

    if (targetIndex != null && targetIndex != 4) {
      context.read<NoticeProvider>().setSelectedIndex(targetIndex);
    }
  }

  void _showLogoutDialog(BuildContext context, SettingsProvider settingsProv) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('로그아웃'),
        content: const Text('정말 로그아웃 하시겠습니까?\n로그아웃 시 계정 연결이 해제됩니다.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('취소', style: TextStyle(color: Colors.grey)),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(context); // 다이얼로그 닫기
              context.read<AuthProvider>().signOut(settingsProv); // 로그아웃 실행
            },
            child: const Text('확인', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );
  }

  void _showEditNicknameDialog(BuildContext context) {
    // 💡 초기값으로 현재 닉네임을 넣어주면 사용자가 수정하기 더 편함
    final TextEditingController controller = TextEditingController(
        text: context.read<AuthProvider>().nickname == '로그인 필요'
            ? ''
            : context.read<AuthProvider>().nickname
    );

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('닉네임 변경'),
        content: TextField(
          controller: controller,
          maxLength: 20, // 💡 DB varchar(20)에 맞춘 글자 수 제한 [cite: 2026-02-20]
          maxLengthEnforcement: MaxLengthEnforcement.enforced, // 20자 초과 입력 차단
          decoration: const InputDecoration(
            hintText: '새로운 닉네임을 입력하세요',
            helperText: '최대 20자까지 입력 가능합니다.', // 사용자 안내 메시지
            suffixIcon: Icon(Icons.abc),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('취소'),
          ),
          TextButton(
            onPressed: () async {
              final String trimmedName = controller.text.trim();

              // 💡 유효성 검사: 비어있지 않고 20자 이하인지 최종 확인
              if (trimmedName.isNotEmpty && trimmedName.length <= 20) {
                await context.read<AuthProvider>().updateNickname(trimmedName);
                if (context.mounted) Navigator.pop(context);
              }
            },
            child: const Text('변경'),
          ),
        ],
      ),
    );
  }

  void _showWithdrawDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (BuildContext context) {
        return AlertDialog(
          title: const Text('회원탈퇴'),
          content: const Text(
            '정말 탈퇴하시겠습니까?\n탈퇴 시 저장된 모든 공지사항과 키워드 설정이 즉시 삭제되며 복구할 수 없습니다.',
            style: TextStyle(fontSize: 14),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('취소'),
            ),
            TextButton(
              onPressed: () async {
                Navigator.pop(context); // 다이얼로그 닫기

                // AuthProvider를 통해 탈퇴 로직 실행
                final authProvider = context.read<AuthProvider>();
                final bool success = await authProvider.deleteAccount();

                if (success && context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('회원탈퇴가 완료되었습니다. 이용해 주셔서 감사합니다.')),
                  );
                  // AuthProvider 내부에서 _user를 null로 만들고 notifyListeners()를 호출하므로,
                  // App의 MainWrapper가 이를 감지해 자동으로 로그인 화면으로 이동시킬 것입니다.
                } else if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('회원탈퇴 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.')),
                  );
                }
              },
              child: const Text('탈퇴하기', style: TextStyle(color: Colors.red)),
            ),
          ],
        );
      },
    );
  }

  void _shareInviteLink(BuildContext context) {
    // 1. 유저 ID 가져오기
    final user = context.read<AuthProvider>().user;
    if (user == null) return;

    // 2. SettingsProvider를 통해 로직 실행
    context.read<SettingsProvider>().shareInviteLink(user.userId);
  }

  @override
  Widget build(BuildContext context) {
    final settingsProv = context.watch<SettingsProvider>();
    final authProvider = context.watch<AuthProvider>();
    // 💡 이제 favoriteProv 데이터를 직접 넘기지 않으므로 watch 대신 read를 쓰거나 생략 가능하지만,
    // 추후 설정 창에 즐겨찾기 관련 요약 정보를 띄울 수도 있으므로 유지해도 무방합니다.
    final favoriteProv = context.watch<FavoriteProvider>();

    final currentSettings = settingsProv.settings;

    return ListView(
      children: [
        const SizedBox(height: 20),
        // 프로필 섹션 (기존 유지)
        ListTile(
          leading: const CircleAvatar(
            backgroundColor: Colors.blueGrey,
            child: Icon(Icons.person, color: Colors.white),
          ),
          title: Text(
              authProvider.nickname,
              style: const TextStyle(fontWeight: FontWeight.bold)
          ),
          trailing: IconButton(
            icon: const Icon(Icons.edit_outlined, size: 20),
            onPressed: () => _showEditNicknameDialog(context),
          ),
        ),
        const Divider(),

        // 1. 알림 설정
        _buildSettingsItem(
          icon: Icons.notifications_active_outlined,
          title: '알림 설정',
          trailing: Text(
            currentSettings.isNotificationEnabled ? "ON" : "OFF",
            style: TextStyle(color: currentSettings.isNotificationEnabled ? Colors.blue : Colors.grey),
          ),
          onTap: () => _navigateToSubScreen(context, const NotificationManagerScreen()),
        ),

        // 2. 키워드 관리 (리팩토링 포인트! 🚀)
        _buildSettingsItem(
          icon: Icons.key_outlined,
          title: '키워드 관리',
          subtitle: "폴더별 자동 분류 키워드를 설정합니다.", // 💡 사용자 이해를 돕는 자막 추가
          onTap: () => _navigateToSubScreen(
            context,
            const KeywordManagerScreen(), // 💡 파라미터 없이 깔끔하게 호출! [cite: 2026-02-21]
          ),
        ),

        // 3. 도움말
        _buildSettingsItem(
          icon: Icons.help_outline,
          title: '도움말 및 지원',
          onTap: () => _navigateToSubScreen(context, const HelpManagerScreen()),
        ),

        // 💡 신규 추가: 친구 초대하기
        // _buildSettingsItem(
        //   icon: Icons.card_giftcard,
        //   title: '친구 초대하고 한도 늘리기',
        //   onTap: () => _shareInviteLink(context),
        // ),

        const Divider(),

        // 4. 로그아웃
        _buildSettingsItem(
          icon: Icons.logout,
          iconColor: Colors.grey,
          title: '로그아웃',
          textColor: Colors.grey,
          onTap: () => _showLogoutDialog(context, settingsProv),
        ),


        // 6. 버전 정보
        Padding(
          padding: const EdgeInsets.all(16.0),
          child: Text(
            '버전 정보 ${currentSettings.appVersion}',
            style: const TextStyle(color: Colors.grey, fontSize: 12),
            textAlign: TextAlign.center,
          ),
        ),

      ],
    );


  }

  // 💡 subtitle을 지원하도록 위젯 빌더 수정
  Widget _buildSettingsItem({
    required IconData icon,
    required String title,
    required VoidCallback onTap,
    String? subtitle, // 👈 추가
    Widget? trailing,
    Color? textColor,
    Color? iconColor,
  }) {
    return ListTile(
      leading: Icon(icon, color: iconColor ?? Colors.black87),
      title: Text(title, style: TextStyle(color: textColor, fontWeight: FontWeight.w500)),
      subtitle: subtitle != null ? Text(subtitle, style: const TextStyle(fontSize: 12)) : null,
      trailing: trailing ?? const Icon(Icons.chevron_right, size: 20),
      onTap: onTap,
    );

  }
}