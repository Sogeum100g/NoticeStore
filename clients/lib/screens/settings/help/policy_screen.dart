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

          _buildPolicyStepItem(
            number: "01",
            title: "보안 및 비정상 접근 방지",
            description: "사용자의 안전한 서비스 이용을 위해 모든 데이터 통신은 암호화(SSL) 처리됩니다. 특정 사이트에 대한 과도한 트래픽 집중을 방지하여 해당 서비스의 안정성을 해치지 않는 범위 내에서 동작합니다.",
          ),

          _buildPolicyStepItem(
            number: "02",
            title: "로그인 및 계정 보안",
            description: "로그인이 필요하지 않은 공개된 사이트에 한해서 접근 가능합니다.",
          ),

          _buildPolicyStepItem(
            number: "03",
            title: "법적 책임 및 고지",
            description: "본 애플리케이션은 공개된 공지사항 정보의 효율적인 전달을 목적으로 하며, 저작권법 및 관련 법령을 준수합니다.",
          ),
          _buildPolicyStepItem(
            number: "04",
            title: "사이트 등록의 유효 범위",
            description: "유효하지 않은 사이트 주소를 등록할 경우 동작하지 않습니다. 간혹 일반적인 사이트이지만 등록되지 않을 경우 \"문의하기\"를 통해 문의바랍니다."
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

  Widget _buildPolicyStepItem({
    required String number,
    required String title,
    required String description,
  }) {
    const Color primaryBlack = Colors.black87;
    const Color secondaryBlack = Colors.black54;

    return Padding(
      padding: const EdgeInsets.only(bottom: 30.0),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 35,
            child: Text(
              number,
              style: const TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.bold,
                color: secondaryBlack,
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
                    color: Colors.grey[800],
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
