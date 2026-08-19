import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../models/site_model.dart';
import '../services/preferences_service.dart';

// 1. 클래스 상단 혹은 전역에 storage 인스턴스 생성
const storage = FlutterSecureStorage();

// 💡 1. Isolate에서 실행될 최상위 파싱 함수 (클래스 외부에 위치해야 합니다)
// 💡 백그라운드 스레드(Isolate)에서 실행될 독립적인 함수입니다.
// Isolate는 단 하나의 인자만 받을 수 있으므로 Map을 이용해 필요한 데이터를 묶어서 전달받습니다.
// 💡 1. Isolate에서 실행될 최상위 파싱 함수 (클래스 외부에 위치해야 합니다)
// 💡 백그라운드 스레드(Isolate)에서 실행될 독립적인 함수입니다.
Map<String, List<Map<String, dynamic>>> _parseNoticesInBackground(Map<String, dynamic> args) {
  // 1. 전달받은 데이터 압축 해제
  final String responseBody = args['responseBody'];
  // 주의: 이전 단계(fetchNoticesFromServer)에서 siteStatusMap의 Key를
  // 반드시 url이 아닌 site_id(String)로 변경해서 넘겨주어야 이 코드가 정상 작동합니다.
  final Map<String, dynamic> siteStatusMap = args['siteStatusMap'];
  final Map<String, List<Map<String, dynamic>>> grouped = args['grouped'];

  // 2. 무거운 JSON 디코딩 수행
  final responseData = json.decode(responseBody);
  List<dynamic> fetchedNotices = responseData['notices'] ?? [];

  // 3. 데이터 가공 및 그룹화 수행
  for (var rawItem in fetchedNotices) {
    // Map<String, dynamic>으로 안전하게 캐스팅
    Map<String, dynamic> item = Map<String, dynamic>.from(rawItem);

    // 💡 [핵심 수정 1] 개별 상세 주소(url)가 아닌, 부모 사이트의 고유 식별자(site_id)를 추출합니다.
    String siteIdStr = item['site_id']?.toString() ?? "";

    // 폴더 이름(siteTitle)의 안전망(Fallback)을 설정합니다.
    // 절대 url을 기본값으로 쓰면 안 됩니다. (무한 증식 방지)
    String siteTitle = "알 수 없는 사이트 ($siteIdStr)";

    // 💡 [핵심 수정 2] 전달받은 siteStatusMap(site_id 기준)을 활용하여 부모 정보 병합
    if (siteStatusMap.containsKey(siteIdStr)) {
      // 기존 item에는 이미 site_id가 있으므로 덮어쓸 필요가 없고, 알림 배지 상태만 갱신합니다.
      item['has_new'] = siteStatusMap[siteIdStr]['has_new'];

      // alias(별칭)가 있으면 최우선으로 사용하고, 없으면 부모의 원래 목록 url을 폴더명으로 씁니다.
      siteTitle = siteStatusMap[siteIdStr]['alias'] ?? siteStatusMap[siteIdStr]['url'].toString();
    }

    // 💡 [핵심 수정 3] 찾아낸 올바른 폴더명(siteTitle)으로 그룹화 맵에 추가합니다.
    grouped.putIfAbsent(siteTitle, () => []).add(item);
  }

  // 가공이 완료된 최종 맵 반환
  return grouped;
}

class NoticeProvider with ChangeNotifier {
  // --- 1. 관리 변수 명세 (전부 반영) ---
  int _selectedIndex = 2;
  bool _isLoading = true;
  bool _isDataLoaded = false;
  String _searchQuery = "";
  String? _pendingUrl;
  String? _ipAddress = dotenv.env['IP_ADDRESS'];

  Timer? _saveTimer; // 💡 디바운스를 위한 타이머

  Map<String, List<Map<String, dynamic>>> _favoriteFolders = {};
  Map<String, List<String>> _siteKeywords = {}; // 사이트별 키워드
  Map<String, List<Map<String, dynamic>>> _notices = {}; // 구독 공지
  Map<String, List<String>> _folderKeywords = {}; // 폴더별 키워드
  // 💡 사이트 별명을 키로 하여 {site_id, has_new}를 저장하는 맵 추가
  Map<String, Map<String, dynamic>> _siteMetadata = {};

