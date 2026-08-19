import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../../providers/favorite_provider.dart';
import '../../../models/favorite_folder_model.dart';
import '../settings_wrapper.dart';

class KeywordManagerScreen extends StatefulWidget {
  // 💡 이제 외부에서 데이터를 넘겨받지 않고 Provider에서 직접 가져옵니다.
  const KeywordManagerScreen({super.key});

  @override
  State<KeywordManagerScreen> createState() => _KeywordManagerScreenState();
}

class _KeywordManagerScreenState extends State<KeywordManagerScreen> {
  final TextEditingController _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  // 키워드 관리 바텀시트
  void _showKeywordBottomSheet(FavoriteFolder folder) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setModalState) {
            // 💡 최신 상태 유지를 위해 Provider 구독
            final favoriteProv = context.watch<FavoriteProvider>();

            // 현재 바텀시트가 보고 있는 폴더의 최신 키워드 목록 추출
            final List<String> keywords = favoriteProv.getKeywordsForFolder(folder.folderId);

            return Padding(
              padding: EdgeInsets.only(
                left: 20, right: 20, top: 20,
                bottom: MediaQuery.of(context).viewInsets.bottom + 20,
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                      "${folder.folderName} 키워드 관리",
                      style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)
                  ),
                  const SizedBox(height: 15),
                  TextField(
                    controller: _controller,
                    // 💡 사용자가 입력하는 텍스트의 색상을 설정합니다.
                    style: const TextStyle(color: Color(0xFF636363), fontSize: 16),
                    decoration: InputDecoration(
                      hintText: "새 키워드 입력",
                      // 💡 힌트 텍스트(안내 문구)의 색상을 설정합니다.
                      hintStyle: const TextStyle(color: Color(0xFF636363), fontSize: 14),

                      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                      suffixIcon: IconButton(
                        // 💡 아이콘 색상도 텍스트와 통일감을 주려면 수정할 수 있습니다.
                        icon: const Icon(Icons.add_circle, color: Color(0xFF636363)),
                        onPressed: () async {
                          final text = _controller.text.trim();
                          if (text.isNotEmpty && !keywords.contains(text)) {
                            await favoriteProv.addKeywordToFolder(folder.folderId, text);
                            _controller.clear();
                            setModalState(() {});
                          }
                        },
                      ),
                    ),
                  ),
                  const SizedBox(height: 15),
                  if (favoriteProv.isLoading)
                    const Center(child: CircularProgressIndicator())
                  else
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: keywords.map((k) => InputChip(
                        label: Text(k),
                        onDeleted: () async {
                          // 💡 API 연동 삭제 호출
                          await favoriteProv.removeKeywordFromFolder(folder.folderId, k);
                          setModalState(() {});
                        },
                        deleteIconColor: Colors.red,
                      )).toList(),
                    ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final favoriteProv = context.watch<FavoriteProvider>();
    final folders = favoriteProv.folders;

    return SettingsWrapper(
      title: "키워드 관리",
      body: favoriteProv.isLoading && folders.isEmpty
          ? const Center(child: CircularProgressIndicator())
          : ListView(
        children: [
          _buildSectionHeader("폴더별 상세 키워드"),
          if (folders.isEmpty)
            _buildEmptyState()
          else
          // 💡 1단계 및 2단계 폴더를 모두 리스트에 표시합니다.
            ...folders.expand((folder) => [
              _buildFolderTile(folder, isSub: false), // 상위 폴더
              ...folder.subFolders.map((sub) => _buildFolderTile(sub, isSub: true)), // 하위 폴더
            ]).toList(),
        ],
      ),
    );
  }

  Widget _buildFolderTile(FavoriteFolder folder, {required bool isSub}) {
    return ListTile(
      contentPadding: EdgeInsets.only(left: isSub ? 40 : 16, right: 16),
      leading: Icon(
          isSub ? Icons.folder_special_outlined : Icons.folder_special,
          color: Colors.amber
      ),
      title: Text(
          folder.folderName,
          style: TextStyle(
              fontWeight: isSub ? FontWeight.normal : FontWeight.bold,
              fontSize: isSub ? 14 : 16
          )
      ),
      subtitle: Text(
        folder.keywords.isEmpty ? "등록된 키워드 없음" : "키워드: ${folder.keywords.join(', ')}",
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: const Icon(Icons.edit_note, color: Colors.grey),
      onTap: () => _showKeywordBottomSheet(folder),
    );
  }

  Widget _buildSectionHeader(String title) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
      child: Text(title, style: TextStyle(fontSize: 13, color: Colors.grey[600], fontWeight: FontWeight.bold)),
    );
  }

  Widget _buildEmptyState() {
    return const Center(
      child: Padding(
        padding: const EdgeInsets.all(40.0),
        child: Text("생성된 즐겨찾기 폴더가 없습니다.", style: TextStyle(color: Colors.grey)),
      ),
    );
  }
}