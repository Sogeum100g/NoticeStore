import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import '../settings_wrapper.dart'; // 프로젝트 구조에 맞는 경로로 확인하세요.

class HowToUseApplication extends StatelessWidget {
  const HowToUseApplication({super.key});

  void _showExampleDetail(BuildContext context) {
    showGeneralDialog(
      context: context,
      barrierDismissible: true,
      barrierLabel: "Dismiss",
      barrierColor: Colors.black54, // 배경을 어둡게 처리하여 몰입감 향상
      transitionDuration: const Duration(milliseconds: 200),
      pageBuilder: (context, animation, secondaryAnimation) {
        return Center(
          child: Container(
            width: MediaQuery.of(context).size.width * 0.9, // 화면 너비의 90% 사용
            margin: const EdgeInsets.symmetric(vertical: 40),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Material(
              child:Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  // 상단 타이틀
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 16),
                    child: Text(
                      "표준 게시판 구조 예시",
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                        color: Colors.black,
                        decoration: TextDecoration.none, // 기본 텍스트 스타일 제거
                      ),
                    ),
                  ),
                  // 확대된 이미지 영역
                  Flexible(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(8),
                        child: Image.asset(
                          'assets/images/example_site.png',
                          fit: BoxFit.contain, // 전체가 다 보이도록 설정
                        ),
                      ),
                    ),
                  ),
                  // 설명 문구
                  const Padding(
                    padding: EdgeInsets.all(16),
                    child: Text(
                      "※ 위 사진처럼 목록형으로 구성된 게시판 페이지의 주소를 넣으면 됩니다.",
                      style: TextStyle(
                        fontSize: 10,
                        height: 1.4,
                        color: Colors.grey,
                        decoration: TextDecoration.none,
                      ),
                      textAlign: TextAlign.center,
                    ),
                  ),
                  // 닫기 버튼 (검은색 테마 반영)
                  CupertinoButton(
                    child: const Text(
                      "닫기",
                      style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold),
                    ),
                    onPressed: () => Navigator.pop(context),
                  ),
                ],
              )
            ),
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return SettingsWrapper(
      title: "사용 방법",
      body: SelectionArea(
        child: ListView(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
          children: [
            _buildHeader(),
            const SizedBox(height: 30),
            // 설명이 추가된 01번 스텝
            _buildStepItem(
              number: "01",
              title: "사이트 구독",
              description: "하단 탭의 '+(추가)' 버튼을 눌러 원하는 기관의 사이트를 검색하고 구독 목록에 추가하세요."
                  "\n\n브라우저 앱(네이버 앱, 크롬 등)의 '공유하기' 기능을 이용하면 현재 보고 있는 웹사이트를 앱으로 더욱 간편하게 추가할 수 있습니다."
                  "\n\n유튜브 커뮤니티 게시글 등록 방법 : "
                  "사이트 주소를 ｢ https://www.youtube.com/@채널명/posts ｣"
                  "\n으로 직접 등록합니다. 유튜버 채널의 채널명 하단의 "
                  "\n'@채널명' 터치로 복사할 수 있습니다."
                  "\n\n구독된 사이트의 소식들은 오래된 것부터 3개월 뒤 "
                  "\n순차적으로 비활성화됩니다.",
              icon: Icons.add_link_rounded,
              iconColor: Colors.blue,
            ),
            _buildStepItem(
              number: "02",
              title: "키워드 등록",
              description: "즐겨찾기 폴더에 특정 키워드를 설정하면 해당 키워드가 포함된 정보만 모아볼 수 있습니다."
                  "\n\n구독 폴더에서 해당 즐겨찾기 폴더로 이동시키면 설정된 키워드 관련 공지만 일괄적으로 추가됩니다."
                  "\n\n키워드는 즐겨찾기 폴더에서 직접 관리하거나 설정에서 관리할 수 있습니다.",
              icon: Icons.vpn_key_outlined,
              iconColor: Colors.orange,
            ),
            _buildStepItem(
              number: "03",
              title: "맞춤 알림 받기",
              description: "알림 시간을 설정해 두면 새로 게시된 정보에 대해 하루 한 번 푸시 알림을 보내드립니다.",
              icon: Icons.notifications_active_outlined,
              iconColor: Colors.deepPurple,
            ),

            const Divider(height: 30),
            _buildTipSectionWithHeader(context),
          ],
        ),
      )
    );
  }

  // 상단 헤더 섹션
  Widget _buildHeader() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          "중요한 정보를 놓치지 마세요!",
          style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, height: 1.3),
        ),
        const SizedBox(height: 12),
        Text(
          "앱을 효과적으로 사용하는 방법을 알려드립니다.",
          style: TextStyle(fontSize: 14, color: Colors.grey[600]),
        ),
      ],
    );
  }

  // 단계별 항목 위젯
  Widget _buildStepItem({
    required String number,
    required String title,
    required String description,
    required IconData icon,
    required Color iconColor,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 30.0),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start, // 핵심: 모든 요소를 상단 정렬
        children: [
          // 1. 숫자 부분 (너비를 고정하여 정렬 유지)
          SizedBox(
            width: 35,
            child: Text(
              number,
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.bold,
                color: iconColor.withOpacity(0.5),
              ),
            ),
          ),

          // 2. 내용 부분 (Icon + Text)
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 아이콘과 타이틀 정렬
                Row(
                  children: [
                    Icon(icon, size: 20, color: iconColor),
                    const SizedBox(width: 8),
                    Text(
                      title,
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),

                // 설명 텍스트 (줄바꿈 시에도 정렬 유지)
                Text(
                  description,
                  style: TextStyle(
                    fontSize: 14,
                    height: 1.6, // 줄 간격을 조절하여 가독성 향상
                    color: Colors.grey[700],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }


  Widget _buildTipSectionWithHeader(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 1. 섹션 헤더
        const Text(
          "이용 시 참고해 주세요!",
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, height: 1.3),
        ),
        const SizedBox(height: 8),
        Text(
          "수집을 위한 안내 사항입니다.",
          style: TextStyle(fontSize: 14, color: Colors.grey[600]),
        ),
        const SizedBox(height: 16),

        // 2. 팁 박스 컨테이너
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.grey[100],
            borderRadius: BorderRadius.circular(12),
          ),
          child: Column(
            children: [
              // 첫 번째 팁: 키워드 필터링
              // _buildTipItem(
              //   icon: Icons.auto_awesome_rounded, // 더 세련된 반짝이 아이콘으로 변경
              //   iconColor: Colors.orangeAccent,
              //   text: "즐겨찾기 폴더별로 키워드를 다르게 설정하면 내가 원하는 것만 볼 수 있도록 정교한 필터링이 가능합니다.",
              // ),
              // const Padding(
              //   padding: EdgeInsets.symmetric(vertical: 12.0),
              //   child: Divider(height: 1, color: Colors.black12),
              // ),
              // 두 번째 팁: 게시판 규격 및 참고자료
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _buildTipItem(
                    // icon: Icons.account_tree_rounded, // 구조(Hierarchy)를 상징하는 아이콘으로 변경
                    // iconColor: Colors.blueAccent,
                    text: "사이트마다 게시판 구조와 동작 방식이 다르므로, 일부 사이트는 추출이 원활하지 않을 수 있습니다. 문제 발생 시 문의를 통해 알려주시기 바랍니다."
                  ),
                  const SizedBox(height: 12),
                  // 추가된 버튼 및 이미지 영역
                  Padding(
                    padding: const EdgeInsets.only(left: 0), // 아이콘 너비만큼 들여쓰기
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        // 1. 참고자료 확인 버튼
                        CupertinoButton(
                          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                          color: const Color(0xFFF0F4F8), // 부드러운 블루그레이 톤
                          borderRadius: BorderRadius.circular(8),
                          onPressed: () {
                            // 버튼 클릭 시 상세 가이드 팝업 노출
                            _showExampleDetail(context);
                          },
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const Text(
                                "참고자료 확인하기",
                                style: TextStyle(
                                  color: Color(0xFF007AFF), // Cupertino Blue
                                  fontSize: 12,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                              const SizedBox(width: 4),
                              Icon(CupertinoIcons.chevron_right, size: 12, color: const Color(0xFF007AFF)),
                            ],
                          ),
                        ),
                        const SizedBox(height: 12),

                        // 2. 게시판 구조 예시 이미지 프리뷰
                        GestureDetector(
                          onTap: () => _showExampleDetail(context), // 이미지 클릭 시에도 상세 보기
                          child: Container(
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(12),
                              border: Border.all(color: Colors.black12), // 이미지 경계 구분
                            ),
                            child: ClipRRect(
                              borderRadius: BorderRadius.circular(11),
                              child: Image.asset(
                                'assets/images/example_site.png',
                                width: double.infinity,
                                height: 160,
                                fit: BoxFit.cover,
                                // 이미지 로드 실패 시 가이드 텍스트 표시
                                errorBuilder: (context, error, stackTrace) => Container(
                                  height: 120,
                                  color: const Color(0xFFF8F9FA),
                                  child: Column(
                                    mainAxisAlignment: MainAxisAlignment.center,
                                    children: [
                                      Icon(CupertinoIcons.photo, color: Colors.grey[400]),
                                      const SizedBox(height: 8),
                                      const Text(
                                        "표준 게시판 구조 예시",
                                        style: TextStyle(fontSize: 20, color: Colors.grey),
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(height: 4),
                        const Text(
                          "※ 위 사진처럼 목록형으로 구성된 게시판 페이지의 주소를 넣으면 됩니다.",
                          style: TextStyle(fontSize: 12, color: Colors.grey),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }

  // 개별 항목을 만드는 헬퍼 위젯
  Widget _buildTipItem({
    // required IconData icon,
    // required Color iconColor,
    required String text,
  }) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start, // 아이콘을 텍스트 첫 줄에 고정
      children: [
        // Icon(icon, color: iconColor, size: 22),
        const SizedBox(width: 12),
        Expanded(
          child: Text(
            text,
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w500,
              height: 1.5,
              color: Colors.grey[600],
            ),
          ),
        ),
      ],
    );
  }
}