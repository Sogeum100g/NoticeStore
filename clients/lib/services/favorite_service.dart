import 'dart:convert';
import 'package:flutter/cupertino.dart';
import 'package:http/http.dart' as http;
import '../models/favorite_folder_model.dart';
import 'preferences_service.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

class FavoriteService {
  String? _ipAddress = dotenv.env['IP_ADDRESS'];
  String get baseUrl => 'https://$_ipAddress/v1/favorites';

  static Future<Map<String, String>> _getHeaders() async {
    final token = await PreferencesService.getAuthToken();

    debugPrint("🔑 [FavoriteService] 현재 저장된 토큰: $token");

    return {
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Bearer $token',
    };
  }

  Future<List<FavoriteFolder>> getFoldersTree() async {
    try {
      final response = await http.get(Uri.parse('$baseUrl/folders'), headers: await _getHeaders());
      if (response.statusCode == 200) {
        final decoded = jsonDecode(utf8.decode(response.bodyBytes));
        final List<dynamic> data = decoded['data'] ?? [];
        return data.map((json) => FavoriteFolder.fromJson(json)).toList();
      } else {
        throw Exception('폴더 목록 로드 실패: ${response.statusCode}');
      }
    } catch (e) {
      print('❌ 폴더 트리 조회 에러: $e');
      return [];
    }
  }

  Future<bool> createFolder(String folderName, {int? parentFolderId}) async {
    try {
      final body = jsonEncode({
        'folder_name': folderName,
        'parent_folder_id': parentFolderId,
      });
      final response = await http.post(Uri.parse('$baseUrl/folders'), headers: await _getHeaders(), body: body);
      return response.statusCode == 201;
    } catch (e) {
      print('❌ 폴더 생성 에러: $e');
      return false;
    }
  }

  Future<bool> renameFolder(int folderId, String newName) async {
    try {
      final body = jsonEncode({'new_folder_name': newName});
      final response = await http.patch(Uri.parse('$baseUrl/folders/$folderId'), headers: await _getHeaders(), body: body);
      return response.statusCode == 200;
    } catch (e) {
      print('❌ 폴더 이름 변경 에러: $e');
      return false;
    }
  }

  Future<bool> deleteFolder(int folderId) async {
    try {
      final response = await http.delete(Uri.parse('$baseUrl/folders/$folderId'), headers: await _getHeaders());
      return response.statusCode == 200;
    } catch (e) {
      print('❌ 폴더 삭제 에러: $e');
      return false;
    }
  }

  Future<bool> addNoticeToFolder(int folderId, int noticeId) async {
    try {
      final body = jsonEncode({'notice_id': noticeId});
      final response = await http.post(Uri.parse('$baseUrl/folders/$folderId/notices'), headers: await _getHeaders(), body: body);
      return response.statusCode == 200;
    } catch (e) {
      print('❌ 공지 추가 에러: $e');
      return false;
    }
  }

  Future<bool> removeNoticeFromFolder(int folderId, int noticeId) async {
    try {
      final response = await http.delete(Uri.parse('$baseUrl/folders/$folderId/notices/$noticeId'), headers: await _getHeaders());
      return response.statusCode == 200;
    } catch (e) {
      print('❌ 공지 제거 에러: $e');
      return false;
    }
  }

  Future<bool> addFolderKeyword(int folderId, String keyword) async {
    try {
      final body = jsonEncode({'keyword': keyword});
      final response = await http.post(
        Uri.parse('$baseUrl/folders/$folderId/keywords'),
        headers: await _getHeaders(),
        body: body,
      );
      return response.statusCode == 201;
    } catch (e) {
      print('❌ 폴더 키워드 추가 에러: $e');
      return false;
    }
  }

  Future<bool> removeFolderKeyword(int folderId, String keyword) async {
    try {
      // 한글, 공백, 특수문자가 포함된 키워드가 URL에 들어갈 때 깨지는 것을 방지(URL 인코딩)
      final encodedKeyword = Uri.encodeComponent(keyword);
      final response = await http.delete(
        Uri.parse('$baseUrl/folders/$folderId/keywords/$encodedKeyword'),
        headers: await _getHeaders(),
      );
      return response.statusCode == 200;
    } catch (e) {
      print('❌ 폴더 키워드 삭제 에러: $e');
      return false;
    }
  }

  Future<bool> updateFolderOrder(List<int> orderedFolderIds) async {
    try {
      final body = jsonEncode({
        'ordered_folder_ids': orderedFolderIds,
      });

      final response = await http.put(
        Uri.parse('$baseUrl/folders/reorder'),
        headers: await _getHeaders(),
        body: body,
      );

      if (response.statusCode == 200) {
        return true;
      } else {
        debugPrint('❌ 폴더 순서 업데이트 실패: 서버 응답 코드 ${response.statusCode}');
        return false;
      }
    } catch (e) {
      debugPrint('❌ 폴더 순서 업데이트 네트워크 에러: $e');
      return false;
    }
  }
}
