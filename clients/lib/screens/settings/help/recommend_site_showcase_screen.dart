import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../providers/settings_provider.dart';
import '../settings_wrapper.dart';
import 'inquiry_submit_screen.dart';

class RecommendSiteShowcaseScreen extends StatefulWidget {
  const RecommendSiteShowcaseScreen({super.key});

  @override
  State<RecommendSiteShowcaseScreen> createState() =>
      _RecommendSiteShowcaseScreenState();
}

class _RecommendSiteShowcaseScreenState
    extends State<RecommendSiteShowcaseScreen> {
  static const _groups = <_RecommendationGroup>[
    _RecommendationGroup(
      label: '대학생',
      icon: Icons.school_outlined,
      color: Color(0xFF5B5BD6),
      headline: '학교 공지를 놓치지 않게',
      description: '신청 기간이 짧은 학사·장학·생활관 소식을 한곳에서 확인해 보세요.',
      examples: ['학교 학사·수업 공지', '학생지원·장학 게시판', '생활관 입사·모집 공지'],
    ),
    _RecommendationGroup(
      label: '취업 준비',
      icon: Icons.work_outline_rounded,
      color: Color(0xFF167D6A),
      headline: '필요한 일정을 능동적으로 챙기기',
      description: '관심 기업과 대외활동 사이트의 새 모집 공고를 꾸준히 확인할 수 있어요.',
      examples: ['관심 기업 채용 게시판', '인턴·대외활동 모집 공고', '공모전·교육 프로그램'],
    ),
    _RecommendationGroup(
      label: '사업·입찰',
      icon: Icons.business_center_outlined,
      color: Color(0xFFB45F24),
      headline: '지원 사업 기회, 정책 변경을 수시로 확인',
      description: '사업자에게 필요한 정부 지원사업과 입찰 공고를 모아서 확인해 보세요.',
      examples: ['K-Startup 사업공고', '기업마당 지원사업', 'KISA', '대한민국 정책브리핑 보도자료'],
    ),
    _RecommendationGroup(
      label: '생활·복지',
      icon: Icons.home_work_outlined,
      color: Color(0xFF376EB5),
      headline: '내 생활에 필요한 소식',
      description: '거주 지역의 복지·청약·행사 소식을 필요할 때 바로 확인할 수 있어요.',
      examples: ['시·구청 새소식', '복지·청년정책 공고', '공공임대·청약 공고', '서울문화포털'],
    ),
    _RecommendationGroup(
      label: '취미·기타',
      icon: Icons.interests_outlined,
      color: Color(0xFF9A4E93),
      headline: '좋아하는 소식도 놓치지 않게',
      description: '자주 찾아보던 모임·행사·크리에이터 소식도 공지처럼 편하게 모아보세요.',
      examples: [
        '동호회·협회 공지',
        '게임 및 기타 게릴라 이벤트',
        '공연·전시·지역 축제',
        '크리에이터 커뮤니티 게시물',
      ],
    ),
  ];

  int _selectedGroupIndex = 0;

  void _goToAddSite() {
    Navigator.pop(context, 3);
  }

  Future<void> _openInquiry() async {
    final targetIndex = await Navigator.push<int>(
      context,
      MaterialPageRoute(builder: (_) => const InquirySubmitScreen()),
    );

    if (targetIndex != null && mounted) {
      Navigator.pop(context, targetIndex);
    }
  }

  @override
  Widget build(BuildContext context) {
    final isDarkMode = context.watch<SettingsProvider>().settings.isDarkMode;
    final palette = _ShowcasePalette.from(isDarkMode);
    final selectedGroup = _groups[_selectedGroupIndex];

    return SettingsWrapper(
      title: '추천 활용법',
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 36),
        children: [
          _buildHero(palette),
          const SizedBox(height: 32),
          Text(
            '어떤 소식을 찾고 있나요?',
            style: TextStyle(
              color: palette.primaryText,
              fontSize: 20,
              fontWeight: FontWeight.w800,
              letterSpacing: -0.4,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            '관심 분야를 고르면 등록해 볼 만한 사이트 유형을 보여드려요.',
            style: TextStyle(
              color: palette.secondaryText,
              fontSize: 14,
              height: 1.45,
            ),
          ),
          const SizedBox(height: 16),
          _buildCategorySelector(palette),
          const SizedBox(height: 18),
          AnimatedSwitcher(
            duration: const Duration(milliseconds: 220),
            transitionBuilder: (child, animation) => FadeTransition(
              opacity: animation,
              child: SlideTransition(
                position: Tween<Offset>(
                  begin: const Offset(0.02, 0),
                  end: Offset.zero,
                ).animate(animation),
                child: child,
              ),
            ),
            child: _buildRecommendationCard(
              key: ValueKey(_selectedGroupIndex),
              group: selectedGroup,
              palette: palette,
            ),
          ),
          const SizedBox(height: 32),
          _buildHowItWorks(palette),
          const SizedBox(height: 28),
          _buildRequestCard(palette),
        ],
      ),
    );
  }

  Widget _buildHero(_ShowcasePalette palette) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '놓치기 쉬운 정보를 한곳에',
            style: TextStyle(
              color: palette.secondaryText,
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 18),
          Text(
            '매일 홈페이지를\n확인하지 않아도 돼요',
            style: TextStyle(
              color: palette.primaryText,
              fontSize: 25,
              height: 1.25,
              fontWeight: FontWeight.w800,
              letterSpacing: -0.7,
            ),
          ),
          const SizedBox(height: 12),
          Text(
            '자주 보는 공개 게시판을 등록하면 새 소식을 한곳에서 확인하고, 원하는 사이트만 별개로 구독해서 알림을 받을 수 있어요.',
            style: TextStyle(
              color: palette.secondaryText,
              fontSize: 14,
              height: 1.55,
            ),
          ),
          const SizedBox(height: 22),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: _goToAddSite,
              icon: const Icon(Icons.add_link_rounded, size: 20),
              label: const Text('사이트 추가하기'),
              style: FilledButton.styleFrom(
                backgroundColor: palette.primaryText,
                foregroundColor: palette.surface,
                padding: const EdgeInsets.symmetric(vertical: 15),
                textStyle: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w800,
                ),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14),
                ),
              ),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                Icons.lock_open_outlined,
                size: 16,
                color: palette.secondaryText,
              ),
              const SizedBox(width: 7),
              Expanded(
                child: Text(
                  '로그인 없이 볼 수 있는 공개 사이트를 등록할 수 있어요.',
                  style: TextStyle(
                    color: palette.secondaryText,
                    fontSize: 12,
                    height: 1.35,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildCategorySelector(_ShowcasePalette palette) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: List.generate(_groups.length, (index) {
          final group = _groups[index];
          final isSelected = index == _selectedGroupIndex;

          return Padding(
            padding: EdgeInsets.only(
              right: index == _groups.length - 1 ? 0 : 8,
            ),
            child: ChoiceChip(
              selected: isSelected,
              onSelected: (_) => setState(() => _selectedGroupIndex = index),
              avatar: Icon(
                group.icon,
                size: 18,
                color: isSelected ? Colors.white : palette.secondaryText,
              ),
              label: Text(group.label),
              labelStyle: TextStyle(
                color: isSelected ? Colors.white : palette.primaryText,
                fontWeight: FontWeight.w700,
              ),
              backgroundColor: palette.surface,
              selectedColor: group.color,
              side: BorderSide(
                color: isSelected ? group.color : palette.border,
              ),
              showCheckmark: false,
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 9),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(999),
              ),
            ),
          );
        }),
      ),
    );
  }

  Widget _buildRecommendationCard({
    required Key key,
    required _RecommendationGroup group,
    required _ShowcasePalette palette,
  }) {
    return Container(
      key: key,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: palette.surface,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: palette.border),
        boxShadow: palette.cardShadow,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: group.color.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(13),
                ),
                child: Icon(group.icon, color: group.color, size: 23),
              ),
              const SizedBox(width: 13),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      group.headline,
                      style: TextStyle(
                        color: palette.primaryText,
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                        letterSpacing: -0.3,
                      ),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      group.description,
                      style: TextStyle(
                        color: palette.secondaryText,
                        fontSize: 13,
                        height: 1.45,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
          ...group.examples.map(
                (example) => Padding(
              padding: const EdgeInsets.only(bottom: 11),
              child: Row(
                children: [
                  Icon(
                    Icons.check_circle_rounded,
                    size: 18,
                    color: group.color,
                  ),
                  const SizedBox(width: 9),
                  Expanded(
                    child: Text(
                      example,
                      style: TextStyle(
                        color: palette.primaryText,
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 5),
        ],
      ),
    );
  }

  Widget _buildHowItWorks(_ShowcasePalette palette) {
    const steps = [
      (Icons.link_rounded, '주소 등록', '자주 보는 게시판 주소를 추가해요. 사이트에서 \'공유\' 기능으로도 추가할 수 있습니다.'),
      (Icons.inventory_2_outlined, '한곳에 정리', '새 공고를 구독별로 모읍니다.'),
      (Icons.notifications_none_rounded, '선택 알림', '원하는 구독의 알림만 받아봅니다.'),
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '주소 한 번 등록하면 끝',
          style: TextStyle(
            color: palette.primaryText,
            fontSize: 20,
            fontWeight: FontWeight.w800,
            letterSpacing: -0.4,
          ),
        ),
        const SizedBox(height: 15),
        ...List.generate(steps.length, (index) {
          final step = steps[index];
          return Padding(
            padding: EdgeInsets.only(
              bottom: index == steps.length - 1 ? 0 : 12,
            ),
            child: Row(
              children: [
                Container(
                  width: 42,
                  height: 42,
                  decoration: BoxDecoration(
                    color: palette.softAccent,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Icon(step.$1, color: palette.accent, size: 21),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${index + 1}. ${step.$2}',
                        style: TextStyle(
                          color: palette.primaryText,
                          fontSize: 14,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        step.$3,
                        style: TextStyle(
                          color: palette.secondaryText,
                          fontSize: 13,
                          height: 1.35,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          );
        }),
      ],
    );
  }

  Widget _buildRequestCard(_ShowcasePalette palette) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: palette.surface,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: palette.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '사이트 등록에 문제가 있나요?',
                  style: TextStyle(
                    color: palette.primaryText,
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            '등록 과정에서 문제가 발생한 사이트는 문의를 통해 전달 부탁드립니다.',
            style: TextStyle(
              color: palette.secondaryText,
              fontSize: 13,
              height: 1.45,
            ),
          ),
          const SizedBox(height: 12),
          TextButton.icon(
            onPressed: _openInquiry,
            icon: const Icon(Icons.chat_bubble_outline_rounded, size: 18),
            label: const Text('문의하기'),
            style: TextButton.styleFrom(
              foregroundColor: palette.accent,
              padding: EdgeInsets.zero,
              textStyle: const TextStyle(fontWeight: FontWeight.w800),
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
          ),
        ],
      ),
    );
  }
}

class _RecommendationGroup {
  final String label;
  final IconData icon;
  final Color color;
  final String headline;
  final String description;
  final List<String> examples;

  const _RecommendationGroup({
    required this.label,
    required this.icon,
    required this.color,
    required this.headline,
    required this.description,
    required this.examples,
  });
}

class _ShowcasePalette {
  final Color primaryText;
  final Color secondaryText;
  final Color surface;
  final Color border;
  final Color accent;
  final Color softAccent;
  final List<BoxShadow> cardShadow;

  const _ShowcasePalette({
    required this.primaryText,
    required this.secondaryText,
    required this.surface,
    required this.border,
    required this.accent,
    required this.softAccent,
    required this.cardShadow,
  });

  factory _ShowcasePalette.from(bool isDarkMode) {
    if (isDarkMode) {
      return const _ShowcasePalette(
        primaryText: Color(0xFFF4F5F7),
        secondaryText: Color(0xFFB8BDC7),
        surface: Color(0xFF1B1D21),
        border: Color(0xFF30343B),
        accent: Color(0xFF8BB8FF),
        softAccent: Color(0xFF222F42),
        cardShadow: [],
      );
    }

    return const _ShowcasePalette(
      primaryText: Color(0xFF17202E),
      secondaryText: Color(0xFF667085),
      surface: Colors.white,
      border: Color(0xFFE7EAF0),
      accent: Color(0xFF2563A9),
      softAccent: Color(0xFFEDF4FC),
      cardShadow: [
        BoxShadow(
          color: Color(0x0F17202E),
          blurRadius: 22,
          offset: Offset(0, 8),
        ),
      ],
    );
  }
}
