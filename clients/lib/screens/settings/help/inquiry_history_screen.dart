import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../settings_wrapper.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

class InquiryHistoryScreen extends StatefulWidget {
  const InquiryHistoryScreen({super.key});

  @override
  State<InquiryHistoryScreen> createState() => _InquiryHistoryScreenState();
}

class _InquiryHistoryScreenState extends State<InquiryHistoryScreen> {
  final storage = const FlutterSecureStorage();
  List<dynamic> _inquiries = [];
  bool _isLoading = true;
  String? _errorMessage;
  String? _ipAddress = dotenv.env['IP_ADDRESS'];

  @override
  void initState() {
    super.initState();
    _fetchInquiries();
  }

  // 서버에서 내 문의 내역 가져오기
  Future<void> _fetchInquiries() async {
    try {
      final token = await storage.read(key: "jwt_token");
      if (token == null) {
        setState(() {
          _errorMessage = "로그인이 필요한 서비스입니다.";
          _isLoading = false;
        });
        return;
      }

      // 💡 서버 IP/도메인 주소로 변경하세요
      final url = Uri.parse('http://${_ipAddress}/v1/inquiries/me');
      final response = await http.get(
        url,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
      ).timeout(const Duration(seconds: 10));

      if (response.statusCode == 200) {
        final decoded = jsonDecode(utf8.decode(response.bodyBytes));
        setState(() {
          _inquiries = decoded['data'] ?? [];
          _isLoading = false;
        });
      } else {
        setState(() {
          _errorMessage = "데이터를 불러오는 데 실패했습니다. (${response.statusCode})";
          _isLoading = false;
        });
      }
    } catch (e) {
      setState(() {
        _errorMessage = "네트워크 오류가 발생했습니다.\n$e";
        _isLoading = false;
      });
    }
  }

  // 날짜 포맷팅 함수 (예: 2026-02-25T21:18:12 -> 2026.02.25)
  String _formatDate(String? dateString) {
    if (dateString == null) return '';
    try {
      final DateTime date = DateTime.parse(dateString).toLocal();
      return "${date.year}.${date.month.toString().padLeft(2, '0')}.${date.day.toString().padLeft(2, '0')}";
    } catch (e) {
      return dateString.split('T').first;
    }
  }

  @override
  Widget build(BuildContext context) {
    return SettingsWrapper(
      title: "나의 문의 내역",
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator(color: Colors.black87));
    }

    if (_errorMessage != null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.error_outline, size: 48, color: Colors.redAccent),
            const SizedBox(height: 16),
            Text(_errorMessage!, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: () {
                setState(() { _isLoading = true; _errorMessage = null; });
                _fetchInquiries();
              },
              child: const Text('다시 시도'),
            )
          ],
        ),
      );
    }

    if (_inquiries.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.inbox_outlined, size: 64, color: Colors.grey[400]),
            const SizedBox(height: 16),
            Text("등록된 문의 내역이 없습니다.", style: TextStyle(color: Colors.grey[600], fontSize: 16)),
          ],
        ),
      );
    }

    return ListView.separated(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 20),
      itemCount: _inquiries.length,
      separatorBuilder: (context, index) => const SizedBox(height: 12),
      itemBuilder: (context, index) {
        final inquiry = _inquiries[index];
        final bool isResolved = inquiry['status'] == 'RESOLVED';

        return Card(
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
            side: BorderSide(color: Colors.grey.shade200),
          ),
          child: ExpansionTile(
            tilePadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            shape: const Border(),
            title: Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: isResolved ? Colors.blue.shade50 : Colors.grey.shade100,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    isResolved ? '답변완료' : '답변대기',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                      color: isResolved ? Colors.blue.shade700 : Colors.grey.shade600,
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    inquiry['title'] ?? '제목 없음',
                    style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            subtitle: Padding(
              padding: const EdgeInsets.only(top: 8.0),
              child: Text(
                "${inquiry['category']} · ${_formatDate(inquiry['created_at'])}",
                style: TextStyle(color: Colors.grey.shade500, fontSize: 13),
              ),
            ),
            children: [
              // 1. 유저의 질문 영역
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                color: Colors.grey.shade50,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text("나의 문의", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13, color: Colors.black54)),
                    const SizedBox(height: 8),
                    Text(inquiry['content'] ?? '', style: const TextStyle(height: 1.5, fontSize: 14)),
                  ],
                ),
              ),
              // 2. 관리자 답변 영역 (답변이 있을 때만 표시)
              if (isResolved && inquiry['reply_content'] != null)
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: Colors.blue.shade50.withOpacity(0.5),
                    border: Border(top: BorderSide(color: Colors.blue.shade100)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Text("관리자 답변", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13, color: Colors.blue.shade700)),
                          const Spacer(),
                          Text(_formatDate(inquiry['replied_at']), style: TextStyle(fontSize: 12, color: Colors.grey.shade500)),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(inquiry['reply_content'], style: const TextStyle(height: 1.5, fontSize: 14)),
                    ],
                  ),
                ),
            ],
          ),
        );
      },
    );
  }
}