import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:video_player/video_player.dart';

/// 레퍼런스 대비 사용자 영상 시작 지연.
const Duration kUserVideoStartDelay = Duration(milliseconds: 200);

Future<void> prepareMutedVideo(
  VideoPlayerController controller, {
  bool loop = false,
}) async {
  await controller.setVolume(0);
  await controller.setLooping(loop);
  await controller.pause();
}

/// 전문가 [reference]가 실제 재생을 시작할 때까지 대기.
/// isPlaying == true AND position > 0 (실제 프레임 재생 시작)
Future<void> waitUntilReferencePlaying(
  VideoPlayerController reference, {
  Duration timeout = const Duration(seconds: 3),
}) async {
  if (reference.value.isPlaying && reference.value.position > Duration.zero) {
    return;
  }

  final completer = Completer<void>();
  late VoidCallback listener;
  Timer? timeoutTimer;

  void cleanup() {
    reference.removeListener(listener);
    timeoutTimer?.cancel();
  }

  listener = () {
    if (reference.value.isPlaying && reference.value.position > Duration.zero) {
      cleanup();
      if (!completer.isCompleted) completer.complete();
    }
  };

  reference.addListener(listener);
  timeoutTimer = Timer(timeout, () {
    cleanup();
    if (!completer.isCompleted) completer.complete();
  });

  await completer.future;
}

/// 전문가 타임라인 [target] + wall-clock [minWallDelay] (재생 시작 기준) 모두 충족까지 대기.
Future<void> waitForReferenceLead({
  required VideoPlayerController reference,
  required DateTime playingStartedAt,
  Duration target = kUserVideoStartDelay,
  Duration timeout = const Duration(seconds: 5),
}) async {
  final deadline = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(deadline)) {
    final wall = DateTime.now().difference(playingStartedAt);
    final pos = reference.value.position;
    if (pos >= target && wall >= target) return;
    await Future.delayed(const Duration(milliseconds: 8));
  }
}

/// 전문가(레퍼런스) 영상을 먼저 재생하고, [userDelay] 경과 후 사용자 영상을 재생합니다.
Future<void> playReferenceThenUser({
  required VideoPlayerController reference,
  VideoPlayerController? user,
  Duration userDelay = kUserVideoStartDelay,
  Duration startTimeout = const Duration(seconds: 3),
}) async {
  if (kDebugMode) {
    debugPrint('[Sync] 시작 - ref=${reference.value.isPlaying}, user=${user?.value.isPlaying}');
  }

  if (user != null && user.value.isInitialized) {
    await user.pause();
    await user.seekTo(Duration.zero);
    if (kDebugMode) {
      debugPrint('[Sync] user 초기화 완료 (pause, pos=0)');
    }
  }
  await reference.pause();
  await reference.seekTo(Duration.zero);

  if (kDebugMode) {
    debugPrint('[Sync] reference.play() 호출');
  }
  await reference.play();
  
  await waitUntilReferencePlaying(reference, timeout: startTimeout);
  final playingStartedAt = DateTime.now();
  if (kDebugMode) {
    debugPrint('[Sync] reference 재생 시작 확인 (isPlaying=true, pos>0)');
  }

  if (user == null || !user.value.isInitialized) return;

  await waitForReferenceLead(
    reference: reference,
    playingStartedAt: playingStartedAt,
    target: userDelay,
  );
  if (kDebugMode) {
    debugPrint('[Sync] 50ms 대기 완료 - ref.pos=${reference.value.position.inMilliseconds}ms');
  }

  if (kDebugMode) {
    debugPrint('[Sync] user.play() 호출');
  }
  await user.play();
  if (kDebugMode) {
    debugPrint('[Sync] 완료 - ref=${reference.value.isPlaying}, user=${user.value.isPlaying}');
  }
}
