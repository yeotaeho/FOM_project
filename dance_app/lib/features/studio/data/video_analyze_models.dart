import '../../../core/config/api_config.dart';

import '../../report/data/report_repository.dart';



/// `POST /video/analyze` 응답 (scores + 비교 영상 URL).

class VideoAnalyzeResult {

  final double creativity;

  final double rom;

  final double power;

  final double isolation;

  final double rhythm;

  final double accuracy;

  final double totalScore;

  final String grade;

  final String? userJson;

  final String? referenceJson;

  final Map<String, dynamic>? rawScores;



  /// Report 전문가 — asset 또는 http.

  final String expertVideoDisplayUrl;



  /// `reference.annotated_video` (전문가 포즈 오버레이).

  final String? expertAnnotatedVideoUrl;



  /// 분석 오버레이 MP4 (`user.annotated_video`).

  final String? userAnnotatedVideoUrl;



  /// 서버 `video_data/` 사용자 원본 (dev by-name).

  final String? userServerVideoFilename;



  /// 카드 asset MP4 (`video_data/cardN/...`).

  final String? userAssetVideoUrl;



  /// 촬영본 로컬 경로.

  final String? userLocalVideoPath;

  

  /// LLM 생성 피드백 (AI 커리어 가이드).

  final String? feedback;

  

  /// LLM 피드백 생성 오류 메시지.

  final String? feedbackError;



  const VideoAnalyzeResult({

    required this.creativity,

    required this.rom,

    required this.power,

    required this.isolation,

    required this.rhythm,

    required this.accuracy,

    required this.totalScore,

    required this.grade,

    required this.expertVideoDisplayUrl,

    this.userJson,

    this.referenceJson,

    this.rawScores,

    this.expertAnnotatedVideoUrl,

    this.userAnnotatedVideoUrl,

    this.userServerVideoFilename,

    this.userAssetVideoUrl,

    this.userLocalVideoPath,

    this.feedback,

    this.feedbackError,

  });



  factory VideoAnalyzeResult.fromJson(

    Map<String, dynamic> json, {

    String expertVideoDisplayUrl = '',

    String? userAssetVideoUrl,

    String? userServerVideoFilename,

  }) {

    final scores = json['scores'] as Map<String, dynamic>? ?? {};

    final total = scores['total_score'];

    final grade = scores['grade']?.toString() ?? '—';

    final meta = json['meta'] as Map<String, dynamic>?;

    final user = json['user'] as Map<String, dynamic>?;

    final reference = json['reference'] as Map<String, dynamic>?;

    final userAnnotated = user?['annotated_video'] as Map<String, dynamic>?;

    final refAnnotated = reference?['annotated_video'] as Map<String, dynamic>?;



    final serverFromMeta = meta?['user_server_video_filename'] as String?;



    return VideoAnalyzeResult(

      creativity: _metricScore(scores, 'creativity'),

      rom: _metricScore(scores, 'rom'),

      power: _metricScore(scores, 'power'),

      isolation: _metricScore(scores, 'isolation'),

      rhythm: _metricScore(scores, 'rhythm'),

      accuracy: _metricScore(scores, 'accuracy'),

      totalScore: total is num ? total.toDouble() : 0,

      grade: grade,

      expertVideoDisplayUrl: expertVideoDisplayUrl,

      userJson: meta?['user_json'] as String?,

      referenceJson: meta?['reference_json'] as String?,

      rawScores: scores,

      expertAnnotatedVideoUrl: ApiConfig.resolvePlaybackUrl(

        refAnnotated?['url'] as String?,

      ),

      userAnnotatedVideoUrl: ApiConfig.resolvePlaybackUrl(

        userAnnotated?['url'] as String?,

      ),

      userServerVideoFilename:
          userServerVideoFilename ?? serverFromMeta,

      userAssetVideoUrl: userAssetVideoUrl,

      feedback: json['feedback']?['feedback'] as String?,

      feedbackError: json['feedback']?['error'] as String?,

    );

  }



