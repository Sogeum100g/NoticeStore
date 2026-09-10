import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../services/preferences_service.dart';
import '../core/utils/notice_chronology.dart';

import 'package:flutter_dotenv/flutter_dotenv.dart';

const storage = FlutterSecureStorage();

Map<String, List<Map<String, dynamic>>> _parseNoticesInBackground(
  Map<String, dynamic> args,
) {
  final String responseBody = args['responseBody'];
  final Map<String, dynamic> siteStatusMap = args['siteStatusMap'];
  final Map<String, List<Map<String, dynamic>>> grouped = args['grouped'];

  final responseData = json.decode(responseBody);
  List<dynamic> fetchedNotices = responseData['notices'] ?? [];

  for (var rawItem in fetchedNotices) {
    Map<String, dynamic> item = Map<String, dynamic>.from(rawItem);

    String siteIdStr = item['site_id']?.toString() ?? "";

    String siteTitle = "알 수 없는 사이트 ($siteIdStr)";

    if (siteStatusMap.containsKey(siteIdStr)) {
      siteTitle =
          siteStatusMap[siteIdStr]['alias'] ??
          siteStatusMap[siteIdStr]['url'].toString();
    }

    grouped.putIfAbsent(siteTitle, () => []).add(item);
  }

  return grouped.map(
    (siteName, notices) =>
        MapEntry(siteName, NoticeChronology.sortedNewestFirst(notices)),
  );
}

class NoticeProvider with ChangeNotifier {
  int _selectedIndex = 2;
  bool _isLoading = true;
  bool _isDataLoaded = false;
  bool _hasFetchedNoticesFromServer = false;
  String _searchQuery = "";
  String? _pendingUrl;
  String? _ipAddress = dotenv.env['IP_ADDRESS'];

  Timer? _saveTimer;
  Future<void>? _fetchInFlight;

  Map<String, List<Map<String, dynamic>>> _favoriteFolders = {};
  Map<String, List<String>> _siteKeywords = {};
  Map<String, List<Map<String, dynamic>>> _notices = {};
  Map<String, List<String>> _folderKeywords = {};
  Map<String, Map<String, dynamic>> _displayLimits = {};
  Map<String, Map<String, dynamic>> _siteMetadata = {};
  List<int> _subscriptionOrder = [];
  bool _isSubscriptionOrderLoaded = false;
  Future<List<int>>? _subscriptionOrderLoadInFlight;
  final Map<String, Set<int>> _newBadgeHighlights = {};
  int? _pendingSubscriptionSiteId;

  int get selectedIndex => _selectedIndex;
  bool get isLoading => _isLoading;
  String get searchQuery => _searchQuery;
  Map<String, List<Map<String, dynamic>>> get favoriteFolders =>
      _favoriteFolders;
  Map<String, List<Map<String, dynamic>>> get notices => _notices;
  Map<String, List<String>> get folderKeywords => _folderKeywords;
  String? get pendingUrl => _pendingUrl;
  int? get pendingSubscriptionSiteId => _pendingSubscriptionSiteId;

  Map<String, dynamic>? getDisplayLimit(String siteName) =>
      _displayLimits[siteName];

  /// 표시 제한이 설정된 폴더의 공지 목록을 화면에 보여줄 만큼만 잘라냅니다.
  /// (목록은 이미 최신순으로 정렬되어 있다고 가정합니다.)
  List<Map<String, dynamic>> applyDisplayLimit(
    String siteName,
    List<Map<String, dynamic>> notices,
  ) {
    final limit = _displayLimits[siteName];
    if (limit == null) return notices;

    if (limit['type'] == 'count') {
      final int? count = _parseId(limit['value']);
      if (count == null || count <= 0) return notices;
      return notices.take(count).toList();
    }

    if (limit['type'] == 'date') {
      final DateTime? cutoff = DateTime.tryParse(limit['value'].toString());
      if (cutoff == null) return notices;
      return notices.where((notice) {
        final date = NoticeChronology.effectiveDate(notice);
        // 날짜를 알 수 없는 공지는 판단할 수 없으므로 그대로 표시합니다.
        return date == null || !date.isBefore(cutoff);
      }).toList();
    }

    return notices;
  }

  Future<void> setDisplayLimitCount(String siteName, int count) async {
    _displayLimits[siteName] = {'type': 'count', 'value': count};
    notifyListeners();
    await PreferencesService.saveDisplayLimits(_displayLimits);
  }

