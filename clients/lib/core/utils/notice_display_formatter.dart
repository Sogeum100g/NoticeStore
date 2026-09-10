class NoticeDisplayFormatter {
  const NoticeDisplayFormatter._();

  static const String unknownAuthor = 'Unknown';
  static const String unknownRegistrationDate = '등록일자 미상';

  static String subscriptionMetadata(Map<String, dynamic> notice) {
    return favoriteMetadata(
      author: notice['author'],
      publishedAt: notice['published_at'],
      createdAt: notice['created_at'],
      fallbackDate: notice['scraped_at'],
    );
  }

  static String favoriteMetadata({
    required Object? author,
    required Object? publishedAt,
    required Object? createdAt,
    Object? fallbackDate,
  }) {
    final formattedAuthor = _author(author);
    final date = _registrationDate(
      _firstNonBlank(publishedAt, _firstNonBlank(createdAt, fallbackDate)),
    );
    return '[$formattedAuthor] $date';
  }

  static String homeMetadata(String folderName, Map<String, dynamic> notice) {
    return '$folderName [${_author(notice['author'])}]';
  }

  static String _author(Object? value) {
    final author = value?.toString().trim() ?? '';
    return author.isEmpty ? unknownAuthor : author;
  }

  static String _registrationDate(Object? value) {
    final rawDate = value?.toString().trim() ?? '';
    if (rawDate.isEmpty) return unknownRegistrationDate;

    final parsedDate = DateTime.tryParse(rawDate);
    if (parsedDate == null) return unknownRegistrationDate;

    final localDate = parsedDate.toLocal();
    final month = localDate.month.toString().padLeft(2, '0');
    final day = localDate.day.toString().padLeft(2, '0');
    return '${localDate.year}-$month-$day';
  }

  static Object? _firstNonBlank(Object? preferred, Object? fallback) {
    if (preferred != null && preferred.toString().trim().isNotEmpty) {
      return preferred;
    }
    return fallback;
  }
}
