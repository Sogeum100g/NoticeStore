import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/settings_provider.dart';

class SettingsWrapper extends StatelessWidget {
  final String title;
  final Widget body;

  const SettingsWrapper({
    super.key,
    required this.title,
    required this.body,
  });

  @override
  Widget build(BuildContext context) {
    // 💡 SettingsProvider를 구독하여 현재 테마 상태를 파악하네.
    final isDarkMode = context.watch<SettingsProvider>().settings.isDarkMode;

    // 테마에 따른 동적 색상 설정
    final bgColor = isDarkMode ? const Color(0xFF121212) : Colors.white;
    final textColor = isDarkMode ? Colors.white : Colors.black;
    final iconColor = isDarkMode ? Colors.white70 : Colors.black87;

    return Scaffold(
      backgroundColor: bgColor,
      // 1. 서비스 로고가 고정된 AppBar
      appBar: AppBar(
        automaticallyImplyLeading: false,
        backgroundColor: bgColor,
        surfaceTintColor: Colors.transparent, // 스크롤 시 색상 변함 방지
        elevation: 0.5, // 얇은 구분선 효과
        title: Row(
          children: [
            const SizedBox(width: 8),
            // 로고 이미지도 다크모드용이 있다면 분기 처리 가능
            Image.asset('assets/images/pigeon_cutout.png', height: 44),
            const SizedBox(width: 8),
            Text(
              "센트리피전",
              style: TextStyle(
                color: textColor,
                fontWeight: FontWeight.bold,
                fontSize: 18,
              ),
            ),
          ],
        ),
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 2. 헤더 섹션: 뒤로가기 + 화면 제목
          Padding(
            padding: const EdgeInsets.only(top: 12, left: 8, bottom: 8),
            child: Row(
              children: [
                IconButton(
                  icon: Icon(Icons.arrow_back_ios_new, size: 20, color: iconColor),
                  onPressed: () => Navigator.pop(context),
                ),
                Text(
                  title,
                  style: TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.bold,
                    color: textColor,
                  ),
                ),
              ],
            ),
          ),
          // 3. 실제 콘텐츠 영역
          Expanded(child: body),
        ],
      ),
      // 4. 하단 탭 내비게이션
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: 4,
        onTap: (index) => Navigator.pop(context, index),
        type: BottomNavigationBarType.fixed,
        backgroundColor: bgColor,
        selectedItemColor: isDarkMode ? Colors.blueAccent : Colors.black,
        unselectedItemColor: Colors.grey,
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.star_border), label: '즐겨찾기'),
          BottomNavigationBarItem(icon: Icon(Icons.folder_open), label: '구독'),
          BottomNavigationBarItem(icon: Icon(Icons.home), label: '홈'),
          BottomNavigationBarItem(icon: Icon(Icons.add), label: '추가'),
          BottomNavigationBarItem(icon: Icon(Icons.settings), label: '설정'),
        ],
      ),
    );
  }
}