  Future<void> setDisplayLimitDate(String siteName, DateTime cutoff) async {
    _displayLimits[siteName] = {
      'type': 'date',
      'value': cutoff.toIso8601String(),
    };
    notifyListeners();
    await PreferencesService.saveDisplayLimits(_displayLimits);
  }

  Future<void> clearDisplayLimit(String siteName) async {
    if (_displayLimits.remove(siteName) != null) {
      notifyListeners();
      await PreferencesService.saveDisplayLimits(_displayLimits);
    }
  }

  // 두 응답이 아주 짧은 시간차로 도착해도 표시가 누락되지 않도록 둘 다 확인합니다.
  bool isSiteNew(String alias) {
    final bool serverHasNew = _siteMetadata[alias]?['has_new'] == true;
    final bool hasNewCard = _notices[alias]?.any(isNoticeNew) ?? false;
    return serverHasNew || hasNewCard;
  }

  bool isNoticeNew(Map<String, dynamic> notice) => notice['is_new'] == true;

  bool shouldShowNewBadge(String siteName, Map<String, dynamic> notice) {
    final int? noticeId = _parseId(notice['notice_id']);
    return isNoticeNew(notice) ||
        (noticeId != null &&
            (_newBadgeHighlights[siteName]?.contains(noticeId) ?? false));
  }

  void clearNewBadgeHighlights(String siteName) {
    if (_newBadgeHighlights.remove(siteName) != null) {
      notifyListeners();
    }
  }

  // 이전 캐시에 메타데이터가 없으면 공지 데이터의 site_id를 사용합니다.
  int? getSiteId(String alias) {
    final int? metadataSiteId = _parseSiteId(_siteMetadata[alias]?['site_id']);
    if (metadataSiteId != null) return metadataSiteId;

    for (final notice in _notices[alias] ?? const <Map<String, dynamic>>[]) {
      final int? noticeSiteId = _parseSiteId(notice['site_id']);
      if (noticeSiteId != null) return noticeSiteId;
    }
    return null;
  }

  String? getAliasBySiteId(int siteId) => _getAliasBySiteId(siteId);

  bool isSubscriptionNotificationEnabled(String alias) =>
      _siteMetadata[alias]?['notification_enabled'] == true;

  Future<bool> setSubscriptionNotificationEnabled(
    String alias,
    bool enabled,
  ) async {
    final int? siteId = getSiteId(alias);
    final String? token = await PreferencesService.getAuthToken();
    if (siteId == null || token == null || token.isEmpty) return false;

    final metadata = _siteMetadata[alias];
    if (metadata == null) return false;
    final bool previous = metadata['notification_enabled'] == true;
    metadata['notification_enabled'] = enabled;
    notifyListeners();
    await PreferencesService.saveSiteMetadata(_siteMetadata);

    try {
      final response = await http.patch(
        Uri.parse(
          'https://${_ipAddress}/v1/subscriptions/$siteId/notification',
        ),
        headers: {
          'Authorization': 'Bearer $token',
          'Content-Type': 'application/json',
        },
        body: jsonEncode({'notification_enabled': enabled}),
      );
      if (response.statusCode == 200) return true;
    } catch (e) {
      debugPrint('구독 알림 설정 실패: $e');
    }

    metadata['notification_enabled'] = previous;
    notifyListeners();
    await PreferencesService.saveSiteMetadata(_siteMetadata);
    return false;
  }

  void openSubscriptionFromNotification(int siteId) {
    _pendingSubscriptionSiteId = siteId;
    _searchQuery = '';
    _selectedIndex = 1;
    notifyListeners();
  }

  void consumePendingSubscriptionSiteId() {
    _pendingSubscriptionSiteId = null;
  }

  List<Map<String, dynamic>> get inquirySiteMetadata =>
      _siteMetadata.values.toList(growable: false);

  void setPendingUrl(String url) {
    _pendingUrl = url;
    notifyListeners();
  }

  void consumePendingUrl() {
    _pendingUrl = null;
  }

