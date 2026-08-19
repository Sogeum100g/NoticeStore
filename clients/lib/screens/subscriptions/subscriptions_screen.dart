import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../models/favorite_folder_model.dart'; // 💡 새로 추가된 모델 임포트
import '../../models/site_model.dart';
import '../../providers/auth_provider.dart';
import '../../providers/favorite_provider.dart';
import '../../providers/notice_provider.dart';
import '../../services/preferences_service.dart';

class _CrawlStatusStyle {
  final Color color;
  final IconData icon;

  const _CrawlStatusStyle({
    required this.color,
    required this.icon,
  });

  factory _CrawlStatusStyle.forStatus(SiteCrawlStatus status) {
    return switch (status) {
      SiteCrawlStatus.pending => const _CrawlStatusStyle(
        color: Color(0xFF9A6A00),
        icon: Icons.hourglass_top_rounded,
      ),
      SiteCrawlStatus.paused => const _CrawlStatusStyle(
        color: Color(0xFF616161),
        icon: Icons.pause_circle_outline,
      ),
      SiteCrawlStatus.failed => const _CrawlStatusStyle(
        color: Color(0xFFB3261E),
        icon: Icons.error_outline_rounded,
      ),
      SiteCrawlStatus.blocked => const _CrawlStatusStyle(
        color: Color(0xFF6D5D00),
        icon: Icons.block_outlined,
      ),
      SiteCrawlStatus.active => const _CrawlStatusStyle(
        color: Color(0xFF616161),
        icon: Icons.info_outline,
      ),
      SiteCrawlStatus.unknown => const _CrawlStatusStyle(
        color: Color(0xFF616161),
        icon: Icons.info_outline,
      ),
    };
  }
}

class SubscriptionsScreen extends StatefulWidget {
  const SubscriptionsScreen({super.key});

  @override
  State<SubscriptionsScreen> createState() => _SubscriptionsScreenState();
}