  // --- Getters ---
  int get selectedIndex => _selectedIndex;
  bool get isLoading => _isLoading;
  String get searchQuery => _searchQuery;
  Map<String, List<Map<String, dynamic>>> get favoriteFolders => _favoriteFolders;
  Map<String, List<Map<String, dynamic>>> get notices => _notices;
  Map<String, List<String>> get folderKeywords => _folderKeywords;
  String? get pendingUrl => _pendingUrl;
  // 특정 사이트가 새로운 공지를 가지고 있는지 확인하는 Getter
  bool isSiteNew(String alias) => _siteMetadata[alias]?['has_new'] ?? false;
  // 특정 사이트의 ID를 가져오는 Getter
  int? getSiteId(String alias) => _siteMetadata[alias]?['site_id'];
  // 백엔드 크롤링 상태를 UI에서 일관되게 표현하기 위한 Getter
  SiteCrawlStatus getSiteCrawlStatus(String alias) {
    return SiteCrawlStatus.fromApi(
      _siteMetadata[alias]?['crawl_status'],
    );
  }

  String? getSiteValidationError(String alias) {
    final error = _siteMetadata[alias]?['validation_error']?.toString().trim();
    return (error == null || error.isEmpty) ? null : error;
  }

  // 외부에서 URL을 주입할 때 호출
  void setPendingUrl(String url) {
    _pendingUrl = url;
    notifyListeners();
  }

  // URL을 소모(화면에 반영)했을 때 호출
  void consumePendingUrl() {
    _pendingUrl = null;
    // 여기서는 굳이 notifyListeners를 하지 않아도 됩니다 (필요 시 추가)
  }

  // --- 2. 초기화 및 로드 함수 ---

  // --- 1. 초기화 (빌드 충돌 방지) ---
  Future<void> loadSavedData() async {
    // 💡 즉시 상태를 변경하지 않고 다음 렌더링 사이클로 미룹니다.
    Future.microtask(() {
      _isLoading = true;
      notifyListeners();
    });

    final data = await PreferencesService.loadFavorites();
    _favoriteFolders = data['folders'] ?? {};
    _folderKeywords = data['keywords'] ?? {};
    _notices = await PreferencesService.loadNotices();

    _isLoading = false;
    _isDataLoaded = true;
    notifyListeners();
  }

  // 서버에서 최신 공지 가져오기
  // providers/notice_provider.dart
  // --- 2. 네트워크 호출 및 파싱 (Isolate 적용) ---
  Future<void> fetchNoticesFromServer() async {
    try {
      final String? token = await storage.read(key: "jwt_token");
      if (token == null) return;

      final Map<String, String> headers = {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      };

      // 1. 구독 중인 사이트 상태 가져오기
      final statusResponse = await http.get(
        Uri.parse('http://${_ipAddress}/v1/subscriptions_sites'),
        headers: headers,
      );

      Map<String, List<Map<String, dynamic>>> grouped = {};
      // 💡 Isolate로 넘기기 위해 타입을 Map<String, dynamic>으로 설정합니다.
      Map<String, dynamic> siteStatusMap = {};

      if (statusResponse.statusCode == 200) {
        final List<dynamic> siteData = json.decode(statusResponse.body)['sites'] ?? [];

        for (var s in siteData) {
          String siteName = s['alias'] ?? s['url'].toString();

          grouped[siteName] = []; // 폴더 미리 초기화

          _siteMetadata[siteName] = {
            'site_id': s['site_id'],
            'has_new': s['has_new'] ?? false,
            'url': s['url'],
            'crawl_status': s['crawl_status'] ?? 'active',
            'validation_error': s['validation_error'],
          };
          // 💡 [수정] url 대신 site_id를 Key로 사용합니다. (타입 오류 방지를 위해 String 변환)
          siteStatusMap[s['site_id'].toString()] = s;
        }
      }

      // 2. 전체 공지 데이터 가져오기
      final response = await http.get(
        Uri.parse('http://${_ipAddress}/v1/notices'),
        headers: headers,
      );

      if (response.statusCode == 200) {
        // 💡 [핵심 최적화] 메인 스레드를 멈추지 않고 백그라운드에서 파싱을 지시합니다.
        final parsedGrouped = await compute(_parseNoticesInBackground, {
          'responseBody': response.body,
          'siteStatusMap': siteStatusMap,
          'grouped': grouped, // 1번에서 초기화한 빈 폴더 구조도 함께 넘깁니다.
        });

        // 파싱이 끝나면 메인 스레드로 돌아와 상태를 업데이트합니다.
        _notices = parsedGrouped;
        notifyListeners();
        await _saveToLocal();
      }
    } catch (e) {
      debugPrint("❌ 공지 로딩 에러: $e");
    }
  }

