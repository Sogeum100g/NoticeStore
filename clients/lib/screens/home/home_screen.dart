import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:intl/intl.dart';
import 'package:table_calendar/table_calendar.dart';

// 프로젝트 구조에 맞게 NoticeProvider 경로를 확인하세요. [cite: 2026-02-15]
import '../../providers/notice_provider.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final ScrollController _scrollController = ScrollController();
  final TextEditingController _searchController = TextEditingController();
  bool _isSearching = false;



  // 💡 [핵심] 날짜별 GlobalKey 저장소.
  // 한번 생성된 키를 유지하여 '작동 안 함' 현상을 방지합니다. [cite: 2026-02-17]
  final Map<String, GlobalKey> _dateKeys = {};

  @override
  void dispose() {
    _scrollController.dispose();
    _searchController.dispose();
    super.dispose();
  }

  // URL 실행 함수
  Future<void> _launchURL(String urlString) async {
    final Uri url = Uri.parse(urlString);
    if (!await launchUrl(url, mode: LaunchMode.externalApplication)) {
      debugPrint("Could not launch $url");
    }
  }

  // 💡 [핵심] 정밀 스크롤 함수
  void _preciseScroll(String searchKey) {
    final context = _dateKeys[searchKey]?.currentContext;
    if (context != null) {
      Scrollable.ensureVisible(
        context,
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeInOut,
        alignment: 0.0, // 화면 최상단 고정 [cite: 2026-02-15]
      );
    }
  }

  // 💡 [핵심] 2단계 이동 전략
  // 1. jumpTo로 해당 영역 근처로 즉시 날아갑니다. (위젯 생성 유도)
  // 2. addPostFrameCallback으로 위젯이 그려진 후 정밀 조준합니다. [cite: 2026-02-17]
  void _scrollToDate(DateTime pickedDate, List<Map<String, dynamic>> timeline) {
    if (timeline.isEmpty) return;

    // 1. 💡 [인덱스 찾기] 선택 날짜 '이후'의 가장 가까운 데이터 찾기
    int targetIndex = -1;
    for (int i = timeline.length - 1; i >= 0; i--) {
      final DateTime itemDate = timeline[i]['scraped_at'] as DateTime;
      // 선택 날짜보다 미래거나 같은 날 중 가장 과거인 것(리스트 상 가장 아래쪽)
      if (itemDate.isAfter(pickedDate) || DateUtils.isSameDay(itemDate, pickedDate)) {
        targetIndex = i;
        break;
      }
    }

    if (targetIndex == -1) targetIndex = 0;

    final targetItem = timeline[targetIndex];
    final searchKey = DateFormat('yyyyMMdd').format(targetItem['scraped_at']);

    // 2. 💡 [정밀 오프셋 계산] 높이 값을 현실적으로 상향 조정
    double estimatedOffset = 0.0;
    String? lastDate;

    for (int i = 0; i < targetIndex; i++) {
      final item = timeline[i];
      String currentDate = DateFormat('yyyyMMdd').format(item['scraped_at']);

      if (currentDate != lastDate) {
        estimatedOffset += 55.0; // 💡 날짜 헤더 높이 상향 (45 -> 55)
        lastDate = currentDate;
      }
      estimatedOffset += 95.0; // 💡 아이템 높이 상향 (75 -> 95)
    }

    // 3. 💡 [이동 실행]
    _scrollController.animateTo(
      estimatedOffset,
      duration: const Duration(milliseconds: 500), // 조금 더 천천히 이동하며 위젯 생성 유도
      curve: Curves.easeOut,
    );

    // 4. 💡 [최종 보정] 이동 후 해당 날짜 헤더를 정확히 시야에 고정 [cite: 2026-02-17]
    WidgetsBinding.instance.addPostFrameCallback((_) {
      Future.delayed(const Duration(milliseconds: 600), () => _preciseScroll(searchKey));
    });
  }


  // 커스텀 달력
  void _showModernCalendar(BuildContext context, List<Map<String, dynamic>> timeline) {
    final DateTime now = DateTime.now();

    // 1. 💡 [데이터 기반 범위 설정] 가장 과거 공지 날짜 추출
    // 리스트가 최신순 정렬이므로 마지막(last) 요소가 가장 과거입니다. [cite: 2026-02-15]
    DateTime firstAvailableDate = now;
    if (timeline.isNotEmpty) {
      final oldestDate = timeline.last['scraped_at'] as DateTime;
      firstAvailableDate = oldestDate.isBefore(now) ? oldestDate : now;
    }

    DateTime focusedDay = now;
    DateTime? selectedDay = now;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,

      builder: (context) {
        return StatefulBuilder(
          builder: (context, setST) => Container(
            height: MediaQuery.of(context).size.height * 0.72,
            decoration: const BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
            ),

            child: Column(
              children: [
                // 💡 [헤더] 연/월 선택 UI (이미지 디자인 반영)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 20, 16, 10),

                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      IconButton(
                        icon: const Icon(Icons.chevron_left, color: Colors.black54),
                        onPressed: () => setST(() => focusedDay = DateTime(focusedDay.year, focusedDay.month - 1)),
                      ),
                      const Spacer(),

                      // 1. 💡 [연도 선택 GestureDetector]
                      GestureDetector(
                        onTap: () async {
                          final int? selectedYear = await showDialog<int>(
                            context: context,
                            builder: (context) => AlertDialog(
                              title: const Text("연도 선택"),
                              content: SizedBox(
                                width: 300,
                                child: GridView.count(
                                  shrinkWrap: true,
                                  crossAxisCount: 3,
                                  children: List.generate(
                                    now.year - firstAvailableDate.year + 1,
                                        (i) => TextButton(
                                      onPressed: () => Navigator.pop(context, firstAvailableDate.year + i),
                                      child: Text("${firstAvailableDate.year + i}"),
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          );
                          if (selectedYear != null) {
                            setST(() {
                              // 💡 1. 일단 사용자가 선택한 연도로 날짜를 만듭니다.
                              DateTime newFocusedDay = DateTime(selectedYear, focusedDay.month, focusedDay.day);

                              // 💡 2. [핵심] 이 날짜가 데이터 시작점보다 과거라면, 시작점으로 강제 고정합니다.
                              if (newFocusedDay.isBefore(firstAvailableDate)) {
                                newFocusedDay = firstAvailableDate;
                              }
                              // 💡 3. 반대로 오늘보다 미래라면 오늘로 고정합니다.
                              if (newFocusedDay.isAfter(now)) {
                                newFocusedDay = now;
                              }

                              focusedDay = newFocusedDay;
                            });
                          }
                        },
                        child: Row(
                          children: [
                            Text("${focusedDay.year}년", style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                            const Icon(Icons.arrow_drop_down),
                          ],
                        ),
                      ),

                      const SizedBox(width: 12),

                      // 2. 💡 [월 선택 GestureDetector]
                      GestureDetector(
                        onTap: () async {
                          final int? selectedMonth = await showDialog<int>(
                            context: context,
                            builder: (context) => AlertDialog(
                              title: const Text("월 선택"),
                              content: SizedBox(
                                width: 300,
                                child: GridView.count(
                                  shrinkWrap: true,
                                  crossAxisCount: 4,
                                  children: List.generate(
                                    12,
                                        (i) => TextButton(
                                      onPressed: () => Navigator.pop(context, i + 1),
                                      child: Text("${i + 1}월"),
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          );
                          if (selectedMonth != null) {
                            setST(() {
                              // 💡 1. 사용자가 선택한 월로 날짜를 만듭니다.
                              DateTime newFocusedDay = DateTime(focusedDay.year, selectedMonth, focusedDay.day);

                              // 💡 2. [핵심] 범위를 벗어나는지 체크하여 보정합니다.
                              if (newFocusedDay.isBefore(firstAvailableDate)) {
                                newFocusedDay = firstAvailableDate;
                              } else if (newFocusedDay.isAfter(now)) {
                                newFocusedDay = now;
                              }

                              focusedDay = newFocusedDay;
                            });
                          }
                        },
                        child: Row(
                          children: [
                            Text("${focusedDay.month}월", style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                            const Icon(Icons.arrow_drop_down),
                          ],
                        ),
                      ),

                      const Spacer(),
                      IconButton(
                        icon: const Icon(Icons.chevron_right, color: Colors.black54),
                        onPressed: () => setST(() => focusedDay = DateTime(focusedDay.year, focusedDay.month + 1)),
                      ),
                    ],
                  ),
                ),

                // 💡 [메인] TableCalendar 영역
                Expanded(
                  child: TableCalendar(
                    locale: 'ko_KR',
                    firstDay: firstAvailableDate, // 💡 2020 대신 실제 최과거 날짜 적용
                    lastDay: now,
                    focusedDay: focusedDay,
                    headerVisible: false, // 커스텀 헤더 사용을 위해 숨김
                    selectedDayPredicate: (day) => isSameDay(selectedDay, day),
                    onDaySelected: (selected, focused) {
                      setST(() {
                        selectedDay = selected;
                        focusedDay = focused;
                      });
                    },
                    // 🎨 이미지와 일치하는 폰트 및 배경색 설정
                    calendarStyle: CalendarStyle(
                      todayDecoration: BoxDecoration(
                        color: const Color(0xFF2E6FF1).withOpacity(0.1),
                        shape: BoxShape.circle,
                      ),
                      todayTextStyle: const TextStyle(color: Color(0xFF2E6FF1), fontWeight: FontWeight.bold),
                      selectedDecoration: const BoxDecoration(
                        color: Color(0xFF2E6FF1), // 이미지의 메인 블루 컬러
                        shape: BoxShape.circle,
                      ),
                      defaultTextStyle: const TextStyle(color: Color(0xFF333333), fontSize: 16),
                      weekendTextStyle: const TextStyle(color: Color(0xFF333333)),
                      outsideDaysVisible: false,
                    ),
                    daysOfWeekStyle: const DaysOfWeekStyle(
                      weekdayStyle: TextStyle(color: Colors.grey, fontSize: 13),
                      weekendStyle: TextStyle(color: Colors.grey, fontSize: 13),
                    ),
                  ),
                ),

                // 💡 [푸터] 버튼 영역 (이미지 하단 구성)
                Container(
                  padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
                  decoration: const BoxDecoration(
                    border: Border(top: BorderSide(color: Color(0xFFF5F5F5))),
                  ),
                  child: Row(
                    children: [
                      TextButton(
                        onPressed: () => setST(() {
                          selectedDay = now;
                          focusedDay = now;
                        }),
                        child: const Text("오늘", style: TextStyle(color: Colors.black87, fontSize: 16)),
                      ),
                      const Spacer(),
                      OutlinedButton(
                        style: OutlinedButton.styleFrom(
                          side: const BorderSide(color: Color(0xFFE0E0E0)),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                        ),
                        onPressed: () => Navigator.pop(context),
                        child: const Text("취소", style: TextStyle(color: Colors.black87)),
                      ),
                      const SizedBox(width: 8),
                      ElevatedButton(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF2E6FF1),
                          elevation: 0,
                          padding: const EdgeInsets.symmetric(horizontal: 24),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                        ),
                        onPressed: () {
                          if (selectedDay != null) _scrollToDate(selectedDay!, timeline);
                          Navigator.pop(context);
                        },
                        child: const Text("선택", style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }


  @override
  Widget build(BuildContext context) {
    final noticeProv = context.watch<NoticeProvider>();

    // [참고] 데이터 가공 로직은 나중에 Provider 내부로 옮기는 것이 성능상 유리합니다. [cite: 2026-02-15]
    List<Map<String, dynamic>> timeline = [];
    final String query = noticeProv.searchQuery.toLowerCase();

    noticeProv.notices.forEach((siteKey, items) {
      for (var item in items) {
        String title = item['title']?.toString() ?? "제목 없음";
        if (query.isEmpty || title.toLowerCase().contains(query)) {
          timeline.add({
            'title': title,
            'scraped_at': DateTime.parse(item['created_at'].toString().split('+')[0]),
            'url': item['url']?.toString() ?? "",
            'siteName': siteKey,
          });
        }
      }
    });

    timeline.sort((a, b) => b['scraped_at'].compareTo(a['scraped_at']));

    return Scaffold(
      backgroundColor: Colors.white,
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 상단 바 (검색 및 달력)
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
            child: Row(
              children: [
                if (!_isSearching) ...[
                  const Icon(Icons.folder_open, color: Colors.orangeAccent),
                  const SizedBox(width: 8),
                ],
                Expanded(
                  child: _isSearching
                      ? TextField(
                    controller: _searchController,
                    autofocus: true,
                    decoration: const InputDecoration(
                      hintText: "알림 내역 검색...",
                      border: InputBorder.none,
                      hintStyle: TextStyle(color: Colors.grey, fontSize: 18),
                    ),
                    style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                    onChanged: (value) => noticeProv.updateSearchQuery(value),
                  )
                      : const Text("알림 내역", style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
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
                if (!_isSearching)
                  IconButton(
                    icon: const Icon(Icons.calendar_month, color: Colors.black54),
                    onPressed: () {
                      // 💡 [수정] 이제 이 한 줄만으로 커스텀 달력이 실행됩니다.
                      _showModernCalendar(context, timeline);
                    },
                  ),
              ],
            ),
          ),

          // 공지 리스트
          Expanded(
            child: noticeProv.isLoading
            // 이미 로딩 중일 때는 기본 인디케이터를 보여줌 (새로고침 제스처 중복 방지)
                ? const Center(child: CircularProgressIndicator())
            // 로딩이 끝난 후, 당겨서 새로고침 기능 활성화
                : RefreshIndicator(
              onRefresh: () async {
                await noticeProv.fetchNoticesFromServer();
              },
              child: timeline.isEmpty
              // 1. 공지가 없을 때: 빈 화면에서도 당겨서 새로고침이 가능하도록 CustomScrollView 적용
                  ? CustomScrollView(
                physics: const AlwaysScrollableScrollPhysics(),
                slivers: [
                  SliverFillRemaining(
                    hasScrollBody: false, // 내부 위젯이 자체 스크롤을 가지지 않음을 명시
                    child: _buildEmptyState(),
                  ),
                ],
              )
              // 2. 공지가 있을 때: ListView에 AlwaysScrollableScrollPhysics 추가
                  : ListView.builder(
                physics: const AlwaysScrollableScrollPhysics(),
                controller: _scrollController,
                padding: const EdgeInsets.symmetric(horizontal: 16),
                itemCount: timeline.length,
                itemBuilder: (context, index) {
                  final item = timeline[index];
                  final currentData = item['scraped_at'] as DateTime;
                  final dateKeyFormat = DateFormat('yyyy년 M월 d일').format(currentData);
                  final searchKey = DateFormat('yyyyMMdd').format(currentData);

                  bool showHeader = index == 0 ||
                      DateFormat('yyyyMMdd').format(timeline[index - 1]['scraped_at']) != searchKey;

                  // 💡 [중요] 키가 없을 때만 생성하여 위치를 고정합니다.
                  if (showHeader) {
                    _dateKeys.putIfAbsent(searchKey, () => GlobalKey());
                  }

                  return Column(
                    key: showHeader ? _dateKeys[searchKey] : null,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (showHeader)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 4),
                          child: Text(dateKeyFormat, style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w500)),
                        ),
                      _buildNoticeItem(item),
                    ],
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }

  // 공지 아이템 위젯
  Widget _buildNoticeItem(Map<String, dynamic> item) {
    return GestureDetector(
      onTap: () => _launchURL(item['url']),
      child: Container(
        width: double.infinity,
        margin: const EdgeInsets.only(bottom: 2),
        padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 8),
        decoration: const BoxDecoration(
          color: Colors.white,
          border: Border(bottom: BorderSide(color: Color(0xFFEEEEEE), width: 1)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(item['title'],
                style: const TextStyle(fontSize: 15, color: Colors.black87),
                maxLines: 3,
                overflow: TextOverflow.ellipsis
            ),
            const SizedBox(height: 4),
            Text(item['siteName'],
                style: const TextStyle(fontSize: 15, color: Colors.grey),
                maxLines: 1,
                overflow: TextOverflow.ellipsis),
          ],
        ),
      ),
    );
  }

  // 데이터 없을 때 UI
  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.insert_drive_file_outlined, size: 64, color: Colors.grey[300]),
          const SizedBox(height: 16),
          Text(_isSearching ? "검색 결과가 없습니다." : "추가 탭에서 웹페이지를 등록해보세요.",
              style: const TextStyle(color: Colors.grey, fontSize: 16)),
        ],
      ),
    );
  }
}