  Future<void> loadSavedData() async {
    Future.microtask(() {
      _isLoading = true;
      notifyListeners();
    });

    final data = await PreferencesService.loadFavorites();
    _favoriteFolders = data['folders'] ?? {};
    _folderKeywords = data['keywords'] ?? {};
    _displayLimits = await PreferencesService.loadDisplayLimits();
    await _ensureSubscriptionOrderLoaded();
    final savedNotices = await PreferencesService.loadNotices();
    final savedSiteMetadata = await PreferencesService.loadSiteMetadata();
    // 오래된 로컬 캐시로 덮어쓰지 않습니다.
    if (_siteMetadata.isEmpty) {
      _siteMetadata = savedSiteMetadata;
    }
    if (!_hasFetchedNoticesFromServer) {
      _notices = _applySubscriptionOrder(
        _sortNoticeGroups(savedNotices),
        _siteMetadata,
      );
    }

    _isLoading = false;
    _isDataLoaded = true;
    notifyListeners();
  }

  Future<void> fetchNoticesFromServer() {
    final runningFetch = _fetchInFlight;
    if (runningFetch != null) return runningFetch;

    final fetch = _fetchNoticesFromServer();
    _fetchInFlight = fetch;
    return fetch.whenComplete(() {
      if (identical(_fetchInFlight, fetch)) {
        _fetchInFlight = null;
      }
    });
  }

  Future<void> _fetchNoticesFromServer() async {
    try {
      await _ensureSubscriptionOrderLoaded();
      final String? token = await storage.read(key: "jwt_token");
      if (token == null) return;

      final Map<String, String> headers = {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      };

      final statusResponse = await http.get(
        Uri.parse('https://${_ipAddress}/v1/subscriptions_sites'),
        headers: headers,
      );

      Map<String, List<Map<String, dynamic>>> grouped = {};
      Map<String, dynamic> siteStatusMap = {};
      final Map<String, Map<String, dynamic>> nextSiteMetadata = {};

      if (statusResponse.statusCode == 200) {
        final List<dynamic> siteData =
            json.decode(statusResponse.body)['sites'] ?? [];

        for (var s in siteData) {
          String siteName = s['alias'] ?? s['url'].toString();

          grouped[siteName] = [];

          nextSiteMetadata[siteName] = {
            'site_id': s['site_id'],
            'has_new': s['has_new'] ?? false,
            'notification_enabled': s['notification_enabled'] ?? false,
            'alias': s['alias'] ?? siteName,
            'url': s['url'],
            'crawl_status': s['crawl_status'] ?? 'active',
            'error_code': s['error_code'],
            'error_message': s['error_message'],
          };
          siteStatusMap[s['site_id'].toString()] = s;
        }

        // 공지 API와 무관한 삭제·읽음 식별자는 구독 응답에서 즉시 반영합니다.
        _siteMetadata = nextSiteMetadata;
        notifyListeners();
        await PreferencesService.saveSiteMetadata(_siteMetadata);
      }

      final response = await http.get(
        Uri.parse('https://${_ipAddress}/v1/notices'),
        headers: headers,
      );

      if (response.statusCode == 200) {
        final parsedGrouped = await compute(_parseNoticesInBackground, {
          'responseBody': response.body,
          'siteStatusMap': siteStatusMap,
          'grouped': grouped,
        });

        _notices = _applySubscriptionOrder(parsedGrouped, nextSiteMetadata);
        _hasFetchedNoticesFromServer = true;
        await _saveCurrentSubscriptionOrder();
        notifyListeners();
        await Future.wait([
          PreferencesService.saveNotices(_notices),
          PreferencesService.saveSiteMetadata(_siteMetadata),
        ]);
      }
    } catch (e) {
      debugPrint("❌ 공지 로딩 에러: $e");
    }
  }

  void addNoticeToFolder(String folderName, Map<String, dynamic> notice) {
    _favoriteFolders[folderName]?.add(notice);
    notifyListeners();
    _debouncedSaveToLocal();
  }

  void moveNoticeToOtherFolder(
    String fromFolder,
    String toFolder,
    Map<String, dynamic> notice,
  ) {
    if (fromFolder == toFolder) return;
    _favoriteFolders[fromFolder]?.removeWhere(
      (item) => item['notice_id'] == notice['notice_id'],
    );
    _favoriteFolders[toFolder]?.add(notice);
    notifyListeners();
    _debouncedSaveToLocal();
  }

