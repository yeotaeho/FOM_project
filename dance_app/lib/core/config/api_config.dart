import 'package:flutter/foundation.dart';

/// backend1 FastAPI (`uvicorn main:app --reload --host 0.0.0.0 --port 8000`)
///
/// 실기기(폰)는 PC와 같은 Wi‑Fi + PC IP 필수:
/// `flutter run --dart-define=API_BASE_URL=http://192.168.x.x:8000`
///
/// 고정 데이터셋: backend1/metrics/docs/DEV_VIDEO_DATASET.md
class ApiConfig {
  /// Debug 기본 true → 촬영 없이 서버 MP4로 `POST /video/analyze/by-name`.
  static bool get useDevServerUserVideo {
    const flag = String.fromEnvironment('USE_DEV_SERVER_VIDEO');
    if (flag == 'true') return true;
    if (flag == 'false') return false;
    return kDebugMode;
  }

  static String get baseUrl {
    const fromEnv = String.fromEnvironment('API_BASE_URL');
    if (fromEnv.isNotEmpty) return fromEnv;

    if (kIsWeb) return 'http://127.0.0.1:8000';

    if (defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:8000';
    }

    return 'http://127.0.0.1:8000';
  }

  /// `GET /video/data/{filename}` — domain1/video_data/ MP4 (공백·괄호 URL 인코딩).
  static String videoDataUrl(String filename) {
    final base = baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl;
    return '$base/video/data/${Uri.encodeComponent(filename)}';
  }

  static String get videoAnalyzeUrl => '$baseUrl/video/analyze';
  static String get videoAnalyzeByNameUrl => '$baseUrl/video/analyze/by-name';
  static String get healthUrl => '$baseUrl/health';
  static String get isolationAnalyzeUrl => '$baseUrl/isolation/analyze';
  static String get isolationReadyUrl => '$baseUrl/isolation/ready';

  /// API 응답 `url` 필드(`/video/data/...`) → 재생 가능한 절대 URL.
  static String? resolvePlaybackUrl(String? pathOrUrl) {
    if (pathOrUrl == null || pathOrUrl.isEmpty) return null;
    if (pathOrUrl.startsWith('http://') || pathOrUrl.startsWith('https://')) {
      return pathOrUrl;
    }
    if (pathOrUrl.startsWith('/')) {
      return '$baseUrl$pathOrUrl';
    }
    return videoDataUrl(pathOrUrl);
  }

  static String get platformHint {
    if (kIsWeb) return 'Web → localhost';
    if (defaultTargetPlatform == TargetPlatform.android) {
      return 'Android: 에뮬레이터=10.0.2.2, 실기기=PC IP (--dart-define)';
    }
    return 'Desktop/Simulator → 127.0.0.1';
  }
}
