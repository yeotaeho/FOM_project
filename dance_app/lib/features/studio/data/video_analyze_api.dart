import 'dart:convert';

import 'package:cross_file/cross_file.dart';
import 'package:http/http.dart' as http;

import '../../../core/config/api_config.dart';
import 'reference_json_assets.dart';
import 'video_analyze_models.dart';

class VideoAnalyzeApiException implements Exception {
  final String message;
  final int? statusCode;

  const VideoAnalyzeApiException(this.message, {this.statusCode});

  @override
  String toString() => message;
}

class VideoAnalyzeApi {
  static Future<void> _attachReferenceJsonFile(
    http.MultipartRequest request, {
    required String referenceJson,
    required String referenceJsonAsset,
  }) async {
    request.fields['reference_json'] = referenceJson;
    final bytes = await ReferenceJsonAssets.loadBytes(referenceJsonAsset);
    if (bytes == null || bytes.isEmpty) {
      throw VideoAnalyzeApiException(
        '레퍼런스 JSON asset을 찾을 수 없습니다: $referenceJsonAsset\n'
        'dance_app/video_data/cardN/ 에 파일을 추가했는지 확인하세요.',
      );
    }
    request.files.add(
      http.MultipartFile.fromBytes(
        'reference_json_file',
        bytes,
        filename: referenceJson,
      ),
    );
  }

  /// 실패 시 [VideoAnalyzeApiException] (URL·원인 포함).
  static Future<void> ensureBackendReachable() async {
    final url = ApiConfig.healthUrl;
    try {
      final res = await http.get(Uri.parse(url)).timeout(const Duration(seconds: 8));
      if (res.statusCode != 200) {
        throw VideoAnalyzeApiException(
          'backend1 헬스 체크 실패 (HTTP ${res.statusCode})\n'
          'GET $url',
          statusCode: res.statusCode,
        );
      }
      final body = jsonDecode(res.body) as Map<String, dynamic>;
      if (body['status'] != 'ok') {
        throw VideoAnalyzeApiException('backend1 응답 이상: $body\nGET $url');
      }
    } on VideoAnalyzeApiException {
      rethrow;
    } catch (e) {
      throw VideoAnalyzeApiException(
        'backend1 서버에 연결할 수 없습니다.\n'
        'GET $url\n'
        '• PC와 폰이 같은 Wi‑Fi인지 확인\n'
        '• PC IP: ipconfig → IPv4 (예: 192.168.0.31)\n'
        '• 서버: cd backend1 && uvicorn main:app --host 0.0.0.0 --port 8000\n'
        '• Windows 방화벽에서 Python/8000 허용\n'
        '• 실행: flutter run -d <기기> --dart-define=API_BASE_URL=http://<PC_IP>:8000\n'
        '원인: $e',
      );
    }
  }

  /// 로컬 mp4 → POST /video/analyze (user_video + reference_json).
  static Future<VideoAnalyzeResult> analyzeVideo({
    required String userVideoPath,
    required String referenceJson,
    required String referenceJsonAsset,
    required String expertVideoDisplayUrl,
    String? referenceVideoFilename,
    String? userAssetVideoUrl,
    bool autoDetectStart = true,
  }) async {
    List<int> bytes;
    try {
      bytes = await XFile(userVideoPath).readAsBytes();
    } catch (e) {
      throw VideoAnalyzeApiException('영상 파일을 읽을 수 없습니다: $e');
    }
    if (bytes.isEmpty) {
      throw VideoAnalyzeApiException('영상 파일이 비어 있습니다.');
    }

    final uri = Uri.parse(ApiConfig.videoAnalyzeUrl);
    final request = http.MultipartRequest('POST', uri)
      ..fields['alignment_method'] = 'time'
      ..fields['auto_detect_start'] = autoDetectStart ? 'true' : 'false'
      ..fields['extraction_mode'] = 'full'
      ..fields['target_fps'] = '15';
    await _attachReferenceJsonFile(
      request,
      referenceJson: referenceJson,
      referenceJsonAsset: referenceJsonAsset,
    );
    if (referenceVideoFilename != null && referenceVideoFilename.isNotEmpty) {
      request.fields['reference_video_filename'] = referenceVideoFilename;
    }
    request.files.add(
      http.MultipartFile.fromBytes(
        'user_video',
        bytes,
        filename: 'user.mp4',
      ),
    );

    final streamed = await request.send().timeout(const Duration(minutes: 20));
    final body = await http.Response.fromStream(streamed);

    if (body.statusCode != 200) {
      String detail = body.body;
      try {
        final err = jsonDecode(body.body);
        if (err is Map<String, dynamic>) {
          detail = err['detail']?.toString() ?? body.body;
        }
      } catch (_) {}
      throw VideoAnalyzeApiException(
        detail,
        statusCode: body.statusCode,
      );
    }

    final json = jsonDecode(body.body) as Map<String, dynamic>;
    return VideoAnalyzeResult.fromJson(
      json,
      expertVideoDisplayUrl: expertVideoDisplayUrl,
      userAssetVideoUrl: userAssetVideoUrl,
    );
  }