  Future<void> _refreshPendingSiteUntilReady(int siteId) async {
    const int maxAttempts = 30;
    const Duration interval = Duration(seconds: 2);

    for (int attempt = 0; attempt < maxAttempts; attempt++) {
      await Future<void>.delayed(interval);

      try {
        final String? token = await storage.read(key: "jwt_token");
        if (token == null) return;

        final response = await http.get(
          Uri.parse('http://${_ipAddress}/v1/sites/$siteId/status'),
          headers: {
            'Authorization': 'Bearer $token',
            'Content-Type': 'application/json',
          },
        ).timeout(const Duration(seconds: 10));

        if (response.statusCode != 200) continue;

        final Map<String, dynamic> responseData =
            Map<String, dynamic>.from(jsonDecode(response.body));
        final Map<String, dynamic> site =
            Map<String, dynamic>.from(responseData['site'] ?? {});
        final SiteCrawlStatus crawlStatus =
            SiteCrawlStatus.fromApi(site['crawl_status']);

        if (crawlStatus == SiteCrawlStatus.pending ||
            crawlStatus == SiteCrawlStatus.unknown) {
          continue;
        }

        // 완료·실패 여부를 서버에서 다시 받아 공지 수와 상태 배지를 갱신한다.
        await fetchNoticesFromServer();
        return;
      } catch (e) {
        debugPrint("⚠️ 사이트 $siteId 상태 확인 재시도: $e");
      }
    }

    // 제한 시간 이후에도 마지막 서버 상태를 한 번 반영한다.
    await fetchNoticesFromServer();
  }

  // --- 3. 비즈니스 로직 함수 (명세 반영) ---

  // --- 3. UI 조작 메서드들 (Debounce 적용) ---
  void addNoticeToFolder(String folderName, Map<String, dynamic> notice) {
    _favoriteFolders[folderName]?.add(notice);
    notifyListeners();
    _debouncedSaveToLocal(); // 💡
  }



  // 공지 이동
  void moveNoticeToOtherFolder(String fromFolder, String toFolder, Map<String, dynamic> notice) {
    if (fromFolder == toFolder) return;
    _favoriteFolders[fromFolder]?.removeWhere((item) => item['notice_id'] == notice['notice_id']);
    _favoriteFolders[toFolder]?.add(notice);
    notifyListeners();
    _debouncedSaveToLocal(); // 💡
  }

  // --- 4. 디스크 I/O 최적화 (Debouncing) ---
  void _debouncedSaveToLocal() {
    if (!_isDataLoaded) return;

    // 타이머가 이미 돌고 있다면 취소하고 새로 시작 (연속 호출 시 마지막 호출만 실행됨)
    if (_saveTimer?.isActive ?? false) _saveTimer!.cancel();

    _saveTimer = Timer(const Duration(seconds: 2), () async {
      await PreferencesService.saveNotices(_notices);
      await PreferencesService.saveFavorites(folders: _favoriteFolders, keywords: _folderKeywords);
      debugPrint("💾 [Provider] 로컬 저장 완료 (디바운스 적용)");
    });
  }

  // 구독 탭 이름 변경 (async인 이유: SharedPreferences 파일 쓰기 때문)
  Future<void> renameSubscriptionAlias(String oldName, String newName) async {
    if (oldName == newName || newName.isEmpty || _notices.containsKey(newName)) return;

    final data = _notices.remove(oldName);
    if (data != null) {
      _notices[newName] = data;
      // SharedPreferences에 별명 영구 저장
      if (data.isNotEmpty) {
        await PreferencesService.saveAlias(data[0]['url'].toString(), newName);
      }
    }
    _saveToLocal();
    notifyListeners();
  }