  VideoAnalyzeResult withPlaybackContext({

    String? userLocalVideoPath,

    String? userServerVideoFilename,

    String? userAssetVideoUrl,

  }) {

    return VideoAnalyzeResult(

      creativity: creativity,

      rom: rom,

      power: power,

      isolation: isolation,

      rhythm: rhythm,

      accuracy: accuracy,

      totalScore: totalScore,

      grade: grade,

      expertVideoDisplayUrl: expertVideoDisplayUrl,

      userJson: userJson,

      referenceJson: referenceJson,

      rawScores: rawScores,

      expertAnnotatedVideoUrl: expertAnnotatedVideoUrl,

      userAnnotatedVideoUrl: userAnnotatedVideoUrl,

      userServerVideoFilename:

          userServerVideoFilename ?? this.userServerVideoFilename,

      userAssetVideoUrl: userAssetVideoUrl ?? this.userAssetVideoUrl,

      userLocalVideoPath: userLocalVideoPath ?? this.userLocalVideoPath,

      feedback: feedback,

      feedbackError: feedbackError,

    );

  }



  /// 전문가: 오버레이 MP4 우선 → asset·원본 fallback.
  List<String> get expertPlaybackUrls {
    final out = <String>[];
    if (expertAnnotatedVideoUrl != null &&
        expertAnnotatedVideoUrl!.isNotEmpty) {
      out.add(expertAnnotatedVideoUrl!);
    }
    if (expertVideoDisplayUrl.isNotEmpty) {
      out.add(expertVideoDisplayUrl);
    }
    return out;
  }



  /// 사용자: annotated → 서버 원본 → 로컬 → asset.

  List<String> get userPlaybackUrls {

    final out = <String>[];

    if (userAnnotatedVideoUrl != null && userAnnotatedVideoUrl!.isNotEmpty) {

      out.add(userAnnotatedVideoUrl!);

    }

    final server = userServerVideoFilename;

    if (server != null && server.isNotEmpty) {

      out.add(ApiConfig.videoDataUrl(server));

    }

    if (userLocalVideoPath != null && userLocalVideoPath!.isNotEmpty) {

      out.add(userLocalVideoPath!);

    }

    if (userAssetVideoUrl != null && userAssetVideoUrl!.isNotEmpty) {

      out.add(userAssetVideoUrl!);

    }

    return out;

  }



  String? get userPlaybackUrl {

    final urls = userPlaybackUrls;

    return urls.isEmpty ? null : urls.first;

  }



  String get userVideoCaption {

    if (userAnnotatedVideoUrl != null && userAnnotatedVideoUrl!.isNotEmpty) {

      return '분석 오버레이';

    }

    return '내 영상';

  }



  String get expertVideoCaption {

    if (expertAnnotatedVideoUrl != null &&

        expertAnnotatedVideoUrl!.isNotEmpty) {

      return '전문가 오버레이';

    }

    return '전문가';

  }



  static double _metricScore(Map<String, dynamic> scores, String key) {

    final block = scores[key];

    if (block is! Map<String, dynamic>) return 0;

    final breakdown = block['breakdown'];

    if (breakdown is Map && breakdown['error'] != null) return 0;

    final s = block['score'];

    if (s is num) return (s / 100).clamp(0.0, 1.0);

    return 0;

  }



  CareerReport toCareerReport({String genre = '팝핑'}) {

    final overall = totalScore.round().clamp(0, 100);

    return CareerReport(

      genre: genre,

      overallScore: overall,

      radar: TalentRadarData(

        creativity: creativity,

        rom: rom,

        power: power,

        isolation: isolation,

        rhythm: rhythm,

        accuracy: accuracy,

      ),

      aiMessage: feedback ?? 
          (feedbackError != null 
            ? '피드백 생성 중 오류 발생: $feedbackError\n\n기본 분석: 6차원 분석이 완료됐어요. 종합 $overall점(등급 $grade). 아래 비교 영상에서 포즈 분석 결과를 확인하고, 레이더에서 6개 지표를 살펴보세요.'
            : '6차원 분석이 완료됐어요. 종합 $overall점(등급 $grade). 아래 비교 영상에서 포즈 분석 결과를 확인하고, 레이더에서 6개 지표를 살펴보세요.'),

      recommendedCareers: const ['백업 댄서', '안무가', '댄스 강사', '뮤직비디오 아티스트'],

    );

  }

}


