import 'dart:io';

import 'package:video_player/video_player.dart';

/// 여러 비디오 동시 재생을 허용하는 옵션
final _multiVideoOptions = VideoPlayerOptions(mixWithOthers: true);

VideoPlayerController videoControllerFromPath(String path) {
  final normalized =
      path.startsWith('file://') ? path.replaceFirst('file://', '') : path;
  if (normalized.startsWith('http://') || normalized.startsWith('https://')) {
    return VideoPlayerController.networkUrl(
      Uri.parse(normalized),
      videoPlayerOptions: _multiVideoOptions,
    );
  }
  if (normalized.startsWith('video_data/')) {
    return VideoPlayerController.asset(
      normalized,
      videoPlayerOptions: _multiVideoOptions,
    );
  }
  return VideoPlayerController.file(
    File(normalized),
    videoPlayerOptions: _multiVideoOptions,
  );
}
