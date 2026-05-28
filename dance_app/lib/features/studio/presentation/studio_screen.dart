import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:video_player/video_player.dart';
import '../../../core/config/api_config.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/video/synced_video_playback.dart';
import '../../../shared/video/video_source.dart';
import '../../../shared/widgets/card_video_preview.dart';
import '../../home/data/home_repository.dart';
import '../data/compare_session.dart';
import '../data/studio_providers.dart';

class StudioScreen extends ConsumerWidget {
  const StudioScreen({super.key});

  void _openRecord(BuildContext context, WidgetRef ref) {
    final challenge = ref.read(selectedChallengeProvider);
    if (challenge == null || challenge.videoUrl.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('홈에서 챌린지를 먼저 선택해 주세요')),
      );
      return;
    }
    ref.read(userVideoPathProvider.notifier).state = null;
    ref.read(compareSessionProvider.notifier).state = null;
    context.push('/studio/record');
  }

  void _startAnalyze(BuildContext context, WidgetRef ref) {
    final selected = ref.read(selectedChallengeProvider);
    if (selected == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('홈에서 챌린지를 먼저 선택해 주세요')),
      );
      return;
    }
    if (ApiConfig.useDevServerUserVideo) {
      final session = CompareSession.devServer(selected);
      ref.read(compareSessionProvider.notifier).state = session;
      context.go('/loading', extra: session);
      return;
    }
    final path = ref.read(userVideoPathProvider);
    if (path == null || path.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('먼저 따라하며 촬영을 완료해 주세요')),
      );
      return;
    }
    final session = CompareSession.fromChallenge(
      selected,
      userVideoPath: path,
    );
    ref.read(compareSessionProvider.notifier).state = session;
    context.go('/loading', extra: session);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final challenge = ref.watch(selectedChallengeProvider);
    final userVideoPath = ref.watch(userVideoPathProvider);
    final hasRecording = userVideoPath != null && userVideoPath.isNotEmpty;
    final recordedPath = userVideoPath;

    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: hasRecording && challenge != null && recordedPath != null
            ? _SyncedCompareReview(
                challenge: challenge,
                userVideoPath: recordedPath,
                onRetake: () {
                  ref.read(userVideoPathProvider.notifier).state = null;
                  ref.read(compareSessionProvider.notifier).state = null;
                  _openRecord(context, ref);
                },
                onAnalyze: () => _startAnalyze(context, ref),
              )
            : Column(
                children: [
                  Expanded(
                    flex: 3,
                    child: _ReferencePanel(challenge: challenge),
                  ),
                  Container(
                    height: 1,
                    margin: const EdgeInsets.symmetric(horizontal: 24),
                    decoration: BoxDecoration(
                      gradient: const LinearGradient(
                        colors: [AppColors.neonGreen, AppColors.neonPurple],
                      ),
                      borderRadius: BorderRadius.circular(1),
                    ),
                  ),
                  Expanded(
                    flex: 4,
                    child: _CapturePanel(
                      challenge: challenge,
                      userVideoPath: userVideoPath,
                      hasRecording: hasRecording,
                      onStartRecord: () => _openRecord(context, ref),
                      onRetake: () {
                        ref.read(userVideoPathProvider.notifier).state = null;
                        ref.read(compareSessionProvider.notifier).state = null;
                        _openRecord(context, ref);
                      },
                      onAnalyze: () => _startAnalyze(context, ref),
                    ),
                  ),
                ],
              ),
      ),
    );
  }
}

class _SyncedCompareReview extends StatefulWidget {
  final DanceVideo challenge;
  final String userVideoPath;
  final VoidCallback onRetake;
  final VoidCallback onAnalyze;

  const _SyncedCompareReview({
    required this.challenge,
    required this.userVideoPath,
    required this.onRetake,
    required this.onAnalyze,
  });

  @override
  State<_SyncedCompareReview> createState() => _SyncedCompareReviewState();
}

class _SyncedCompareReviewState extends State<_SyncedCompareReview> {
  VideoPlayerController? _reference;
  VideoPlayerController? _user;
  String? _error;

  @override
  void initState() {
    super.initState();
    _initPlayback();
  }

  Future<void> _initPlayback() async {
    final refController = videoControllerFromPath(widget.challenge.videoUrl);
    final userController = videoControllerFromPath(widget.userVideoPath);

    try {
      await Future.wait([
        refController.initialize(),
        userController.initialize(),
      ]);
      await prepareMutedVideo(refController, loop: true);
      await prepareMutedVideo(userController, loop: true);

      if (!mounted) {
        refController.dispose();
        userController.dispose();
        return;
      }

      setState(() {
        _reference = refController;
        _user = userController;
      });

      await playReferenceThenUser(
        reference: refController,
        user: userController,
      );
    } catch (e) {
      refController.dispose();
      userController.dispose();
      if (mounted) setState(() => _error = e.toString());
    }
  }

