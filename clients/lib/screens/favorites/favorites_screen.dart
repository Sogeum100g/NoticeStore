import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../providers/favorite_provider.dart';
import '../../providers/notice_provider.dart';
import '../../models/favorite_folder_model.dart';
import '../../models/favorite_notice_model.dart';
import '../../core/utils/notice_display_formatter.dart';

class FavoritesScreen extends StatefulWidget {
  const FavoritesScreen({super.key});

  @override
  State<FavoritesScreen> createState() => _FavoritesScreenState();
}

class _FavoritesScreenState extends State<FavoritesScreen> {
  bool _isSearching = false;
  final TextEditingController _searchController = TextEditingController();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<FavoriteProvider>().loadFavorites();
    });
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  void _showAddFolderDialog(
      BuildContext context,
      FavoriteProvider prov, {
        int? parentFolderId,
      }) {
    final TextEditingController controller = TextEditingController();
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(parentFolderId == null ? "새 폴더 추가" : "하위 폴더 추가"),
        content: TextField(
          controller: controller,
          decoration: const InputDecoration(hintText: "폴더 이름을 입력하세요"),
          autofocus: true,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text("취소"),
          ),
          TextButton(
            onPressed: () {
              if (controller.text.isNotEmpty) {
                prov.createFavoriteFolder(
                  controller.text,
                  parentFolderId: parentFolderId,
                );
                Navigator.pop(context);
              }
            },
            child: const Text("추가", style: TextStyle(color: Colors.blue)),
          ),
        ],
      ),
    );
  }

  void _showRenameDialog(
      BuildContext context,
      FavoriteProvider prov,
      FavoriteFolder folder,
      ) {
    final TextEditingController controller = TextEditingController(
      text: folder.folderName,
    );
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text("이름 바꾸기"),
        content: TextField(
          controller: controller,
          decoration: const InputDecoration(hintText: "새 이름을 입력하세요"),
          autofocus: true,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text("취소"),
          ),
          TextButton(
            onPressed: () {
              if (controller.text.isNotEmpty) {
                prov.renameFavoriteFolder(folder.folderId, controller.text);
              }
              Navigator.pop(context);
            },
            child: const Text("변경"),
          ),
        ],
      ),
    );
  }

  void _showKeywordManageBottomSheet(
      BuildContext context,
      FavoriteFolder folder,
      ) {
    final TextEditingController controller = TextEditingController();

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setModalState) {
            final favoriteProv = context.watch<FavoriteProvider>();

            final List<String> keywords = favoriteProv.getKeywordsForFolder(
              folder.folderId,
            );

            return Padding(
              padding: EdgeInsets.only(
                left: 20,
                right: 20,
                top: 20,
                bottom: MediaQuery.of(context).viewInsets.bottom + 20,
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    "${folder.folderName} 키워드",
                    style: const TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 15),

                  TextField(
                    controller: controller,
                    style: const TextStyle(
                      color: Color(0xFF636363),
                      fontSize: 16,
                    ),
                    decoration: InputDecoration(
                      hintText: "새 키워드 입력",
                      hintStyle: const TextStyle(
                        color: Color(0xFF636363),
                        fontSize: 14,
                      ),

                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 16,
                        vertical: 12,
                      ),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                      suffixIcon: IconButton(
                        icon: const Icon(
                          Icons.add_circle,
                          color: Color(0xFF636363),
                        ),
                        onPressed: () async {
                          final text = controller.text.trim();
                          if (text.isNotEmpty && !keywords.contains(text)) {
                            await favoriteProv.addKeywordToFolder(
                              folder.folderId,
                              text,
                            );
                            controller.clear();
                            setModalState(() {});
                          }
                        },
                      ),
                    ),
                  ),
                  const SizedBox(height: 20),

                  if (favoriteProv.isLoading)
                    const Center(
                      child: Padding(
                        padding: EdgeInsets.all(16.0),
                        child: CircularProgressIndicator(),
                      ),
                    )
                  else if (keywords.isEmpty)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 8.0),
                      child: Text(
                        "등록된 키워드가 없습니다.",
                        style: TextStyle(color: Colors.grey, fontSize: 14),
                      ),
                    )
                  else
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: keywords
                          .map(
                            (k) => InputChip(
                          label: Text(k),
                          onDeleted: () async {
                            await favoriteProv.removeKeywordFromFolder(
                              folder.folderId,
                              k,
                            );
                            setModalState(() {});
                          },
                          deleteIconColor: Colors.redAccent,
                          backgroundColor: Colors.grey[100],
                          side: BorderSide(color: Colors.grey[300]!),
                        ),
                      )
                          .toList(),
                    ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  void _showBulkMoveBottomSheet(
      BuildContext context,
      FavoriteProvider prov,
      FavoriteFolder sourceFolder,
      ) {
    final List<FavoriteFolder> allFolders = prov.folders;

    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) {
        return Container(
          padding: const EdgeInsets.symmetric(vertical: 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text(
                "이동할 대상 폴더 선택",
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 10),
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  children: allFolders
                      .expand(
                        (f) => [
                      if (f.folderId != sourceFolder.folderId)
                        ListTile(
                          leading: const Icon(
                            Icons.folder,
                            color: Colors.amber,
                          ),
                          title: Text(f.folderName),
                          onTap: () => _executeBulkMove(
                            context,
                            prov,
                            sourceFolder.folderId,
                            f.folderId,
                          ),
                        ),
                      ...f.subFolders
                          .where(
                            (sub) => sub.folderId != sourceFolder.folderId,
                      )
                          .map(
                            (sub) => ListTile(
                          contentPadding: const EdgeInsets.only(
                            left: 40,
                            right: 16,
                          ),
                          leading: const Icon(
                            Icons.subdirectory_arrow_right,
                            color: Colors.grey,
                          ),
                          title: Text(sub.folderName),
                          onTap: () => _executeBulkMove(
                            context,
                            prov,
                            sourceFolder.folderId,
                            sub.folderId,
                          ),
                        ),
                      ),
                    ],
                  )
                      .toList(),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Future<void> _executeBulkMove(
      BuildContext context,
      FavoriteProvider prov,
      int sourceId,
      int targetId,
      ) async {
    Navigator.pop(context);
    await prov.moveAllNotices(sourceId, targetId);
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('모든 공지가 이동되었습니다.'),
          duration: Duration(seconds: 1),
        ),
      );
    }
  }

  Future<void> _executeNoticeMove(
      BuildContext context,
      FavoriteProvider prov,
      int sourceFolderId,
      int targetFolderId,
      FavoriteNotice notice,
      ) async {
    Navigator.pop(context);

    await prov.addNoticeToFolder(targetFolderId, notice.noticeId);
    await prov.removeNoticeFromFolder(sourceFolderId, notice.noticeId);

    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('공지가 이동되었습니다.'),
          duration: Duration(seconds: 1),
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  void _showNoticeMoveBottomSheet(
      BuildContext parentContext,
      FavoriteProvider prov,
      int sourceFolderId,
      FavoriteNotice notice,
      ) {
    final List<FavoriteFolder> allFolders = prov.folders;

    showModalBottomSheet(
      context: parentContext,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (sheetContext) {
        return Container(
          padding: const EdgeInsets.symmetric(vertical: 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text(
                "이동할 대상 폴더 선택",
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 10),
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  children: allFolders
                      .expand(
                        (f) => [
                      if (f.folderId != sourceFolderId)
                        ListTile(
                          leading: const Icon(
                            Icons.folder,
                            color: Colors.amber,
                          ),
                          title: Text(f.folderName),
                          onTap: () => _executeNoticeMove(
                            parentContext,
                            prov,
                            sourceFolderId,
                            f.folderId,
                            notice,
                          ),
                        ),
                      ...f.subFolders
                          .where((sub) => sub.folderId != sourceFolderId)
                          .map(
                            (sub) => ListTile(
                          contentPadding: const EdgeInsets.only(
                            left: 40,
                            right: 16,
                          ),
                          leading: const Icon(
                            Icons.subdirectory_arrow_right,
                            color: Colors.grey,
                          ),
                          title: Text(sub.folderName),
                          onTap: () => _executeNoticeMove(
                            parentContext,
                            prov,
                            sourceFolderId,
                            sub.folderId,
                            notice,
                          ),
                        ),
                      ),
                    ],
                  )
                      .toList(),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final favoriteProv = context.watch<FavoriteProvider>();
    final noticeProv = context.watch<NoticeProvider>();

    final String query = noticeProv.searchQuery.toLowerCase();

    List<FavoriteFolder> displayFolders = favoriteProv.folders;
    if (query.isNotEmpty) {
      displayFolders = favoriteProv.folders.where((folder) {
        bool hasMatchingNotice = folder.notices.any(
              (n) => n.title.toLowerCase().contains(query),
        );
        bool hasMatchingSubNotice = folder.subFolders.any(
              (sub) =>
              sub.notices.any((n) => n.title.toLowerCase().contains(query)),
        );
        return hasMatchingNotice || hasMatchingSubNotice;
      }).toList();
    }

    return Scaffold(
      backgroundColor: Colors.white,
      floatingActionButton: FloatingActionButton(
        onPressed: () =>
            _showAddFolderDialog(context, favoriteProv),
        backgroundColor: const Color(0xFFFFC107),
        elevation: 4,
        child: const Icon(
          Icons.create_new_folder_rounded,
          size: 30,
          color: Colors.white,
        ),
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
            child: Row(
              children: [
                if (!_isSearching) ...[
                  const Icon(Icons.folder_special, color: Colors.orangeAccent),
                  const SizedBox(width: 8),
                ],
                Expanded(
                  child: _isSearching
                      ? TextField(
                    controller: _searchController,
                    autofocus: true,
                    decoration: const InputDecoration(
                      hintText: "즐겨찾기 내 검색...",
                      border: InputBorder.none,
                      hintStyle: TextStyle(
                        color: Colors.grey,
                        fontSize: 18,
                      ),
                    ),
                    style: const TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                    ),
                    onChanged: (value) =>
                        noticeProv.updateSearchQuery(value),
                  )
                      : const Text(
                    "즐겨찾기",
                    style: TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
                IconButton(
                  icon: Icon(
                    _isSearching ? Icons.close : Icons.search,
                    color: Colors.black54,
                  ),
                  onPressed: () {
                    setState(() {
                      if (_isSearching) {
                        _isSearching = false;
                        _searchController.clear();
                        noticeProv.updateSearchQuery("");
                      } else {
                        _isSearching = true;
                      }
                    });
                  },
                ),
              ],
            ),
          ),

          Expanded(
            child: favoriteProv.isLoading
                ? const Center(
              child: CircularProgressIndicator(),
            )
                : displayFolders.isEmpty
                ? Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Image.asset('assets/images/pigeon_sad_gray.png', width: 120),
                  const SizedBox(height: 16),
                  Text(
                    textAlign: TextAlign.center,
                    _isSearching ? "검색 결과가 없습니다." : "아무런 소식이 없어요.\n즐겨찾기를 등록해보세요.",
                    style: const TextStyle(
                      color: Colors.grey,
                      fontSize: 16,
                    ),
                  ),
                ],
              ),
            )
                : _isSearching
                ? ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: displayFolders.length,
              itemBuilder: (context, index) {
                return Container(
                  margin: const EdgeInsets.only(bottom: 12),
                  child: _buildFolderCard(
                    context,
                    favoriteProv,
                    displayFolders[index],
                    index,
                  ),
                );
              },
            )
                : ReorderableListView.builder(
              buildDefaultDragHandles: false,
              padding: const EdgeInsets.all(16),
              itemCount: displayFolders.length,
              onReorder: (oldIndex, newIndex) {
                favoriteProv.reorderFolders(oldIndex, newIndex);
              },
              itemBuilder: (context, index) {
                final folder = displayFolders[index];
                return Container(
                  // ReorderableListView의 자식은 반드시 고유한 Key를 가져야 합니다.
                  key: ValueKey('folder_${folder.folderId}'),
                  margin: const EdgeInsets.only(bottom: 12),
                  child: _buildFolderCard(
                    context,
                    favoriteProv,
                    folder,
                    index,
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildFolderCard(
      BuildContext context,
      FavoriteProvider prov,
      FavoriteFolder folder,
      int index,
      ) {
    int totalFolders = folder.subFolders.length;
    int totalNotices = folder.notices.length;
    int totalItems = totalFolders + totalNotices;
    final List<FavoriteFolder> allFolders = prov.folders;

    final String keywordText = folder.keywords.isEmpty
        ? "-"
        : "키워드: ${folder.keywords.join(', ')}";

    return Card(
      elevation: 0,
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: Color(0xFFEEEEEE)),
      ),
      child: ExpansionTile(
        key: PageStorageKey(folder.folderId),
        shape: const RoundedRectangleBorder(
          side: BorderSide(color: Colors.transparent),
        ),
        collapsedShape: const RoundedRectangleBorder(
          side: BorderSide(color: Colors.transparent),
        ),
        tilePadding: const EdgeInsets.only(
          left: 20,
          right: 8,
        ),
        leading: ReorderableDragStartListener(
          index: index,
          child: const Icon(
            Icons.folder_special,
            color: Colors.amber,
            size: 32,
          ),
        ),
        title: Text(
          folder.folderName,
          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
        ),
        subtitle: Text(
          "하위 폴더 $totalFolders개  |  소식 $totalNotices개  |  $keywordText",
          style: const TextStyle(fontSize: 12, color: Color(0xFF636363)),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            PopupMenuButton<Object>(
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(),
              onSelected: (value) async {
                if (value == 'add_sub')
                  _showAddFolderDialog(
                    context,
                    prov,
                    parentFolderId: folder.folderId,
                  );
                else if (value == 'rename')
                  _showRenameDialog(context, prov, folder);
                else if (value == 'delete')
                  prov.deleteFavoriteFolder(folder.folderId);
                else if (value == 'manage_keywords') {
                  _showKeywordManageBottomSheet(context, folder);
                }
                else if (value == 'clear') {
                  if (folder.notices.isEmpty) return;
                  final tasks = folder.notices
                      .map((n) => prov.clearFavoriteFolder(folder.folderId))
                      .toList();
                  await Future.wait(tasks);

                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('폴더를 비웠습니다.'),
                        duration: Duration(seconds: 1),
                      ),
                    );
                  }
                }
                else if (value == 'bulk_move_trigger') {
                  _showBulkMoveBottomSheet(context, prov, folder);
                }
              },
              itemBuilder: (context) => [
                const PopupMenuItem(value: 'add_sub', child: Text("하위 폴더 추가")),
                const PopupMenuItem(
                  value: 'manage_keywords',
                  child: Text("키워드 관리"),
                ),
                const PopupMenuItem(value: 'rename', child: Text("이름 바꾸기")),
                const PopupMenuItem(
                  value: 'clear',
                  child: Text("폴더 비우기"),
                ),
                const PopupMenuItem(
                  value: 'delete',
                  child: Text("폴더 삭제", style: TextStyle(color: Colors.red)),
                ),

                if (folder.notices.isNotEmpty) ...[
                  const PopupMenuDivider(),
                  const PopupMenuItem(
                    value: 'bulk_move_trigger',
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text("폴더 일괄 이동"),
                        Icon(Icons.chevron_right, size: 20, color: Colors.grey),
                      ],
                    ),
                  ),
                ],
              ],
            ),
          ],
        ),
        children: [
          ...folder.subFolders.map(
                (subFolder) =>
                _buildSubFolderTile(context, prov, subFolder, folder),
          ),
          ...folder.notices.map(
                (notice) =>
                _buildNoticeTile(context, prov, folder.folderId, notice),
          ),
          if (totalItems == 0)
            const ListTile(
              title: Text(
                "비어 있는 폴더입니다.",
                style: TextStyle(fontSize: 13, color: Colors.grey),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildSubFolderTile(
      BuildContext context,
      FavoriteProvider prov,
      FavoriteFolder subFolder,
      FavoriteFolder folder,
      ) {
    int totalNotices = subFolder.notices.length;
    final List<FavoriteFolder> allFolders = prov.folders;

    final String keywordText = subFolder.keywords.isEmpty
        ? "-"
        : "키워드: ${subFolder.keywords.join(', ')}";

    return Padding(
      padding: const EdgeInsets.only(left: 32.0),
      child: ExpansionTile(
        key: PageStorageKey(subFolder.folderId),
        shape: const RoundedRectangleBorder(
          side: BorderSide(color: Colors.transparent),
        ),
        collapsedShape: const RoundedRectangleBorder(
          side: BorderSide(color: Colors.transparent),
        ),

        tilePadding: const EdgeInsets.only(left: 20, right: 8),

        leading: const Icon(
          Icons.folder_special_outlined,
          color: Colors.amber,
          size: 28,
        ),

        title: Text(
          subFolder.folderName,
          style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w500),
        ),
        subtitle: Text(
          "소식 $totalNotices개  |  $keywordText",
          style: const TextStyle(fontSize: 12, color: Color(0xFF636363)),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),

        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            PopupMenuButton<Object>(
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(),
              onSelected: (value) async {
                if (value == 'rename')
                  _showRenameDialog(context, prov, subFolder);
                else if (value == 'delete')
                  prov.deleteFavoriteFolder(subFolder.folderId);
                else if (value == 'manage_keywords') {
                  _showKeywordManageBottomSheet(context, subFolder);
                }
                else if (value == 'clear') {
                  if (subFolder.notices.isEmpty) return;

                  final tasks = subFolder.notices
                      .map((n) => prov.clearFavoriteFolder(subFolder.folderId))
                      .toList();
                  await Future.wait(tasks);

                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('폴더를 비웠습니다.'),
                        duration: Duration(seconds: 1),
                      ),
                    );
                  }
                }
                else if (value == 'bulk_move_trigger') {
                  _showBulkMoveBottomSheet(context, prov, subFolder);
                }
              },
              itemBuilder: (context) => [
                const PopupMenuItem(
                  value: 'manage_keywords',
                  child: Text("키워드 관리"),
                ),
                const PopupMenuItem(value: 'rename', child: Text("이름 바꾸기")),
                const PopupMenuItem(
                  value: 'clear',
                  child: Text("폴더 비우기"),
                ),
                const PopupMenuItem(
                  value: 'delete',
                  child: Text("폴더 삭제", style: TextStyle(color: Colors.red)),
                ),

                if (subFolder.notices.isNotEmpty) ...[
                  const PopupMenuDivider(),
                  const PopupMenuItem(
                    value: 'bulk_move_trigger',
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text("폴더 일괄 이동"),
                        Icon(Icons.chevron_right, size: 20, color: Colors.grey),
                      ],
                    ),
                  ),
                ],
              ],
            ),
          ],
        ),
        children: subFolder.notices.isEmpty
            ? [
          const ListTile(
            title: Text(
              "저장된 공지가 없습니다.",
              style: TextStyle(fontSize: 13, color: Colors.grey),
            ),
          ),
        ]
            : subFolder.notices
            .map(
              (notice) => _buildNoticeTile(
            context,
            prov,
            subFolder.folderId,
            notice,
          ),
        )
            .toList(),
      ),
    );
  }

  Widget _buildNoticeTile(
      BuildContext context,
      FavoriteProvider prov,
      int folderId,
      FavoriteNotice notice,
      ) {
    final List<FavoriteFolder> allFolders = prov.folders;

    return Padding(
      padding: const EdgeInsets.only(left: 8.0),
      child: ListTile(
        contentPadding: const EdgeInsets.only(left: 20, right: 8),
        title: Text(
          notice.title,
          style: const TextStyle(fontSize: 14, color: Color(0xFF424242)),
          maxLines: 3,
          overflow: TextOverflow.ellipsis,
        ),
        subtitle: Text(
          NoticeDisplayFormatter.favoriteMetadata(
            author: notice.author,
            publishedAt: notice.publishedAt,
            createdAt: notice.createdAt,
          ),
          style: const TextStyle(fontSize: 12, color: Color(0xFF636363)),
        ),
        onTap: () => launchUrl(
          Uri.parse(notice.url),
          mode: LaunchMode.externalApplication,
        ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            PopupMenuButton<Object>(
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(),
              icon: const Icon(Icons.more_vert, color: Colors.grey, size: 20),
              onSelected: (val) {
                if (val == "DELETE") {
                  prov.removeNoticeFromFolder(folderId, notice.noticeId);
                } else if (val == "MOVE") {
                  _showNoticeMoveBottomSheet(context, prov, folderId, notice);
                }
              },
              itemBuilder: (context) => [
                const PopupMenuItem(
                  value: "DELETE",
                  child: Text("삭제", style: TextStyle(color: Colors.red)),
                ),
                if (allFolders.isNotEmpty) ...[
                  const PopupMenuDivider(),
                  const PopupMenuItem(
                    value: "MOVE",
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text("폴더 이동"),
                        Icon(Icons.chevron_right, size: 20, color: Colors.grey),
                      ],
                    ),
                  ),
                ],
              ],
            ),
          ],
        ),
      ),
    );
  }
}
