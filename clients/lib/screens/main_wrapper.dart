import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/auth_provider.dart';
import 'auth/login_screen.dart';
import 'home/home_screen.dart';
import 'favorites/favorites_screen.dart';
import 'subscriptions/subscriptions_screen.dart';
import 'settings/settings_screen.dart';
import 'add/add_site_screen.dart';

import '../providers/notice_provider.dart';
import '../providers/favorite_provider.dart';
import '../providers/settings_provider.dart';

class MainWrapper extends StatefulWidget {
  const MainWrapper({super.key});
  @override
  State<MainWrapper> createState() => _MainWrapperState();
}

class _MainWrapperState extends State<MainWrapper> {
  @override
  void initState() {
    super.initState();
    // Provider 변경 알림이 첫 빌드와 충돌하지 않도록 다음 프레임에 초기화합니다.
    WidgetsBinding.instance.addPostFrameCallback((_) => _initializeAppData());
  }

  Future<void> _initializeAppData() async {
    final authProv = context.read<AuthProvider>();
    final noticeProv = context.read<NoticeProvider>();
    final favoriteProv = context.read<FavoriteProvider>();
    final settingsProv = context.read<SettingsProvider>();

    await Future.wait([
      authProv.checkAutoLogin(noticeProv, settingsProv),
      noticeProv.loadSavedData(),
      favoriteProv.loadFavorites(),
    ]);

    if (mounted && authProv.isAuthenticated) {
      noticeProv.fetchNoticesFromServer();
    }
  }

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
    final int selectedIndex = noticeProv.selectedIndex;

    if (authProvider.isLoading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    if (!authProvider.isAuthenticated) {
      return const LoginScreen();
    }

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
            const Text(
              "공지저장소",
              style: TextStyle(
                color: Colors.black,
                fontWeight: FontWeight.bold,
              ),
            ),
          ],
        ),
      ),
      body: IndexedStack(index: selectedIndex, children: _screens),
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
