import 'package:clients/core/utils/notice_chronology.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('NoticeChronology', () {
    test('sorts notices by displayed date newest first', () {
      final sorted = NoticeChronology.sortedNewestFirst([
        {
          'notice_id': 1,
          'published_at': '2026-08-20T09:00:00Z',
          'created_at': '2026-08-28T09:00:00Z',
        },
        {
          'notice_id': 2,
          'published_at': '2026-08-27T09:00:00Z',
          'created_at': '2026-08-27T09:00:00Z',
        },
      ]);

      expect(sorted.map((notice) => notice['notice_id']), [2, 1]);
    });

    test('falls back from published date to created and scraped dates', () {
      final sorted = NoticeChronology.sortedNewestFirst([
        {
          'notice_id': 1,
          'published_at': '',
          'created_at': '2026-08-26T09:00:00Z',
        },
        {
          'notice_id': 2,
          'published_at': 'invalid-date',
          'created_at': '',
          'scraped_at': '2026-08-27T09:00:00Z',
        },
      ]);

      expect(sorted.map((notice) => notice['notice_id']), [2, 1]);
    });

    test('uses notice id descending as a deterministic tie breaker', () {
      final sorted = NoticeChronology.sortedNewestFirst([
        {'notice_id': 3, 'published_at': '2026-08-27'},
        {'notice_id': 7, 'published_at': '2026-08-27'},
        {'notice_id': 1},
      ]);

      expect(sorted.map((notice) => notice['notice_id']), [7, 3, 1]);
    });
  });
}
