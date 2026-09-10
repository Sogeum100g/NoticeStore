import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../../../models/site_model.dart';
import '../../../providers/notice_provider.dart';
import '../settings_wrapper.dart';

class InquirySubmitScreen extends StatefulWidget {
  final int? initialSiteId;

  const InquirySubmitScreen({super.key, this.initialSiteId});

  @override
  State<InquirySubmitScreen> createState() => _InquirySubmitScreenState();
}

class _InquirySiteOption {
  final int siteId;
  final String alias;
  final String url;
  final SiteCrawlStatus crawlStatus;
  final String? errorCode;
  final String? errorMessage;

  const _InquirySiteOption({
    required this.siteId,
    required this.alias,
    required this.url,
    required this.crawlStatus,
    this.errorCode,
    this.errorMessage,
  });

  factory _InquirySiteOption.fromJson(Map<String, dynamic> json) {
    final String url = json['url']?.toString() ?? '';
    final String alias = json['alias']?.toString().trim() ?? '';
    final String? serverMessage = json['error_message']?.toString().trim();
    final String? errorCode = json['error_code']?.toString().trim();
    final String localMessage = SiteCrawlStatus.errorMessageFor(errorCode);

    return _InquirySiteOption(
      siteId: (json['site_id'] as num).toInt(),
      alias: alias.isEmpty ? url : alias,
      url: url,
      crawlStatus: SiteCrawlStatus.fromApi(json['crawl_status']),
      errorCode: errorCode == null || errorCode.isEmpty ? null : errorCode,
      errorMessage: serverMessage != null && serverMessage.isNotEmpty
          ? serverMessage
          : localMessage.isNotEmpty
          ? localMessage
          : null,
    );
  }

  String get statusLabel => crawlStatus.label;
}

class _InquirySubmitScreenState extends State<InquirySubmitScreen> {
  final _formKey = GlobalKey<FormState>();
  final TextEditingController _titleController = TextEditingController();
  final TextEditingController _contentController = TextEditingController();

  String _selectedCategory = '서비스 이용 문의';
  final List<String> _categories = [
    '서비스 이용 문의',
    '버그 제보',
    '기능 건의',
    '기타',
  ];
  bool _isSubmitting = false;
  bool _isLoadingSites = true;
  int? _selectedSiteId;
  List<_InquirySiteOption> _sites = const [];

  final String? _ipAddress = dotenv.env['IP_ADDRESS'];
  final storage = const FlutterSecureStorage();

  @override
  void initState() {
    super.initState();
    _selectedSiteId = widget.initialSiteId;
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final metadata = context.watch<NoticeProvider>().inquirySiteMetadata;
    final sites = <_InquirySiteOption>[];
    for (final siteJson in metadata) {
      if (siteJson['site_id'] is! num) continue;
      sites.add(_InquirySiteOption.fromJson(siteJson));
    }
    sites.sort((a, b) {
      final int statusCompare = _siteSortRank(a.crawlStatus)
          .compareTo(_siteSortRank(b.crawlStatus));
      return statusCompare != 0
          ? statusCompare
          : a.alias.compareTo(b.alias);
    });

    _sites = sites;
    _isLoadingSites = false;
    if (_selectedSiteId != null && _selectedSite == null) {
      _selectedSiteId = null;
    }
  }

  @override
  void dispose() {
    _titleController.dispose();
    _contentController.dispose();
    super.dispose();
  }

  _InquirySiteOption? get _selectedSite {
    for (final site in _sites) {
      if (site.siteId == _selectedSiteId) return site;
    }
    return null;
  }

  int _siteSortRank(SiteCrawlStatus status) {
    return switch (status) {
      SiteCrawlStatus.failed => 0,
      SiteCrawlStatus.blocked => 1,
      SiteCrawlStatus.pending => 2,
      SiteCrawlStatus.paused => 3,
      SiteCrawlStatus.active => 4,
      SiteCrawlStatus.unknown => 5,
    };
  }