  @override
  void dispose() {
    _reference?.dispose();
    _user?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text('영상 재생 오류: $_error', textAlign: TextAlign.center),
        ),
      );
    }

    final refReady = _reference?.value.isInitialized ?? false;
    final userReady = _user?.value.isInitialized ?? false;

    return Column(
      children: [
        Expanded(
          flex: 3,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      width: 8,
                      height: 8,
                      decoration: const BoxDecoration(
                        color: AppColors.neonGreen,
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text('레퍼런스', style: Theme.of(context).textTheme.labelSmall),
                  ],
                ),
                const SizedBox(height: 12),
                Expanded(
                  child: _SyncedVideoPane(
                    controller: _reference,
                    ready: refReady,
                    caption: '${widget.challenge.title} — 전문가 영상',
                    captionColor: AppColors.neonGreen,
                  ),
                ),
              ],
            ),
          ),
        ),
        Container(
          height: 1,
          margin: const EdgeInsets.symmetric(horizontal: 24),
          decoration: BoxDecoration(
            gradient: const LinearGradient(
              colors: [AppColors.neonGreen, AppColors.neonPurple],
            ),
            borderRadius: BorderRadius.circular(1),
          ),
        ),
        Expanded(
          flex: 4,
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('내 영상', style: Theme.of(context).textTheme.labelSmall),
                const SizedBox(height: 8),
                Text(
                  '',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 12),
                Expanded(
                  child: _SyncedVideoPane(
                    controller: _user,
                    ready: userReady,
                    caption: '내 촬영 영상',
                    captionColor: AppColors.neonBlue,
                  ),
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton(
                        onPressed: widget.onRetake,
                        style: OutlinedButton.styleFrom(
                          foregroundColor: AppColors.textSecondary,
                          side: const BorderSide(color: AppColors.divider),
                          padding: const EdgeInsets.symmetric(vertical: 14),
                        ),
                        child: const Text('다시 촬영'),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      flex: 2,
                      child: ElevatedButton(
                        onPressed: widget.onAnalyze,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppColors.neonGreen,
                          foregroundColor: Colors.black,
                          padding: const EdgeInsets.symmetric(vertical: 14),
                        ),
                        child: const Text(
                          '비교 분석 시작',
                          style: TextStyle(fontWeight: FontWeight.w800),
                        ),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _SyncedVideoPane extends StatelessWidget {
  final VideoPlayerController? controller;
  final bool ready;
  final String caption;
  final Color captionColor;

  const _SyncedVideoPane({
    required this.controller,
    required this.ready,
    required this.caption,
    required this.captionColor,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(14),
        color: AppColors.card,
        border: Border.all(color: captionColor.withValues(alpha: 0.3)),
      ),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        fit: StackFit.expand,
        children: [
          if (ready && controller != null)
            FittedBox(
              fit: BoxFit.cover,
              clipBehavior: Clip.hardEdge,
              child: SizedBox(
                width: controller!.value.size.width,
                height: controller!.value.size.height,
                child: VideoPlayer(controller!),
              ),
            )
          else
            const Center(
              child: CircularProgressIndicator(
                color: AppColors.neonGreen,
                strokeWidth: 2,
              ),
            ),
          Positioned(
            bottom: 12,
            left: 12,
            right: 12,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                color: Colors.black.withValues(alpha: 0.6),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                caption,
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: captionColor,
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ReferencePanel extends StatelessWidget {
  final DanceVideo? challenge;

  const _ReferencePanel({required this.challenge});

  @override
  Widget build(BuildContext context) {
    final title = challenge?.title ?? '챌린지를 선택해 주세요';
    final videoUrl = challenge?.videoUrl ?? '';

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 8,
                height: 8,
                decoration: const BoxDecoration(
                  color: AppColors.neonGreen,
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: 8),
              Text('레퍼런스', style: Theme.of(context).textTheme.labelSmall),
            ],
          ),
          const SizedBox(height: 12),
          Expanded(
            child: Container(
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(14),
                color: AppColors.card,
                border: Border.all(color: AppColors.neonPurple.withValues(alpha: 0.3)),
              ),
              clipBehavior: Clip.antiAlias,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  if (videoUrl.isNotEmpty)
                    CardVideoPreview(
                      videoUrl: videoUrl,
                      height: null,
                      borderRadius: BorderRadius.circular(14),
                    )
                  else
                    Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            Icons.touch_app_rounded,
                            color: AppColors.textSecondary.withValues(alpha: 0.6),
                            size: 40,
                          ),
                          const SizedBox(height: 8),
                          Text(
                            '홈에서 카드를 선택하세요',
                            style: Theme.of(context).textTheme.bodyMedium,
                          ),
                        ],
                      ),
                    ),
                  Positioned(
                    bottom: 12,
                    left: 12,
                    right: 12,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                      decoration: BoxDecoration(
                        color: Colors.black.withValues(alpha: 0.6),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        videoUrl.isEmpty ? title : '$title — 전문가 영상',
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          color: AppColors.neonGreen,
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _CapturePanel extends StatelessWidget {
  final DanceVideo? challenge;
  final String? userVideoPath;
  final bool hasRecording;
  final VoidCallback onStartRecord;
  final VoidCallback onRetake;
  final VoidCallback onAnalyze;

  const _CapturePanel({
    required this.challenge,
    required this.userVideoPath,
    required this.hasRecording,
    required this.onStartRecord,
    required this.onRetake,
    required this.onAnalyze,
  });

  @override
  Widget build(BuildContext context) {
    final canRecord = challenge != null && challenge!.videoUrl.isNotEmpty;

    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('내 영상', style: Theme.of(context).textTheme.labelSmall),
          const SizedBox(height: 8),
          Text(
            '레퍼런스와 동시에 재생되며, 영상이 끝나면 촬영이 자동 종료됩니다.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 12),
          Expanded(
            child: hasRecording
                ? _RecordedPreview(
                    userPath: userVideoPath!,
                    referencePath: challenge?.videoUrl ?? '',
                    onRetake: onRetake,
                    onAnalyze: onAnalyze,
                  )
                : Center(
                    child: _ActionButton(
                      icon: Icons.videocam_rounded,
                      label: '따라하며 촬영하기',
                      subtitle: '레퍼런스와 동시 녹화',
                      color: AppColors.neonPurple,
                      enabled: canRecord,
                      onTap: canRecord ? onStartRecord : null,
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}

class _RecordedPreview extends StatelessWidget {
  final String userPath;
  final String referencePath;
  final VoidCallback onRetake;
  final VoidCallback onAnalyze;

  const _RecordedPreview({
    required this.userPath,
    required this.referencePath,
    required this.onRetake,
    required this.onAnalyze,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Expanded(
          child: _LabeledPreview(
            label: '내 촬영 영상',
            videoUrl: userPath,
          ),
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: onRetake,
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.textSecondary,
                  side: const BorderSide(color: AppColors.divider),
                  padding: const EdgeInsets.symmetric(vertical: 14),
                ),
                child: const Text('다시 촬영'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              flex: 2,
              child: ElevatedButton(
                onPressed: onAnalyze,
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.neonGreen,
                  foregroundColor: Colors.black,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                ),
                child: const Text(
                  '비교 분석 시작',
                  style: TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _LabeledPreview extends StatelessWidget {
  final String label;
  final String videoUrl;

  const _LabeledPreview({required this.label, required this.videoUrl});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(label, style: Theme.of(context).textTheme.labelSmall),
        const SizedBox(height: 4),
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: CardVideoPreview(
              videoUrl: videoUrl,
              height: null,
              borderRadius: BorderRadius.circular(12),
            ),
          ),
        ),
      ],
    );
  }
}

class _ActionButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final String subtitle;
  final Color color;
  final bool enabled;
  final VoidCallback? onTap;

  const _ActionButton({
    required this.icon,
    required this.label,
    required this.subtitle,
    required this.color,
    this.enabled = true,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final effectiveColor = enabled ? color : AppColors.textSecondary;

    return GestureDetector(
      onTap: enabled ? onTap : null,
      child: Opacity(
        opacity: enabled ? 1 : 0.45,
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
          decoration: BoxDecoration(
            color: effectiveColor.withValues(alpha: 0.08),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: effectiveColor.withValues(alpha: 0.4), width: 1.5),
          ),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: effectiveColor.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(icon, color: effectiveColor, size: 28),
              ),
              const SizedBox(width: 16),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    label,
                    style: TextStyle(
                      color: effectiveColor,
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  Text(
                    subtitle,
                    style: const TextStyle(
                      color: AppColors.textSecondary,
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
              const Spacer(),
              Icon(Icons.arrow_forward_ios_rounded, color: effectiveColor, size: 18),
            ],
          ),
        ),
      ),
    );
  }
}
