import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:intl/intl.dart';
import 'package:table_calendar/table_calendar.dart';

import '../../providers/notice_provider.dart';
import '../../core/utils/notice_display_formatter.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final ScrollController _scrollController = ScrollController();
  final TextEditingController _searchController = TextEditingController();
  bool _isSearching = false;

  // 날짜 헤더의 렌더링 위치를 안정적으로 찾도록 키를 재사용합니다.
  final Map<String, GlobalKey> _dateKeys = {};

  @override
  void dispose() {
    _scrollController.dispose();
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _launchURL(String urlString) async {
    final Uri url = Uri.parse(urlString);
    if (!await launchUrl(url, mode: LaunchMode.externalApplication)) {
      debugPrint("Could not launch $url");
    }
  }

  void _preciseScroll(String searchKey) {
    final context = _dateKeys[searchKey]?.currentContext;
    if (context != null) {
      Scrollable.ensureVisible(
        context,
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeInOut,
        alignment: 0.0,
      );
    }
  }

  // 추정 위치로 먼저 이동한 뒤 다음 프레임에서 실제 헤더 위치로 보정합니다.
  void _scrollToDate(DateTime pickedDate, List<Map<String, dynamic>> timeline) {
    if (timeline.isEmpty) return;

    int targetIndex = -1;
    for (int i = timeline.length - 1; i >= 0; i--) {
      final DateTime itemDate = timeline[i]['scraped_at'] as DateTime;
      if (itemDate.isAfter(pickedDate) || DateUtils.isSameDay(itemDate, pickedDate)) {
        targetIndex = i;
        break;
      }
    }

    if (targetIndex == -1) targetIndex = 0;

    final targetItem = timeline[targetIndex];
    final searchKey = DateFormat('yyyyMMdd').format(targetItem['scraped_at']);

    double estimatedOffset = 0.0;
    String? lastDate;

    for (int i = 0; i < targetIndex; i++) {
      final item = timeline[i];
      String currentDate = DateFormat('yyyyMMdd').format(item['scraped_at']);

      if (currentDate != lastDate) {
        estimatedOffset += 55.0;
        lastDate = currentDate;
      }
      estimatedOffset += 95.0;
    }

    _scrollController.animateTo(
      estimatedOffset,
      duration: const Duration(milliseconds: 500),
      curve: Curves.easeOut,
    );

    WidgetsBinding.instance.addPostFrameCallback((_) {
      Future.delayed(const Duration(milliseconds: 600), () => _preciseScroll(searchKey));
    });
  }

  void _showModernCalendar(BuildContext context, List<Map<String, dynamic>> timeline) {
    final DateTime now = DateTime.now();

    // 리스트가 최신순 정렬이므로 마지막(last) 요소가 가장 과거입니다.
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
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 20, 16, 10),

                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      IconButton(
                        icon: const Icon(Icons.chevron_left, color: Colors.black54),
                        onPressed: () {
                          final DateTime prevMonth = DateTime(focusedDay.year, focusedDay.month - 1, 1);
                          setST(() {
                            focusedDay = prevMonth.isBefore(firstAvailableDate) ? firstAvailableDate : prevMonth;
                          });
                        },
                      ),
                      const Spacer(),

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
                              DateTime newFocusedDay = DateTime(selectedYear, focusedDay.month, focusedDay.day);

                              if (newFocusedDay.isBefore(firstAvailableDate)) {
                                newFocusedDay = firstAvailableDate;
                              }
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
                              DateTime newFocusedDay = DateTime(focusedDay.year, selectedMonth, focusedDay.day);

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
                        onPressed: () {
                          final DateTime nextMonth = DateTime(focusedDay.year, focusedDay.month + 1, 1);
                          setST(() {
                            focusedDay = nextMonth.isAfter(now) ? now : nextMonth;
                          });
                        },
                      ),
                    ],
                  ),
                ),

                Expanded(
                  child: TableCalendar(
                    locale: 'ko_KR',
                    firstDay: firstAvailableDate,
                    lastDay: now,
                    focusedDay: focusedDay,
                    headerVisible: false,
                    selectedDayPredicate: (day) => isSameDay(selectedDay, day),
                    onDaySelected: (selected, focused) {
                      setST(() {
                        selectedDay = selected;
                        focusedDay = focused;
                      });
                    },
                    calendarStyle: CalendarStyle(
                      todayDecoration: BoxDecoration(
                        color: const Color(0xFF2E6FF1).withOpacity(0.1),
                        shape: BoxShape.circle,
                      ),
                      todayTextStyle: const TextStyle(color: Color(0xFF2E6FF1), fontWeight: FontWeight.bold),
                      selectedDecoration: const BoxDecoration(
                        color: Color(0xFF2E6FF1),
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
            'author': item['author'],
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
                      _showModernCalendar(context, timeline);
                    },
                  ),
              ],
            ),
          ),

          Expanded(
            child: noticeProv.isLoading
                ? const Center(child: CircularProgressIndicator())
                : RefreshIndicator(
              onRefresh: () async {
                await noticeProv.fetchNoticesFromServer();
              },
              child: timeline.isEmpty
                  ? CustomScrollView(
                physics: const AlwaysScrollableScrollPhysics(),
                slivers: [
                  SliverFillRemaining(
                    hasScrollBody: false,
                    child: _buildEmptyState(),
                  ),
                ],
              )
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
            Text(
              NoticeDisplayFormatter.homeMetadata(
                item['siteName'].toString(),
                item,
              ),
              style: const TextStyle(fontSize: 15, color: Colors.grey),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Image.asset('assets/images/pigeon_sad_gray.png', width: 120),
          const SizedBox(height: 16),
          Text(_isSearching ? "검색 결과가 없습니다." : "아무런 소식이 없어요.\n추가 탭에서 웹페이지를 등록해보세요.",
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.grey, fontSize: 16)),
        ],
      ),
    );
  }
}