  void _debouncedSaveToLocal() {
    if (!_isDataLoaded) return;

    // 타이머가 이미 돌고 있다면 취소하고 새로 시작 (연속 호출 시 마지막 호출만 실행됨)
    if (_saveTimer?.isActive ?? false) _saveTimer!.cancel();

    _saveTimer = Timer(const Duration(seconds: 2), () async {
      await PreferencesService.saveNotices(_notices);
      await PreferencesService.saveFavorites(
        folders: _favoriteFolders,
        keywords: _folderKeywords,
      );
      debugPrint("💾 [Provider] 로컬 저장 완료 (디바운스 적용)");
    });
  }

  Future<void> renameSubscriptionAlias(String oldName, String newName) async {
    if (oldName == newName || newName.isEmpty || _notices.containsKey(newName))
      return;

    final data = _notices.remove(oldName);
    if (data != null) {
      _notices[newName] = data;
      final metadata = _siteMetadata.remove(oldName);
      if (metadata != null) _siteMetadata[newName] = metadata;
      final highlights = _newBadgeHighlights.remove(oldName);
      if (highlights != null) _newBadgeHighlights[newName] = highlights;
      final displayLimit = _displayLimits.remove(oldName);
      if (displayLimit != null) {
        _displayLimits[newName] = displayLimit;
        await PreferencesService.saveDisplayLimits(_displayLimits);
      }
      if (data.isNotEmpty) {
        await PreferencesService.saveAlias(data[0]['url'].toString(), newName);
      }
    }
    _saveToLocal();
    notifyListeners();
  }

  void autoCategorizeToFavorites() {
    _folderKeywords.forEach((folderName, keywords) {
      if (keywords.isEmpty) return;
      _notices.forEach((site, noticeList) {
        for (var notice in noticeList) {
          String title = notice["title"].toString().toLowerCase();
          if (keywords.any((k) => title.contains(k.toLowerCase()))) {
            bool exists = _favoriteFolders[folderName]!.any(
              (item) => item['notice_id'] == notice['notice_id'],
            );
            if (!exists) _favoriteFolders[folderName]!.add(notice);
          }
        }
      });
    });
    _saveToLocal();
    notifyListeners();
  }

  Future<void> _saveToLocal() async {
    if (!_isDataLoaded) return;
    await Future.wait([
      PreferencesService.saveNotices(_notices),
      PreferencesService.saveSiteMetadata(_siteMetadata),
      PreferencesService.saveFavorites(
        folders: _favoriteFolders,
        keywords: _folderKeywords,
      ),
    ]);
  }

  void updateSearchQuery(String query) {
    _searchQuery = query;
    notifyListeners();
  }

  void setSelectedIndex(int index) {
    _selectedIndex = index;
    notifyListeners();
  }

  /// site_id를 기반으로 현재 메모리에 저장된 사이트 별명(alias)을 찾습니다.
  String? _getAliasBySiteId(int siteId) {
    try {
      return _siteMetadata.entries
          .firstWhere((entry) => _parseSiteId(entry.value['site_id']) == siteId)
          .key;
    } catch (e) {
      debugPrint("⚠️ [Provider] ID $siteId에 해당하는 별명을 찾을 수 없습니다.");
      return null;
    }
  }

  void onFetchComplete(List<Map<String, dynamic>> fetchedData, int siteId) {
    final String? alias = _getAliasBySiteId(siteId);
    if (alias == null) return;

    debugPrint("🚨 [Provider] 신규 데이터 수신: ${fetchedData.length}개 (별명: $alias)");

    if (fetchedData.isEmpty) return;

    if (!_notices.containsKey(alias)) {
      _notices[alias] = [];
    }

    // 서버 공지 ID를 우선 사용해 중복을 확인하고 신규 상태를 부여합니다.
    int addedCount = 0;
    for (final rawItem in fetchedData) {
      final item = Map<String, dynamic>.from(rawItem);
      final dynamic noticeId = item['notice_id'];
      final bool isAlreadyExist = _notices[alias]!.any((old) {
        if (noticeId != null) return old['notice_id'] == noticeId;
        return old['url'] == item['url'] && old['title'] == item['title'];
      });
      if (!isAlreadyExist) {
        item['site_id'] ??= siteId;
        item['is_new'] = true;
        _notices[alias]!.add(item);
        addedCount++;
      }
    }

    if (addedCount > 0) {
      _notices[alias] = NoticeChronology.sortedNewestFirst(_notices[alias]!);
      _siteMetadata[alias]?['has_new'] = true;
      notifyListeners();
      _saveToLocal();
    }
  }

