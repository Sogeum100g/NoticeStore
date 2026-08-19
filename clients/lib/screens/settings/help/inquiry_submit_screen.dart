import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import '../settings_wrapper.dart'; // 경로 확인 필요
import 'package:flutter_dotenv/flutter_dotenv.dart';


class InquirySubmitScreen extends StatefulWidget {
  const InquirySubmitScreen({super.key});

  @override
  State<InquirySubmitScreen> createState() => _InquirySubmitScreenState();
}

class _InquirySubmitScreenState extends State<InquirySubmitScreen> {
  final _formKey = GlobalKey<FormState>();
  final TextEditingController _titleController = TextEditingController();
  final TextEditingController _contentController = TextEditingController();

  String _selectedCategory = '서비스 이용 문의';
  final List<String> _categories = ['서비스 이용 문의', '버그 제보', '기능 건의', '기타'];
  bool _isSubmitting = false;
  String? _ipAddress = dotenv.env['IP_ADDRESS'];

  final storage = const FlutterSecureStorage();
  // FastAPI 서버로 데이터 전송
  Future<void> _submitInquiry() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() { _isSubmitting = true; });

    try {
      final String? token = await storage.read(key: "jwt_token");
      if (token == null) return null;

      // 예: http://10.0.2.2:8000/v1/inquiries (에뮬레이터 기준)
      final response = await http.post(
        Uri.parse('http://${_ipAddress}/v1/inquiries'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token', // 💡 로그인 시 저장한 토큰 연동 필요
        },
        body: jsonEncode({
          'category': _selectedCategory,
          'title': _titleController.text,
          'content': _contentController.text,
        }),
      );

      if (response.statusCode == 200) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('문의가 접수되었습니다!')),
        );
        Navigator.pop(context);
      } else {
        throw Exception('서버 응답 오류: ${response.statusCode}');
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('접수 실패: $e')),
      );
    } finally {
      if (mounted) setState(() { _isSubmitting = false; });
    }
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
                items: _categories.map((c) => DropdownMenuItem(value: c, child: Text(c))).toList(),
                onChanged: (v) => setState(() => _selectedCategory = v!),
                decoration: _inputDecoration(),
              ),
              const SizedBox(height: 20),

              _buildLabel("제목"),
              TextFormField(
                controller: _titleController,
                decoration: _inputDecoration(hint: "제목을 입력해주세요"),
                validator: (v) => v!.isEmpty ? "제목은 필수입니다" : null,
              ),
              const SizedBox(height: 20),

              _buildLabel("문의 내용"),
              TextFormField(
                controller: _contentController,
                maxLines: 8,
                decoration: _inputDecoration(hint: "상세한 내용을 입력해주시면 큰 도움이 됩니다"),
                validator: (v) => v!.isEmpty ? "내용을 입력해주세요" : null,
              ),
              const SizedBox(height: 40),

              ElevatedButton(
                onPressed: _isSubmitting ? null : _submitInquiry,
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.black87,
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
                child: _isSubmitting
                    ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(color: Colors.white))
                    : const Text("문의 제출하기", style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildLabel(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8.0),
      child: Text(text, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
    );
  }

  InputDecoration _inputDecoration({String? hint}) {
    return InputDecoration(
      hintText: hint,
      filled: true,
      fillColor: const Color(0xFFF5F5F7),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
    );
  }
}