  // 키워드 자동 분류
  void autoCategorizeToFavorites() {
    _folderKeywords.forEach((folderName, keywords) {
      if (keywords.isEmpty) return;
      _notices.forEach((site, noticeList) {
        for (var notice in noticeList) {
          String title = notice["title"].toString().toLowerCase();
          if (keywords.any((k) => title.contains(k.toLowerCase()))) {
            bool exists = _favoriteFolders[folderName]!.any((item) => item['notice_id'] == notice['notice_id']);
            if (!exists) _favoriteFolders[folderName]!.add(notice);
          }
        }
      });
    });
    _saveToLocal();
    notifyListeners();
  }

  // --- 공통: 로컬 저장 ---
  Future<void> _saveToLocal() async {
    if (!_isDataLoaded) return;
    await PreferencesService.saveNotices(_notices);
    await PreferencesService.saveFavorites(folders: _favoriteFolders, keywords: _folderKeywords);
  }

  // 검색어 업데이트
  void updateSearchQuery(String query) {
    _searchQuery = query;
    notifyListeners();
  }

  // 탭 변경
  void setSelectedIndex(int index) {
    _selectedIndex = index;
    notifyListeners();
  }

  /// site_id를 기반으로 현재 메모리에 저장된 사이트 별명(alias)을 찾습니다.
  String? _getAliasBySiteId(int siteId) {
    try {
      // _siteMetadata의 모든 엔트리를 순회하며 site_id가 일치하는 Key(alias)를 찾습니다.
      return _siteMetadata.entries
          .firstWhere((entry) => entry.value['site_id'] == siteId)
          .key;
    } catch (e) {
      // 일치하는 ID가 없을 경우 null을 반환합니다.
      debugPrint("⚠️ [Provider] ID $siteId에 해당하는 별명을 찾을 수 없습니다.");
      return null;
    }
  }

  // --- 신규 데이터 수집 완료 시 처리 로직 ---
  void onFetchComplete(List<Map<String, dynamic>> fetchedData, int siteId) {

    // siteId를 통해 alias를 찾는 로직 추가 필요
    final String? alias = _getAliasBySiteId(siteId);
    if (alias == null) return;

    debugPrint("🚨 [Provider] 신규 데이터 수신: ${fetchedData.length}개 (별명: $alias)");

    if (fetchedData.isEmpty) return;

    // 1. 해당 별명을 키로 가지는 리스트가 없으면 생성
    if (!_notices.containsKey(alias)) {
      _notices[alias] = [];
    }

    // 2. 제목(title) 중복 체크를 하며 데이터 추가
    for (var item in fetchedData) {
      bool isAlreadyExist = _notices[alias]!.any((old) => old['title'] == item['title']);
      if (!isAlreadyExist) {
        _notices[alias]!.add(item);
      }
    }

    // 3. 상태 변경 알림 및 로컬 저장소 동기화
    notifyListeners();
    _saveToLocal();
  }