  Future<String> registerNewSite(
    String url,
    String alias, {
    void Function(int siteId)? onSiteAccepted,
  }) async {
    try {
      final String? token = await storage.read(key: "jwt_token");

      if (token == null) {
        return "NEED_LOGIN";
      }

      final response = await http
          .post(
            Uri.parse('https://${_ipAddress}/v1/add-site'),
            headers: {
              'Content-Type': 'application/json',
              'Authorization': 'Bearer $token',
            },
            body: jsonEncode({'url': url, 'alias': alias}),
          )
          .timeout(const Duration(seconds: 120));

      if (response.statusCode == 401) return "NEED_LOGIN";

      final dynamic decodedBody = jsonDecode(response.body);
      if (decodedBody is! Map<String, dynamic>) {
        return "INVALID_SERVER_RESPONSE";
      }

      if (response.statusCode != 200) {
        final dynamic detail = decodedBody['detail'];
        final String errorCode = detail is String
            ? detail
            : response.statusCode == 422
            ? "INVALID_REQUEST"
            : "INVALID_SERVER_RESPONSE";
        debugPrint("❌ 서버 응답 에러 (상태코드 ${response.statusCode}): $errorCode");
        return errorCode;
      }

      if (decodedBody['status'] != 'success') {
        return "INVALID_SERVER_RESPONSE";
      }

      final int? siteId = _parseSiteId(decodedBody['site_id']);
      if (siteId == null) return "INVALID_SERVER_RESPONSE";
      onSiteAccepted?.call(siteId);

      await PreferencesService.saveAlias(url, alias);
      await fetchNoticesFromServer();

      final bool registrationCompleted =
          decodedBody['registration_completed'] == true;
      final String registrationState =
          decodedBody['message']?.toString().toUpperCase() ?? '';

      debugPrint(
        "✅ 사이트 등록 요청 접수. Site ID: $siteId, "
        "State: $registrationState",
      );

      if (registrationCompleted || registrationState == 'ACTIVE') {
        return "SUCCESS";
      }
      if (registrationState == 'PENDING') {
        return "PENDING";
      }
      return "INVALID_SERVER_RESPONSE";
    } on TimeoutException {
      return "TIMEOUT_ERROR";
    } on http.ClientException {
      return "NETWORK_ERROR";
    } on FormatException {
      return "INVALID_SERVER_RESPONSE";
    } catch (e) {
      debugPrint("❌ 사이트 등록 실패: $e");
      return "UNKNOWN_ERROR";
    }
  }

  static int? _parseId(dynamic value) {
    if (value is int) return value;
    if (value is num) return value.toInt();
    return int.tryParse(value?.toString() ?? '');
  }

  int? _parseSiteId(dynamic value) => _parseId(value);

  /// 최초 수집이 성공하거나 실패할 때까지 사이트 상태를 확인합니다.
  ///
  /// 통신 timeout과 일시적인 네트워크 오류는 수집 실패가 아니므로
  /// polling을 계속합니다. 화면이 폐기되면 [shouldContinue]로 종료합니다.
  Future<String> waitForSiteRegistration(
    int siteId, {
    Duration pollInterval = const Duration(seconds: 3),
    bool Function()? shouldContinue,
  }) async {
    while (shouldContinue?.call() ?? true) {
      try {
        final String? token = await storage.read(key: "jwt_token");
        if (token == null) return "NEED_LOGIN";

        final response = await http
            .get(
              Uri.parse('https://${_ipAddress}/v1/sites/$siteId/status'),
              headers: {
                'Authorization': 'Bearer $token',
                'Content-Type': 'application/json',
              },
            )
            .timeout(const Duration(seconds: 15));

        if (response.statusCode == 401) return "NEED_LOGIN";

        if (response.statusCode == 200) {
          final dynamic decodedBody = jsonDecode(response.body);
          if (decodedBody is! Map<String, dynamic> ||
              decodedBody['site'] is! Map) {
            return "INVALID_SERVER_RESPONSE";
          }

          final Map<String, dynamic> site = Map<String, dynamic>.from(
            decodedBody['site'] as Map,
          );
          final bool registrationCompleted =
              site['registration_completed'] == true;
          final String crawlStatus =
              site['crawl_status']?.toString().toLowerCase() ?? 'unknown';

          if (registrationCompleted || crawlStatus == 'active') {
            await fetchNoticesFromServer();
            return "SUCCESS";
          }

          if (crawlStatus == 'failed' || crawlStatus == 'blocked') {
            await fetchNoticesFromServer();
            final String? errorCode = site['error_code']?.toString().trim();
            if (errorCode != null && errorCode.isNotEmpty) return errorCode;
            return crawlStatus == 'blocked'
                ? "SITE_ACCESS_BLOCKED"
                : "SITE_REGISTRATION_FAILED";
          }
        } else if (response.statusCode == 404) {
          return "SITE_NOT_FOUND";
        }
      } on TimeoutException {
        debugPrint("⚠️ Site $siteId 상태 조회 timeout. 재시도합니다.");
      } on http.ClientException catch (e) {
        debugPrint("⚠️ Site $siteId 상태 조회 네트워크 오류: $e");
      } on FormatException {
        return "INVALID_SERVER_RESPONSE";
      } catch (e) {
        debugPrint("⚠️ Site $siteId 상태 조회 실패: $e");
      }

      if (!(shouldContinue?.call() ?? true)) break;
      await Future<void>.delayed(pollInterval);
    }

    return "CANCELLED";
  }

