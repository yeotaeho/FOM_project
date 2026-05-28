import 'dart:async';

import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:video_player/video_player.dart';

import '../../../core/config/api_config.dart';
import '../../../core/theme/app_theme.dart';
import '../../home/data/home_repository.dart';
import '../../../shared/video/synced_video_playback.dart';
import '../../../shared/video/video_source.dart';
import '../data/compare_session.dart';
import '../data/studio_providers.dart';

enum _RecordPhase { initializing, ready, countdown, recording, finishing, error }

class StudioRecordScreen extends ConsumerStatefulWidget {
  const StudioRecordScreen({super.key});

  @override
  ConsumerState<StudioRecordScreen> createState() => _StudioRecordScreenState();
}

class _StudioRecordScreenState extends ConsumerState<StudioRecordScreen> {
  CameraController? _camera;
  VideoPlayerController? _reference;
  /// Debug·에뮬: 카메라 대신 서버 `video_data/` 사용자 MP4 미리보기.
  VideoPlayerController? _userSubstitute;
  bool _useDevServerUserVideo = false;
  _RecordPhase _phase = _RecordPhase.initializing;
  String? _errorMessage;
  bool _isRecording = false;
  int _countdown = 0;
  bool _stopRequested = false;
  Timer? _endWatchTimer;

  @override
  void initState() {
    super.initState();
    _setup();
  }

