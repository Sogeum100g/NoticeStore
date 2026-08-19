import 'package:flutter/material.dart';
import '../models/favorite_folder_model.dart';
import '../models/favorite_notice_model.dart';
import '../services/favorite_service.dart';

class FavoriteProvider with ChangeNotifier {
  // --- 1. 상태 변수 ---
  List<FavoriteFolder> _folders = [];
  bool _isLoading = false;

  // --- Getters ---
  List<FavoriteFolder> get folders => _folders;
  bool get isLoading => _isLoading;

  final FavoriteService _favoriteService = FavoriteService();

  // --- 내부 유틸리티: ID로 폴더 찾기 ---
  FavoriteFolder? _findFolder(int folderId) {
    for (var f in _folders) {
      if (f.folderId == folderId) return f;
      for (var sub in f.subFolders) {
        if (sub.folderId == folderId) return sub;
      }
    }
    return null;
  }

  // --- 2. 초기화 및 로드 (💡 조용한 동기화 옵션 추가) ---
  Future<void> loadFavorites({bool silent = false}) async {
    // silent가 true일 때는 화면 중앙의 로딩 바를 띄우지 않습니다.
    if (!silent) {
      _isLoading = true;
      notifyListeners();
    }

    try {
      _folders = await _favoriteService.getFoldersTree();
    } catch (e) {
      debugPrint("❌ 즐겨찾기 폴더 로드 에러: $e");
    } finally {
      if (!silent) _isLoading = false;
      notifyListeners();
    }
  }

  // --- 3. 폴더 관리 로직 ---

  Future<void> createFavoriteFolder(String folderName, {int? parentFolderId}) async {
    final trimmedName = folderName.trim();
    if (trimmedName.isEmpty) return;

    // 💡 생성은 서버에서 부여하는 새 ID가 필요하므로 조용한 동기화 사용
    final success = await _favoriteService.createFolder(trimmedName, parentFolderId: parentFolderId);
    if (success) {
      await loadFavorites(silent: true);
    }
  }

  Future<void> renameFavoriteFolder(int folderId, String newName) async {
    final trimmedName = newName.trim();
    if (trimmedName.isEmpty) return;

    // 💡 낙관적 업데이트
    final folder = _findFolder(folderId);
    String? oldName;
    if (folder != null) {
      oldName = folder.folderName;
      folder.folderName = trimmedName;
      notifyListeners(); // UI 즉시 반영
    }

    final success = await _favoriteService.renameFolder(folderId, trimmedName);
    if (!success && folder != null && oldName != null) {
      folder.folderName = oldName; // 실패 시 롤백
      notifyListeners();
    }
  }

  Future<void> deleteFavoriteFolder(int folderId) async {
    // 💡 낙관적 업데이트: 로컬에서 먼저 삭제
    int targetIndex = _folders.indexWhere((f) => f.folderId == folderId);
    if (targetIndex != -1) {
      _folders.removeAt(targetIndex);
    } else {
      for (var f in _folders) {
        targetIndex = f.subFolders.indexWhere((sub) => sub.folderId == folderId);
        if (targetIndex != -1) {
          f.subFolders.removeAt(targetIndex);
          break;
        }
      }
    }
    notifyListeners(); // UI 즉시 반영

    final success = await _favoriteService.deleteFolder(folderId);
    if (!success) {
      await loadFavorites(silent: true); // 실패 시 전체 복구
    }
  }

  // --- 4. 키워드 관리 로직 ---

  List<String> getKeywordsForFolder(int folderId) {
    return _findFolder(folderId)?.keywords ?? [];
  }

  Future<void> addKeywordToFolder(int folderId, String keyword) async {
    final trimmedKeyword = keyword.trim();
    if (trimmedKeyword.isEmpty) return;

    // 💡 낙관적 업데이트
    final folder = _findFolder(folderId);
    if (folder != null && !folder.keywords.contains(trimmedKeyword)) {
      folder.keywords.add(trimmedKeyword);
      notifyListeners();
    }

    final success = await _favoriteService.addFolderKeyword(folderId, trimmedKeyword);
    if (!success && folder != null) {
      folder.keywords.remove(trimmedKeyword); // 롤백
      notifyListeners();
    }
  }

  Future<void> removeKeywordFromFolder(int folderId, String keyword) async {
    // 💡 낙관적 업데이트
    final folder = _findFolder(folderId);
    if (folder != null) {
      folder.keywords.remove(keyword);
      notifyListeners();
    }

    final success = await _favoriteService.removeFolderKeyword(folderId, keyword);
    if (!success && folder != null) {
      folder.keywords.add(keyword); // 롤백
      notifyListeners();
    }
  }

