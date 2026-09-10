import 'package:clients/core/utils/notice_display_formatter.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('NoticeDisplayFormatter', () {
    test(
      'subscription metadata always includes author and registration date',
          () {
        final metadata = NoticeDisplayFormatter.subscriptionMetadata({
          'author': '인사팀',
          'published_at': '2026-08-20T09:30:00',
          'created_at': '2026-08-24T09:30:00',
        });

        expect(metadata, '[인사팀] 2026-08-20');
      },
    );

    test('home metadata includes the user folder name and author', () {
      final metadata = NoticeDisplayFormatter.homeMetadata('삼성 채용', {
        'author': '반도체부문',
      });

      expect(metadata, '삼성 채용 [반도체부문]');
    });

    test('favorite metadata uses the same author and date shape', () {
      final metadata = NoticeDisplayFormatter.favoriteMetadata(
        author: '채용팀',
        publishedAt: '2026-08-21T01:20:00',
        createdAt: '2026-08-25T01:20:00',
      );

      expect(metadata, '[채용팀] 2026-08-21');
    });

    test('blank values keep the unified display shape', () {
      expect(
        NoticeDisplayFormatter.subscriptionMetadata(const {}),
        '[Unknown] 등록일자 미상',
      );
      expect(
        NoticeDisplayFormatter.homeMetadata('네이버 채용', const {}),
        '네이버 채용 [Unknown]',
      );
    });

    test('created date is used when published date is blank', () {
      final metadata = NoticeDisplayFormatter.subscriptionMetadata({
        'author': '운영팀',
        'published_at': '',
        'created_at': '2026-08-22T18:00:00',
        'scraped_at': '2026-08-23T18:00:00',
      });

      expect(metadata, '[운영팀] 2026-08-22');
    });

    test('scraped date is used when published and created dates are blank', () {
      final metadata = NoticeDisplayFormatter.subscriptionMetadata({
        'author': '운영팀',
        'published_at': '',
        'created_at': '',
        'scraped_at': '2026-08-23T18:00:00',
      });

      expect(metadata, '[운영팀] 2026-08-23');
    });
  });
}