  Future<void> _submitInquiry() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _isSubmitting = true;
    });

    try {
      final String? token = await storage.read(key: "jwt_token");
      if (token == null) {
        throw const _InquirySubmitException('로그인이 필요합니다.');
      }

      final body = <String, dynamic>{
        'category': _selectedCategory,
        'title': _titleController.text.trim(),
        'content': _contentController.text.trim(),
      };
      if (_selectedSiteId != null) {
        body['site_id'] = _selectedSiteId;
      }

      final response = await http.post(
        Uri.parse('https://${_ipAddress}/v1/inquiries'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
        body: jsonEncode(body),
      ).timeout(const Duration(seconds: 15));

      if (response.statusCode == 200) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('문의가 접수되었습니다!')),
        );
        Navigator.pop(context);
        return;
      }

      String message = '문의를 접수하지 못했습니다. 잠시 후 다시 시도해 주세요.';
      try {
        final dynamic decoded = jsonDecode(response.body);
        if (decoded is Map<String, dynamic> &&
            decoded['detail'] == 'SUBSCRIBED_SITE_NOT_FOUND') {
          message = '선택한 사이트를 찾을 수 없습니다. 사이트 목록을 새로고침해 주세요.';
        } else if (response.statusCode == 401) {
          message = '로그인이 필요합니다.';
        }
      } on FormatException {
      }
      throw _InquirySubmitException(message);
    } on TimeoutException {
      _showSubmitError('문의 접수 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.');
    } on http.ClientException {
      _showSubmitError('네트워크 연결을 확인한 후 다시 시도해 주세요.');
    } on _InquirySubmitException catch (e) {
      _showSubmitError(e.message);
    } catch (_) {
      _showSubmitError('문의를 접수하지 못했습니다. 잠시 후 다시 시도해 주세요.');
    } finally {
      if (mounted) {
        setState(() {
          _isSubmitting = false;
        });
      }
    }
  }

  void _showSubmitError(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }

  @override
  Widget build(BuildContext context) {
    return SettingsWrapper(
      title: "문의하기",
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20.0),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _buildLabel("문의 유형"),
              DropdownButtonFormField<String>(
                value: _selectedCategory,
                items: _categories
                    .map((category) => DropdownMenuItem(
                  value: category,
                  child: Text(category),
                ))
                    .toList(),
                onChanged: (value) {
                  if (value == null) return;
                  setState(() {
                    _selectedCategory = value;
                  });
                },
                decoration: _inputDecoration(),
              ),
              const SizedBox(height: 20),

              _buildLabel("관련 사이트 / 오류 유형 (선택)"),
              _buildSiteSelector(),
              if (_selectedSite != null) ...[
                const SizedBox(height: 10),
                _buildSelectedSiteContext(_selectedSite!),
              ],
              const SizedBox(height: 20),

              _buildLabel("제목"),
              TextFormField(
                controller: _titleController,
                decoration: _inputDecoration(hint: "제목을 입력해주세요"),
                validator: (value) => value == null || value.trim().isEmpty
                    ? "제목은 필수입니다"
                    : null,
              ),
              const SizedBox(height: 20),

              _buildLabel("문의 내용"),
              TextFormField(
                controller: _contentController,
                maxLines: 8,
                decoration: _inputDecoration(
                  hint: "상세한 내용을 입력해주시면 큰 도움이 됩니다",
                ),
                validator: (value) => value == null || value.trim().isEmpty
                    ? "내용을 입력해주세요"
                    : null,
              ),
              const SizedBox(height: 40),

              ElevatedButton(
                onPressed: _isSubmitting ? null : _submitInquiry,
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.black87,
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                  ),
                ),
                child: _isSubmitting
                    ? const SizedBox(
                  height: 20,
                  width: 20,
                  child: CircularProgressIndicator(color: Colors.white),
                )
                    : const Text(
                  "문의 제출하기",
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildSiteSelector() {
    if (_isLoadingSites) {
      return const LinearProgressIndicator(minHeight: 2);
    }

    if (_sites.isEmpty) {
      return const Text(
        '등록된 사이트가 없습니다. 사이트와 무관한 문의로 접수됩니다.',
        style: TextStyle(color: Colors.black54, fontSize: 13),
      );
    }

    return DropdownButtonFormField<int>(
      value: _selectedSiteId ?? -1,
      isExpanded: true,
      items: [
        const DropdownMenuItem<int>(
          value: -1,
          child: Text('사이트 무관'),
        ),
        ..._sites.map(
              (site) => DropdownMenuItem<int>(
            value: site.siteId,
            child: Text(
              '${site.alias} · ${site.statusLabel}',
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ),
      ],
      onChanged: (value) {
        setState(() {
          _selectedSiteId = value == -1 ? null : value;
        });
      },
      decoration: _inputDecoration(),
    );
  }

  Widget _buildSelectedSiteContext(_InquirySiteOption site) {
    final String errorType = site.errorCode ?? '현재 감지된 오류 없음';
    final String errorMessage = site.errorMessage ??
        (site.crawlStatus.userMessage.isNotEmpty
            ? site.crawlStatus.userMessage
            : '문의 내용에 발생한 문제를 자세히 적어 주세요.');

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFF5F5F7),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            site.url,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 12, color: Colors.black54),
          ),
          const SizedBox(height: 8),
          Text(
            '사이트 상태: ${site.statusLabel}',
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 4),
          Text(
            '오류 유형: $errorType',
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 4),
          Text(
            errorMessage,
            style: const TextStyle(fontSize: 13, color: Colors.black54),
          ),
          const SizedBox(height: 8),
          const Text(
            '사이트 상태와 오류 유형이 문의에 자동으로 첨부됩니다.',
            style: TextStyle(fontSize: 12, color: Colors.black45),
          ),
        ],
      ),
    );
  }

  Widget _buildLabel(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8.0),
      child: Text(
        text,
        style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
      ),
    );
  }

  InputDecoration _inputDecoration({String? hint}) {
    return InputDecoration(
      hintText: hint,
      filled: true,
      fillColor: const Color(0xFFF5F5F7),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide.none,
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
    );
  }
}

class _InquirySubmitException implements Exception {
  final String message;

  const _InquirySubmitException(this.message);
}