  Future<void> _setup() async {
    final challenge = ref.read(selectedChallengeProvider);
    if (challenge == null || challenge.videoUrl.isEmpty) {
      setState(() {
        _phase = _RecordPhase.error;
        _errorMessage = '홈에서 챌린지를 먼저 선택해 주세요.';
      });
      return;
    }

    try {
      final refController = videoControllerFromPath(challenge.videoUrl);
      _useDevServerUserVideo = ApiConfig.useDevServerUserVideo &&
          challenge.serverVideoFilename.isNotEmpty;

      if (_useDevServerUserVideo) {
        await refController.initialize();
        await prepareMutedVideo(refController, loop: false);

        final userController = await _initDevUserPreview(challenge);

        if (!mounted) {
          refController.dispose();
          userController?.dispose();
          return;
        }

        setState(() {
          _reference = refController;
          _userSubstitute = userController;
          _phase = _RecordPhase.ready;
        });
        if (kDebugMode) {
          debugPrint('[REC Setup] ready - ref.isPlaying=${refController.value.isPlaying}, user.isPlaying=${userController?.value.isPlaying}');
        }
        return;
      }

      final cameras = await availableCameras();
      if (cameras.isEmpty) {
        throw StateError('사용 가능한 카메라가 없습니다.');
      }

      final camera = cameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.front,
        orElse: () => cameras.first,
      );

      final cameraController = CameraController(
        camera,
        ResolutionPreset.low,
        enableAudio: false,
      );

      await Future.wait([
        cameraController.initialize(),
        refController.initialize(),
      ]);

      await prepareMutedVideo(refController, loop: false);

      if (!mounted) {
        await cameraController.dispose();
        refController.dispose();
        return;
      }

      setState(() {
        _camera = cameraController;
        _reference = refController;
        _phase = _RecordPhase.ready;
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _phase = _RecordPhase.error;
          _errorMessage = e.toString();
        });
      }
    }
  }

  Future<VideoPlayerController?> _initDevUserPreview(DanceVideo challenge) async {
    final slash = challenge.videoUrl.lastIndexOf('/');
    final dir = slash >= 0 ? challenge.videoUrl.substring(0, slash + 1) : '';
    final candidates = <String>[
      if (challenge.userPreviewAsset.isNotEmpty) challenge.userPreviewAsset,
      if (dir.isNotEmpty) '${dir}card${challenge.id}_user.mp4',
      if (challenge.serverVideoFilename.isNotEmpty)
        ApiConfig.videoDataUrl(challenge.serverVideoFilename),
    ];

    for (final path in candidates) {
      VideoPlayerController? controller;
      try {
        controller = videoControllerFromPath(path);
        await controller.initialize();
        await prepareMutedVideo(controller, loop: false);
        await controller.seekTo(Duration.zero);
        return controller;
      } catch (e) {
        debugPrint('user preview init 실패 ($path): $e');
        controller?.dispose();
      }
    }
    return null;
  }

  Future<void> _beginCountdown() async {
    if (_phase != _RecordPhase.ready || _reference == null) return;
    if (!_useDevServerUserVideo && _camera == null) return;

    setState(() {
      _phase = _RecordPhase.countdown;
      _countdown = 3;
    });

    for (var i = 3; i >= 1; i--) {
      if (!mounted) return;
      setState(() => _countdown = i);
      await Future.delayed(const Duration(seconds: 1));
    }

    if (!mounted) return;
    await _startSyncedCapture();
  }

  Future<void> _startSyncedCapture() async {
    final camera = _camera;
    final reference = _reference;
    final userSubstitute = _userSubstitute;
    if (reference == null || !reference.value.isInitialized) return;

    if (kDebugMode) {
      debugPrint('[REC Capture 시작] ref.isPlaying=${reference.value.isPlaying}, user.isPlaying=${userSubstitute?.value.isPlaying}');
    }

    if (_useDevServerUserVideo) {
      // 사용자 VideoPlayer는 ready 단계에서 미리 마운트(2번 화면과 동일). 재생만 REC 시 시작.
    } else if (camera == null || !camera.value.isInitialized) {
      return;
    }

    _stopEndWatch();
    await reference.pause();
    await reference.seekTo(Duration.zero);
    await userSubstitute?.pause();
    await userSubstitute?.seekTo(Duration.zero);

    setState(() {
      _phase = _RecordPhase.recording;
      _isRecording = true;
      _stopRequested = false;
    });
    await Future<void>.delayed(Duration.zero);

    _startEndWatch();

    if (_useDevServerUserVideo) {
      try {
        await playReferenceThenUser(
          reference: reference,
          user: userSubstitute,
        );
      } catch (e) {
        debugPrint('synced playback 실패: $e');
      }
      return;
    }

    await reference.play();
    await waitUntilReferencePlaying(reference);
    final playingStartedAt = DateTime.now();
    await waitForReferenceLead(
      reference: reference,
      playingStartedAt: playingStartedAt,
    );
    await camera!.startVideoRecording();
  }

  void _startEndWatch() {
    _stopEndWatch();
    _endWatchTimer = Timer.periodic(const Duration(milliseconds: 100), (_) {
      _checkReferenceEnd();
    });
  }

  void _stopEndWatch() {
    _endWatchTimer?.cancel();
    _endWatchTimer = null;
  }

  void _checkReferenceEnd() {
    if (!_isRecording || _stopRequested) return;

    final reference = _reference;
    if (reference == null || !reference.value.isInitialized) return;

    final duration = reference.value.duration;
    if (duration == Duration.zero) return;

    final position = reference.value.position;
    if (position >= duration - const Duration(milliseconds: 50)) {
      _stopSyncedCapture();
    }
  }

  Future<void> _stopSyncedCapture() async {
    if (_stopRequested) return;
    _stopRequested = true;

    final camera = _camera;
    final reference = _reference;
    final userSubstitute = _userSubstitute;

    setState(() => _phase = _RecordPhase.finishing);

    _stopEndWatch();
    await reference?.pause();
    await userSubstitute?.pause();

    if (_useDevServerUserVideo) {
      await _finishDevServerCapture();
      return;
    }

    if (camera == null) return;

    XFile? recorded;
    try {
      if (camera.value.isRecordingVideo) {
        recorded = await camera.stopVideoRecording();
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _phase = _RecordPhase.error;
          _errorMessage = '녹화 저장 실패: $e';
          _isRecording = false;
        });
      }
      return;
    }

    if (!mounted) return;

    final challenge = ref.read(selectedChallengeProvider);
    if (recorded == null || challenge == null) {
      setState(() {
        _phase = _RecordPhase.error;
        _errorMessage = '녹화 파일을 찾을 수 없습니다.';
        _isRecording = false;
      });
      return;
    }

    final session = CompareSession.fromChallenge(
      challenge,
      userVideoPath: recorded.path,
    );

    ref.read(userVideoPathProvider.notifier).state = recorded.path;
    ref.read(compareSessionProvider.notifier).state = session;

    if (!mounted) return;
    context.pop();
  }

  Future<void> _finishDevServerCapture() async {
    final challenge = ref.read(selectedChallengeProvider);
    if (!mounted) return;

    if (challenge == null) {
      setState(() {
        _phase = _RecordPhase.error;
        _errorMessage = '챌린지 정보가 없습니다.';
        _isRecording = false;
      });
      return;
    }

    final previewPath = challenge.userPreviewAsset.isNotEmpty
        ? challenge.userPreviewAsset
        : ApiConfig.videoDataUrl(challenge.serverVideoFilename);
    final session = CompareSession.fromChallenge(
      challenge,
      userVideoPath: previewPath,
      useDevServerVideo: true,
    );

    ref.read(userVideoPathProvider.notifier).state = previewPath;
    ref.read(compareSessionProvider.notifier).state = session;

    if (!mounted) return;
    setState(() => _isRecording = false);
    context.pop();
  }

  @override
  void dispose() {
    _stopEndWatch();
    _camera?.dispose();
    _userSubstitute?.dispose();
    _reference?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final challenge = ref.watch(selectedChallengeProvider);

    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: switch (_phase) {
          _RecordPhase.initializing => const Center(
              child: CircularProgressIndicator(color: AppColors.neonGreen),
            ),
          _RecordPhase.error => _ErrorView(
              message: _errorMessage ?? '알 수 없는 오류',
              onBack: () => context.pop(),
            ),
          _ => _RecordLayout(
              phase: _phase,
              countdown: _countdown,
              isRecording: _isRecording,
              challengeTitle: challenge?.title ?? '',
              useDevServerUserVideo: _useDevServerUserVideo,
              devUserLabel: challenge?.serverVideoFilename ?? '',
              camera: _camera,
              userSubstitute: _userSubstitute,
              reference: _reference,
              onBack: () {
                if (_isRecording) {
                  _stopSyncedCapture();
                } else {
                  context.pop();
                }
              },
              onStart: _beginCountdown,
            ),
        },
      ),
    );
  }
}

