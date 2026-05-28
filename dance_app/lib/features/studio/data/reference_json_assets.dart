import 'dart:typed_data';

import 'package:flutter/services.dart' show rootBundle;

/// 카드별 레퍼런스 추출 JSON (`video_data/cardN/*.json`) 로드.
class ReferenceJsonAssets {
  ReferenceJsonAssets._();

  static Future<Uint8List?> loadBytes(String assetPath) async {
    if (assetPath.isEmpty) return null;
    try {
      final data = await rootBundle.load(assetPath);
      return data.buffer.asUint8List();
    } catch (_) {
      return null;
    }
  }
}
