import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

/// Muted looping preview (asset, local file, or network URL).
class CardVideoPreview extends StatefulWidget {
  final String videoUrl;
  /// When null, fills available space from parent constraints.
  final double? height;
  final BorderRadius borderRadius;
  final VoidCallback? onPlaybackFailed;

  const CardVideoPreview({
    super.key,
    required this.videoUrl,
    this.height = 180,
    this.borderRadius = const BorderRadius.vertical(top: Radius.circular(16)),
    this.onPlaybackFailed,
  });

  @override
  State<CardVideoPreview> createState() => _CardVideoPreviewState();
}

class _CardVideoPreviewState extends State<CardVideoPreview> {
  VideoPlayerController? _controller;
  String? _error;
  bool _notifiedFailure = false;
  Timer? _stallTimer;

  @override
  void initState() {
    super.initState();
    _initController();
  }

  @override
  void didUpdateWidget(CardVideoPreview oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.videoUrl != widget.videoUrl) {
      _cancelStallWatch();
      _controller?.dispose();
      _controller = null;
      _error = null;
      _notifiedFailure = false;
      _initController();
    }
  }

  void _cancelStallWatch() {
    _stallTimer?.cancel();
    _stallTimer = null;
  }

  VideoPlayerController _createController(String path) {
    final normalized =
        path.startsWith('file://') ? path.replaceFirst('file://', '') : path;
    if (normalized.startsWith('http://') || normalized.startsWith('https://')) {
      return VideoPlayerController.networkUrl(Uri.parse(normalized));
    }
    if (normalized.startsWith('video_data/')) {
      return VideoPlayerController.asset(normalized);
    }
    return VideoPlayerController.file(File(normalized));
  }

  void _notifyFailure() {
    if (_notifiedFailure || widget.onPlaybackFailed == null) return;
    _notifiedFailure = true;
    widget.onPlaybackFailed!();
  }

  void _startStallWatch(VideoPlayerController controller) {
    _cancelStallWatch();
    final isNetwork = widget.videoUrl.startsWith('http');
    if (!isNetwork || widget.onPlaybackFailed == null) return;

    var samples = 0;
    Duration? lastPos;
    _stallTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      if (!mounted || _controller != controller) {
        _cancelStallWatch();
        return;
      }
      if (!controller.value.isInitialized) return;

      final pos = controller.value.position;
      final playing = controller.value.isPlaying;

      if (!playing && samples >= 2) {
        _cancelStallWatch();
        _notifyFailure();
        return;
      }

      if (lastPos != null && pos > lastPos! + const Duration(milliseconds: 100)) {
        _cancelStallWatch();
        return;
      }

      lastPos = pos;
      samples += 1;
      if (samples >= 3) {
        _cancelStallWatch();
        _notifyFailure();
      }
    });
  }

  Future<void> _initController() async {
    final path = widget.videoUrl;
    if (path.isEmpty) return;

    final controller = _createController(path);

    try {
      await controller.initialize();
      await controller.setLooping(true);
      await controller.setVolume(0);

      if (!mounted) {
        controller.dispose();
        return;
      }
      setState(() => _controller = controller);

      final isNetwork = path.startsWith('http');
      if (isNetwork) {
        await Future.delayed(const Duration(milliseconds: 200));
      }

      await controller.play();

      if (isNetwork && mounted) {
        await Future.delayed(const Duration(milliseconds: 500));
        if (!controller.value.isPlaying && mounted) {
          await controller.play();
        }
      }

      _startStallWatch(controller);
    } catch (e) {
      controller.dispose();
      if (mounted) {
        setState(() => _error = e.toString());
        _notifyFailure();
      }
    }
  }

  @override
  void dispose() {
    _cancelStallWatch();
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = _controller;

    if (_error != null && widget.onPlaybackFailed != null) {
      return ClipRRect(
        borderRadius: widget.borderRadius,
        child: _placeholder(),
      );
    }

    final videoChild = controller != null && controller.value.isInitialized
        ? FittedBox(
            fit: BoxFit.cover,
            clipBehavior: Clip.hardEdge,
            child: SizedBox(
              width: controller.value.size.width,
              height: controller.value.size.height,
              child: VideoPlayer(controller),
            ),
          )
        : _placeholder();

    return ClipRRect(
      borderRadius: widget.borderRadius,
      child: widget.height != null
          ? SizedBox(
              height: widget.height,
              width: double.infinity,
              child: videoChild,
            )
          : LayoutBuilder(
              builder: (context, constraints) => SizedBox(
                width: constraints.maxWidth,
                height: constraints.maxHeight,
                child: videoChild,
              ),
            ),
    );
  }

  Widget _placeholder() {
    if (_error != null) {
      return const Center(
        child: Icon(Icons.videocam_off_outlined, color: Colors.white38, size: 40),
      );
    }
    return const Center(
      child: SizedBox(
        width: 28,
        height: 28,
        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white38),
      ),
    );
  }
}

String formatDurationLabel(Duration duration) {
  final total = duration.inSeconds;
  final minutes = total ~/ 60;
  final seconds = total % 60;
  return '$minutes:${seconds.toString().padLeft(2, '0')}';
}
