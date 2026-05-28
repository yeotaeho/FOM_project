import '../../home/data/home_repository.dart';

/// 사용자 촬영본 + 선택 챌린지 레퍼런스(서버 JSON) 비교 세션.
class CompareSession {
  final String userVideoPath;

  /// 챌린지 asset MP4 (Studio·Report 전문가 미리보기).
  final String referenceVideoPath;

  /// `POST /video/analyze` Form `reference_json` (저장 파일명).
  final String referenceJson;

  /// `video_data/cardN/*.json` asset 경로 — `reference_json_file` 업로드.
  final String referenceJsonAsset;

  /// 서버 `video_data/` 사용자 MP4 (by-name).
  final String serverUserVideoFilename;

  /// 서버 `video_data/` 전문가 MP4 (reference JSON 오버레이).
  final String serverReferenceVideoFilename;

  /// true면 촬영 없이 서버 MP4 + by-name.
  final bool useDevServerVideo;

  const CompareSession({
    required this.userVideoPath,
    this.referenceVideoPath = '',
    required this.referenceJson,
    this.referenceJsonAsset = '',
    this.serverUserVideoFilename = '',
    this.serverReferenceVideoFilename = '',
    this.useDevServerVideo = false,
  });

  factory CompareSession.fromChallenge(
    DanceVideo challenge, {
    required String userVideoPath,
    bool useDevServerVideo = false,
  }) {
    return CompareSession(
      userVideoPath: userVideoPath,
      referenceVideoPath: challenge.videoUrl,
      referenceJson: challenge.referenceJson,
      referenceJsonAsset: challenge.referenceJsonAsset,
      serverUserVideoFilename: challenge.serverVideoFilename,
      serverReferenceVideoFilename: challenge.serverReferenceVideoFilename,
      useDevServerVideo: useDevServerVideo,
    );
  }

  /// 개발: 선택 카드의 서버 MP4 + 해당 카드 reference_json.
  factory CompareSession.devServer(DanceVideo challenge) => CompareSession(
        userVideoPath: '',
        referenceVideoPath: challenge.videoUrl,
        referenceJson: challenge.referenceJson,
        referenceJsonAsset: challenge.referenceJsonAsset,
        serverUserVideoFilename: challenge.serverVideoFilename,
        serverReferenceVideoFilename: challenge.serverReferenceVideoFilename,
        useDevServerVideo: true,
      );
}
