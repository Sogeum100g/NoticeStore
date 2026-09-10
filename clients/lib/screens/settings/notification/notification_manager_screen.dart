import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../providers/settings_provider.dart';
import '../settings_wrapper.dart';

class NotificationManagerScreen extends StatelessWidget {
  const NotificationManagerScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final settingsProv = context.watch<SettingsProvider>();
    final isEnabled = settingsProv.settings.isNotificationEnabled;

    return SettingsWrapper(
      title: '알림 설정',
      body: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 16),
        children: [
          SwitchListTile(
            activeThumbColor: Colors.deepPurple,
            title: const Text(
              '전체 푸시 알림',
              style: TextStyle(fontWeight: FontWeight.bold),
            ),
            subtitle: const Text('모든 구독의 새 소식 알림을 한 번에 켜거나 끕니다.'),
            secondary: Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: Colors.deepPurple.withValues(alpha: 0.1),
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.notifications_active_outlined,
                color: Colors.deepPurple,
              ),
            ),
            value: isEnabled,
            onChanged: (value) async {
              await settingsProv.updateSettings(isNotificationEnabled: value);
            },
          ),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 16),
            child: Divider(),
          ),
          const ListTile(
            leading: Icon(Icons.folder_outlined, color: Colors.orangeAccent),
            title: Text(
              '구독별 알림 선택',
              style: TextStyle(fontWeight: FontWeight.w500),
            ),
            subtitle: Text('구독 화면의 폴더 타일 오른쪽 종 아이콘에서 새 소식 알림을 선택할 수 있습니다.'),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
            child: Text(
              isEnabled
                  ? '새 공지가 실제로 추가된 수집 결과에 대해서만 알림을 보냅니다.'
                  : '전체 알림이 꺼져 있습니다. 구독별 선택값은 그대로 보존됩니다.',
              style: TextStyle(
                color: Colors.grey[600],
                fontSize: 13,
                height: 1.5,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
