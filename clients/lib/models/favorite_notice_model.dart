class FavoriteNotice {
  final int noticeId;
  final String title;
  final String url;
  final int siteId;
  final String createdAt;

  FavoriteNotice({
    required this.noticeId,
    required this.title,
    required this.url,
    required this.siteId,
    required this.createdAt,
  });

  // JSON 데이터를 Dart 객체로 변환하는 팩토리 생성자
  factory FavoriteNotice.fromJson(Map<String, dynamic> json) {
    return FavoriteNotice(
      noticeId: json['notice_id'] ?? 0,
      title: json['title'] ?? '',
      url: json['url'] ?? '',
      siteId: json['site_id'] ?? 0,
      createdAt: json['created_at'] ?? '',
    );
  }
}