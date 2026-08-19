import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import 'auth/login_screen.dart';
import 'home/home_screen.dart';
import 'favorites/favorites_screen.dart';
import 'subscriptions/subscriptions_screen.dart';
import 'settings/settings_screen.dart';
import 'add/add_site_screen.dart';

// 우리가 만든 Provider 임포트
import '../providers/notice_provider.dart';
import '../providers/favorite_provider.dart';

class MainWrapper extends StatefulWidget {
  const MainWrapper({super.key});
  @override
  State<MainWrapper> createState() => _MainWrapperState();
}

class _MainWrapperState extends State<MainWrapper> {

  @override
  void initState() {
    super.initState();
    _initializeAppData();
  }

  Future<void> _initializeAppData() async {
    final authProv = context.read<AuthProvider>();
    final noticeProv = context.read<NoticeProvider>();
    final favoriteProv = context.read<FavoriteProvider>();

    // 인증 확인과 데이터 로딩을 동시에 시작
    await Future.wait([
      authProv.checkAutoLogin(noticeProv),
      noticeProv.loadSavedData(),
      favoriteProv.loadFavorites(),
    ]);

    // 모든 로딩이 끝나면 서버 동기화는 별도로 실행 (UI를 막지 않음)
    if (mounted && authProv.isAuthenticated) {
      noticeProv.fetchNoticesFromServer();
    }
  }

  // 화면 리스트: 이제 파라미터가 0개입니다!
  final List<Widget> _screens = const [
    FavoritesScreen(),
    SubscriptionsScreen(),
    HomeScreen(),
    AddSiteScreen(),
    SettingsScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    final authProvider = context.watch<AuthProvider>();
    final noticeProv = context.watch<NoticeProvider>();
    // 💡 실제 UI를 제어하는 인덱스
    final int selectedIndex = noticeProv.selectedIndex;

    // 1. 로딩 중일 때 (서버와 통신 중이거나 초기화 중)
    if (authProvider.isLoading) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }

    // 2. [핵심] 인증 여부에 따른 화면 분기 [cite: 2025-10-01, 2026-02-15]
    // 로그인하지 않은 경우, Scaffold를 아예 타지 않고 바로 LoginScreen을 보여주네.
    if (!authProvider.isAuthenticated) {
      return const LoginScreen();
    }

    // 3. 로그인 성공 시 보여줄 메인 네비게이션 구조 [cite: 2026-02-15]
    // 이제 selectedIndex에 따라 _screens 리스트의 화면들이 전환됨
    return Scaffold(
      appBar: AppBar(
        backgroundColor: Colors.white,
        surfaceTintColor: Colors.white,
        elevation: 1,
        title: Row(
          children: [
            const SizedBox(width: 8),
            Image.asset('assets/images/pigeon_cutout.png', height: 44),
            const SizedBox(width: 8),
            const Text("센트리피전",
                style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold)
            ),
          ],
        ),
      ),
      // IndexedStack이 현재 인덱스에 맞는 화면(Favorites, Home 등)을 보여주네.
      body: IndexedStack(
        index: selectedIndex,
        children: _screens,
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: selectedIndex,
        onTap: (index) => noticeProv.setSelectedIndex(index),
        type: BottomNavigationBarType.fixed,
        selectedItemColor: Colors.black,
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