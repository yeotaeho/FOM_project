/// 앱 내 영상 재생·촬영 해상도 설정.
class VideoConfig {
  /// Flutter asset / 미리보기 재생용 최대 세로 해상도 (480p).
  static const int previewMaxHeight = 480;

  /// 16:9 기준 480p 가로 해상도.
  static const int previewMaxWidth = 854;

  /// `video_data/.../foo.mp4` → `video_data/.../foo_480.mp4`
  static String previewAssetPath(String assetPath) {
    if (assetPath.contains('_480.')) return assetPath;
    final dot = assetPath.lastIndexOf('.');
    if (dot < 0) return assetPath;
    return '${assetPath.substring(0, dot)}_480${assetPath.substring(dot)}';
  }
}
