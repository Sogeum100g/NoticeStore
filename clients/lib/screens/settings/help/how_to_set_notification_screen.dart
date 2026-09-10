import 'package:flutter/material.dart';

import '../settings_wrapper.dart';

class HowToSetNotificationScreen extends StatelessWidget {
  const HowToSetNotificationScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return SettingsWrapper(
      title: "알림 설정",
      body: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
        children: [
          _buildIllustration(),
          const SizedBox(height: 32),
          _buildSectionTitle("푸시 알림 활성화 및 구독 선택"),
          _buildInstructionStep(
            icon: Icons.toggle_on_outlined,
            title: "전체 푸시 알림 스위치",
            description: "모든 구독의 푸시 알림을 한 번에 켜거나 끕니다. 개별 구독 선택값은 그대로 보존됩니다.",
          ),
          _buildInstructionStep(
            icon: Icons.access_time,
            title: "구독별 알림 선택",
            description:
                "구독 화면의 폴더 타일 오른쪽 종 아이콘을 눌러 새 소식 알림을 받을 구독을 선택할 수 있습니다.",
          ),
          const Divider(height: 48),
          _buildSectionTitle("알림이 오지 않나요?"),
          _buildWarningBox(
            "기기 자체 설정에서 '공지저장소' 앱의 알림 권한이 허용되어 있는지 확인해 주세요. 시스템 알림이 꺼져 있으면 앱 설정과 관계없이 알림을 받을 수 없습니다.",
          ),
        ],
      ),
    );
  }

  Widget _buildIllustration() {
    return Center(
      child: Container(
        padding: const EdgeInsets.all(30),
        decoration: BoxDecoration(
          color: Colors.deepPurple.withOpacity(0.05),
          shape: BoxShape.circle,
        ),
        child: const Stack(
          alignment: Alignment.topRight,
          children: [
            Icon(
              Icons.notifications_active_outlined,
              size: 50,
              color: Colors.deepPurple,
            ),
            CircleAvatar(
              radius: 10,
              backgroundColor: Colors.redAccent,
              child: Icon(Icons.priority_high, size: 14, color: Colors.white),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSectionTitle(String title) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16.0),
      child: Text(
        title,
        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
      ),
    );
  }

  Widget _buildInstructionStep({
    required IconData icon,
    required String title,
    required String description,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 24.0),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: Colors.black87, size: 24),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  description,
                  style: TextStyle(
                    fontSize: 14,
                    color: Colors.grey[700],
                    height: 1.5,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildWarningBox(String text) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.amber.withOpacity(0.1),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.amber.withOpacity(0.3)),
      ),
      child: Text(
        text,
        style: const TextStyle(fontSize: 13, color: Colors.brown, height: 1.5),
      ),
    );
  }
}
