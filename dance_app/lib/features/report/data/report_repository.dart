class TalentRadarData {
  /// fl_chart 레이더·범례 공통 스케일 (0~100점).
  static const int chartMaxScore = 100;

  final double creativity;
  final double rom;
  final double power;
  final double isolation;
  final double rhythm;
  final double accuracy;

  const TalentRadarData({
    required this.creativity,
    required this.rom,
    required this.power,
    required this.isolation,
    required this.rhythm,
    required this.accuracy,
  });

  /// API 점수(0~1 정규화) → 0~100 정수 표시.
  static int toPercent(double normalized) =>
      (normalized.clamp(0.0, 1.0) * chartMaxScore).round();

  /// 레이더 차트 축 순서: 창의성 → 가동범위 → 파워 → 아이솔 → 리듬 → 정확도
  List<({String label, double value})> get axes => [
        (label: '창의성', value: creativity),
        (label: '가동범위', value: rom),
        (label: '파워', value: power),
        (label: '아이솔', value: isolation),
        (label: '리듬', value: rhythm),
        (label: '정확도', value: accuracy),
      ];
}

class CareerReport {
  final String genre;
  final int overallScore;
  final TalentRadarData radar;
  final String aiMessage;
  final List<String> recommendedCareers;

  const CareerReport({
    required this.genre,
    required this.overallScore,
    required this.radar,
    required this.aiMessage,
    required this.recommendedCareers,
  });
}

class ReportRepository {
  Future<CareerReport> fetchReport() async {
    await Future.delayed(const Duration(milliseconds: 600));
    return const CareerReport(
      genre: '팝핑',
      overallScore: 87,
      radar: TalentRadarData(
        creativity: 0.72,
        rom: 0.78,
        power: 0.92,
        isolation: 0.95,
        rhythm: 0.88,
        accuracy: 0.85,
      ),
      aiMessage:
          '너의 팝핑 타격감은 상위 10%야! 이 뛰어난 리듬감을 살려 안무가나 백업 댄서로 진로를 탐색해보는 건 어떨까? 지역 진로체험센터 프로그램을 추천해줄게.',
      recommendedCareers: ['백업 댄서', '안무가', '댄스 강사', '뮤직비디오 아티스트'],
    );
  }
}
