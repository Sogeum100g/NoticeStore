import 'dart:convert';
import 'package:flutter/cupertino.dart';
import 'package:http/http.dart' as http;
import '../models/favorite_folder_model.dart';
import 'preferences_service.dart'; // 토큰을 가져오기 위해 import
import 'package:flutter_dotenv/flutter_dotenv.dart';

class FavoriteService {
  // 실제 서버 주소 또는 로컬 테스트 주소 (안드로이드 에뮬레이터는 10.0.2.2 사용)
  String? _ipAddress = dotenv.env['IP_ADDRESS'];
  String get baseUrl => 'http://$_ipAddress/v1/favorites';

  // 공통 헤더 생성 (JWT 토큰 포함)
  static Future<Map<String, String>> _getHeaders() async {
    final token = await PreferencesService.getAuthToken();

    // 💡 디버깅을 위해 토큰 값을 출력해 보세요.
    debugPrint("🔑 [FavoriteService] 현재 저장된 토큰: $token");

    return {
      'Content-Type': 'application/json',
      // 💡 'Bearer ' 뒤에 한 칸 공백이 반드시 있어야 합니다.
      if (token != null) 'Authorization': 'Bearer $token',
    };
  }

  // 1. 전체 폴더 트리 가져오기 (GET)
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

  // 2. 폴더 생성 (POST)
  Future<bool> createFolder(String folderName, {int? parentFolderId}) async {
    try {
      final body = jsonEncode({
        'folder_name': folderName,
        'parent_folder_id': parentFolderId,
      });
      final response = await http.post(Uri.parse('$baseUrl/folders'), headers: await _getHeaders(), body: body);
      return response.statusCode == 201; // FastAPI에서 201 Created로 설정함
    } catch (e) {
      print('❌ 폴더 생성 에러: $e');
      return false;
    }
  }

  // 3. 폴더 이름 변경 (PATCH)
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

  // 4. 폴더 삭제 (DELETE)
  Future<bool> deleteFolder(int folderId) async {
    try {
      final response = await http.delete(Uri.parse('$baseUrl/folders/$folderId'), headers: await _getHeaders());
      return response.statusCode == 200;
    } catch (e) {
      print('❌ 폴더 삭제 에러: $e');
      return false;
    }
  }

  // 5. 공지사항 추가 (POST)
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

  // 6. 공지사항 제거 (DELETE)
  Future<bool> removeNoticeFromFolder(int folderId, int noticeId) async {
    try {
      final response = await http.delete(Uri.parse('$baseUrl/folders/$folderId/notices/$noticeId'), headers: await _getHeaders());
      return response.statusCode == 200;
    } catch (e) {
      print('❌ 공지 제거 에러: $e');
      return false;
    }
  }

  // 7. 폴더 키워드 추가 (POST)
  Future<bool> addFolderKeyword(int folderId, String keyword) async {
    try {
      final body = jsonEncode({'keyword': keyword});
      final response = await http.post(
        Uri.parse('$baseUrl/folders/$folderId/keywords'),
        headers: await _getHeaders(),
        body: body,
      );
      // FastAPI에서 status_code=status.HTTP_201_CREATED 로 설정했으므로 201을 체크합니다.
      return response.statusCode == 201;
    } catch (e) {
      print('❌ 폴더 키워드 추가 에러: $e');
      return false;
    }
  }

  // 8. 폴더 키워드 삭제 (DELETE)
  Future<bool> removeFolderKeyword(int folderId, String keyword) async {
    try {
      // 💡 한글, 공백, 특수문자가 포함된 키워드가 URL에 들어갈 때 깨지는 것을 방지(URL 인코딩)
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

  // 9. 폴더 일괄 순서 변경 (PUT)
  Future<bool> updateFolderOrder(List<int> orderedFolderIds) async {
    try {
      // 💡 FastAPI의 FolderReorderRequest 모델 필드명(ordered_folder_ids)과 정확히 일치시킵니다.
      final body = jsonEncode({
        'ordered_folder_ids': orderedFolderIds,
      });

      // 💡 백엔드 라우터 주소에 맞춰 '/folders/reorder' 엔드포인트를 호출합니다.
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