class _RecordLayout extends StatelessWidget {
  final _RecordPhase phase;
  final int countdown;
  final bool isRecording;
  final String challengeTitle;
  final bool useDevServerUserVideo;
  final String devUserLabel;
  final CameraController? camera;
  final VideoPlayerController? userSubstitute;
  final VideoPlayerController? reference;
  final VoidCallback onBack;
  final VoidCallback onStart;

  const _RecordLayout({
    required this.phase,
    required this.countdown,
    required this.isRecording,
    required this.challengeTitle,
    required this.useDevServerUserVideo,
    required this.devUserLabel,
    required this.camera,
    required this.userSubstitute,
    required this.reference,
    required this.onBack,
    required this.onStart,
  });

  @override
  Widget build(BuildContext context) {
    final refReady = reference?.value.isInitialized ?? false;
    final camReady = camera?.value.isInitialized ?? false;
    final userReady = userSubstitute?.value.isInitialized ?? false;
    final captureReady = useDevServerUserVideo ? refReady : camReady;

    return Stack(
      children: [
        Column(
          children: [
            _TopBar(
              title: challengeTitle,
              isRecording: isRecording,
              onBack: onBack,
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(16),
                  child: ColoredBox(
                    color: AppColors.card,
                    child: refReady
                        ? _VideoFit(controller: reference!)
                        : const Center(
                            child: CircularProgressIndicator(
                              color: AppColors.neonPurple,
                              strokeWidth: 2,
                            ),
                          ),
                  ),
                ),
              ),
            ),
            if (phase == _RecordPhase.ready)
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
                child: SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: captureReady && refReady ? onStart : null,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppColors.neonGreen,
                      foregroundColor: Colors.black,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                    ),
                    child: const Text(
                      '따라하며 촬영 시작',
                      style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900),
                    ),
                  ),
                ),
              )
            else if (phase == _RecordPhase.finishing)
              const Padding(
                padding: EdgeInsets.only(bottom: 24),
                child: CircularProgressIndicator(color: AppColors.neonGreen),
              )
            else
              const SizedBox(height: 56),
          ],
        ),
        if (captureReady)
          Positioned(
            right: 20,
            bottom: phase == _RecordPhase.ready ? 90 : 80,
            child: Container(
              width: 100,
              height: 150,
              decoration: BoxDecoration(
                color: AppColors.card,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: AppColors.neonGreen, width: 2),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.5),
                    blurRadius: 12,
                    offset: const Offset(0, 4),
                  ),
                ],
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(10),
                child: useDevServerUserVideo
                    ? (userReady
                        ? _VideoFit(controller: userSubstitute!)
                        : _DevUserPlaceholder(label: devUserLabel))
                    : CameraPreview(camera!),
              ),
            ),
          ),
        if (phase == _RecordPhase.countdown)
          _CountdownOverlay(value: countdown),
      ],
    );
  }
}

