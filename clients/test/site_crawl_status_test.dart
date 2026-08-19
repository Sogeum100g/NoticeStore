import 'package:clients/models/site_model.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('SiteCrawlStatus', () {
    test('parses every backend status', () {
      expect(
        SiteCrawlStatus.fromApi('pending'),
        SiteCrawlStatus.pending,
      );
      expect(
        SiteCrawlStatus.fromApi('active'),
        SiteCrawlStatus.active,
      );
      expect(
        SiteCrawlStatus.fromApi('paused'),
        SiteCrawlStatus.paused,
      );
      expect(
        SiteCrawlStatus.fromApi('failed'),
        SiteCrawlStatus.failed,
      );
      expect(
        SiteCrawlStatus.fromApi('blocked'),
        SiteCrawlStatus.blocked,
      );
    });

    test('unknown and null values remain non-disruptive', () {
      expect(
        SiteCrawlStatus.fromApi('unexpected'),
        SiteCrawlStatus.unknown,
      );
      expect(
        SiteCrawlStatus.fromApi(null),
        SiteCrawlStatus.unknown,
      );
      expect(
        SiteCrawlStatus.unknown.shouldShowInSubscription,
        isFalse,
      );
    });

    test('only non-active known states render a status message', () {
      expect(
        SiteCrawlStatus.active.shouldShowInSubscription,
        isFalse,
      );
      expect(
        SiteCrawlStatus.pending.shouldShowInSubscription,
        isTrue,
      );
      expect(
        SiteCrawlStatus.failed.shouldShowInSubscription,
        isTrue,
      );
      expect(
        SiteCrawlStatus.blocked.shouldShowInSubscription,
        isTrue,
      );
    });
  });
}