  // --- 5. 공지 관리 로직 ---

  Future<void> addNoticeToFolder(int folderId, int noticeId) async {
    // 💡 공지 추가는 전체 공지 데이터(날짜 등)를 불러와야 하므로 조용한 동기화 사용
    final success = await _favoriteService.addNoticeToFolder(folderId, noticeId);
    if (success) {
      await loadFavorites(silent: true);
    }
  }

  Future<void> removeNoticeFromFolder(int folderId, int noticeId) async {
    // 💡 낙관적 업데이트
    final folder = _findFolder(folderId);
    if (folder != null) {
      folder.notices.removeWhere((n) => n.noticeId == noticeId);
      notifyListeners();
    }

    final success = await _favoriteService.removeNoticeFromFolder(folderId, noticeId);
    if (!success) {
      await loadFavorites(silent: true); // 실패 시 원상 복구
    }
  }

  // 💡 폴더 비우기 전용 메서드 (UI 1회 갱신으로 렉 완벽 해결)
  Future<void> clearFavoriteFolder(int folderId) async {
    final folder = _findFolder(folderId);
    if (folder == null || folder.notices.isEmpty) return;

    // 1. 삭제할 공지 리스트를 메모리에 임시 복사
    final noticesToDelete = List<FavoriteNotice>.from(folder.notices);

    // 2. 낙관적 업데이트: 프론트엔드 리스트를 한 번에 싹 비웁니다.
    folder.notices.clear();

    // 3. UI 갱신: 단 한 번만 호출되므로 렉이 발생하지 않습니다.
    notifyListeners();

    try {
      // 4. 백그라운드에서 API 병렬 통신 (화면은 이미 비워져 있음)
      await Future.wait(noticesToDelete.map(
              (n) => _favoriteService.removeNoticeFromFolder(folderId, n.noticeId)
      ));
    } catch (e) {
      debugPrint("❌ 폴더 비우기 에러: $e");
      await loadFavorites(silent: true); // 실패 시 조용히 원상 복구
    }
  }

  // --- 6. 폴더 순서 변경 로직 ---
  Future<void> reorderFolders(int oldIndex, int newIndex) async {
    if (oldIndex < newIndex) newIndex -= 1;

    final folder = _folders.removeAt(oldIndex);
    _folders.insert(newIndex, folder);
    notifyListeners();

    final orderedFolderIds = _folders.map((f) => f.folderId).toList();
    try {
      final success = await _favoriteService.updateFolderOrder(orderedFolderIds);
      if (!success) await loadFavorites(silent: true);
    } catch (e) {
      await loadFavorites(silent: true);
    }
  }

  Future<void> reorderSubFolders(int parentId, int oldIndex, int newIndex) async {
    if (oldIndex < newIndex) newIndex -= 1;

    final parentFolder = _findFolder(parentId);
    if (parentFolder == null) return;

    final subFolder = parentFolder.subFolders.removeAt(oldIndex);
    parentFolder.subFolders.insert(newIndex, subFolder);
    notifyListeners();

    final orderedIds = parentFolder.subFolders.map((sf) => sf.folderId).toList();
    try {
      final success = await _favoriteService.updateFolderOrder(orderedIds);
      if (!success) await loadFavorites(silent: true);
    } catch (e) {
      await loadFavorites(silent: true);
    }
  }

  Future<void> moveAllNotices(int sourceFolderId, int targetFolderId) async {
    if (sourceFolderId == targetFolderId) return;

    final sourceFolder = _findFolder(sourceFolderId);
    if (sourceFolder == null || sourceFolder.notices.isEmpty) return;

    // 💡 UI에서 공지가 사라지는 연출을 먼저 보여줍니다 (낙관적 UI 효과)
    final noticesToMove = List<FavoriteNotice>.from(sourceFolder.notices);
    sourceFolder.notices.clear();
    notifyListeners();

    try {
      await Future.wait(noticesToMove.expand((notice) => [
        _favoriteService.addNoticeToFolder(targetFolderId, notice.noticeId),
        _favoriteService.removeNoticeFromFolder(sourceFolderId, notice.noticeId),
      ]));
      // 이동 완료 후 서버 전체 상태와 동기화
      await loadFavorites(silent: true);
    } catch (e) {
      debugPrint("❌ 일괄 이동 에러: $e");
      await loadFavorites(silent: true); // 에러 발생 시 원래대로 복구
    }
  }
}
