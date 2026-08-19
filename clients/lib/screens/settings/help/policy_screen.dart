import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import '../settings_wrapper.dart';

class PolicyScreen extends StatelessWidget {
  const PolicyScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return SettingsWrapper(
      title: "정책 및 보안 안내",
      body: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
        children: [
          _buildPolicyHeader(),
          const SizedBox(height: 20),
          const Divider(height: 10, thickness: 1),
          const SizedBox(height: 20),

          // 1. 데이터 수집 정책
          _buildPolicyStepItem(
            number: "01",
            title: "데이터 수집 및 Robots.txt 정책",
            description: "센트리피전는 각 웹사이트의 robots.txt 규약을 엄격히 준수합니다. 수집 허용된 범위 내에서만 정보를 가져오며, 서버 부하를 방지하기 위해 요청에 간격을 두고 있습니다.",
          ),

          // 2. 보안 정책
          _buildPolicyStepItem(
            number: "02",
            title: "보안 및 비정상 접근 방지",
            description: "사용자의 안전한 서비스 이용을 위해 모든 데이터 통신은 암호화(SSL) 처리됩니다. 특정 사이트에 대한 과도한 트래픽 집중을 방지하여 해당 서비스의 안정성을 해치지 않는 범위 내에서만 동작합니다.",
          ),

          // 3. 계정 보안
          _buildPolicyStepItem(
            number: "03",
            title: "로그인 및 계정 보안",
            description: "로그인이 필요한 서비스의 경우 수집이 제한됩니다.",
          ),

          // 4. 법적 책임 및 고지
          _buildPolicyStepItem(
            number: "04",
            title: "법적 책임 및 고지",
            description: "본 앱은 공개된 공지사항 정보의 효율적인 전달을 목적으로 하며, 저작권법 및 관련 법령을 준수합니다.",
          ),

        ],
      ),
    );
  }

  Widget _buildPolicyHeader() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          "수집 정책 및 보안 관련 고지",
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, height: 1.3),
        ),
        const SizedBox(height: 12),
        Text(
          "데이터를 처리하고 보호하는 기준을 안내드립니다.",
          style: TextStyle(fontSize: 14, color: Colors.grey[600]),
        ),
      ],
    );
  }

  // 정책 항목 위젯 - 아이콘과 숫자 색상을 검은색으로 고정
  Widget _buildPolicyStepItem({
    required String number,
    required String title,
    required String description,
  }) {
    // 모든 포인트 컬러를 검은색 계열로 설정
    const Color primaryBlack = Colors.black87;
    const Color secondaryBlack = Colors.black54;

    return Padding(
      padding: const EdgeInsets.only(bottom: 30.0),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 숫자 영역 (검은색 투명도 조절)
          SizedBox(
            width: 35,
            child: Text(
              number,
              style: const TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.bold,
                color: secondaryBlack, // 차분한 검은색
              ),
            ),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      title,
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                        color: primaryBlack,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                Text(
                  description,
                  style: TextStyle(
                    fontSize: 14,
                    height: 1.6,
                    color: Colors.grey[800], // 본문은 가독성을 위해 짙은 회색
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}