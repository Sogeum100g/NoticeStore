class FavoriteNotice {
  final int noticeId;
  final String title;
  final String author;
  final String url;
  final int siteId;
  final String publishedAt;
  final String createdAt;

  FavoriteNotice({
    required this.noticeId,
    required this.title,
    required this.author,
    required this.url,
    required this.siteId,
    required this.publishedAt,
    required this.createdAt,
  });

  factory FavoriteNotice.fromJson(Map<String, dynamic> json) {
    return FavoriteNotice(
      noticeId: json['notice_id'] ?? 0,
      title: json['title'] ?? '',
      author: json['author'] ?? '',
      url: json['url'] ?? '',
      siteId: json['site_id'] ?? 0,
      publishedAt: json['published_at'] ?? '',
      createdAt: json['created_at'] ?? '',
    );
  }
}
