import 'package:flutter/material.dart';
import '../settings_wrapper.dart'; // 프로젝트 구조에 맞는 경로로 확인하세요.

class HowToPayScreen extends StatelessWidget {
  const HowToPayScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return SettingsWrapper(
      title: "결제 및 구독",
      body: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
        children: [
          _buildInfoCard(),
          const SizedBox(height: 32),
          _buildSectionTitle("구독 플랜 안내"),
          _buildPlanTile(
            title: "베이직 (무료)",
            price: "₩0 / 월",
            description: "최대 10개의 사이트 구독 및 키워드 알림 제공",
            isHighlight: false,
          ),
          _buildPlanTile(
            title: "프리미엄 (유료)",
            price: "₩2,900 / 월",
            description: "무제한 사이트 구독, 광고 제거 및 우선 알림 혜택",
            isHighlight: true,
          ),
          const SizedBox(height: 32),
          _buildSectionTitle("환불 및 정기결제 해지"),
          _buildPolicyText(
              "• 정기결제 해지는 앱 내 '설정 > 구독 관리'에서 언제든 가능합니다.\n"
                  "• 결제 후 7일 이내에 서비스 이용 내역이 없는 경우 전액 환불이 가능합니다.\n"
                  "• 스토어(Google/Apple) 결제 건은 각 스토어의 환불 정책을 따릅니다."
          ),
        ],
      ),
    );
  }

  // 상단 안내 카드
  Widget _buildInfoCard() {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.blueAccent.withOpacity(0.05),
        borderRadius: BorderRadius.circular(15),
        border: Border.all(color: Colors.blueAccent.withOpacity(0.1)),
      ),
      child: const Row(
        children: [
          Icon(Icons.stars_rounded, color: Colors.blueAccent, size: 40),
          const SizedBox(width: 16),
          Expanded(
            child: Text(
              "프리미엄 멤버십으로 더욱 강력한 공지 필터링을 경험하세요!",
              style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold, height: 1.4),
            ),
          ),
        ],
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

  // 플랜 항목 위젯
  Widget _buildPlanTile({
    required String title,
    required String price,
    required String description,
    required bool isHighlight,
  }) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: isHighlight ? Colors.white : Colors.grey[50],
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isHighlight ? Colors.blueAccent : Colors.grey[200]!,
          width: isHighlight ? 2 : 1,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
              Text(price, style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.bold,
                color: isHighlight ? Colors.blueAccent : Colors.black,
              )),
            ],
          ),
          const SizedBox(height: 8),
          Text(description, style: TextStyle(fontSize: 13, color: Colors.grey[600])),
        ],
      ),
    );
  }

  Widget _buildPolicyText(String text) {
    return Text(
      text,
      style: TextStyle(fontSize: 14, color: Colors.grey[700], height: 1.6),
    );
  }
}