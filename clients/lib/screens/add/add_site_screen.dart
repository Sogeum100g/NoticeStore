import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/notice_provider.dart';
import 'package:http/http.dart' as http; // HTTP 패키지 추가 필요
import '../settings/help/how_to_use_application.dart';


class AddSiteScreen extends StatefulWidget {
  // 외부에서 전달받을 URL을 위한 파라미터 추가
  final String? initialUrl;

  const AddSiteScreen({super.key, this.initialUrl});

  @override
  State<AddSiteScreen> createState() => _AddSiteScreenState();
}

class _AddSiteScreenState extends State<AddSiteScreen> {
  final _urlController = TextEditingController();
  final _nameController = TextEditingController();
  bool _isSubmitting = false;

  @override
  void initState() {
    super.initState();
    // 화면이 켜질 때 initialUrl이 있다면 컨트롤러에 자동 입력
    if (widget.initialUrl != null && widget.initialUrl!.isNotEmpty) {
      _urlController.text = widget.initialUrl!;
    }
  }

  @override
  void dispose() {
    _urlController.dispose();
    _nameController.dispose();
    super.dispose();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();

    // 💡 1. NoticeProvider를 구독하여 공유된 URL이 들어오는지 감시합니다.
    final pendingUrl = context.watch<NoticeProvider>().pendingUrl;

    if (pendingUrl != null && pendingUrl.isNotEmpty) {
      // 💡 2. 값이 있다면 텍스트 필드에 즉시 반영합니다.
      _urlController.text = pendingUrl;

      // 💡 3. 반영 후 즉시 보관함을 비워줍니다 (중복 입력 및 무한 루프 방지).
      WidgetsBinding.instance.addPostFrameCallback((_) {
        context.read<NoticeProvider>().consumePendingUrl();
      });
    }
  }

  // URL 전개 유틸리티 함수 (내부 메서드로 두거나 별도 파일로 분리 추천)
  Future<String> _expandUrlIfNeeded(String url) async {
    try {
      if (!url.startsWith('http')) return url;
      final response = await http.get(Uri.parse(url));
      return response.request?.url.toString() ?? url;
    } catch (e) {
      return url;
    }
  }

  // 1. 등록 버튼 클릭 시 실행되는 함수
  Future<void> _submitSite() async {
    final inputUrl = _urlController.text.trim();
    final alias = _nameController.text.trim();

    if (inputUrl.isEmpty || alias.isEmpty) {
      _showSnackBar("주소와 이름을 모두 입력해주세요.", isError: true);
      return;
    }

    // [UI 개선] 입력 필드를 즉시 비워 다음 입력을 준비합니다.
    _urlController.clear();
    _nameController.clear();

    _showSnackBar("[$alias] 등록을 시작합니다. 잠시만 기다려주세요.");

    // [비동기 실행] await 하지 않고 백그라운드 핸들러로 넘깁니다.
    _handleBackgroundRegistration(inputUrl, alias);
  }

