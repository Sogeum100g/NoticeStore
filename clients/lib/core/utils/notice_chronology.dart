class NoticeChronology {
  const NoticeChronology._();

  /// 화면에 표시하는 날짜와 같은 우선순위로 공지를 최신순 정렬합니다.
  ///
  /// 날짜가 없거나 파싱할 수 없으면 다음 후보를 사용하고, 모든 날짜가
  /// 같거나 없을 때는 notice_id가 큰 공지를 먼저 배치해 순서를 고정합니다.
  static List<Map<String, dynamic>> sortedNewestFirst(
      Iterable<Map<String, dynamic>> notices,
      ) {
    final sorted = notices.toList(growable: true);
    sorted.sort(compareNewestFirst);
    return sorted;
  }

  static int compareNewestFirst(
      Map<String, dynamic> left,
      Map<String, dynamic> right,
      ) {
    final leftDate = effectiveDate(left);
    final rightDate = effectiveDate(right);

    if (leftDate != null && rightDate != null) {
      final dateComparison = rightDate.compareTo(leftDate);
      if (dateComparison != 0) return dateComparison;
    } else if (leftDate != null) {
      return -1;
    } else if (rightDate != null) {
      return 1;
    }

    final leftId = _parseInt(left['notice_id']);
    final rightId = _parseInt(right['notice_id']);
    if (leftId != null && rightId != null) {
      return rightId.compareTo(leftId);
    }
    if (leftId != null) return -1;
    if (rightId != null) return 1;
    return 0;
  }

  static DateTime? effectiveDate(Map<String, dynamic> notice) {
    for (final field in const ['published_at', 'created_at', 'scraped_at']) {
      final rawValue = notice[field]?.toString().trim() ?? '';
      if (rawValue.isEmpty) continue;

      final parsed = DateTime.tryParse(rawValue);
      if (parsed != null) return parsed;
    }
    return null;
  }

  static int? _parseInt(dynamic value) {
    if (value is int) return value;
    if (value is num) return value.toInt();
    return int.tryParse(value?.toString() ?? '');
  }
}