  Future<void> deleteIndividualNotice(
    String siteName,
    int noticeId,
    String userToken,
  ) async {
    final url = Uri.parse('https://${_ipAddress}/v1/notices/$noticeId');

    try {
      final response = await http.delete(
        url,
        headers: {
          'Authorization':
              'Bearer $userToken',
        },
      );

      if (response.statusCode == 200) {
        if (_notices.containsKey(siteName)) {
          _notices[siteName]!.removeWhere(
            (notice) => notice['notice_id'] == noticeId,
          );
          notifyListeners();
          _saveToLocal();
          debugPrint("✅ 백엔드 및 로컬 항목 삭제 완료: $noticeId");
        }
      } else {
        debugPrint("❌ 서버 삭제 실패: 상태 코드 ${response.statusCode}");
      }
    } catch (e) {
      debugPrint("❌ 네트워크 API 통신 오류 발생: $e");
    }
  }

  Future<void> reorderSubscriptions(int oldIndex, int newIndex) async {
    if (oldIndex < newIndex) {
      newIndex -= 1;
    }

    List<String> keys = _notices.keys.toList();

    final String movedKey = keys.removeAt(oldIndex);
    keys.insert(newIndex, movedKey);

    Map<String, List<Map<String, dynamic>>> reorderedMap = {};
    for (var key in keys) {
      reorderedMap[key] = _notices[key]!;
    }

    _notices = reorderedMap;
    notifyListeners();
    await _saveCurrentSubscriptionOrder();
    await _saveToLocal();
  }

  Future<List<int>> _ensureSubscriptionOrderLoaded() {
    if (_isSubscriptionOrderLoaded) {
      return Future.value(_subscriptionOrder);
    }

    final runningLoad = _subscriptionOrderLoadInFlight;
    if (runningLoad != null) return runningLoad;

    final load = PreferencesService.loadSubscriptionOrder().then((order) {
      _subscriptionOrder = order;
      _isSubscriptionOrderLoaded = true;
      return order;
    });
    _subscriptionOrderLoadInFlight = load;
    return load.whenComplete(() {
      if (identical(_subscriptionOrderLoadInFlight, load)) {
        _subscriptionOrderLoadInFlight = null;
      }
    });
  }

  Map<String, List<Map<String, dynamic>>> _applySubscriptionOrder(
    Map<String, List<Map<String, dynamic>>> source,
    Map<String, Map<String, dynamic>> metadata,
  ) {
    if (_subscriptionOrder.isEmpty || source.length < 2) {
      return Map<String, List<Map<String, dynamic>>>.from(source);
    }

    final remaining = Map<String, List<Map<String, dynamic>>>.from(source);
    final ordered = <String, List<Map<String, dynamic>>>{};

    for (final siteId in _subscriptionOrder) {
      String? matchingAlias;
      for (final alias in remaining.keys) {
        if (_siteIdForAlias(alias, remaining, metadata) == siteId) {
          matchingAlias = alias;
          break;
        }
      }
      if (matchingAlias != null) {
        ordered[matchingAlias] = remaining.remove(matchingAlias)!;
      }
    }

    ordered.addAll(remaining);
    return ordered;
  }

