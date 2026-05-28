import 'dart:convert';

import 'package:cross_file/cross_file.dart';
import 'package:http/http.dart' as http;

import '../../../core/config/api_config.dart';
import 'isolation_models.dart';

class IsolationApiException implements Exception {
  final String message;
  final int? statusCode;

  const IsolationApiException(this.message, {this.statusCode});

  @override
  String toString() => message;
}

class IsolationApi {
  static Future<bool> checkReady() async {
    try {
      final res = await http
          .get(Uri.parse(ApiConfig.isolationReadyUrl))
          .timeout(const Duration(seconds: 8));
      if (res.statusCode != 200) return false;
      final body = jsonDecode(res.body) as Map<String, dynamic>;
      return body['ready'] == true;
    } catch (_) {
      return false;
    }
  }

  /// 로컬 mp4 경로 → POST /isolation/analyze (dart:io 미사용 — Windows/Web 호환)
  static Future<IsolationAnalyzeResult> analyzeVideo(
    String videoPath, {
    bool autoDetectStart = true,
  }) async {
    List<int> bytes;
    try {
      bytes = await XFile(videoPath).readAsBytes();
    } catch (e) {
      throw IsolationApiException('영상 파일을 읽을 수 없습니다: $e');
    }
    if (bytes.isEmpty) {
      throw IsolationApiException('영상 파일이 비어 있습니다.');
    }

    final uri = Uri.parse(ApiConfig.isolationAnalyzeUrl);
    final request = http.MultipartRequest('POST', uri)
      ..fields['auto_detect_start'] = autoDetectStart ? 'true' : 'false'
      ..fields['user_offset_sec'] = '0'
      ..fields['ref_offset_sec'] = '0'
      ..files.add(
        http.MultipartFile.fromBytes(
          'user_video',
          bytes,
          filename: 'user.mp4',
        ),
      );

    final streamed = await request.send().timeout(const Duration(minutes: 15));
    final body = await http.Response.fromStream(streamed);

    if (body.statusCode != 200) {
      String detail = body.body;
      try {
        final err = jsonDecode(body.body) as Map<String, dynamic>;
        detail = err['detail']?.toString() ?? body.body;
      } catch (_) {}
      throw IsolationApiException(
        detail,
        statusCode: body.statusCode,
      );
    }

    final json = jsonDecode(body.body) as Map<String, dynamic>;
    return IsolationAnalyzeResult.fromJson(json);
  }
}
