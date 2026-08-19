import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../../../providers/settings_provider.dart';
import '../settings_wrapper.dart';

// -----------------------------------------------------------------------------
// 💡 커스텀 스크롤 휠 + 직접 입력 타임피커 위젯
// -----------------------------------------------------------------------------
class CustomWheelTimePicker extends StatefulWidget {
  final TimeOfDay initialTime;
  final ValueChanged<TimeOfDay> onTimeChanged;

  const CustomWheelTimePicker({
    super.key,
    required this.initialTime,
    required this.onTimeChanged,
  });

  @override
  State<CustomWheelTimePicker> createState() => _CustomWheelTimePickerState();
}

class _CustomWheelTimePickerState extends State<CustomWheelTimePicker> {
  late int selectedAmPm; // 0: 오전, 1: 오후
  late int selectedHourIndex; // 0~11 (실제 표시는 1~12)
  late int selectedMinute; // 0~59

  late FixedExtentScrollController amPmController;
  late FixedExtentScrollController hourController;
  late FixedExtentScrollController minuteController;

  // 💡 [핵심] 텍스트 직접 입력을 위한 상태 및 컨트롤러 추가
  bool isEditingHour = false;
  bool isEditingMinute = false;
  final FocusNode hourFocus = FocusNode();
  final FocusNode minuteFocus = FocusNode();
  final TextEditingController hourTextController = TextEditingController();
  final TextEditingController minuteTextController = TextEditingController();

  @override
  void initState() {
    super.initState();
    selectedAmPm = widget.initialTime.hour < 12 ? 0 : 1;
    int h = widget.initialTime.hour % 12;
    selectedHourIndex = (h == 0 ? 12 : h) - 1;
    selectedMinute = widget.initialTime.minute;

    amPmController = FixedExtentScrollController(initialItem: selectedAmPm);
    hourController = FixedExtentScrollController(initialItem: selectedHourIndex);
    minuteController = FixedExtentScrollController(initialItem: selectedMinute);
  }

  @override
  void dispose() {
    amPmController.dispose();
    hourController.dispose();
    minuteController.dispose();
    hourFocus.dispose();
    minuteFocus.dispose();
    hourTextController.dispose();
    minuteTextController.dispose();
    super.dispose();
  }

  void _notifyChange() {
    int hour = selectedHourIndex + 1;
    if (selectedAmPm == 0 && hour == 12) hour = 0;
    if (selectedAmPm == 1 && hour < 12) hour += 12;
    widget.onTimeChanged(TimeOfDay(hour: hour, minute: selectedMinute));
  }

  // 💡 [핵심] 시간(시) 입력 완료 처리 로직
  void _submitHour(String value) {
    int? parsed = int.tryParse(value);
    if (parsed != null) {
      if (parsed > 12) parsed = 12;
      if (parsed < 1) parsed = 1;
      setState(() {
        selectedHourIndex = parsed! - 1;
        isEditingHour = false;
      });
      hourController.jumpToItem(selectedHourIndex);
      _notifyChange();
    } else {
      setState(() => isEditingHour = false);
    }
  }

  // 💡 [핵심] 시간(분) 입력 완료 처리 로직
  void _submitMinute(String value) {
    int? parsed = int.tryParse(value);
    if (parsed != null) {
      if (parsed > 59) parsed = 59;
      if (parsed < 0) parsed = 0;
      setState(() {
        selectedMinute = parsed!;
        isEditingMinute = false;
      });
      minuteController.jumpToItem(selectedMinute);
      _notifyChange();
    } else {
      setState(() => isEditingMinute = false);
    }
  }

