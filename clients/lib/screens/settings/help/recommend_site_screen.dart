import 'package:flutter/material.dart';
import '../settings_wrapper.dart';

class RecommendSiteScreen extends StatelessWidget {
  const RecommendSiteScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return SettingsWrapper(
      title: "사이트 추천(예시)",
      body: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
        children: [
          const SizedBox(height: 10),
          _buildHeroSection(),
          const SizedBox(height: 30),

          _buildCategorySection(
            context,
            title: "🎓 학교 및 교육 정보",
            description: "학사 일정, 성적 공고, 장학금 신청 등 휘발성이 강한 학내 소식",
            sites: ["대학교 학사 게시판 및 생활관 게시판", "장학금 또는 복지 관련 공지", "학내 유용한 정보 사이트"],
            themeColor: Colors.indigo,
          ),

          _buildCategorySection(
            context,
            title: "🏆 공모전, 대외활동 및 채용 공고",
            description: "스펙업을 위한 대외활동, 기한이 정해진 공모전 및 최신 채용 소식",
            sites: [
              "링커리어 (대외활동/인턴)",
              "캠퍼즈 (공모전)",
              "잡코리아/사람인 (채용)",
              "자소설닷컴 (채용일정)",
              "대외활동 플러스"
            ],
            themeColor: Colors.indigo,
          ),

          _buildCategorySection(
            context,
            title: "🏆 대기업 공채 및 기술 채용",
            description: "대기업 공채 일정과 네이버/카카오 등 IT 기업의 기술 중심 채용 공고",
            sites: [
              "삼성 채용 (SAMSUNG CAREERS)",
              "현대자동차 채용",
              "네이버 커리어 (SPA/React)",
              "카카오 채용 (GraphQL/API)",
              "토스/당근 기술 채용",
            ],
            themeColor: Colors.indigo,
          ),

          _buildCategorySection(
            context,
            title: "🏡 거주지 및 복지 소식",
            description: "지자체 행사, 청년 수당, 복지 혜택 및 거주지 관할 긴급 공고",
            sites: ["관할 시/구청 홈페이지", "복지로(Bokjiro)", "LH 청약플러스"],
            themeColor: Colors.indigo,
          ),

          _buildCategorySection(
            context,
            title: "💼 지원사업 및 입찰 공고",
            description: "정부 지원금, 창업 지원사업, 공공기관 입찰 및 채용 정보",
            sites: ["K-Startup", "기업마당(Bizinfo)", "나라장터(입찰)", "공공기관 알리오"],
            themeColor: Colors.indigo,
          ),

          _buildCategorySection(
            context,
            title: "⚖️ 법률 및 제도 개정",
            description: "놓치면 손해 보는 법률 개정안, 제도 변경, 최신 판례 소식",
            sites: ["대한민국 법제처", "국가법령정보센터", "분야별 최신 조례"],
            themeColor: Colors.indigo,
          ),

          _buildCategorySection(
            context,
            title: "🗳️ 정치 및 정책 소통",
            description: "가공되지 않은 원천 정보! 지지 정치인의 일정, 정당 공지, 국회 정책 세미나 소식",
            sites: [
              "국회 정책자료실 (세미나/보고서)",
              "각 정당(더불어민주당/국민의힘 등) 공지사항",
              "중앙선거관리위원회 공고",
              "열린국회정보포털 (입법 현황)",
              "국회의원 개인 블로그 및 홈페이지"
            ],
            themeColor: Colors.indigo,
          ),

          const SizedBox(height: 20),
          _buildRequestBox(),
          const SizedBox(height: 30),
        ],
      ),
    );
  }

  Widget _buildHeroSection() {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.blueAccent.withOpacity(0.05),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            "중요한 공고, 한곳에서 관리하세요",
            style: TextStyle(fontSize: 19, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          Text(
            "공고들은 일반적으로 게시되어도 일일이 알려주지 않습니다.\n기한이 정해진 지원금부터 놓치기 쉬운 개정안까지\n카테고리별로 추천하는 사이트 목록입니다.",
            style: TextStyle(color: Colors.grey[700], fontSize: 12, height: 1.5),
          ),
        ],
      ),
    );
  }

  Widget _buildCategorySection(
      BuildContext context, {
        required String title,
        required String description,
        required List<String> sites,
        required Color themeColor,
      }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
            title,
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Color(0xFF2D2D2D))
        ),
        const SizedBox(height: 6),
        Text(
            description,
            style: TextStyle(fontSize: 13, color: Colors.grey[600])
        ),
        const SizedBox(height: 16),

        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: sites.map((site) => Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(
              color: themeColor.withOpacity(0.12),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.circle, size: 4, color: themeColor.withOpacity(0.6)),
                const SizedBox(width: 6),
                Text(
                  site,
                  style: TextStyle(
                    fontSize: 13,
                    color: themeColor.withOpacity(0.8),
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          )).toList(),
        ),
        const SizedBox(height: 36),
      ],
    );
  }

  Widget _buildRequestBox() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.grey[100],
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          Icon(Icons.lightbulb_outline, color: Colors.orange),
          SizedBox(width: 12),
          Expanded(
            child: Text(
              "기타 사이트나 본인이 속한 단체의 사이트 추가가 필요한가요? '문의하기'를 통해 요청해 주세요!",
              style: TextStyle(fontSize: 12, color: Colors.grey[800], height: 1.4),
            ),
          ),
        ],
      ),
    );
  }
}
