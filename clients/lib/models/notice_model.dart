// notice_model.dart 예시
class Notice {
  final int id;
  final String title;
  final String url;

  Notice({required this.id, required this.title, required this.url});

  factory Notice.fromJson(Map<String, dynamic> json) {
    return Notice(
      id: json['notice_id'],
      title: json['title'],
      url: json['url'],
    );
  }
}