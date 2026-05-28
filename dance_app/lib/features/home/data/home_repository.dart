import '../../../core/config/video_config.dart';

/// 챌린지 카드 1~5 ↔ `dance_app/video_data/cardN/` (mp4 + reference JSON).
class DanceVideo {
  final String id;
  final String title;
  final String genre;
  final String difficulty;
  final String thumbnailUrl;

  /// Flutter asset — `video_data/cardN/xxx_480.mp4` (앱 재생용 480p).
  final String videoUrl;

  /// 서버 `video_json/` 저장 파일명 + multipart `reference_json` 필드.
  final String referenceJson;

  /// 서버 `video_data/` 사용자 MP4 (by-name dev).
  final String serverVideoFilename;

  /// 서버 `video_data/` 전문가 MP4 — reference JSON 오버레이 렌더용.
  final String serverReferenceVideoFilename;

  final String artist;
  final int durationSeconds;

  const DanceVideo({
    required this.id,
    required this.title,
    required this.genre,
    required this.difficulty,
    required this.thumbnailUrl,
    required this.videoUrl,
    required this.referenceJson,
    required this.serverVideoFilename,
    required this.serverReferenceVideoFilename,
    required this.artist,
    required this.durationSeconds,
  });
}

extension DanceVideoAssets on DanceVideo {
  /// Flutter asset — `video_data/cardN/<referenceJson>` (서버 업로드용).
  String get referenceJsonAsset {
    final slash = videoUrl.lastIndexOf('/');
    if (slash < 0) return referenceJson;
    return '${videoUrl.substring(0, slash + 1)}$referenceJson';
  }

  /// 에뮬·Studio 미리보기용 사용자 MP4 asset (`video_data/cardN/cardN_user_480.mp4`).
  String get userPreviewAsset {
    final slash = videoUrl.lastIndexOf('/');
    if (slash < 0) return '';
    return VideoConfig.previewAssetPath(
      '${videoUrl.substring(0, slash + 1)}card${id}_user.mp4',
    );
  }
}

class HomeRepository {
  static const challenges = <DanceVideo>[
    DanceVideo(
      id: '1',
      title: "It's Me",
      genre: '아일릿',
      difficulty: '초급',
      thumbnailUrl: 'video_data/card1/maxresdefault.jpg',
      videoUrl: 'video_data/card1/gBR_sBM_c01_d06_mBR3_ch03_480.mp4',
      referenceJson: '20260521_134352_bed9b6d2.json',
      serverVideoFilename: 'gBR_sBM_c01_d06_mBR3_ch03.mp4',
      serverReferenceVideoFilename: 'gBR_sBM_c01_d06_mBR3_ch03.mp4',
      artist: 'ILLIT',
      durationSeconds: 12,
    ),
    DanceVideo(
      id: '2',
      title: '캐치 캐치(Catch Catch)',
      genre: '최예나',
      difficulty: '중급',
      thumbnailUrl: 'video_data/card2/638023.jpg',
      videoUrl: 'video_data/card2/card2_reference_480.mp4',
      referenceJson: '20260523_021914_d70a0372.json',
      serverVideoFilename: 'Video Project 1 (2).mp4',
      serverReferenceVideoFilename: 'card2_reference.mp4',
      artist: 'YENA(최예나)',
      durationSeconds: 14,
    ),
    DanceVideo(
      id: '3',
      title: 'Whiplash',
      genre: 'aespa',
      difficulty: '초급',
      thumbnailUrl:
          'video_data/card3/news-p.v1.20241021.1dab4c4120284a44a9a5b91e9beea018_Z1.jpg',
      videoUrl: 'video_data/card3/gHO_sBM_c01_d19_mHO3_ch03_480.mp4',
      referenceJson: '20260521_154842_eee5efdc.json',
      serverVideoFilename: 'gHO_sBM_c01_d19_mHO3_ch03.mp4',
      serverReferenceVideoFilename: 'gHO_sBM_c01_d19_mHO3_ch03.mp4',
      artist: 'aespa',
      durationSeconds: 25,
    ),
    DanceVideo(
      id: '4',
      title: 'SWIM',
      genre: 'BTS',
      difficulty: '고급',
      thumbnailUrl: 'video_data/card4/HEu_9rNawAAlV1A.jpg',
      videoUrl: 'video_data/card4/gJB_sBM_c01_d07_mJB3_ch03_480.mp4',
      referenceJson: '20260521_155027_4acf1e1d.json',
      serverVideoFilename: 'gJB_sBM_c01_d07_mJB3_ch03.mp4',
      serverReferenceVideoFilename: 'gJB_sBM_c01_d07_mJB3_ch03.mp4',
      artist: 'BTS(방탄소년단)',
      durationSeconds: 22,
    ),
    DanceVideo(
      id: '5',
      title: 'CRAZY',
      genre: 'LE SSERAFIM',
      difficulty: '중급',
      thumbnailUrl: 'video_data/card5/maxresdefault (1).jpg',
      videoUrl: 'video_data/card5/gMH_sBM_c01_d24_mMH3_ch03_480.mp4',
      referenceJson: '20260521_155225_a8cc4d5b.json',
      serverVideoFilename: 'gMH_sBM_c01_d24_mMH3_ch03.mp4',
      serverReferenceVideoFilename: 'gMH_sBM_c01_d24_mMH3_ch03.mp4',
      artist: 'LE SSERAFIM (르세라핌)',
      durationSeconds: 22,
    ),
  ];

  Future<List<DanceVideo>> fetchVideos() async {
    await Future.delayed(const Duration(milliseconds: 800));
    return List<DanceVideo>.from(challenges);
  }
}