class _TopBar extends StatelessWidget {
  final String title;
  final bool isRecording;
  final VoidCallback onBack;

  const _TopBar({
    required this.title,
    required this.isRecording,
    required this.onBack,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 8, 16, 8),
      child: Row(
        children: [
          IconButton(
            onPressed: onBack,
            icon: const Icon(Icons.close_rounded, color: Colors.white),
          ),
          Expanded(
            child: Text(
              title.isEmpty ? '따라하며 촬영' : title,
              style: Theme.of(context).textTheme.titleMedium,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          if (isRecording)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: Colors.red.withValues(alpha: 0.85),
                borderRadius: BorderRadius.circular(6),
              ),
              child: const Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.fiber_manual_record, color: Colors.white, size: 10),
                  SizedBox(width: 4),
                  Text(
                    'REC',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 12,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _VideoFit extends StatelessWidget {
  final VideoPlayerController controller;

  const _VideoFit({required this.controller});

  @override
  Widget build(BuildContext context) {
    return RepaintBoundary(
      child: FittedBox(
        fit: BoxFit.cover,
        clipBehavior: Clip.hardEdge,
        child: SizedBox(
          width: controller.value.size.width,
          height: controller.value.size.height,
          child: VideoPlayer(controller),
        ),
      ),
    );
  }
}

class _CountdownOverlay extends StatelessWidget {
  final int value;

  const _CountdownOverlay({required this.value});

  @override
  Widget build(BuildContext context) {
    return Positioned.fill(
      child: Container(
        color: Colors.black54,
        alignment: Alignment.center,
        child: Text(
          '$value',
          style: const TextStyle(
            color: Colors.white,
            fontSize: 96,
            fontWeight: FontWeight.w900,
          ),
        ),
      ),
    );
  }
}

class _DevUserPlaceholder extends StatelessWidget {
  final String label;

  const _DevUserPlaceholder({required this.label});

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: const Color(0xFF1A1A1E),
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.person_outline, color: AppColors.neonBlue, size: 48),
              const SizedBox(height: 8),
              Text(
                label.isEmpty ? '사용자 영상' : label,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  final String message;
  final VoidCallback onBack;

  const _ErrorView({required this.message, required this.onBack});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.error_outline, color: AppColors.error, size: 48),
          const SizedBox(height: 16),
          Text(message, textAlign: TextAlign.center),
          const SizedBox(height: 24),
          ElevatedButton(onPressed: onBack, child: const Text('돌아가기')),
        ],
      ),
    );
  }
}