  /// [개발] 서버 `video_data/` MP4 + reference_json (`POST /video/analyze/by-name`).
  static Future<VideoAnalyzeResult> analyzeServerDevVideo({
    required String userVideoFilename,
    required String referenceJson,
    required String referenceJsonAsset,
    required String expertVideoDisplayUrl,
    String? referenceVideoFilename,
    String? userAssetVideoUrl,
    bool autoDetectStart = true,
  }) async {
    final uri = Uri.parse(ApiConfig.videoAnalyzeByNameUrl);
    final refVideo = referenceVideoFilename ?? userVideoFilename;
    final request = http.MultipartRequest('POST', uri)
      ..fields['user_video_filename'] = userVideoFilename
      ..fields['reference_video_filename'] = refVideo
      ..fields['alignment_method'] = 'time'
      ..fields['auto_detect_start'] = autoDetectStart ? 'true' : 'false'
      ..fields['extraction_mode'] = 'full'
      ..fields['target_fps'] = '15';
    await _attachReferenceJsonFile(
      request,
      referenceJson: referenceJson,
      referenceJsonAsset: referenceJsonAsset,
    );

    final streamed = await request.send().timeout(const Duration(minutes: 20));
    final body = await http.Response.fromStream(streamed);

    if (body.statusCode != 200) {
      String detail = body.body;
      try {
        final err = jsonDecode(body.body);
        if (err is Map<String, dynamic>) {
          detail = err['detail']?.toString() ?? body.body;
        }
      } catch (_) {}
      throw VideoAnalyzeApiException(
        detail,
        statusCode: body.statusCode,
      );
    }

    final json = jsonDecode(body.body) as Map<String, dynamic>;
    return VideoAnalyzeResult.fromJson(
      json,
      expertVideoDisplayUrl: expertVideoDisplayUrl,
      userServerVideoFilename: userVideoFilename,
      userAssetVideoUrl: userAssetVideoUrl,
    );
  }

  /// LLM 피드백 생성 (POST /video/analyze/feedback).
  static Future<Map<String, dynamic>> generateFeedback({
    required String userJson,
    required String referenceJson,
    String alignmentMethod = 'dtw',
    bool autoDetectStart = true,
  }) async {
    final uri = Uri.parse('${ApiConfig.baseUrl}/video/analyze/feedback');
    final request = http.MultipartRequest('POST', uri)
      ..fields['user_json'] = userJson
      ..fields['reference_json'] = referenceJson
      ..fields['alignment_method'] = alignmentMethod
      ..fields['auto_detect_start'] = autoDetectStart ? 'true' : 'false'
      ..fields['enable_accuracy'] = 'true'
      ..fields['enable_rom'] = 'true'
      ..fields['enable_creativity'] = 'true'
      ..fields['enable_isolation'] = 'true'
      ..fields['enable_power'] = 'true'
      ..fields['enable_rhythm'] = 'true';

    final streamed = await request.send().timeout(const Duration(minutes: 2));
    final body = await http.Response.fromStream(streamed);

    if (body.statusCode != 200) {
      String detail = body.body;
      try {
        final err = jsonDecode(body.body);
        if (err is Map<String, dynamic>) {
          detail = err['detail']?.toString() ?? body.body;
        }
      } catch (_) {}
      throw VideoAnalyzeApiException(
        detail,
        statusCode: body.statusCode,
      );
    }

    final json = jsonDecode(body.body) as Map<String, dynamic>;
    return json['feedback'] as Map<String, dynamic>? ?? {};
  }
}