  Map<String, List<Map<String, dynamic>>> _sortNoticeGroups(
    Map<String, List<Map<String, dynamic>>> source,
  ) {
    return source.map(
      (siteName, notices) =>
          MapEntry(siteName, NoticeChronology.sortedNewestFirst(notices)),
    );
  }

  int? _siteIdForAlias(
    String alias,
    Map<String, List<Map<String, dynamic>>> notices,
    Map<String, Map<String, dynamic>> metadata,
  ) {
    final metadataId = _parseSiteId(metadata[alias]?['site_id']);
    if (metadataId != null) return metadataId;

    for (final notice in notices[alias] ?? const <Map<String, dynamic>>[]) {
      final noticeSiteId = _parseSiteId(notice['site_id']);
      if (noticeSiteId != null) return noticeSiteId;
    }
    return null;
  }

  Future<void> _saveCurrentSubscriptionOrder() async {
    final order = <int>[];
    for (final alias in _notices.keys) {
      final siteId = _siteIdForAlias(alias, _notices, _siteMetadata);
      if (siteId != null && !order.contains(siteId)) order.add(siteId);
    }
    _subscriptionOrder = order;
    _isSubscriptionOrderLoaded = true;
    await PreferencesService.saveSubscriptionOrder(order);
  }

  Future<bool> deleteSubscription(String targetAlias) async {
    final String? token = await PreferencesService.getAuthToken();

    if (token == null || token.isEmpty) {
      debugPrint("❌ 로그인 토큰이 없어 구독 삭제를 중단합니다.");
      return false;
    }

    int? siteId = getSiteId(targetAlias);
    if (siteId == null) {
      await _refreshSubscriptionMetadata(token);
      siteId = getSiteId(targetAlias);
    }
    if (siteId == null) {
      debugPrint("❌ '$targetAlias'의 siteId를 찾을 수 없어 구독 삭제를 중단합니다.");
      return false;
    }

    final prefs = await SharedPreferences.getInstance();
    final allKeys = prefs.getKeys();
    String? targetUrl;
    final cleanTargetAlias = targetAlias.trim();

    for (String key in allKeys) {
      final storedValue = prefs.getString(key);
      if (storedValue != null && storedValue.trim() == cleanTargetAlias) {
        targetUrl = key;
        break;
      }
    }

    final bool backupHasKey = _notices.containsKey(targetAlias);
    final List<Map<String, dynamic>>? backupNotices = _notices[targetAlias];
    final Map<String, dynamic>? backupMetadata = _siteMetadata[targetAlias];
    final Map<String, dynamic>? backupDisplayLimit =
        _displayLimits[targetAlias];

    if (backupHasKey || backupMetadata != null) {
      _notices.remove(targetAlias);
      _siteMetadata.remove(targetAlias);
      _newBadgeHighlights.remove(targetAlias);
      _displayLimits.remove(targetAlias);
      notifyListeners();
    }

    try {
      final response = await http.delete(
        Uri.parse('https://${_ipAddress}/v1/subscriptions/$siteId'),
        headers: {
          'Authorization': 'Bearer $token',
          'Content-Type': 'application/json',
        },
      );

      if (response.statusCode == 200 || response.statusCode == 204) {
        if (targetUrl != null) {
          await prefs.remove(targetUrl);
        }
        await PreferencesService.saveDisplayLimits(_displayLimits);
        await _saveToLocal();
        debugPrint("✅ 서버 및 로컬에서 '$targetAlias' 구독 삭제 완료");
        return true;
      } else {
        throw Exception('서버 측 삭제 실패 (상태 코드: ${response.statusCode})');
      }
    } catch (e) {
      debugPrint("⚠️ 통신 에러 또는 서버 삭제 실패: $e");

      if (backupHasKey && backupNotices != null) {
        _notices[targetAlias] = backupNotices;
      }
      if (backupMetadata != null) {
        _siteMetadata[targetAlias] = backupMetadata;
      }
      if (backupDisplayLimit != null) {
        _displayLimits[targetAlias] = backupDisplayLimit;
      }
      if (backupHasKey || backupMetadata != null) {
        notifyListeners();
        debugPrint("🔄 서버 통신 실패로 인해 '$targetAlias' UI 상태를 롤백했습니다.");
      }
      return false;
    }
  }

