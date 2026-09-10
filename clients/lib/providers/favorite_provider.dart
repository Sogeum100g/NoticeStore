import 'package:flutter/material.dart';
import '../models/favorite_folder_model.dart';
import '../models/favorite_notice_model.dart';
import '../services/favorite_service.dart';

class FavoriteProvider with ChangeNotifier {
  List<FavoriteFolder> _folders = [];
  bool _isLoading = false;

  List<FavoriteFolder> get folders => _folders;
  bool get isLoading => _isLoading;

  final FavoriteService _favoriteService = FavoriteService();

  FavoriteFolder? _findFolder(int folderId) {
    for (var f in _folders) {
      if (f.folderId == folderId) return f;
      for (var sub in f.subFolders) {
        if (sub.folderId == folderId) return sub;
      }
    }
    return null;
  }

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

  Future<void> createFavoriteFolder(String folderName, {int? parentFolderId}) async {
    final trimmedName = folderName.trim();
    if (trimmedName.isEmpty) return;

    final success = await _favoriteService.createFolder(trimmedName, parentFolderId: parentFolderId);
    if (success) {
      await loadFavorites(silent: true);
    }
  }

  Future<void> renameFavoriteFolder(int folderId, String newName) async {
    final trimmedName = newName.trim();
    if (trimmedName.isEmpty) return;

    final folder = _findFolder(folderId);
    String? oldName;
    if (folder != null) {
      oldName = folder.folderName;
      folder.folderName = trimmedName;
      notifyListeners();
    }

    final success = await _favoriteService.renameFolder(folderId, trimmedName);
    if (!success && folder != null && oldName != null) {
      folder.folderName = oldName;
      notifyListeners();
    }
  }

  Future<void> deleteFavoriteFolder(int folderId) async {
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
    notifyListeners();

    final success = await _favoriteService.deleteFolder(folderId);
    if (!success) {
      await loadFavorites(silent: true);
    }
  }

  List<String> getKeywordsForFolder(int folderId) {
    return _findFolder(folderId)?.keywords ?? [];
  }

  Future<void> addKeywordToFolder(int folderId, String keyword) async {
    final trimmedKeyword = keyword.trim();
    if (trimmedKeyword.isEmpty) return;

    final folder = _findFolder(folderId);
    if (folder != null && !folder.keywords.contains(trimmedKeyword)) {
      folder.keywords.add(trimmedKeyword);
      notifyListeners();
    }

    final success = await _favoriteService.addFolderKeyword(folderId, trimmedKeyword);
    if (!success && folder != null) {
      folder.keywords.remove(trimmedKeyword);
      notifyListeners();
    }
  }

  Future<void> removeKeywordFromFolder(int folderId, String keyword) async {
    final folder = _findFolder(folderId);
    if (folder != null) {
      folder.keywords.remove(keyword);
      notifyListeners();
    }

    final success = await _favoriteService.removeFolderKeyword(folderId, keyword);
    if (!success && folder != null) {
      folder.keywords.add(keyword);
      notifyListeners();
    }
  }

  Future<void> addNoticeToFolder(int folderId, int noticeId) async {
    final success = await _favoriteService.addNoticeToFolder(folderId, noticeId);
    if (success) {
      await loadFavorites(silent: true);
    }
  }

  Future<void> removeNoticeFromFolder(int folderId, int noticeId) async {
    final folder = _findFolder(folderId);
    if (folder != null) {
      folder.notices.removeWhere((n) => n.noticeId == noticeId);
      notifyListeners();
    }

    final success = await _favoriteService.removeNoticeFromFolder(folderId, noticeId);
    if (!success) {
      await loadFavorites(silent: true);
    }
  }

  Future<void> clearFavoriteFolder(int folderId) async {
    final folder = _findFolder(folderId);
    if (folder == null || folder.notices.isEmpty) return;

    final noticesToDelete = List<FavoriteNotice>.from(folder.notices);

    folder.notices.clear();

    notifyListeners();

    try {
      await Future.wait(noticesToDelete.map(
              (n) => _favoriteService.removeNoticeFromFolder(folderId, n.noticeId)
      ));
    } catch (e) {
      debugPrint("❌ 폴더 비우기 에러: $e");
      await loadFavorites(silent: true);
    }
  }

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

    final noticesToMove = List<FavoriteNotice>.from(sourceFolder.notices);
    sourceFolder.notices.clear();
    notifyListeners();

    try {
      await Future.wait(noticesToMove.expand((notice) => [
        _favoriteService.addNoticeToFolder(targetFolderId, notice.noticeId),
        _favoriteService.removeNoticeFromFolder(sourceFolderId, notice.noticeId),
      ]));
      await loadFavorites(silent: true);
    } catch (e) {
      debugPrint("❌ 일괄 이동 에러: $e");
      await loadFavorites(silent: true);
    }
  }
}
