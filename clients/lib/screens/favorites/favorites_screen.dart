import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../providers/favorite_provider.dart';
import '../../providers/notice_provider.dart';
import '../../models/favorite_folder_model.dart';
import '../../models/favorite_notice_model.dart';

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
    // 화면이 처음 렌더링될 때 서버에서 최신 폴더 트리를 불러옵니다.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<FavoriteProvider>().loadFavorites();
    });
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  // 폴더 추가 다이얼로그 (1단계, 2단계 공통 사용)
  void _showAddFolderDialog(BuildContext context, FavoriteProvider prov, {int? parentFolderId}) {
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
          TextButton(onPressed: () => Navigator.pop(context), child: const Text("취소")),
          TextButton(
            onPressed: () {
              if (controller.text.isNotEmpty) {
                // API 연동 Provider 함수 호출
                prov.createFavoriteFolder(controller.text, parentFolderId: parentFolderId);
                Navigator.pop(context);
              }
            },
            child: const Text("추가", style: TextStyle(color: Colors.blue)),
          ),
        ],
      ),
    );
  }

  // 폴더 이름 변경 다이얼로그 (이제 oldName 대신 folderId를 사용합니다)
  void _showRenameDialog(BuildContext context, FavoriteProvider prov, FavoriteFolder folder) {
    final TextEditingController controller = TextEditingController(text: folder.folderName);
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
          TextButton(onPressed: () => Navigator.pop(context), child: const Text("취소")),
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

  // 💡 모바일 사용성에 맞게 다이얼로그에서 바텀 시트로 변경된 키워드 관리 기능
  void _showKeywordManageBottomSheet(BuildContext context, FavoriteFolder folder) {
    // 함수 내부에서 컨트롤러를 선언하여 메모리 누수 및 상태 꼬임 방지
    final TextEditingController controller = TextEditingController();

    showModalBottomSheet(
      context: context,
      isScrollControlled: true, // 키보드가 올라올 때 바텀시트가 전체 화면 영역을 활용하도록 설정
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setModalState) {
            // 💡 수동 배열 조작 대신, Provider를 구독하여 서버 통신 결과가 즉각 UI에 반영되도록 설계
            final favoriteProv = context.watch<FavoriteProvider>();

            // 현재 바텀시트가 보고 있는 폴더의 최신 키워드 목록 추출
            final List<String> keywords = favoriteProv.getKeywordsForFolder(folder.folderId);

            return Padding(
              padding: EdgeInsets.only(
                left: 20, right: 20, top: 20,
                // 💡 기기 하단 키보드가 올라올 때, 입력창이 가려지지 않도록 동적 여백 확보
                bottom: MediaQuery.of(context).viewInsets.bottom + 20,
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min, // 콘텐츠 높이만큼만 공간 차지
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                      "${folder.folderName} 키워드",
                      style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)
                  ),
                  const SizedBox(height: 15),

                  // 1. 새 키워드 입력 필드 (버튼을 텍스트 필드 내부로 통합하여 UI 깔끔하게 처리)
                  TextField(
                    controller: controller,
                    // 💡 사용자가 입력하는 텍스트의 색상을 설정합니다.
                    style: const TextStyle(color: Color(0xFF636363), fontSize: 16),
                    decoration: InputDecoration(
                      hintText: "새 키워드 입력",
                      // 💡 힌트 텍스트(안내 문구)의 색상을 설정합니다.
                      hintStyle: const TextStyle(color: Color(0xFF636363), fontSize: 14),

                      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                      suffixIcon: IconButton(
                        // 💡 아이콘 색상도 텍스트와 통일감을 주려면 수정할 수 있습니다.
                        icon: const Icon(Icons.add_circle, color: Color(0xFF636363)),
                        onPressed: () async {
                          final text = controller.text.trim();
                          if (text.isNotEmpty && !keywords.contains(text)) {
                            await favoriteProv.addKeywordToFolder(folder.folderId, text);
                            controller.clear();
                            setModalState(() {});
                          }
                        },
                      ),
                    ),
                  ),
                  const SizedBox(height: 20),

                  // 2. 등록된 키워드 목록 영역

                  if (favoriteProv.isLoading)
                    const Center(child: Padding(
                      padding: EdgeInsets.all(16.0),
                      child: CircularProgressIndicator(),
                    ))
                  else if (keywords.isEmpty)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 8.0),
                      child: Text("등록된 키워드가 없습니다.", style: TextStyle(color: Colors.grey, fontSize: 14)),
                    )
                  else
                  // ListView 대신 Wrap과 InputChip을 사용하여 해시태그처럼 직관적인 UI 제공
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: keywords.map((k) => InputChip(
                        label: Text(k),
                        onDeleted: () async {
                          // API 연동 삭제 호출
                          await favoriteProv.removeKeywordFromFolder(folder.folderId, k);
                          setModalState(() {});
                        },
                        deleteIconColor: Colors.redAccent,
                        backgroundColor: Colors.grey[100],
                        side: BorderSide(color: Colors.grey[300]!),
                      )).toList(),
                    ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  // 💡 신규 추가: 일괄 이동을 위한 대상 폴더 선택 바텀 시트
  // 💡 구독 화면용: 일괄 이동 대상 폴더 선택 바텀 시트 (2뎁스 포함)
  void _showBulkMoveBottomSheet(BuildContext context, FavoriteProvider prov, FavoriteFolder sourceFolder) {
    final List<FavoriteFolder> allFolders = prov.folders;

    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (context) {
        return Container(
          padding: const EdgeInsets.symmetric(vertical: 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text("이동할 대상 폴더 선택", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 10),
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  children: allFolders.expand((f) => [
                    // 자기 자신 폴더는 제외
                    if (f.folderId != sourceFolder.folderId)
                      ListTile(
                        leading: const Icon(Icons.folder, color: Colors.amber),
                        title: Text(f.folderName),
                        onTap: () => _executeBulkMove(context, prov, sourceFolder.folderId, f.folderId),
                      ),
                    // 하위 폴더 탐색
                    ...f.subFolders.where((sub) => sub.folderId != sourceFolder.folderId).map((sub) =>
                        ListTile(
                          contentPadding: const EdgeInsets.only(left: 40, right: 16),
                          leading: const Icon(Icons.subdirectory_arrow_right, color: Colors.grey),
                          title: Text(sub.folderName),
                          onTap: () => _executeBulkMove(context, prov, sourceFolder.folderId, sub.folderId),
                        )
                    ),
                  ]).toList(),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  // 일괄 이동 실행 로직 분리
  Future<void> _executeBulkMove(BuildContext context, FavoriteProvider prov, int sourceId, int targetId) async {
    Navigator.pop(context); // 바텀 시트 닫기
    await prov.moveAllNotices(sourceId, targetId);
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('모든 공지가 이동되었습니다.'), duration: Duration(seconds: 1)),
      );
    }
  }

  // 💡 즐겨찾기 내 개별 공지 이동 실행 로직
  Future<void> _executeNoticeMove(
      BuildContext context,
      FavoriteProvider prov,
      int sourceFolderId,
      int targetFolderId,
      FavoriteNotice notice) async {

    Navigator.pop(context); // 폴더 선택 바텀 시트 닫기

    // 1. 새 폴더에 추가 및 기존 폴더에서 삭제
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

  // 💡 즐겨찾기 내 공지용 폴더 선택 바텀 시트
  void _showNoticeMoveBottomSheet(
      BuildContext parentContext,
      FavoriteProvider prov,
      int sourceFolderId,
      FavoriteNotice notice) {

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
              const Text("이동할 대상 폴더 선택", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 10),
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  children: allFolders.expand((f) => [
                    // 현재 속한 폴더는 제외하고 표시
                    if (f.folderId != sourceFolderId)
                      ListTile(
                        leading: const Icon(Icons.folder, color: Colors.amber),
                        title: Text(f.folderName),
                        onTap: () => _executeNoticeMove(parentContext, prov, sourceFolderId, f.folderId, notice),
                      ),
                    // 하위 폴더들 (2단계)
                    ...f.subFolders.where((sub) => sub.folderId != sourceFolderId).map((sub) =>
                        ListTile(
                          contentPadding: const EdgeInsets.only(left: 40, right: 16),
                          leading: const Icon(Icons.subdirectory_arrow_right, color: Colors.grey),
                          title: Text(sub.folderName),
                          onTap: () => _executeNoticeMove(parentContext, prov, sourceFolderId, sub.folderId, notice),
                        )
                    ),
                  ]).toList(),
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

    // MVP용 간단한 검색 필터링 로직 (1단계 폴더 내 공지사항 제목 기준)
    List<FavoriteFolder> displayFolders = favoriteProv.folders;
    if (query.isNotEmpty) {
      displayFolders = favoriteProv.folders.where((folder) {
        bool hasMatchingNotice = folder.notices.any((n) => n.title.toLowerCase().contains(query));
        bool hasMatchingSubNotice = folder.subFolders.any((sub) => sub.notices.any((n) => n.title.toLowerCase().contains(query)));
        return hasMatchingNotice || hasMatchingSubNotice;
      }).toList();
    }

    return Scaffold(
      backgroundColor: Colors.white,
      floatingActionButton: FloatingActionButton(
        onPressed: () => _showAddFolderDialog(context, favoriteProv), // 최상위 폴더 생성
        backgroundColor: const Color(0xFFFFC107),
        elevation: 4,
        child: const Icon(Icons.create_new_folder_rounded, size: 30, color: Colors.white),
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 상단 헤더 영역 (기존 유지)
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
                      hintStyle: TextStyle(color: Colors.grey, fontSize: 18),
                    ),
                    style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                    onChanged: (value) => noticeProv.updateSearchQuery(value),
                  )
                      : const Text("즐겨찾기", style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
                ),
                IconButton(
                  icon: Icon(_isSearching ? Icons.close : Icons.search, color: Colors.black54),
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

          // 리스트 영역
          Expanded(
            child: favoriteProv.isLoading
                ? const Center(child: CircularProgressIndicator()) // API 로딩 인디케이터
                : displayFolders.isEmpty
                ? Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.folder_special, size: 64, color: Colors.grey[300]),
                  const SizedBox(height: 16),
                  Text(
                    _isSearching ? "검색 결과가 없습니다." : "즐겨찾기를 등록해보세요.",
                    style: const TextStyle(color: Colors.grey, fontSize: 16),
                  ),
                ],
              ),
            )
            // 💡 검색 여부에 따라 안전하게 분기 처리합니다.
                : _isSearching
                ? ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: displayFolders.length,
              itemBuilder: (context, index) {
                return Container(
                  margin: const EdgeInsets.only(bottom: 12),
                  child: _buildFolderCard(context, favoriteProv, displayFolders[index], index),
                );
              },
            )
                : ReorderableListView.builder(
              buildDefaultDragHandles: false, // 이 줄을 추가합니다.
              padding: const EdgeInsets.all(16),
              itemCount: displayFolders.length,
              // 💡 드래그 앤 드롭 이벤트 발생 시 Provider의 순서 변경 로직을 호출합니다.
              onReorder: (oldIndex, newIndex) {
                favoriteProv.reorderFolders(oldIndex, newIndex);
              },
              itemBuilder: (context, index) {
                final folder = displayFolders[index];
                return Container(
                  // 💡 [핵심] ReorderableListView의 자식은 반드시 고유한 Key를 가져야 합니다.
                  key: ValueKey('folder_${folder.folderId}'),
                  margin: const EdgeInsets.only(bottom: 12),
                  child: _buildFolderCard(context, favoriteProv, folder, index),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  // 폴더 카드 빌더 (1단계 최상위 폴더)
  Widget _buildFolderCard(BuildContext context, FavoriteProvider prov, FavoriteFolder folder, int index) {
    int totalFolders = folder.subFolders.length;
    int totalNotices = folder.notices.length;
    int totalItems = totalFolders + totalNotices;
    final List<FavoriteFolder> allFolders = prov.folders; // 전체 폴더 목록

    // 💡 1. 키워드 리스트를 UI용 텍스트로 변환하는 로직 추가
    final String keywordText = folder.keywords.isEmpty
        ? "-"
        : "키워드: ${folder.keywords.join(', ')}";

    return Card(
      elevation: 0,
      margin: const EdgeInsets.only(bottom: 12), // 💡 여백 통일
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: Color(0xFFEEEEEE)),
      ),
      child: ExpansionTile(
        key: PageStorageKey(folder.folderId),
        shape: const RoundedRectangleBorder(side: BorderSide(color: Colors.transparent)),
        collapsedShape: const RoundedRectangleBorder(side: BorderSide(color: Colors.transparent)),
        tilePadding: const EdgeInsets.only(left: 20, right: 8), // 💡 우측 여백 8 부여 (구독 목록과 일치)
        // leading 부분을 ReorderableDragStartListener로 감싸줍니다.
        leading: ReorderableDragStartListener(
          index: index,
          child: const Icon(Icons.folder_special, color: Colors.amber, size: 32),
        ),
        title: Text(
            folder.folderName,
            style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)
        ),
        // 💡 2. subtitle 위젯을 키워드 표시용으로 교체
        subtitle: Text(
          "하위 폴더 $totalFolders개  |  소식 $totalNotices개  |  $keywordText",
          style: const TextStyle(fontSize: 12, color: Color(0xFF636363)),
          maxLines: 1, // 키워드가 너무 길어지면 한 줄로 처리 (UI 깨짐 방지)
          overflow: TextOverflow.ellipsis,
        ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            PopupMenuButton<Object>( // 💡 String에서 Object로 변경하여 ID(int) 처리
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(),
              onSelected: (value) async {
                if (value == 'add_sub') _showAddFolderDialog(context, prov, parentFolderId: folder.folderId);
                else if (value == 'rename') _showRenameDialog(context, prov, folder);
                else if (value == 'delete') prov.deleteFavoriteFolder(folder.folderId);
                // 💡 [기능 추가] 키워드 관리
                else if (value == 'manage_keywords') {
                  _showKeywordManageBottomSheet(context, folder);
                }
                // 💡 [기능 추가] 폴더 비우기
                else if (value == 'clear') {
                  if (folder.notices.isEmpty) return;
                  final tasks = folder.notices.map((n) => prov.clearFavoriteFolder(folder.folderId)).toList();
                  await Future.wait(tasks);

                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('폴더를 비웠습니다.'), duration: Duration(seconds: 1)),
                    );
                  }
                }
                // 💡 [변경] 일괄 이동은 전용 UI로 연결
                else if (value == 'bulk_move_trigger') {
                  _showBulkMoveBottomSheet(context, prov, folder);
                }
              },
              itemBuilder: (context) => [
                const PopupMenuItem(value: 'add_sub', child: Text("하위 폴더 추가")),
                const PopupMenuItem(value: 'manage_keywords', child: Text("키워드 관리")), // 💡 신규
                const PopupMenuItem(value: 'rename', child: Text("이름 바꾸기")),
                const PopupMenuItem(value: 'clear', child: Text("폴더 비우기")), // 💡 신규
                const PopupMenuItem(value: 'delete', child: Text("폴더 삭제", style: TextStyle(color: Colors.red))),

                // 💡 [변경] 복잡한 리스트 대신 단일 메뉴로 구성
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
                      )
                  ),
                ],
              ],
            ),
          ],
        ),
        children: [
          ...folder.subFolders.map((subFolder) => _buildSubFolderTile(context, prov, subFolder, folder)),
          ...folder.notices.map((notice) => _buildNoticeTile(context, prov, folder.folderId, notice)),
          if (totalItems == 0)
            const ListTile(title: Text("비어 있는 폴더입니다.", style: TextStyle(fontSize: 13, color: Colors.grey))),
        ],
      ),
    );
  }

  // 하위 폴더 타일 빌더 (2 Depth 폴더)
  Widget _buildSubFolderTile(BuildContext context, FavoriteProvider prov, FavoriteFolder subFolder, FavoriteFolder folder) {


    int totalNotices = subFolder.notices.length;
    final List<FavoriteFolder> allFolders = prov.folders;

    // 💡 하위 폴더용 키워드 텍스트 추출
    final String keywordText = subFolder.keywords.isEmpty
        ? "-"
        : "키워드: ${subFolder.keywords.join(', ')}";

    return Padding(
      padding: const EdgeInsets.only(left: 32.0), // 계층 표현을 위한 좌측 여백 유지
      child: ExpansionTile(
        key: PageStorageKey(subFolder.folderId),
        shape: const RoundedRectangleBorder(side: BorderSide(color: Colors.transparent)),
        collapsedShape: const RoundedRectangleBorder(side: BorderSide(color: Colors.transparent)),

        // 💡 [수정] 부모 카드와 동일하게 우측 여백을 8로 설정하여 버튼 위치를 맞춥니다.
        tilePadding: const EdgeInsets.only(left: 20, right: 8),

        // 💡 [수정] 아이콘 크기를 28 정도로 조정하여 1단계(32)와 차이를 주되 정렬감을 유지합니다.
        leading: const Icon(Icons.folder_special_outlined, color: Colors.amber, size: 28),

        title: Text(
            subFolder.folderName,
            style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w500)
        ),
        // 💡 2단계 폴더에도 subtitle 추가
        subtitle: Text(
          "소식 $totalNotices개  |  $keywordText",
          style: const TextStyle(fontSize: 12, color: Color(0xFF636363)),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),

        // 💡 [수정] Row 구조와 PopupMenuButton 설정을 부모 카드와 100% 일치시킵니다.
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            PopupMenuButton<Object>(
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(),
              onSelected: (value) async {
                if (value == 'rename') _showRenameDialog(context, prov, subFolder);
                else if (value == 'delete') prov.deleteFavoriteFolder(subFolder.folderId);
                // 💡 [기능 추가] 키워드 관리
                else if (value == 'manage_keywords') {
                  _showKeywordManageBottomSheet(context, subFolder);
                }
                // 💡 [기능 추가] 폴더 비우기
                else if (value == 'clear') {
                  if (subFolder.notices.isEmpty) return;

                  final tasks = subFolder.notices.map(
                          (n) => prov.clearFavoriteFolder(subFolder.folderId)
                  ).toList();
                  await Future.wait(tasks);

                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('폴더를 비웠습니다.'), duration: Duration(seconds: 1)),
                    );
                  }
                }
                // 💡 [변경] 일괄 이동은 전용 UI로 연결
                else if (value == 'bulk_move_trigger') {
                  _showBulkMoveBottomSheet(context, prov, subFolder);
                }
              },
              itemBuilder: (context) => [
                const PopupMenuItem(value: 'manage_keywords', child: Text("키워드 관리")), // 💡 신규
                const PopupMenuItem(value: 'rename', child: Text("이름 바꾸기")),
                const PopupMenuItem(value: 'clear', child: Text("폴더 비우기")), // 💡 신규
                const PopupMenuItem(value: 'delete', child: Text("폴더 삭제", style: TextStyle(color: Colors.red))),

                // 💡 [변경] 복잡한 리스트 대신 단일 메뉴로 구성
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
                      )
                  ),
                ],
              ],
            ),
          ],
        ),
        children: subFolder.notices.isEmpty
            ? [const ListTile(title: Text("저장된 공지가 없습니다.", style: TextStyle(fontSize: 13, color: Colors.grey)))]
            : subFolder.notices.map((notice) => _buildNoticeTile(context, prov, subFolder.folderId, notice)).toList(),
      ),
    );
  }

  // 공지사항 타일 빌더 (고도화 버전)
  Widget _buildNoticeTile(BuildContext context, FavoriteProvider prov, int folderId, FavoriteNotice notice) {
    final List<FavoriteFolder> allFolders = prov.folders;

    return Padding(
      padding: const EdgeInsets.only(left: 8.0),
      child: ListTile(
        contentPadding: const EdgeInsets.only(left: 20, right: 8),
        title: Row(
          children: [
            const Text("└ ", style: TextStyle(color: Colors.grey, fontWeight: FontWeight.bold)),
            Expanded(
              child: Text(
                  notice.title,
                  style: const TextStyle(fontSize: 14, color: Color(0xFF424242)),
                  // maxLines: 1,
                  // overflow: TextOverflow.ellipsis
              ),
            ),
          ],
        ),
        onTap: () => launchUrl(Uri.parse(notice.url), mode: LaunchMode.externalApplication),
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
                }
                else if (val == "MOVE") {
                  // 💡 바텀 시트 호출 (2단계 뎁스로 이동 대상 선택)
                  _showNoticeMoveBottomSheet(context, prov, folderId, notice);
                }
              },
              itemBuilder: (context) => [
                const PopupMenuItem(value: "DELETE", child: Text("삭제", style: TextStyle(color: Colors.red))),
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
                      )
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