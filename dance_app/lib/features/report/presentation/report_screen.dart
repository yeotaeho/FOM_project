import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/fallback_video_preview.dart';
import '../../../shared/widgets/neon_badge.dart';
import '../../studio/data/studio_providers.dart';
import '../../studio/data/video_analyze_models.dart';
import '../data/report_repository.dart';

class ReportScreen extends ConsumerWidget {
  const ReportScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final analyze = ref.watch(videoAnalyzeResultProvider);

    if (analyze == null) {
      return Scaffold(
        backgroundColor: AppColors.background,
        body: SafeArea(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.all(32),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(
                    Icons.radar_outlined,
                    color: AppColors.neonPurple,
                    size: 56,
                  ),
                  const SizedBox(height: 16),
                  Text(
                    '아직 분석 결과가 없습니다',
                    style: Theme.of(context).textTheme.titleMedium,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'Studio에서 촬영 후\n「비교 분석 시작」을 눌러 주세요.',
                    style: Theme.of(context).textTheme.bodyMedium,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 24),
                  ElevatedButton(
                    onPressed: () => context.go('/studio'),
                    child: const Text('Studio로 이동'),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }

    final challenge = ref.watch(selectedChallengeProvider);
    final report = analyze.toCareerReport(
      genre: challenge?.genre ?? '팝핑',
    );
    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: _ReportBody(
          report: report,
          grade: analyze.grade,
          analyze: analyze,
        ),
      ),
    );
  }
}

class _ReportBody extends StatelessWidget {
  final CareerReport report;
  final String grade;
  final VideoAnalyzeResult analyze;

  const _ReportBody({
    required this.report,
    required this.grade,
    required this.analyze,
  });

  @override
  Widget build(BuildContext context) {
    return CustomScrollView(
      slivers: [
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '재능\n리포트',
                  style: Theme.of(context).textTheme.displayLarge?.copyWith(
                        foreground: Paint()
                          ..shader = const LinearGradient(
                            colors: [AppColors.neonPurple, AppColors.neonBlue],
                          ).createShader(const Rect.fromLTWH(0, 0, 200, 60)),
                      ),
                ),
                const SizedBox(height: 4),
                Row(
                  children: [
                    NeonBadge(label: report.genre, color: AppColors.neonGreen),
                    const SizedBox(width: 8),
                    NeonBadge(
                      label: '점수 ${report.overallScore}',
                      color: AppColors.neonPurple,
                    ),
                    const SizedBox(width: 8),
                    NeonBadge(label: '등급 $grade', color: AppColors.neonBlue),
                  ],
                ),
                const SizedBox(height: 24),
                _CompareAnalysisCard(analyze: analyze),
                const SizedBox(height: 20),
                _RadarChartCard(radar: report.radar),
                const SizedBox(height: 20),
                _AiMessageCard(message: report.aiMessage),
                const SizedBox(height: 20),
                _CareerCards(careers: report.recommendedCareers),
                const SizedBox(height: 32),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _CompareAnalysisCard extends StatelessWidget {
  final VideoAnalyzeResult analyze;

  const _CompareAnalysisCard({required this.analyze});

  @override
  Widget build(BuildContext context) {
    final expertUrls = analyze.expertPlaybackUrls;
    final userUrls = analyze.userPlaybackUrls;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: AppColors.neonGreen.withValues(alpha: 0.25)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.compare_rounded, color: AppColors.neonGreen, size: 18),
              const SizedBox(width: 8),
              Text(
                '비교 분석 영상',
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: AppColors.neonGreen,
                    ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            '',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 12),
          SizedBox(
            height: 200,
            child: Row(
              children: [
                Expanded(
                  child: _CompareVideoPane(
                    label: analyze.expertVideoCaption,
                    urls: expertUrls,
                    placeholder: expertUrls.isEmpty
                        ? '전문가 영상을 불러올 수 없습니다'
                        : null,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _CompareVideoPane(
                    label: analyze.userVideoCaption,
                    urls: userUrls,
                    placeholder: userUrls.isEmpty
                        ? '분석 영상을 불러올 수 없습니다'
                        : null,
                  ),
                ),
              ],
            ),
          ),
          if (analyze.referenceJson != null) ...[
            const SizedBox(height: 10),
            Text(
              '',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(fontSize: 10),
            ),
          ],
        ],
      ),
    );
  }
}

class _CompareVideoPane extends StatelessWidget {
  final String label;
  final List<String> urls;
  final String? placeholder;

  const _CompareVideoPane({
    required this.label,
    required this.urls,
    this.placeholder,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(label, style: Theme.of(context).textTheme.labelSmall),
        const SizedBox(height: 6),
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: urls.isNotEmpty
                ? FallbackVideoPreview(
                    urls: urls,
                    height: null,
                    borderRadius: BorderRadius.circular(12),
                  )
                : ColoredBox(
                    color: AppColors.surface,
                    child: Center(
                      child: Text(
                        placeholder ?? '영상 없음',
                        textAlign: TextAlign.center,
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ),
                  ),
          ),
        ),
      ],
    );
  }
}