class _SubscriptionsScreenState extends State<SubscriptionsScreen> {
  bool _isSearching = false;
  final TextEditingController _searchController = TextEditingController();

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  // 별명 변경 다이얼로그
  void _showRenameDialog(BuildContext context, NoticeProvider prov, String oldName) {
    final TextEditingController controller = TextEditingController(text: oldName);
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text("구독 별명 변경"),
        content: TextField(
          controller: controller,
          decoration: const InputDecoration(hintText: "새로운 별명을 입력하세요"),
          autofocus: true,
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text("취소")),
          TextButton(
            onPressed: () async {
              if (controller.text.isNotEmpty) {
                await prov.renameSubscriptionAlias(oldName, controller.text);
              }
              Navigator.pop(context);
            },
            child: const Text("변경"),
          ),
        ],
      ),
    );
  }

  // 💡 1. 일괄 이동 실행 로직 (Navigator.pop 제거됨)
  Future<void> _executeKeywordBulkMove(
      BuildContext context,
      FavoriteProvider fProv,
      int targetFolderId,
      List<Map<String, dynamic>> items,
      List<FavoriteFolder> folders) async {

    String targetFolderName = "알 수 없는 폴더";
    for (var f in folders) {
      if (f.folderId == targetFolderId) targetFolderName = f.folderName;
      for (var sub in f.subFolders) {
        if (sub.folderId == targetFolderId) targetFolderName = sub.folderName;
      }
    }

    List<String> folderKeywords = fProv.getKeywordsForFolder(targetFolderId);
    List<Future<void>> moveTasks = [];

    int matchCount = 0; // 키워드에 일치하는 전체 공지 수
    int newMoveCount = 0; // 실제로 새롭게 이동될 공지 수

    for (var notice in items) {
      final title = notice['title'].toString().toLowerCase();
      final noticeId = notice['notice_id'] as int;

      bool isKeywordMatched = folderKeywords.isEmpty ||
          folderKeywords.any((keyword) => title.contains(keyword.toLowerCase()));

      if (isKeywordMatched) {
        matchCount++;

        // 💡 프론트엔드 사전 검증: 이미 폴더에 해당 공지가 존재하는지 확인
        bool isAlreadyExist = false;
        for (var f in folders) {
          if (f.folderId == targetFolderId && f.notices.any((n) => n.noticeId == noticeId)) {
            isAlreadyExist = true;
          }
          for (var sub in f.subFolders) {
            if (sub.folderId == targetFolderId && sub.notices.any((n) => n.noticeId == noticeId)) {
              isAlreadyExist = true;
            }
          }
        }

        // 중복이 아닐 경우에만 API 호출 리스트에 추가
        if (!isAlreadyExist) {
          moveTasks.add(fProv.addNoticeToFolder(targetFolderId, noticeId));
          newMoveCount++;
        }
      }
    }

    // 통신 실행
    if (moveTasks.isNotEmpty) {
      try {
        await Future.wait(moveTasks);
      } catch (e) {
        debugPrint("❌ 일괄 이동 처리 중 에러: $e");
      }
    }

    if (context.mounted) {
      String message;
      if (newMoveCount > 0) {
        message = "$targetFolderName 폴더로 $newMoveCount개의 공지가 이동되었습니다.";
      } else if (matchCount > 0 && newMoveCount == 0) {
        // 💡 필터링은 되었으나 모두 이미 추가된 공지일 경우
        message = "이미 모두 이동되었습니다.";
      } else {
        message = folderKeywords.isEmpty
            ? '이동할 공지가 없습니다.'
            : '키워드(${folderKeywords.join(', ')})에 일치하는 공지가 없습니다.';
      }

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(message),
          duration: const Duration(seconds: 2),
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }
  // 💡 2. 일괄 이동 바텀 시트 (context 분리)
  void _showBulkMoveBottomSheet(
      BuildContext parentContext, // 부모 화면의 context
      FavoriteProvider fProv,
      List<Map<String, dynamic>> items,
      List<FavoriteFolder> folders) {
    showModalBottomSheet(
      context: parentContext,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (sheetContext) { // 💡 바텀 시트 전용 context로 이름 변경
        return Container(
          padding: const EdgeInsets.symmetric(vertical: 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text("키워드 일괄 이동", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 10),
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  children: folders.expand((f) => [
                    ListTile(
                      leading: const Icon(Icons.folder, color: Colors.amber),
                      title: Text(f.folderName),
                      onTap: () {
                        // 1. 바텀 시트의 context로 창을 먼저 닫음
                        Navigator.pop(sheetContext);
                        // 2. 부모 화면의 context를 넘겨 비동기 작업 실행
                        _executeKeywordBulkMove(parentContext, fProv, f.folderId, items, folders);
                      },
                    ),
                    ...f.subFolders.map((sub) =>
                        ListTile(
                          contentPadding: const EdgeInsets.only(left: 40, right: 16),
                          leading: const Icon(Icons.folder_special_outlined, color: Colors.amber),
                          title: Text(sub.folderName),
                          onTap: () {
                            Navigator.pop(sheetContext);
                            _executeKeywordBulkMove(parentContext, fProv, sub.folderId, items, folders);
                          },
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

  // 💡 3. 개별 이동 실행 로직 (Navigator.pop 제거됨)
  Future<void> _executeIndividualNoticeMove(
      BuildContext context,
      FavoriteProvider fProv,
      int targetFolderId,
      int noticeId,
      List<FavoriteFolder> folders) async {

    String targetFolderName = "알 수 없는 폴더";
    bool isAlreadyExist = false; // 💡 중복 여부 플래그

    for (var f in folders) {
      if (f.folderId == targetFolderId) {
        targetFolderName = f.folderName;
        // 1단계 폴더 내 중복 검사
        if (f.notices.any((n) => n.noticeId == noticeId)) isAlreadyExist = true;
      }
      for (var sub in f.subFolders) {
        if (sub.folderId == targetFolderId) {
          targetFolderName = sub.folderName;
          // 2단계 폴더 내 중복 검사
          if (sub.notices.any((n) => n.noticeId == noticeId)) isAlreadyExist = true;
        }
      }
    }

    // 💡 사전 검증 완료: 중복이면 서버로 요청을 보내지 않고 즉시 스낵바 표시 후 종료
    if (isAlreadyExist) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("이미 해당 폴더에 존재하는 공지입니다."),
            duration: Duration(seconds: 1),
            behavior: SnackBarBehavior.floating,
          ),
        );
      }
      return;
    }

    // 중복이 아닐 때만 실제 통신 발생
    await fProv.addNoticeToFolder(targetFolderId, noticeId);

    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text("$targetFolderName 폴더에 추가되었습니다."),
          duration: const Duration(seconds: 1),
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  // 💡 4. 개별 이동 바텀 시트 (context 분리)
  void _showIndividualMoveBottomSheet(
      BuildContext parentContext, // 부모 화면의 context
      FavoriteProvider fProv,
      int noticeId,
      List<FavoriteFolder> folders) {
    showModalBottomSheet(
      context: parentContext,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (sheetContext) { // 💡 바텀 시트 전용 context
        return Container(
          padding: const EdgeInsets.symmetric(vertical: 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text("즐겨찾기 폴더 선택", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 10),
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  children: folders.expand((f) => [
                    ListTile(
                      leading: const Icon(Icons.folder, color: Colors.amber),
                      title: Text(f.folderName),
                      onTap: () {
                        Navigator.pop(sheetContext);
                        _executeIndividualNoticeMove(parentContext, fProv, f.folderId, noticeId, folders);
                      },
                    ),
                    ...f.subFolders.map((sub) =>
                        ListTile(
                          contentPadding: const EdgeInsets.only(left: 40, right: 16),
                          leading: const Icon(Icons.folder_special_outlined, color: Colors.amber),
                          title: Text(sub.folderName),
                          onTap: () {
                            Navigator.pop(sheetContext);
                            _executeIndividualNoticeMove(parentContext, fProv, sub.folderId, noticeId, folders);
                          },
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
    final noticeProv = context.watch<NoticeProvider>();
    final favoriteProv = context.watch<FavoriteProvider>();

    // 💡 [핵심 추가] 상태 관리를 통해 로그인된 유저 정보를 가져옵니다.
    // 실제 프로젝트에서 사용 중인 유저 관련 Provider 이름으로 맞춰주세요.
    // 💡 [수정] UserProvider 대신 프로젝트에 있는 AuthProvider를 사용합니다.
    final authProv = context.watch<AuthProvider>();

    // 💡 AuthProvider 내부에 유저 정보를 담고 있는 변수명(예: user)을 통해 상한선을 가져옵니다.
    // 변수명이 user가 아니라 currentUser 등이라면 그에 맞게 변경해 주세요.
    final int maxSitesLimit = authProv.user!.maxSitesLimit;
    final String? nick = authProv.user!.nickname;

    print("nick : ${nick}");
    print("maxSitesLimit : ${maxSitesLimit}");

    final String query = noticeProv.searchQuery.toLowerCase();
    Map<String, List<Map<String, dynamic>>> filteredNotices = {};

    noticeProv.notices.forEach((key, value) {
      final matched = value.where((n) =>
          n['title'].toString().toLowerCase().contains(query)).toList();
      if (query.isEmpty || matched.isNotEmpty) {
        filteredNotices[key] = query.isEmpty ? value : matched;
      }
    });

    final siteNames = filteredNotices.keys.toList();
    final List<FavoriteFolder> currentFolders = favoriteProv.folders;

    // 현재 사용자가 구독 중인 실제 사이트(폴더) 개수
    final int currentSubscriptionCount = noticeProv.notices.length;

    return Scaffold(
      backgroundColor: Colors.white,
      body: Column(
        children: [
          // 상단 헤더
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
            child: Row(
              children: [
                if (!_isSearching) ...[
                  const Icon(Icons.subscriptions_outlined, color: Colors.orangeAccent),
                  const SizedBox(width: 8),
                ],
                Expanded(
                  child: _isSearching
                      ? TextField(
                    controller: _searchController,
                    autofocus: true,
                    decoration: const InputDecoration(hintText: "구독 내 공지 검색...", border: InputBorder.none),
                    onChanged: (val) => noticeProv.updateSearchQuery(val),
                  )
                      : Row(
                    crossAxisAlignment: CrossAxisAlignment.center,
                    children: [
                      const Text("구독 목록", style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
                      const SizedBox(width: 8),
                      // 💡 [수정된 부분] 현재 구독 개수 / 사용자별 최대 상한선 표시
                      Text(
                        "$currentSubscriptionCount / $maxSitesLimit",
                        style: TextStyle(
                          fontSize: 20,
                          fontWeight: FontWeight.bold,
                          // UX 개선: 한도에 도달하면 붉은색으로 경고, 아니면 기본 주황색
                          color: currentSubscriptionCount >= maxSitesLimit
                              ? Colors.redAccent
                              : const Color(0xFF636363),
                        ),
                      ),
                    ],
                  ),
                ),
                IconButton(
                  icon: Icon(_isSearching ? Icons.close : Icons.search),
                  onPressed: () {
                    setState(() => _isSearching = !_isSearching);
                    if (!_isSearching) {
                      _searchController.clear();
                      noticeProv.updateSearchQuery("");
                    }
                  },
                ),
              ],
            ),
          ),

          // 리스트 영역
          Expanded(
            child: RefreshIndicator(
              onRefresh: () async {
                // 서버에서 최신 공지를 가져오는 함수 호출
                await noticeProv.fetchNoticesFromServer();
              },
              // 데이터가 없을 때와 있을 때 모두 RefreshIndicator 안에서 분기 처리
              child: siteNames.isEmpty
                  ? CustomScrollView(
                // 빈 화면에서도 스크롤(당기기)이 가능하도록 강제 설정
                physics: const AlwaysScrollableScrollPhysics(),
                slivers: [
                  SliverFillRemaining(
                    child: Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(
                            Icons.folder_special_outlined,
                            size: 64,
                            color: Colors.grey[300],
                          ),
                          const SizedBox(height: 16),
                          const Text(
                            "추가 탭에서 웹페이지를 등록해보세요.",
                            style: TextStyle(
                              color: Colors.grey,
                              fontSize: 16,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              )
                  : ReorderableListView.builder(
                // 아이템 개수가 적어 화면을 덜 채워도 당겨서 새로고침이 가능하도록 설정
                physics: const AlwaysScrollableScrollPhysics(),
                buildDefaultDragHandles: false,
                padding: const EdgeInsets.all(16),
                itemCount: siteNames.length,
                onReorder: (oldIndex, newIndex) => noticeProv.reorderSubscriptions(oldIndex, newIndex),
                itemBuilder: (context, index) {
                  String siteName = siteNames[index];
                  List<Map<String, dynamic>> items = filteredNotices[siteName]!;

                  return Container(
                    key: ValueKey(siteName),
                    margin: const EdgeInsets.only(bottom: 12),
                    child: _buildSubscriptionCard(
                      context,
                      noticeProv,
                      favoriteProv,
                      siteName,
                      items,
                      currentFolders,
                      index,
                    ),
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSubscriptionCard(
    BuildContext context,
    NoticeProvider nProv,
    FavoriteProvider fProv,
    String siteName,
    List<Map<String, dynamic>> items,
    List<FavoriteFolder> folders,
    int index, // 추가된 부분
  ) {
    final bool hasNew = nProv.isSiteNew(siteName);
    final SiteCrawlStatus crawlStatus =
        nProv.getSiteCrawlStatus(siteName);
    final _CrawlStatusStyle statusStyle =
        _CrawlStatusStyle.forStatus(crawlStatus);

    return Card(
      elevation: 0,
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: Color(0xFFEEEEEE)),
      ),
      child: ExpansionTile(
        shape: const RoundedRectangleBorder(side: BorderSide(color: Colors.transparent)),
        collapsedShape: const RoundedRectangleBorder(side: BorderSide(color: Colors.transparent)),
        key: PageStorageKey(siteName),
        // 💡 [수정] 우측 여백을 8로 고정하여 메뉴 버튼 라인을 일치시킵니다. [cite: 2026-02-21]
        tilePadding: const EdgeInsets.only(left: 20, right: 8),
        onExpansionChanged: (expanded) {
          if (expanded && hasNew) nProv.markAsRead(siteName);
        },
        leading: ReorderableDragStartListener(
          index: index,
          child: Stack(
            clipBehavior: Clip.none,
            children: [
              const Icon(Icons.folder, color: Color(0xFFFFB74D), size: 32),
              if (hasNew)
                Positioned(
                  right: -2, top: -2,
                  child: Container(
                    width: 10, height: 10,
                    decoration: BoxDecoration(
                      color: Colors.red,
                      shape: BoxShape.circle,
                      border: Border.all(color: Colors.white, width: 1.5),
                    ),
                  ),
                ),
            ],
          ),
        ),
        title: Row(
          children: [
            Expanded(
              child: Text(
                siteName,
                style: const TextStyle(
                  fontWeight: FontWeight.bold,
                  fontSize: 16,
                ),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            if (crawlStatus.shouldShowInSubscription) ...[
              const SizedBox(width: 8),
              _buildCrawlStatusBadge(crawlStatus, statusStyle),
            ],
          ],
        ),
        subtitle: Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                "공지 ${items.length}개",
                style: const TextStyle(
                  fontSize: 12,
                  color: Color(0xFF636363),
                ),
              ),
              if (crawlStatus.shouldShowInSubscription) ...[
                const SizedBox(height: 4),
                Text(
                  crawlStatus.userMessage,
                  style: TextStyle(
                    fontSize: 12,
                    height: 1.35,
                    color: statusStyle.color,
                  ),
                ),
              ],
            ],
          ),
        ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (hasNew)
              Container(
                margin: const EdgeInsets.only(right: 8),
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: Colors.red.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(4),
                ),
                child: const Text(
                  "N",
                  style: TextStyle(color: Colors.red, fontSize: 10, fontWeight: FontWeight.bold),
                ),
              ),
            PopupMenuButton<Object>(
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(),
              onSelected: (val) async {
                if (val == "RENAME") {
                  _showRenameDialog(context, nProv, siteName);
                } else if (val == "DELETE") {
                  nProv.deleteSubscription(siteName);
                } else if (val == "BULK_MOVE") {
                  // 💡 바텀 시트 호출
                  _showBulkMoveBottomSheet(context, fProv, items, folders);
                }
              },
              itemBuilder: (context) => [
                const PopupMenuItem(value: "RENAME", child: Text("이름 바꾸기")),
                const PopupMenuItem(value: "DELETE", child: Text("삭제하기", style: TextStyle(color: Colors.red))),

                // 💡 [변경] 폴더가 존재할 경우에만 2뎁스 연결 메뉴 표시
                if (folders.isNotEmpty && items.isNotEmpty) ...[
                  const PopupMenuDivider(),
                  const PopupMenuItem(
                      value: "BULK_MOVE",
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text("즐겨찾기에 추가"),
                          Icon(Icons.chevron_right, size: 20, color: Colors.grey),
                        ],
                      )
                  ),
                ],
              ],
            ),
          ],
        ),
        children: items.map((notice) => _buildNoticeTile(context, fProv, nProv, siteName, notice, folders)).toList(),
      ),
    );
  }

  Widget _buildCrawlStatusBadge(
    SiteCrawlStatus status,
    _CrawlStatusStyle style,
  ) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: style.color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(style.icon, size: 13, color: style.color),
          const SizedBox(width: 3),
          Text(
            status.label,
            style: TextStyle(
              color: style.color,
              fontSize: 10,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildNoticeTile(BuildContext context, FavoriteProvider fProv, NoticeProvider nProv, String siteName, Map<String, dynamic> notice, List<FavoriteFolder> folders) {
    return Padding(
      padding: const EdgeInsets.only(left: 16.0),
      child: ListTile(
        contentPadding: const EdgeInsets.only(left: 20, right: 8),
        title: Text(
            notice['title'],
            style: const TextStyle(fontSize: 14),
            maxLines: 3,
            overflow: TextOverflow.ellipsis
        ),
        // 수정 후 (DateTime 객체인 경우)
        subtitle: Text(
          DateTime.parse(notice['created_at'].toString()).toLocal().toString().substring(0, 10),
          style: const TextStyle(fontSize: 12, color: Color(0xFF636363)),
        ),
        onTap: () => launchUrl(Uri.parse(notice['url']), mode: LaunchMode.externalApplication),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            PopupMenuButton<Object>(
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(),
              icon: const Icon(Icons.more_vert, color: Colors.grey, size: 20),
              onSelected: (val) async {
                if (val == "DELETE") {
                  // 💡 [수정] 기존 함수가 요구하는 3가지 파라미터를 모두 전달합니다.
                  try {
                    // 1. 토큰 가져오기 (PreferencesService 사용)
                    final token = await PreferencesService.getAuthToken();

                    if (token != null) {
                      // 2. Provider 함수 호출 (사이트명, 공지 ID, 토큰)
                      await nProv.deleteIndividualNotice(
                          siteName,
                          notice['notice_id'] as int,
                          token
                      );

                      // 3. (옵션) 삭제 완료 스낵바 띄우기
                      if (context.mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('공지가 삭제되었습니다.'),
                            duration: Duration(seconds: 1),
                            behavior: SnackBarBehavior.floating,
                          ),
                        );
                      }
                    } else {
                      debugPrint("❌ 인증 토큰을 찾을 수 없습니다.");
                    }
                  } catch (e) {
                    debugPrint("❌ 삭제 로직 실행 중 에러: $e");
                  }
                }
                else if (val == "MOVE_TO") {
                  // 💡 바텀 시트 호출
                  _showIndividualMoveBottomSheet(context, fProv, notice['notice_id'] as int, folders);
                }
              },
              itemBuilder: (context) => [
                const PopupMenuItem(value: "DELETE", child: Text("삭제", style: TextStyle(color: Colors.red))),
                if (folders.isNotEmpty) ...[
                  const PopupMenuDivider(),
                  const PopupMenuItem(
                      value: "MOVE_TO",
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text("즐겨찾기에 추가"),
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