  // 일반 스크롤 휠 생성기
  Widget _buildWheel({
    required FixedExtentScrollController controller,
    required int itemCount,
    required int selectedIndex,
    required void Function(int) onChanged,
    required String Function(int) textMapper,
    required double width,
    VoidCallback? onEdit, // 탭 시 편집 모드로 전환하는 콜백
  }) {
    return SizedBox(
      width: width,
      child: ListWheelScrollView.useDelegate(
        controller: controller,
        itemExtent: 50,
        physics: const FixedExtentScrollPhysics(),
        overAndUnderCenterOpacity: 1,
        onSelectedItemChanged: onChanged,
        childDelegate: ListWheelChildBuilderDelegate(
          builder: (context, index) {
            final isSelected = index == selectedIndex;
            return GestureDetector(
              // 선택된 항목만 터치 시 onEdit 실행
              onTap: (isSelected && onEdit != null) ? onEdit : null,
              child: Container(
                color: Colors.transparent, // 터치 영역 확보
                alignment: Alignment.center,
                child: Text(
                  textMapper(index),
                  style: TextStyle(
                    fontSize: isSelected ? 32 : 24, // 크기 강조
                    fontWeight: isSelected ? FontWeight.w500 : FontWeight.w300,
                    color: isSelected ? const Color(0xFF5A67D8) : const Color(0xFFC4C4C4),
                  ),
                ),
              ),
            );
          },
          childCount: itemCount,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 250,
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          // 1. 오전/오후 휠
          _buildWheel(
            controller: amPmController,
            itemCount: 2,
            selectedIndex: selectedAmPm,
            width: 70,
            onChanged: (index) {
              setState(() => selectedAmPm = index);
              _notifyChange();
            },
            textMapper: (index) => index == 0 ? '오전' : '오후',
          ),
          const SizedBox(width: 16),

          // 2. 시간(시) 영역 - 편집 모드 여부에 따라 TextField 또는 Wheel 렌더링
          isEditingHour
              ? Container(
            width: 80,
            height: 60,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: const Color(0xFFD6E4FF), // 선택 시 파란 배경 (이미지 3번 참조)
              borderRadius: BorderRadius.circular(12),
            ),
            child: TextField(
              controller: hourTextController,
              focusNode: hourFocus,
              autofocus: true,
              keyboardType: TextInputType.number,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 32, color: Color(0xFF5A67D8), fontWeight: FontWeight.bold),
              decoration: const InputDecoration(border: InputBorder.none, contentPadding: EdgeInsets.zero),

              // 💡 [추가] 숫자만 입력 가능하게 하고, 최대 2자리까지만 입력되도록 제한
              inputFormatters: [
                FilteringTextInputFormatter.digitsOnly,
                LengthLimitingTextInputFormatter(2),
              ],

              // 💡 [추가] 실시간 입력 검증: 12를 초과하면 즉시 12로 변경
              onChanged: (value) {
                if (value.isNotEmpty) {
                  int? parsed = int.tryParse(value);
                  if (parsed != null && parsed > 12) {
                    hourTextController.text = '12';
                    // 텍스트를 강제로 바꾼 뒤 커서를 맨 뒤로 이동시켜 자연스러운 타이핑 유지
                    hourTextController.selection = const TextSelection.collapsed(offset: 2);
                  }
                }
              },

              onSubmitted: _submitHour,
              onTapOutside: (_) => _submitHour(hourTextController.text),
            )
          )
              : _buildWheel(
            controller: hourController,
            itemCount: 12,
            selectedIndex: selectedHourIndex,
            width: 80,
            onChanged: (index) {
              setState(() => selectedHourIndex = index);
              _notifyChange();
            },
            textMapper: (index) => (index + 1).toString(),
            onEdit: () {
              setState(() {
                isEditingHour = true;
                isEditingMinute = false;
                hourTextController.text = (selectedHourIndex + 1).toString();
              });
            },
          ),

          // 콜론(:)
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 8.0),
            child: Text(':', style: TextStyle(fontSize: 32, color: Colors.black54)),
          ),

          // 3. 분(분) 영역 - 편집 모드 여부에 따라 TextField 또는 Wheel 렌더링
          isEditingMinute
              ? Container(
            width: 80,
            height: 60,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: const Color(0xFFD6E4FF), // 선택 시 파란 배경
              borderRadius: BorderRadius.circular(12),
            ),
            child: TextField(
              controller: minuteTextController,
              focusNode: minuteFocus,
              autofocus: true,
              keyboardType: TextInputType.number,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 32, color: Color(0xFF5A67D8), fontWeight: FontWeight.bold),
              decoration: const InputDecoration(border: InputBorder.none, contentPadding: EdgeInsets.zero),

              // 💡 [추가] 숫자만 입력 가능, 최대 2자리 제한
              inputFormatters: [
                FilteringTextInputFormatter.digitsOnly,
                LengthLimitingTextInputFormatter(2),
              ],

              // 💡 [추가] 실시간 입력 검증: 59를 초과하면 즉시 59로 변경
              onChanged: (value) {
                if (value.isNotEmpty) {
                  int? parsed = int.tryParse(value);
                  if (parsed != null && parsed > 59) {
                    minuteTextController.text = '59';
                    minuteTextController.selection = const TextSelection.collapsed(offset: 2);
                  }
                }
              },

              onSubmitted: _submitMinute,
              onTapOutside: (_) => _submitMinute(minuteTextController.text),
            )
          )
              : _buildWheel(
            controller: minuteController,
            itemCount: 60,
            selectedIndex: selectedMinute,
            width: 80,
            onChanged: (index) {
              setState(() => selectedMinute = index);
              _notifyChange();
            },
            textMapper: (index) => index.toString().padLeft(2, '0'),
            onEdit: () {
              setState(() {
                isEditingMinute = true;
                isEditingHour = false;
                minuteTextController.text = selectedMinute.toString().padLeft(2, '0');
              });
            },
          ),
        ],
      ),
    );
  }
}