class _RadarChartCard extends StatelessWidget {
  final TalentRadarData radar;

  const _RadarChartCard({required this.radar});

  /// fl_chart는 데이터 min~max 상대 스케일이라 최저 점수가 중심에 붙음 → 0점 앵커로 0~100 고정.
  List<RadarDataSet> _radarDataSets() {
    final n = radar.axes.length;
    final anchor = RadarDataSet(
      dataEntries: List.generate(n, (_) => const RadarEntry(value: 0)),
      fillColor: Colors.transparent,
      borderColor: Colors.transparent,
      borderWidth: 0,
      entryRadius: 0,
    );
    final scores = RadarDataSet(
      fillColor: AppColors.neonPurple.withValues(alpha: 0.2),
      borderColor: AppColors.neonPurple,
      borderWidth: 2,
      entryRadius: 4,
      dataEntries: [
        for (final axis in radar.axes)
          RadarEntry(
            value: axis.value.clamp(0.0, 1.0) * TalentRadarData.chartMaxScore,
          ),
      ],
    );
    return [anchor, scores];
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: AppColors.neonPurple.withValues(alpha: 0.25)),
      ),
      child: Column(
        children: [
          Row(
            children: [
              const Icon(Icons.radar, color: AppColors.neonPurple, size: 18),
              const SizedBox(width: 8),
              Text(
                '재능 레이더',
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: AppColors.neonPurple,
                    ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          SizedBox(
            height: 240,
            child: RadarChart(
              RadarChartData(
                radarShape: RadarShape.polygon,
                tickCount: 4,
                ticksTextStyle:
                    const TextStyle(color: Colors.transparent, fontSize: 0),
                gridBorderData:
                    const BorderSide(color: AppColors.divider, width: 1),
                radarBorderData:
                    const BorderSide(color: AppColors.divider, width: 1),
                titlePositionPercentageOffset: 0.2,
                titleTextStyle: const TextStyle(
                  color: AppColors.textSecondary,
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
                getTitle: (index, _) {
                  return RadarChartTitle(text: radar.axes[index].label);
                },
                dataSets: _radarDataSets(),
                tickBorderData:
                    const BorderSide(color: AppColors.divider, width: 1),
              ),
            ),
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 16,
            runSpacing: 8,
            children: [
              for (final axis in radar.axes)
                _LegendItem(label: axis.label, value: axis.value),
            ],
          ),
        ],
      ),
    );
  }
}

class _LegendItem extends StatelessWidget {
  final String label;
  final double value;

  const _LegendItem({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: const BoxDecoration(
            color: AppColors.neonPurple,
            shape: BoxShape.circle,
          ),
        ),
        const SizedBox(width: 4),
        Text(
          '$label ${TalentRadarData.toPercent(value)}',
          style: const TextStyle(color: AppColors.textSecondary, fontSize: 11),
        ),
      ],
    );
  }
}

class _AiMessageCard extends StatelessWidget {
  final String message;

  const _AiMessageCard({required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            AppColors.neonGreen.withValues(alpha: 0.08),
            AppColors.neonPurple.withValues(alpha: 0.08),
          ],
        ),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: AppColors.neonGreen.withValues(alpha: 0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: AppColors.neonGreen.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: const Text('🤖', style: TextStyle(fontSize: 20)),
              ),
              const SizedBox(width: 10),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'AI 커리어 가이드',
                    style: TextStyle(
                      color: AppColors.neonGreen,
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  Text(
                    '6차원 분석 기반',
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(fontSize: 11),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(
              message,
              style: const TextStyle(
                color: AppColors.textPrimary,
                fontSize: 15,
                height: 1.7,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _CareerCards extends StatelessWidget {
  final List<String> careers;

  const _CareerCards({required this.careers});

  static const _icons = ['💃', '🎭', '🎬', '🎵'];
  static const _colors = [
    AppColors.neonGreen,
    AppColors.neonPurple,
    AppColors.neonBlue,
    Color(0xFFFF9F0A),
  ];

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '추천 진로',
          style: TextStyle(
            color: AppColors.textSecondary,
            fontSize: 11,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.8,
          ),
        ),
        const SizedBox(height: 12),
        GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: 2,
            crossAxisSpacing: 12,
            mainAxisSpacing: 12,
            childAspectRatio: 2.2,
          ),
          itemCount: careers.length,
          itemBuilder: (_, i) => Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: AppColors.card,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(
                color: _colors[i % _colors.length].withValues(alpha: 0.3),
              ),
            ),
            child: Row(
              children: [
                Text(_icons[i % _icons.length], style: const TextStyle(fontSize: 24)),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    careers[i],
                    style: TextStyle(
                      color: _colors[i % _colors.length],
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