  Future<void> _refreshSubscriptionMetadata(String token) async {
    try {
      final response = await http.get(
        Uri.parse('https://${_ipAddress}/v1/subscriptions_sites'),
        headers: {
          'Authorization': 'Bearer $token',
          'Content-Type': 'application/json',
        },
      );
      if (response.statusCode != 200) return;

      final dynamic decoded = jsonDecode(response.body);
      if (decoded is! Map || decoded['sites'] is! List) return;

      final Map<String, Map<String, dynamic>> refreshed = {};
      for (final dynamic rawSite in decoded['sites'] as List) {
        if (rawSite is! Map) continue;
        final Map<String, dynamic> site = Map<String, dynamic>.from(rawSite);
        final String alias =
            site['alias']?.toString() ?? site['url']?.toString() ?? '';
        final int? siteId = _parseSiteId(site['site_id']);
        if (alias.isEmpty || siteId == null) continue;
        refreshed[alias] = {
          'site_id': siteId,
          'has_new': site['has_new'] == true,
          'notification_enabled': site['notification_enabled'] == true,
        };
      }

      _siteMetadata = refreshed;
      notifyListeners();
      await PreferencesService.saveSiteMetadata(_siteMetadata);
    } catch (e) {
      debugPrint("⚠️ 구독 식별자 갱신 실패: $e");
    }
  }

  Future<void> markAsRead(String siteName) async {
    final int? siteId = getSiteId(siteName);

    if (siteId == null) {
      debugPrint("❌ $siteName에 해당하는 siteId를 찾을 수 없습니다.");
      return;
    }

    // 후속 작업 실패 시 복원할 수 있도록 네트워크 요청 전에 신규 상태를 보관합니다.
    final bool previousHasNew = _siteMetadata[siteName]?['has_new'] == true;
    final List<Map<String, dynamic>> notices = _notices[siteName] ?? [];
    final Set<int> previouslyNewNoticeIds = notices
        .where(isNoticeNew)
        .map((notice) => _parseId(notice['notice_id']))
        .whereType<int>()
        .toSet();

    // 빈 Set도 폴더를 연 현재 세션에서 신규 표시를 관리 중임을 뜻합니다.
    if (previousHasNew || previouslyNewNoticeIds.isNotEmpty) {
      _newBadgeHighlights[siteName] = previouslyNewNoticeIds;
    }
    _siteMetadata[siteName]?['has_new'] = false;
    for (final notice in notices) {
      notice['is_new'] = false;
    }
    notifyListeners();

    void restoreUnreadState() {
      _newBadgeHighlights.remove(siteName);
      _siteMetadata[siteName]?['has_new'] = previousHasNew;
      for (final notice in notices) {
        if (previouslyNewNoticeIds.contains(_parseId(notice['notice_id']))) {
          notice['is_new'] = true;
        }
      }
      notifyListeners();
    }

    // 진행 중인 새로고침이 읽기 전 상태를 덮지 않도록 완료 후 다시 정리합니다.
    final Future<void>? fetchToReconcile = _fetchInFlight;

    final String? token = await storage.read(key: "jwt_token");

    if (token == null) {
      restoreUnreadState();
      debugPrint("로그인 토큰이 없습니다.");
      return;
    }

    try {
      final response = await http.patch(
        Uri.parse('https://${_ipAddress}/v1/sites/$siteId/view'),
        headers: {
          'Authorization': 'Bearer $token',
          'Content-Type': 'application/json',
        },
      );

      if (response.statusCode == 200) {
        if (fetchToReconcile != null) {
          await fetchToReconcile;
        }

        // 늦게 끝난 새로고침이 복원한 신규 상태를 성공 시 다시 정리합니다.
        final latestNotices = _notices[siteName] ?? [];
        final latestNewNoticeIds = latestNotices
            .where(isNoticeNew)
            .map((notice) => _parseId(notice['notice_id']))
            .whereType<int>()
            .toSet();
        final activeHighlights = _newBadgeHighlights[siteName];
        if (activeHighlights != null) {
          activeHighlights.addAll(latestNewNoticeIds);
        }
        _siteMetadata[siteName]?['has_new'] = false;
        for (final notice in latestNotices) {
          notice['is_new'] = false;
        }
        notifyListeners();
        await _saveToLocal();
        debugPrint("✅ Site $siteId ($siteName) 읽음 처리 완료");
      } else {
        throw Exception('읽음 처리 실패: ${response.statusCode}');
      }
    } catch (e) {
      restoreUnreadState();
      debugPrint("❌ 읽음 처리 API 호출 에러: $e");
    }
  }
}
