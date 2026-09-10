import 'package:clients/providers/notice_provider.dart';
import 'package:clients/services/preferences_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('subscription site order is persisted by stable site id', () async {
    SharedPreferences.setMockInitialValues({});
    await PreferencesService.init();

    await PreferencesService.saveSubscriptionOrder([30, 10, 20]);

    expect(await PreferencesService.loadSubscriptionOrder(), [30, 10, 20]);
  });

  test('a new provider restores subscriptions in the saved order', () async {
    dotenv.testLoad(fileInput: 'IP_ADDRESS=example.com');
    await PreferencesService.saveNotices({
      '첫 번째': [
        {'notice_id': 1, 'site_id': 10},
      ],
      '두 번째': [
        {'notice_id': 2, 'site_id': 20},
      ],
    });
    await PreferencesService.saveSiteMetadata({
      '첫 번째': {'site_id': 10},
      '두 번째': {'site_id': 20},
    });
    await PreferencesService.saveSubscriptionOrder([20, 10]);

    final provider = NoticeProvider();
    await provider.loadSavedData();

    expect(provider.notices.keys.toList(), ['두 번째', '첫 번째']);
  });

  test('a new provider restores cached notices newest first', () async {
    SharedPreferences.setMockInitialValues({});
    await PreferencesService.init();
    dotenv.testLoad(fileInput: 'IP_ADDRESS=example.com');
    await PreferencesService.saveNotices({
      '테스트 사이트': [
        {'notice_id': 1, 'site_id': 10, 'published_at': '2026-08-20T09:00:00Z'},
        {'notice_id': 2, 'site_id': 10, 'published_at': '2026-08-27T09:00:00Z'},
      ],
    });
    await PreferencesService.saveSiteMetadata({
      '테스트 사이트': {'site_id': 10},
    });

    final provider = NoticeProvider();
    await provider.loadSavedData();

    expect(provider.notices['테스트 사이트']!.map((notice) => notice['notice_id']), [
      2,
      1,
    ]);

    provider.onFetchComplete([
      {'notice_id': 3, 'site_id': 10, 'published_at': '2026-08-28T09:00:00Z'},
    ], 10);

    expect(provider.notices['테스트 사이트']!.map((notice) => notice['notice_id']), [
      3,
      2,
      1,
    ]);
  });
}
