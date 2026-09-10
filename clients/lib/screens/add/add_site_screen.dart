import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../models/site_model.dart';
import '../../providers/notice_provider.dart';
import '../settings/help/how_to_use_application.dart';

class AddSiteScreen extends StatefulWidget {
  final String? initialUrl;

  const AddSiteScreen({super.key, this.initialUrl});

  @override
  State<AddSiteScreen> createState() => _AddSiteScreenState();
}

class _AddSiteScreenState extends State<AddSiteScreen> {
  final _urlController = TextEditingController();
  final _nameController = TextEditingController();
  final bool _isSubmitting = false;

  @override
  void initState() {
    super.initState();
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

    final pendingUrl = context.watch<NoticeProvider>().pendingUrl;

    if (pendingUrl != null && pendingUrl.isNotEmpty) {
      _urlController.text = pendingUrl;

      // 같은 URL이 다시 입력되지 않도록 반영한 값을 즉시 소비합니다.
      WidgetsBinding.instance.addPostFrameCallback((_) {
        context.read<NoticeProvider>().consumePendingUrl();
      });
    }
  }

  Future<void> _submitSite() async {
    final inputUrl = _urlController.text.trim();
    final alias = _nameController.text.trim();

    if (inputUrl.isEmpty || alias.isEmpty) {
      _showSnackBar("주소와 이름을 모두 입력해주세요.", isError: true);
      return;
    }

    _urlController.clear();
    _nameController.clear();

    _showSnackBar("[$alias] 등록을 시작합니다. 잠시만 기다려주세요.");

    // 화면을 막지 않도록 등록 결과 처리를 백그라운드 핸들러에 맡깁니다.
    _handleBackgroundRegistration(inputUrl, alias);
  }

  Future<void> _handleBackgroundRegistration(String url, String alias) async {
    if (!mounted) return;

    final noticeProvider = context.read<NoticeProvider>();
    int? acceptedSiteId;
    final String resultCode = await noticeProvider.registerNewSite(
      url,
      alias,
      onSiteAccepted: (siteId) => acceptedSiteId = siteId,
    );

    if (!mounted) return;

    if (resultCode == "SUCCESS") {
      _showSnackBar("[$alias] 수집 완료!", isSuccess: true);
      return;
    }

    if (resultCode != "PENDING") {
      _showSnackBar("[$alias] ${_getErrorMessage(resultCode)}", isError: true);
      return;
    }

    _showSnackBar("[$alias] 요청 완료. 사이트를 분석 중입니다.");

    if (acceptedSiteId == null) {
      _showSnackBar(
        "[$alias] ${_getErrorMessage('INVALID_SERVER_RESPONSE')}",
        isError: true,
      );
      return;
    }

    final String completionCode = await noticeProvider.waitForSiteRegistration(
      acceptedSiteId!,
      shouldContinue: () => mounted,
    );

    if (!mounted || completionCode == "CANCELLED") return;
    if (completionCode == "SUCCESS") {
      _showSnackBar("[$alias] 수집 완료!", isSuccess: true);
    } else {
      _showSnackBar(
        "[$alias] ${_getErrorMessage(completionCode)}",
        isError: true,
      );
    }
  }

  String _getErrorMessage(String code) {
    final serverMessage = SiteCrawlStatus.errorMessageFor(code);
    if (serverMessage.isNotEmpty) return serverMessage;

    return switch (code) {
      'NEED_LOGIN' => '로그인이 필요한 서비스입니다.',
      'MAX_SITES_LIMIT' => '등록 가능한 사이트 최대 개수를 초과했습니다.',
      'INVALID_URL' => '공개 HTTP/HTTPS 주소만 등록할 수 있습니다.',
      'INVALID_REQUEST' => '입력한 주소와 사이트 이름을 다시 확인해 주세요.',
      'SITE_NOT_FOUND' => '등록한 사이트 정보를 찾을 수 없습니다.',
      'TIMEOUT_ERROR' => '서버 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.',
      'NETWORK_ERROR' => '네트워크 연결을 확인한 후 다시 시도해 주세요.',
      'INVALID_SERVER_RESPONSE' =>
        '서버 응답을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.',
      'TIMEOUT_OR_NETWORK_ERROR' =>
        '네트워크 연결이 불안정하거나 응답 시간이 초과되었습니다.',
      'UNKNOWN_ERROR' => '사이트 등록 중 알 수 없는 오류가 발생했습니다.',
      _ => '오류가 발생했습니다. ($code)',
    };
  }

  void _showSnackBar(
      String message, {
        bool isError = false,
        bool isSuccess = false,
      }) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError
            ? const Color(0xFFA59971)
            : (isSuccess ? Colors.green : Colors.black87),
        behavior: SnackBarBehavior.floating,
        duration: const Duration(seconds: 3),
      ),
    );
  }

  Future<void> _navigateToSubScreen(BuildContext context, Widget screen) async {
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

    if (targetIndex != null && context.mounted) {
      context.read<NoticeProvider>().setSelectedIndex(targetIndex);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.white,
      width: double.infinity,
      height: double.infinity,
      child: SingleChildScrollView(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                "사이트 등록",
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 30),
              TextField(
                controller: _urlController,
                decoration: const InputDecoration(
                  labelText: "주소(URL)",
                  hintText: "https://...",
                  filled: true,
                  fillColor: Colors.white,
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
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(30),
                    ),
                    elevation: 0,
                  ),
                  child: _isSubmitting
                      ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                      color: Colors.white,
                      strokeWidth: 2,
                    ),
                  )
                      : const Text(
                    "등록하기",
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 16),
              Center(
                child: TextButton(
                  onPressed: () {
                    _navigateToSubScreen(context, const HowToUseApplication());
                  },
                  child: Container(
                    padding: const EdgeInsets.only(bottom: 2),
                    decoration: const BoxDecoration(
                      border: Border(
                        bottom: BorderSide(
                          color: Colors.grey,
                          width: 1.0,
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
            ],
          ),
        ),
      ),
    );
  }
}
