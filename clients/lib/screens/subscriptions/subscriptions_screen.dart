import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../providers/auth_provider.dart';
import '../../providers/notice_provider.dart';
import '../../providers/favorite_provider.dart';
import '../../providers/settings_provider.dart';
import '../../services/preferences_service.dart';
import '../../models/favorite_folder_model.dart';
import '../../core/utils/notice_display_formatter.dart';

class SubscriptionsScreen extends StatefulWidget {
  const SubscriptionsScreen({super.key});

  @override
  State<SubscriptionsScreen> createState() => _SubscriptionsScreenState();
}

class _SubscriptionsScreenState extends State<SubscriptionsScreen> {
  bool _isSearching = false;
  final TextEditingController _searchController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final Map<int, ExpansibleController> _expansionControllers = {};
  final Map<int, GlobalKey> _subscriptionCardKeys = {};
  bool _isOpeningNotificationTarget = false;

  @override
  void dispose() {
    _searchController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _openPendingNotificationTarget(
    NoticeProvider provider,
    List<String> siteNames,
  ) {
    final int? siteId = provider.pendingSubscriptionSiteId;
    if (siteId == null || _isOpeningNotificationTarget) return;
    final String? alias = provider.getAliasBySiteId(siteId);
    final int index = alias == null ? -1 : siteNames.indexOf(alias);
    if (index < 0) return;

    _isOpeningNotificationTarget = true;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      try {
        if (!mounted) return;
        if (_scrollController.hasClients) {
          final targetOffset = (index * 104.0)
              .clamp(0.0, _scrollController.position.maxScrollExtent)
              .toDouble();
          await _scrollController.animateTo(
            targetOffset,
            duration: const Duration(milliseconds: 350),
            curve: Curves.easeOut,
          );
        }
        if (!mounted) return;
        await Future<void>.delayed(const Duration(milliseconds: 100));
        final cardContext = _subscriptionCardKeys[siteId]?.currentContext;
        if (cardContext == null) return;
        await Scrollable.ensureVisible(
          cardContext,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
          alignment: 0.15,
        );
        _expansionControllers
            .putIfAbsent(siteId, ExpansibleController.new)
            .expand();
        provider.consumePendingSubscriptionSiteId();
      } finally {
        _isOpeningNotificationTarget = false;
      }
    });
  }

  void _showRenameDialog(
    BuildContext context,
    NoticeProvider prov,
    String oldName,
  ) {
    final TextEditingController controller = TextEditingController(
      text: oldName,
    );
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
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text("취소"),
          ),
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

  void _showDisplayLimitDialog(
    BuildContext context,
    NoticeProvider nProv,
    String siteName,
  ) {
    final currentLimit = nProv.getDisplayLimit(siteName);
    String mode = 'none';
    int count = 50;
    DateTime? cutoffDate;

    if (currentLimit != null) {
      if (currentLimit['type'] == 'count') {
        mode = 'count';
        count = currentLimit['value'] as int;
      } else if (currentLimit['type'] == 'date') {
        mode = 'date';
        cutoffDate = DateTime.tryParse(currentLimit['value'].toString());
      }
    }

    final TextEditingController countController = TextEditingController(
      text: count.toString(),
    );
    String? errorText;

    showDialog(
      context: context,
      builder: (dialogContext) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return AlertDialog(
              title: const Text("표시 개수 제한"),
              content: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      "폴더에 공지가 너무 많이 쌓였을 때, 화면에 표시할 공지의 개수 또는 날짜 범위를 제한할 수 있어요.",
                      style: TextStyle(fontSize: 12, color: Color(0xFF636363)),
                    ),
                    const SizedBox(height: 12),
                    RadioListTile<String>(
                      contentPadding: EdgeInsets.zero,
                      dense: true,
                      title: const Text("제한 없음 (모두 표시)"),
                      value: 'none',
                      groupValue: mode,
                      onChanged: (val) => setDialogState(() {
                        mode = val!;
                        errorText = null;
                      }),
                    ),
                    RadioListTile<String>(
                      contentPadding: EdgeInsets.zero,
                      dense: true,
                      title: const Text("최근 N개만 표시"),
                      value: 'count',
                      groupValue: mode,
                      onChanged: (val) => setDialogState(() {
                        mode = val!;
                        errorText = null;
                      }),
                    ),
                    if (mode == 'count')
                      Padding(
                        padding: const EdgeInsets.only(left: 32, bottom: 8),
                        child: TextField(
                          controller: countController,
                          keyboardType: TextInputType.number,
                          decoration: InputDecoration(
                            hintText: "예: 50",
                            isDense: true,
                            errorText: errorText,
                          ),
                        ),
                      ),
                    RadioListTile<String>(
                      contentPadding: EdgeInsets.zero,
                      dense: true,
                      title: const Text("특정 날짜 이후만 표시"),
                      value: 'date',
                      groupValue: mode,
                      onChanged: (val) => setDialogState(() {
                        mode = val!;
                        errorText = null;
                      }),
                    ),
                    if (mode == 'date')
                      Padding(
                        padding: const EdgeInsets.only(left: 32, bottom: 8),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Expanded(
                                  child: Text(
                                    cutoffDate == null
                                        ? "날짜를 선택하세요"
                                        : "${cutoffDate!.year}-${cutoffDate!.month.toString().padLeft(2, '0')}-${cutoffDate!.day.toString().padLeft(2, '0')} 이후만 표시",
                                  ),
                                ),
                                TextButton(
                                  onPressed: () async {
                                    final picked = await showDatePicker(
                                      context: context,
                                      initialDate: cutoffDate ?? DateTime.now(),
                                      firstDate: DateTime(2000),
                                      lastDate: DateTime.now(),
                                    );
                                    if (picked != null) {
                                      setDialogState(() {
                                        cutoffDate = picked;
                                        errorText = null;
                                      });
                                    }
                                  },
                                  child: const Text("날짜 선택"),
                                ),
                              ],
                            ),
                            if (errorText != null && mode == 'date')
                              Padding(
                                padding: const EdgeInsets.only(top: 4),
                                child: Text(
                                  errorText!,
                                  style: const TextStyle(
                                    color: Colors.red,
                                    fontSize: 12,
                                  ),
                                ),
                              ),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(dialogContext),
                  child: const Text("취소"),
                ),
                TextButton(
                  onPressed: () async {
                    if (mode == 'none') {
                      await nProv.clearDisplayLimit(siteName);
                    } else if (mode == 'count') {
                      final int? parsed = int.tryParse(
                        countController.text.trim(),
                      );
                      if (parsed == null || parsed <= 0) {
                        setDialogState(() => errorText = "1 이상의 숫자를 입력하세요.");
                        return;
                      }
                      await nProv.setDisplayLimitCount(siteName, parsed);
                    } else if (mode == 'date') {
                      if (cutoffDate == null) {
                        setDialogState(() => errorText = "날짜를 선택하세요.");
                        return;
                      }
                      await nProv.setDisplayLimitDate(siteName, cutoffDate!);
                    }
                    Navigator.pop(dialogContext);
                  },
                  child: const Text("적용"),
                ),
              ],
            );
          },
        );
      },
    );
  }

  Future<void> _executeKeywordBulkMove(
    BuildContext context,
    FavoriteProvider fProv,
    int targetFolderId,
    List<Map<String, dynamic>> items,
    List<FavoriteFolder> folders,
  ) async {
    String targetFolderName = "알 수 없는 폴더";
    for (var f in folders) {
      if (f.folderId == targetFolderId) targetFolderName = f.folderName;
      for (var sub in f.subFolders) {
        if (sub.folderId == targetFolderId) targetFolderName = sub.folderName;
      }
    }

    List<String> folderKeywords = fProv.getKeywordsForFolder(targetFolderId);
    List<Future<void>> moveTasks = [];

    int matchCount = 0;
    int newMoveCount = 0;

    for (var notice in items) {
      final title = notice['title'].toString().toLowerCase();
      final noticeId = notice['notice_id'] as int;

      bool isKeywordMatched =
          folderKeywords.isEmpty ||
          folderKeywords.any(
            (keyword) => title.contains(keyword.toLowerCase()),
          );

      if (isKeywordMatched) {
        matchCount++;

        bool isAlreadyExist = false;
        for (var f in folders) {
          if (f.folderId == targetFolderId &&
              f.notices.any((n) => n.noticeId == noticeId)) {
            isAlreadyExist = true;
          }
          for (var sub in f.subFolders) {
            if (sub.folderId == targetFolderId &&
                sub.notices.any((n) => n.noticeId == noticeId)) {
              isAlreadyExist = true;
            }
          }
        }

        if (!isAlreadyExist) {
          moveTasks.add(fProv.addNoticeToFolder(targetFolderId, noticeId));
          newMoveCount++;
        }
      }
    }

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

  void _showBulkMoveBottomSheet(
    BuildContext parentContext,
    FavoriteProvider fProv,
    List<Map<String, dynamic>> items,
    List<FavoriteFolder> folders,
  ) {
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
                "키워드 일괄 이동",
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 10),
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  children: folders
                      .expand(
                        (f) => [
                          ListTile(
                            leading: const Icon(
                              Icons.folder,
                              color: Colors.amber,
                            ),
                            title: Text(f.folderName),
                            onTap: () {
                              Navigator.pop(sheetContext);
                              _executeKeywordBulkMove(
                                parentContext,
                                fProv,
                                f.folderId,
                                items,
                                folders,
                              );
                            },
                          ),
                          ...f.subFolders.map(
                            (sub) => ListTile(
                              contentPadding: const EdgeInsets.only(
                                left: 40,
                                right: 16,
                              ),
                              leading: const Icon(
                                Icons.folder_special_outlined,
                                color: Colors.amber,
                              ),
                              title: Text(sub.folderName),
                              onTap: () {
                                Navigator.pop(sheetContext);
                                _executeKeywordBulkMove(
                                  parentContext,
                                  fProv,
                                  sub.folderId,
                                  items,
                                  folders,
                                );
                              },
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

  Future<void> _executeIndividualNoticeMove(
    BuildContext context,
    FavoriteProvider fProv,
    int targetFolderId,
    int noticeId,
    List<FavoriteFolder> folders,
  ) async {
    String targetFolderName = "알 수 없는 폴더";
    bool isAlreadyExist = false;

    for (var f in folders) {
      if (f.folderId == targetFolderId) {
        targetFolderName = f.folderName;
        if (f.notices.any((n) => n.noticeId == noticeId)) isAlreadyExist = true;
      }
      for (var sub in f.subFolders) {
        if (sub.folderId == targetFolderId) {
          targetFolderName = sub.folderName;
          if (sub.notices.any((n) => n.noticeId == noticeId))
            isAlreadyExist = true;
        }
      }
    }

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

  void _showIndividualMoveBottomSheet(
    BuildContext parentContext,
    FavoriteProvider fProv,
    int noticeId,
    List<FavoriteFolder> folders,
  ) {
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
                "즐겨찾기 폴더 선택",
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 10),
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  children: folders
                      .expand(
                        (f) => [
                          ListTile(
                            leading: const Icon(
                              Icons.folder,
                              color: Colors.amber,
                            ),
                            title: Text(f.folderName),
                            onTap: () {
                              Navigator.pop(sheetContext);
                              _executeIndividualNoticeMove(
                                parentContext,
                                fProv,
                                f.folderId,
                                noticeId,
                                folders,
                              );
                            },
                          ),
                          ...f.subFolders.map(
                            (sub) => ListTile(
                              contentPadding: const EdgeInsets.only(
                                left: 40,
                                right: 16,
                              ),
                              leading: const Icon(
                                Icons.folder_special_outlined,
                                color: Colors.amber,
                              ),
                              title: Text(sub.folderName),
                              onTap: () {
                                Navigator.pop(sheetContext);
                                _executeIndividualNoticeMove(
                                  parentContext,
                                  fProv,
                                  sub.folderId,
                                  noticeId,
                                  folders,
                                );
                              },
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
    final noticeProv = context.watch<NoticeProvider>();
    final favoriteProv = context.watch<FavoriteProvider>();

    final authProv = context.watch<AuthProvider>();

    final int maxSitesLimit = authProv.user!.maxSitesLimit;
    final String? nick = authProv.user!.nickname;

    print("nick : ${nick}");
    print("maxSitesLimit : ${maxSitesLimit}");

    final String query = noticeProv.searchQuery.toLowerCase();
    Map<String, List<Map<String, dynamic>>> filteredNotices = {};

    noticeProv.notices.forEach((key, value) {
      final matched = value
          .where((n) => n['title'].toString().toLowerCase().contains(query))
          .toList();
      if (query.isEmpty || matched.isNotEmpty) {
        filteredNotices[key] = query.isEmpty ? value : matched;
      }
    });

    final siteNames = filteredNotices.keys.toList();
    _openPendingNotificationTarget(noticeProv, siteNames);
    final List<FavoriteFolder> currentFolders = favoriteProv.folders;

    final int currentSubscriptionCount = noticeProv.notices.length;

    return Scaffold(
      backgroundColor: Colors.white,
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
            child: Row(
              children: [
                if (!_isSearching) ...[
                  const Icon(
                    Icons.subscriptions_outlined,
                    color: Colors.orangeAccent,
                  ),
                  const SizedBox(width: 8),
                ],
                Expanded(
                  child: _isSearching
                      ? TextField(
                          controller: _searchController,
                          autofocus: true,
                          decoration: const InputDecoration(
                            hintText: "구독 내 공지 검색...",
                            border: InputBorder.none,
                          ),
                          onChanged: (val) => noticeProv.updateSearchQuery(val),
                        )
                      : Row(
                          crossAxisAlignment: CrossAxisAlignment.center,
                          children: [
                            const Text(
                              "구독 목록",
                              style: TextStyle(
                                fontSize: 22,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                            const SizedBox(width: 8),
                            Text(
                              "$currentSubscriptionCount / $maxSitesLimit",
                              style: TextStyle(
                                fontSize: 20,
                                fontWeight: FontWeight.bold,
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

          Expanded(
            child: RefreshIndicator(
              onRefresh: () async {
                await noticeProv.fetchNoticesFromServer();
              },
              child: siteNames.isEmpty
                  ? CustomScrollView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      slivers: [
                        SliverFillRemaining(
                          child: Center(
                            child: Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Image.asset(
                                  'assets/images/pigeon_sad_gray.png',
                                  width: 120,
                                ),
                                const SizedBox(height: 16),
                                const Text(
                                  "아무런 소식이 없어요.\n추가 탭에서 웹페이지를 등록해보세요.",
                                  textAlign: TextAlign.center,
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
                      scrollController: _scrollController,
                      physics: const AlwaysScrollableScrollPhysics(),
                      buildDefaultDragHandles: false,
                      padding: const EdgeInsets.all(16),
                      itemCount: siteNames.length,
                      onReorder: (oldIndex, newIndex) =>
                          noticeProv.reorderSubscriptions(oldIndex, newIndex),
                      itemBuilder: (context, index) {
                        String siteName = siteNames[index];
                        List<Map<String, dynamic>> items =
                            filteredNotices[siteName]!;

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
    int index,
  ) {
    final bool hasNew = nProv.isSiteNew(siteName);
    final int? siteId = nProv.getSiteId(siteName);
    final bool notificationEnabled = nProv.isSubscriptionNotificationEnabled(
      siteName,
    );
    final bool globalNotificationsEnabled = context
        .watch<SettingsProvider>()
        .settings
        .isNotificationEnabled;
    final List<Map<String, dynamic>> displayedItems = nProv.applyDisplayLimit(
      siteName,
      items,
    );
    final bool isLimited = displayedItems.length != items.length;

    return Card(
      key: siteId == null
          ? null
          : _subscriptionCardKeys.putIfAbsent(siteId, GlobalKey.new),
      elevation: 0,
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: Color(0xFFEEEEEE)),
      ),
      child: ExpansionTile(
        controller: siteId == null
            ? null
            : _expansionControllers.putIfAbsent(
                siteId,
                ExpansibleController.new,
              ),
        shape: const RoundedRectangleBorder(
          side: BorderSide(color: Colors.transparent),
        ),
        collapsedShape: const RoundedRectangleBorder(
          side: BorderSide(color: Colors.transparent),
        ),
        key: PageStorageKey(siteName),
        tilePadding: const EdgeInsets.only(left: 20, right: 8),
        onExpansionChanged: (expanded) {
          if (expanded && nProv.isSiteNew(siteName)) {
            nProv.markAsRead(siteName);
          } else if (!expanded) {
            nProv.clearNewBadgeHighlights(siteName);
          }
        },
        leading: ReorderableDragStartListener(
          index: index,
          child: Stack(
            clipBehavior: Clip.none,
            children: [
              const Icon(Icons.folder, color: Color(0xFFFFB74D), size: 32),
              if (hasNew)
                Positioned(
                  right: -2,
                  top: -2,
                  child: Container(
                    width: 10,
                    height: 10,
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
        title: Text(
          siteName,
          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        subtitle: Text(
          isLimited
              ? "공지 ${displayedItems.length}개 표시 중 (전체 ${items.length}개)"
              : "공지 ${items.length}개",
          style: const TextStyle(fontSize: 12, color: Color(0xFF636363)),
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
                  style: TextStyle(
                    color: Colors.red,
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            IconButton(
              key: ValueKey('subscription_notification_${siteId ?? siteName}'),
              visualDensity: VisualDensity.compact,
              tooltip: notificationEnabled
                  ? globalNotificationsEnabled
                        ? '새 소식 알림 끄기'
                        : '개별 알림 ON · 전체 알림 OFF'
                  : '새 소식 알림 켜기',
              icon: Icon(
                notificationEnabled
                    ? Icons.notifications_active
                    : Icons.notifications_none,
                size: 21,
                color: notificationEnabled && globalNotificationsEnabled
                    ? Colors.deepPurple
                    : Colors.grey,
              ),
              onPressed: () async {
                final success = await nProv.setSubscriptionNotificationEnabled(
                  siteName,
                  !notificationEnabled,
                );
                if (!success && context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('알림 설정을 저장하지 못했습니다.')),
                  );
                }
              },
            ),
            PopupMenuButton<Object>(
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(),
              onSelected: (val) async {
                if (val == "RENAME") {
                  _showRenameDialog(context, nProv, siteName);
                } else if (val == "DELETE") {
                  final bool deleted = await nProv.deleteSubscription(siteName);
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        content: Text(
                          deleted ? '구독이 삭제되었습니다.' : '구독을 삭제하지 못했습니다.',
                        ),
                      ),
                    );
                  }
                } else if (val == "BULK_MOVE") {
                  _showBulkMoveBottomSheet(context, fProv, items, folders);
                } else if (val == "DISPLAY_LIMIT") {
                  _showDisplayLimitDialog(context, nProv, siteName);
                }
              },
              itemBuilder: (context) => [
                const PopupMenuItem(value: "RENAME", child: Text("이름 바꾸기")),
                const PopupMenuItem(
                  value: "DISPLAY_LIMIT",
                  child: Text("표시 개수 제한"),
                ),
                const PopupMenuItem(
                  value: "DELETE",
                  child: Text("삭제하기", style: TextStyle(color: Colors.red)),
                ),
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
                    ),
                  ),
                ],
              ],
            ),
          ],
        ),
        children: displayedItems
            .map(
              (notice) => _buildNoticeTile(
                context,
                fProv,
                nProv,
                siteName,
                notice,
                folders,
              ),
            )
            .toList(),
      ),
    );
  }

  Widget _buildNoticeTile(
    BuildContext context,
    FavoriteProvider fProv,
    NoticeProvider nProv,
    String siteName,
    Map<String, dynamic> notice,
    List<FavoriteFolder> folders,
  ) {
    final bool isNew = nProv.shouldShowNewBadge(siteName, notice);

    return Padding(
      padding: const EdgeInsets.only(left: 16.0),
      child: ListTile(
        contentPadding: const EdgeInsets.only(left: 20, right: 8),
        title: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (isNew) ...[
              Container(
                margin: const EdgeInsets.only(top: 2, right: 7),
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: Colors.red,
                  borderRadius: BorderRadius.circular(4),
                ),
                child: const Text(
                  'NEW',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 9,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ],
            Expanded(
              child: Text(
                notice['title']?.toString() ?? '',
                style: const TextStyle(fontSize: 14),
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        ),
        subtitle: Text(
          NoticeDisplayFormatter.subscriptionMetadata(notice),
          style: const TextStyle(fontSize: 12, color: Color(0xFF636363)),
        ),
        onTap: () => launchUrl(
          Uri.parse(notice['url']),
          mode: LaunchMode.externalApplication,
        ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            PopupMenuButton<Object>(
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(),
              icon: const Icon(Icons.more_vert, color: Colors.grey, size: 20),
              onSelected: (val) async {
                if (val == "DELETE") {
                  try {
                    final token = await PreferencesService.getAuthToken();

                    if (token != null) {
                      await nProv.deleteIndividualNotice(
                        siteName,
                        notice['notice_id'] as int,
                        token,
                      );

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
                } else if (val == "MOVE_TO") {
                  _showIndividualMoveBottomSheet(
                    context,
                    fProv,
                    notice['notice_id'] as int,
                    folders,
                  );
                }
              },
              itemBuilder: (context) => [
                const PopupMenuItem(
                  value: "DELETE",
                  child: Text("삭제", style: TextStyle(color: Colors.red)),
                ),
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