  // 2. 백그라운드 등록 및 상세 에러 처리 핸들러
  Future<void> _handleBackgroundRegistration(String url, String alias) async {
    final expandedUrl = await _expandUrlIfNeeded(url);

    if (!mounted) return;

    // NoticeProvider로부터 결과 코드를 받아옵니다.
    final String resultCode = await context.read<NoticeProvider>().registerNewSite(expandedUrl, alias);

    if (!mounted) return;

    // 결과에 따른 에러 메시지 분기 (기존 로직 복구 및 강화)
    if (resultCode == "SUCCESS") {
      _showSnackBar("[$alias] 사이트 등록 완료!", isSuccess: true);
    } else if (resultCode == "PENDING") {
      _showSnackBar("[$alias] 등록 요청 완료. 사이트를 분석 중입니다.", isSuccess: true);
    } else {
      String errorMessage = _getErrorMessage(resultCode);
      _showSnackBar("[$alias] $errorMessage", isError: true);
    }
  }

// 3. 에러 코드별 메시지 매핑 (추출하여 관리)
  String _getErrorMessage(String code) {
    switch (code) {
      case "NEED_LOGIN":
        return "로그인이 필요한 서비스입니다.";
      case "MAX_SITES_LIMIT":
        return "등록 가능한 사이트 최대 개수를 초과했습니다.";
      case "ROBOTS_TXT_BLOCKED":
        return "해당 사이트의 보안 정책에 의해 정보를 가져올 수 없습니다.";
      case "INVALID_URL":
        return "공개 HTTP/HTTPS 주소만 등록할 수 있습니다.";
      // case "CRAWLING_ERROR":
      //   return "사이트 구조가 복잡하여 데이터를 읽어올 수 없습니다.";
      case "TIMEOUT_OR_NETWORK_ERROR":
        return "네트워크 연결이 불안정하거나 응답 시간이 초과되었습니다.";
      default:
        return "오류가 발생했습니다. ($code)";
    }
  }

// 4. 공통 스낵바 출력 유틸리티
  void _showSnackBar(String message, {bool isError = false, bool isSuccess = false}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError ? const Color(0xFFA59971) : (isSuccess ? Colors.green : Colors.black87),
        behavior: SnackBarBehavior.floating,
        duration: const Duration(seconds: 3),
      ),
    );
  }



  void _showResultSnackBar(String alias, String resultCode) {
    if (resultCode == "SUCCESS") {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("[$alias] 등록 성공!"), backgroundColor: Colors.green)
      );
    } else {
      // 에러 케이스 처리 (기존 switch-case 로직 활용)
      String message = "[$alias] 등록 실패: $resultCode";
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(message), backgroundColor: Colors.redAccent)
      );
    }
  }

  Future<void> _navigateToSubScreen(BuildContext context, Widget screen) async {
    // 1. 도움말 화면으로 이동하고, 유저가 다른 탭 버튼을 눌렀을 때 반환하는 index를 기다립니다.
    final int? targetIndex = await Navigator.push<int>(
      context,
      PageRouteBuilder(
        transitionDuration: const Duration(milliseconds: 100),
        pageBuilder: (context, animation, secondaryAnimation) => screen,
        transitionsBuilder: (context, animation, secondaryAnimation, child) {
          return FadeTransition(opacity: animation, child: child);
        },
      ),
    );

    // 2. 돌아온 targetIndex 값이 있다면 (유저가 도움말 화면에서 다른 탭으로 이동하길 원한다면)
    if (targetIndex != null && context.mounted) {

      // 💡 핵심: 화면을 pop 하는 대신, MainWrapper를 제어하는 NoticeProvider의 탭 변경 함수를 호출합니다!
      context.read<NoticeProvider>().setSelectedIndex(targetIndex);

    }
  }


  @override
  Widget build(BuildContext context) {
    // 💡 배경을 흰색으로 통일하고, Scaffold 없이 Container로 구성하여
    // 메인 화면(MainWrapper)의 일부처럼 보이게 합니다.
    return Container(
      color: Colors.white, // 전체 배경 흰색 설정
      width: double.infinity,
      height: double.infinity,
      child: SingleChildScrollView(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 💡 탭바 위쪽 헤더(비둘기)는 MainWrapper에서 그려주므로 여기선 제목만 유지
              const Text("사이트 등록", style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
              const SizedBox(height: 30),
              TextField(
                controller: _urlController,
                decoration: const InputDecoration(
                  labelText: "주소(URL)",
                  hintText: "https://...",
                  filled: true,
                  fillColor: Colors.white, // 입력창 내부도 흰색
                ),
              ),
              const SizedBox(height: 20),
              TextField(
                controller: _nameController,
                decoration: const InputDecoration(
                  labelText: "사이트 이름",
                  hintText: "사이트 별명",
                  filled: true,
                  fillColor: Colors.white,
                ),
              ),
              const SizedBox(height: 40),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: _isSubmitting ? null : _submitSite,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: _isSubmitting ? Colors.grey : Colors.black,
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(30)),
                    elevation: 0, // 평면적인 느낌을 위해 그림자 제거 가능
                  ),
                  child: _isSubmitting
                      ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                      : const Text("등록하기", style: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.bold)),
                ),
              ),
              // --- 💡 여기서부터 새롭게 추가되는 부분 ---
              const SizedBox(height: 16), // 버튼 사이의 여백
              Center(
                child: TextButton(
                  // 💡 작성된 함수(_navigateToSubScreen)를 호출하도록 수정되었습니다.
                  onPressed: () {
                    _navigateToSubScreen(context, const HowToUseApplication());
                  },
                  child: Container(
                    // 💡 아래쪽 패딩으로 밑줄과 글자 사이의 간격을 조절합니다.
                    padding: const EdgeInsets.only(bottom: 2),
                    decoration: const BoxDecoration(
                      border: Border(
                        bottom: BorderSide(
                          color: Colors.grey, // 밑줄 색상
                          width: 1.0,           // 밑줄 두께
                        ),
                      ),
                    ),
                    child: const Text(
                      "사용 방법 도움말",
                      style: TextStyle(
                        color: Colors.black54,
                        fontSize: 16,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ),
                ),
              ),
            // --- 추가 완료 ---
            ],
          ),
        ),
      ),
    );
  }
}
