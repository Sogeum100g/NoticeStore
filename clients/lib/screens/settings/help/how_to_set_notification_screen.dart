import 'package:flutter/material.dart';
import '../settings_wrapper.dart'; // 프로젝트 구조에 맞는 경로로 확인하세요.

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
          _buildSectionTitle("푸시 알림 활성화 및 시간 설정"),
          _buildInstructionStep(
            icon: Icons.toggle_on_outlined,
            title: "일일 공지 알림 스위치",
            description: "스위치를 켜면 매일 정해진 시간에 새로운 공지사항을 확인하여 푸시 알림을 보내드립니다. 새로운 내용이 없을 경우 알림이 전송되지 않습니다.",
          ),
          _buildInstructionStep(
            icon: Icons.access_time,
            title: "알림 시간 선택",
            description: "원하는 시간을 클릭하여 알림을 받을 시각을 자유롭게 변경할 수 있습니다. (기본값 오후 6:00)",
          ),
          const Divider(height: 48),
          _buildSectionTitle("알림이 오지 않나요?"),
          _buildWarningBox(
              "기기 자체 설정에서 '센트리피전' 앱의 알림 권한이 허용되어 있는지 확인해 주세요. 시스템 알림이 꺼져 있으면 앱 설정과 관계없이 알림을 받을 수 없습니다."
          ),
        ],
      ),
    );
  }

  // 상단 시각적 요소 (사진의 느낌을 살린 아이콘 조합)
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
            Icon(Icons.notifications_active_outlined, size: 50, color: Colors.deepPurple),
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

  Widget _buildInstructionStep({required IconData icon, required String title, required String description}) {
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
                Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
                const SizedBox(height: 6),
                Text(
                  description,
                  style: TextStyle(fontSize: 14, color: Colors.grey[700], height: 1.5),
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