  // NoticeProvider.dart 내부에 추가
  Future<String> registerNewSite(String url, String alias) async {
    try {
      final String? token = await storage.read(key: "jwt_token");

      if (token == null) {
        return "NEED_LOGIN"; // 로그인 필요
      }

      final response = await http.post(
        Uri.parse('http://${_ipAddress}/v1/add-site'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
        body: jsonEncode({
          'url': url,
          'alias': alias,
        }),
      ).timeout(const Duration(seconds: 15));

      if (response.statusCode == 200) {
        final responseData = jsonDecode(response.body);

        // 💡 수정됨: 백엔드가 보내는 'status' 필드를 확인합니다.
        if (responseData['status'] == 'success') {
          final bool isPending = responseData['message'] == 'PENDING';
          debugPrint(
            isPending
                ? "⏳ 사이트 등록 접수. Site ID: ${responseData['site_id']}"
                : "✅ 사이트 등록 성공. Site ID: ${responseData['site_id']}",
          );

          // notices 추출 로직 제거 (백엔드에서 주지 않음)
          // 새로 추가된 사이트 정보를 반영하기 위해 전체 리스트를 다시 불러옵니다.
          await PreferencesService.saveAlias(url, alias);
          await fetchNoticesFromServer();
          if (isPending) {
            final int? siteId = (responseData['site_id'] as num?)?.toInt();
            if (siteId != null) {
              unawaited(_refreshPendingSiteUntilReady(siteId));
            }
          }

          return isPending ? "PENDING" : "SUCCESS";
        } else {
          return "UNKNOWN_ERROR";
        }
      } else {
        // 💡 에러 발생 시 백엔드에서 던진 detail 메시지를 파싱합니다.
        final errorData = jsonDecode(response.body);
        final errorDetail = errorData['detail'] ?? "UNKNOWN_ERROR";
        debugPrint("❌ 서버 응답 에러 (상태코드 ${response.statusCode}): $errorDetail");
        return errorDetail;
      }
    } catch (e) {
      debugPrint("❌ 사이트 등록 실패: $e");
      return "TIMEOUT_OR_NETWORK_ERROR";
    }
  }

  // --- 1. 개별 공지 삭제 함수 ---
  Future<void> deleteIndividualNotice(String siteName, int noticeId, String userToken) async {
    // 1. 로컬 환경의 FastAPI 서버 주소 (안드로이드 에뮬레이터 기준 10.0.2.2 사용)
    // 실제 서비스 시에는 환경 변수(dotenv 등)로 관리하는 것이 좋습니다.
    final url = Uri.parse('http://${_ipAddress}/v1/notices/$noticeId');

    try {
      // 2. 서버로 DELETE 요청 전송 (JWT 토큰 포함)
      final response = await http.delete(
        url,
        headers: {
          'Authorization': 'Bearer $userToken', // Depends(get_current_user_id) 통과를 위해 필요
        },
      );

      // 3. 서버 통신 성공(200 OK) 시에만 로컬 UI 업데이트 수행
      if (response.statusCode == 200) {
        if (_notices.containsKey(siteName)) {
          _notices[siteName]!.removeWhere((notice) => notice['notice_id'] == noticeId);
          notifyListeners();
          _saveToLocal();
          debugPrint("✅ 백엔드 및 로컬 항목 삭제 완료: $noticeId");
        }
      } else {
        // 400, 500 등 서버 에러 발생 시 처리
        debugPrint("❌ 서버 삭제 실패: 상태 코드 ${response.statusCode}");
        // TODO: 사용자에게 "삭제에 실패했습니다"라는 SnackBar 또는 Dialog 띄우기
      }
    } catch (e) {
      // 네트워크 단절 등 예외 상황 처리
      debugPrint("❌ 네트워크 API 통신 오류 발생: $e");
    }
  }

  // --- 2. 구독 탭 폴더 순서 변경 ---
  void reorderSubscriptions(int oldIndex, int newIndex) {
    if (oldIndex < newIndex) {
      newIndex -= 1;
    }

    // 1. 현재 키(사이트 별명/이름) 순서를 리스트로 추출 [cite: 2026-02-15]
    List<String> keys = _notices.keys.toList();

    // 2. 리스트 내 순서 변경 [cite: 2026-02-15]
    final String movedKey = keys.removeAt(oldIndex);
    keys.insert(newIndex, movedKey);

    // 3. 변경된 순서대로 새로운 Map 재구성 (순서 보존 핵심) [cite: 2026-02-15]
    Map<String, List<Map<String, dynamic>>> reorderedMap = {};
    for (var key in keys) {
      reorderedMap[key] = _notices[key]!;
    }

    // 4. 전체 데이터 교체 및 알림 [cite: 2026-02-15]
    _notices = reorderedMap;
    notifyListeners();
    _saveToLocal();
  }

  // --- 3. 구독 탭 폴더 삭제 함수 (서버 연동 및 낙관적 업데이트 적용) ---
  Future<void> deleteSubscription(String targetAlias) async {
    // 1. 서버 통신에 필요한 식별자(site_id) 및 인증 토큰 획득
    final int? siteId = _siteMetadata[targetAlias]?['site_id'];
    final String? token = await storage.read(key: "jwt_token");

    if (siteId == null || token == null) {
      debugPrint("❌ 삭제에 필요한 정보(siteId 또는 로그인 토큰)가 없어 삭제를 중단합니다.");
      return;
    }

    // 2. 로컬 저장소(SharedPreferences) 키 찾기 (기존 로직 유지)
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

    // 3. 낙관적 업데이트를 위한 데이터 백업
    final bool backupHasKey = _notices.containsKey(targetAlias);
    final List<Map<String, dynamic>>? backupNotices = _notices[targetAlias];
    final Map<String, dynamic>? backupMetadata = _siteMetadata[targetAlias];

    // 4. UI 즉시 반영: 서버 응답을 기다리지 않고 메모리에서 먼저 삭제하여 체감 속도 향상
    if (backupHasKey) {
      _notices.remove(targetAlias);
      _siteMetadata.remove(targetAlias); // 메타데이터도 찌꺼기가 남지 않게 함께 지워줍니다.
      notifyListeners();
    }

    try {
      // 5. 실제 서버(DB)에 삭제 요청 전송
      // 💡 [데이터 부족 안내] 삭제를 위한 정확한 API 엔드포인트는 백엔드 구현에 따라 다를 수 있습니다.
      // RESTful 표준 및 기존 코드를 참고하여 임의로 '/subscriptions/$siteId' 로 작성했습니다.
      final response = await http.delete(
        Uri.parse('http://${_ipAddress}/v1/subscriptions/$siteId'),
        headers: {
          'Authorization': 'Bearer $token',
          'Content-Type': 'application/json',
        },
      );

      // 6. 서버 응답 확인
      if (response.statusCode == 200 || response.statusCode == 204) {
        // 서버 DB에서 성공적으로 삭제된 것이 확인되면, 기기의 SharedPreferences에서도 영구 삭제
        if (targetUrl != null) {
          await prefs.remove(targetUrl);
        }
        await _saveToLocal(); // 로컬 파일 갱신
        debugPrint("✅ 서버 및 로컬에서 '$targetAlias' 구독 삭제 완료");
      } else {
        // HTTP 상태 코드가 실패를 가리키면 예외를 발생시킴
        throw Exception('서버 측 삭제 실패 (상태 코드: ${response.statusCode})');
      }

    } catch (e) {
      debugPrint("⚠️ 통신 에러 또는 서버 삭제 실패: $e");

      // 7. 에러 발생 시 롤백 (원상복구)
      // 네트워크 연결이 끊겼거나 서버 에러 시, 화면에서 지웠던 데이터를 다시 복구시켜 데이터 유실 방지
      if (backupHasKey && backupNotices != null) {
        _notices[targetAlias] = backupNotices;
        if (backupMetadata != null) {
          _siteMetadata[targetAlias] = backupMetadata;
        }
        notifyListeners();
        debugPrint("🔄 서버 통신 실패로 인해 '$targetAlias' UI 상태를 롤백했습니다.");
      }
    }
  }


  // NoticeProvider.dart 내부에 추가할 로직
  // 읽음 처리 함수 수정 [cite: 2026-02-17]
  Future<void> markAsRead(String siteName) async { // 다시 String으로 변경
    // 1. 이미 저장된 메타데이터에서 siteId를 찾습니다. [cite: 2026-02-17]
    // _siteMetadata는 서버에서 사이트 목록을 가져올 때 site_id를 저장하고 있어야 합니다.
    final int? siteId = _siteMetadata[siteName]?['site_id'];

    if (siteId == null) {
      debugPrint("❌ $siteName에 해당하는 siteId를 찾을 수 없습니다.");
      return;
    }

    // 2. 보안을 위해 저장된 JWT 토큰을 가져옵니다.
    final String? token = await storage.read(key: "jwt_token");

    if (token == null) {
      debugPrint("로그인 토큰이 없습니다.");
      return;
    }

    // 3. 추출한 siteId를 사용하여 API를 호출합니다.
    try {
      final response = await http.patch(
        Uri.parse('http://${_ipAddress}/v1/sites/$siteId/view'),
        headers: {
          'Authorization': 'Bearer $token',
          'Content-Type': 'application/json',
        },
      );

      if (response.statusCode == 200) {
        // 4. 로컬 상태 업데이트: "New" 표시를 즉시 제거합니다. [cite: 2026-02-17]
        _siteMetadata[siteName]?['has_new'] = false;
        notifyListeners();
        await _saveToLocal();
        debugPrint("✅ Site $siteId ($siteName) 읽음 처리 완료");
      }
    } catch (e) {
      debugPrint("❌ 읽음 처리 API 호출 에러: $e");
    }
  }
}