// -----------------------------------------------------------------------------
// 📱 메인 화면 UI
// -----------------------------------------------------------------------------
class NotificationManagerScreen extends StatelessWidget {
  const NotificationManagerScreen({super.key});

  Future<void> _updateTime(BuildContext context, SettingsProvider provider) async {
    final currentSettings = provider.settings;

    final initialTime = TimeOfDay(
      hour: currentSettings.notificationHour ?? 18,
      minute: currentSettings.notificationMinute ?? 0,
    );

    TimeOfDay tempPickedTime = initialTime;

    await showModalBottomSheet(
      context: context,
      isScrollControlled: true, // 키보드 대응 및 높이 제어를 위해 필수
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)), // 더 부드러운 곡선
      ),
      builder: (BuildContext context) {
        return Padding(
          // 키보드가 올라올 때만 바텀시트가 밀려 올라가도록 설정
          padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
          child: SafeArea(
            top: false,
            child: Container(
              // 💡 [수정] 높이를 화면의 45% 정도로 줄여서 답답함을 해소했습니다.
              height: MediaQuery.of(context).size.height * 0.45,
              padding: const EdgeInsets.only(bottom: 20),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  // 상단 바 버튼 영역
                  Padding(
                    padding: const EdgeInsets.fromLTRB(20, 12, 20, 0),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        TextButton(
                          onPressed: () => Navigator.of(context).pop(),
                          child: const Text('취소', style: TextStyle(color: Colors.grey, fontSize: 17)),
                        ),
                        TextButton(
                          onPressed: () {
                            provider.updateSettings(
                              notificationHour: tempPickedTime.hour,
                              notificationMinute: tempPickedTime.minute,
                            );
                            Navigator.of(context).pop();
                          },
                          child: const Text('확인', style: TextStyle(color: Color(0xFF5A67D8), fontSize: 17, fontWeight: FontWeight.bold)),
                        ),
                      ],
                    ),
                  ),
                  // 💡 [수정] 남은 공간의 중앙에 타임피커가 오도록 배치
                  Expanded(
                    child: Center(
                      child: CustomWheelTimePicker(
                        initialTime: initialTime,
                        onTimeChanged: (newTime) {
                          tempPickedTime = newTime;
                        },
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    // ... 기존 build 부분과 동일하므로 생략 없이 아래에 작성합니다.
    final settingsProv = context.watch<SettingsProvider>();
    final settings = settingsProv.settings;
    final isEnabled = settings.isNotificationEnabled;

    final displayTime = TimeOfDay(
      hour: settings.notificationHour ?? 18,
      minute: settings.notificationMinute ?? 0,
    ).format(context);

    return SettingsWrapper(
      title: "알림 설정",
      body: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 16),
        children: [
          SwitchListTile(
            activeColor: Colors.deepPurple,
            title: const Text('일일 공지 알림', style: TextStyle(fontWeight: FontWeight.bold)),
            subtitle: const Text('매일 정해진 시간에 새로운 공지를 확인합니다.'),
            secondary: Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: Colors.deepPurple.withOpacity(0.1),
                shape: BoxShape.circle,
              ),
              child: const Icon(Icons.notifications_active_outlined, color: Colors.deepPurple),
            ),
            value: isEnabled,
            onChanged: (value) async {
              await settingsProv.updateSettings(isNotificationEnabled: value);
            },
          ),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 16.0),
            child: Divider(),
          ),
          ListTile(
            enabled: isEnabled,
            leading: Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: isEnabled ? Colors.blue.withOpacity(0.1) : Colors.grey.withOpacity(0.1),
                shape: BoxShape.circle,
              ),
              child: Icon(
                Icons.access_time,
                color: isEnabled ? Colors.blue : Colors.grey,
              ),
            ),
            title: const Text('알림 시간 설정', style: TextStyle(fontWeight: FontWeight.w500)),
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  displayTime,
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                    color: isEnabled ? Colors.black : Colors.grey,
                  ),
                ),
                const Icon(Icons.chevron_right, color: Colors.grey),
              ],
            ),
            onTap: isEnabled ? () => _updateTime(context, settingsProv) : null,
          ),
          const SizedBox(height: 20),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20.0),
            child: Text(
              '※ 설정된 시간에 맞춰 즐겨찾기 폴더의 키워드를 기반으로 필터링된 공지 사항을 알려드립니다.',
              style: TextStyle(color: Colors.grey[600], fontSize: 13, height: 1.5),
            ),
          ),
        ],
      ),
    );
  }
}