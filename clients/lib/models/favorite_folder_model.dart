import 'favorite_notice_model.dart';

class FavoriteFolder {
  final int folderId;
  final int? parentFolderId;
  String folderName;
  final List<FavoriteFolder> subFolders;
  final List<FavoriteNotice> notices;
  final List<String> keywords; // 💡 1. 키워드 속성 추가

  FavoriteFolder({
    required this.folderId,
    this.parentFolderId,
    required this.folderName,
    required this.subFolders,
    required this.notices,
    required this.keywords, // 💡 2. 생성자에 필수값 추가
  });

  factory FavoriteFolder.fromJson(Map<String, dynamic> json) {
    return FavoriteFolder(
      folderId: json['folder_id'] ?? 0,
      parentFolderId: json['parent_folder_id'],
      folderName: json['folder_name'] ?? '',
      subFolders: (json['sub_folders'] as List<dynamic>?)
          ?.map((e) => FavoriteFolder.fromJson(e as Map<String, dynamic>))
          .toList() ??
          [],
      notices: (json['notices'] as List<dynamic>?)
          ?.map((e) => FavoriteNotice.fromJson(e as Map<String, dynamic>))
          .toList() ??
          [],
      // 💡 3. 서버에서 내려주는 키워드 배열 파싱
      keywords: (json['keywords'] as List<dynamic>?)
          ?.map((e) => e.toString())
          .toList() ??
          [],
    );
  }
}