import 'package:flutter/material.dart';
import 'package:provider/provider.dart'; // 💡 Provider 패키지 임포트
import '../../../providers/auth_provider.dart';

import '../settings_wrapper.dart';
import 'how_to_pay_screen.dart';
import 'how_to_set_notification_screen.dart';
import 'how_to_use_application.dart';
import 'policy_screen.dart';
import 'recommend_site_screen.dart';

// 💡 문의 관련 화면 임포트
import 'inquiry_submit_screen.dart';
import 'inquiry_history_screen.dart';

class HelpManagerScreen extends StatelessWidget {
  const HelpManagerScreen({super.key});

  // 1. 공통 내비게이션 함수 적용: 하단 탭 인덱스 전달 기능 포함
  Future<void> _navigateToSubScreen(BuildContext context, Widget screen) async {
    final int? targetIndex = await Navigator.push<int>(
      context,
      PageRouteBuilder(
        transitionDuration: const Duration(milliseconds: 100),
        pageBuilder: (context, animation, secondaryAnimation) => screen,
        transitionsBuilder: (context, animation, secondaryAnimation, child) {
          return FadeTransition(opacity: animation, child: child);
        },
      ),
    );

    // 결과값(index)이 있고, 현재 '설정' 탭(4)이 아닐 때 부모에게 팝하여 전달
    if (targetIndex != null && targetIndex != 4) {
      if (context.mounted) {
        Navigator.pop(context, targetIndex);
      }
    }
  }

  // 🚨 회원탈퇴 다이얼로그 및 실행 로직 추가
  void _showWithdrawDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (BuildContext dialogContext) {
        return AlertDialog(
          title: const Text('회원탈퇴'),
          content: const Text(
            '정말 탈퇴하시겠습니까?\n탈퇴 시 저장된 모든 공지사항과 키워드 설정이 즉시 삭제되며 복구할 수 없습니다.',
            style: TextStyle(fontSize: 14),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('취소'),
            ),
            TextButton(
              onPressed: () async {
                Navigator.pop(dialogContext); // 다이얼로그 먼저 닫기

                // AuthProvider를 통해 탈퇴 API 호출
                final authProvider = context.read<AuthProvider>();
                final bool success = await authProvider.deleteAccount();

                if (success && context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('회원탈퇴가 완료되었습니다. 이용해 주셔서 감사합니다.')),
                  );
                  // 💡 참고: Provider의 상태가 변경되면서 MainWrapper에 의해 로그인 화면으로 자동 전환됩니다.
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

  @override
  Widget build(BuildContext context) {
    return SettingsWrapper(
      title: "도움말 및 지원",
      body: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 20.0, vertical: 10.0),
        children: [
          const SizedBox(height: 20),
          _buildSectionTitle('자주 묻는 질문 (FAQ)'),
          _buildHelpTile(context, Icons.help_outline, '사용 방법'),
          _buildHelpTile(context, Icons.notifications_active_outlined, '알림 설정'),
          _buildHelpTile(context, Icons.add_chart_outlined, '사이트 추천(예시)'),
          _buildHelpTile(context, Icons.error_outline_sharp, '정책 및 보안 안내'),

          const Padding(
            padding: EdgeInsets.symmetric(vertical: 24.0),
            child: Divider(thickness: 1, color: Color(0xFFF0F0F0)),
          ),

          _buildSectionTitle('문의하기'),
          _buildContactTile(
              context,
              Icons.live_help_outlined,
              '문의하기',
              '작동하지 않는 사이트 등 이용 중 불편한 점이나 건의사항을 알려주세요.',
              const InquirySubmitScreen()
          ),
          // _buildContactTile(
          //     context,
          //     Icons.history,
          //     '나의 문의 내역',
          //     '내가 남긴 문의와 답변을 확인합니다.',
          //     const InquiryHistoryScreen()
          // ),

          // ---------------------------------------------------
          // 🚀 신규 추가: 계정 관리 섹션 (회원탈퇴)
          // ---------------------------------------------------
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 24.0),
            child: Divider(thickness: 1, color: Color(0xFFF0F0F0)),
          ),

          _buildSectionTitle('계정 관리'),
          _buildAccountActionTile(context),

          const SizedBox(height: 20),
        ],
      ),
    );
  }

  Widget _buildSectionTitle(String title) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16.0),
      child: Text(
        title,
        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.black87),
      ),
    );
  }

  Widget _buildHelpTile(BuildContext context, IconData icon, String title) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          color: const Color(0xFFF5F5F7),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Icon(icon, color: Colors.black54, size: 22),
      ),
      title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 16)),
      trailing: const Icon(Icons.chevron_right, size: 18, color: Colors.grey),
      onTap: () {
        Widget nextScreen;
        switch (title) {
          case '사용 방법':
            nextScreen = const HowToUseApplication();
            break;
          case '알림 설정':
            nextScreen = const HowToSetNotificationScreen();
            break;
          case '사이트 추천(예시)':
            nextScreen = const RecommendSiteScreen();
            break;
          case '정책 및 보안 안내':
            nextScreen = const PolicyScreen();
            break;
          default:
            return;
        }
        _navigateToSubScreen(context, nextScreen);
      },
    );
  }

  Widget _buildContactTile(BuildContext context, IconData icon, String title, String subtitle, Widget targetScreen) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          color: const Color(0xFFF5F5F7),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Icon(icon, color: Colors.black54, size: 22),
      ),
      title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 16)),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 4.0),
        child: Text(subtitle, style: TextStyle(color: Colors.grey[600], fontSize: 13)),
      ),
      trailing: const Icon(Icons.chevron_right, size: 18, color: Colors.grey),
      onTap: () {
        _navigateToSubScreen(context, targetScreen);
      },
    );
  }

  // 🚀 회원탈퇴 전용 타일 위젯 (디자인 통일성을 위해 별도 분리)
  Widget _buildAccountActionTile(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          color: const Color(0xFFF5F5F7),
          borderRadius: BorderRadius.circular(10),
        ),
        child: const Icon(Icons.person_remove_outlined, color: Colors.grey, size: 22),
      ),
      title: const Text(
          '회원탈퇴',
          style: TextStyle(fontWeight: FontWeight.w500, fontSize: 16, color: Colors.grey)
      ),
      trailing: const Icon(Icons.chevron_right, size: 18, color: Colors.grey),
      onTap: () => _showWithdrawDialog(context),
    );
  }
}