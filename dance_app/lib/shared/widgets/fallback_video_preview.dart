import 'package:flutter/material.dart';

import 'card_video_preview.dart';

/// annotated·네트워크 실패 시 fallback URL 순서대로 재시도.
class FallbackVideoPreview extends StatefulWidget {
  final List<String> urls;
  final double? height;
  final BorderRadius borderRadius;

  const FallbackVideoPreview({
    super.key,
    required this.urls,
    this.height = 180,
    this.borderRadius = const BorderRadius.vertical(top: Radius.circular(16)),
  });

  @override
  State<FallbackVideoPreview> createState() => _FallbackVideoPreviewState();
}

class _FallbackVideoPreviewState extends State<FallbackVideoPreview> {
  int _index = 0;
  int _attempt = 0;

  List<String> get _candidates =>
      widget.urls.where((u) => u.isNotEmpty).toList();

  void _onFailed() {
    final list = _candidates;
    if (list.isEmpty) return;
    if (_index + 1 < list.length) {
      setState(() {
        _index += 1;
        _attempt = 0;
      });
      return;
    }
    setState(() => _attempt += 1);
  }

  @override
  Widget build(BuildContext context) {
    final list = _candidates;
    if (list.isEmpty) {
      return _emptyBox(Icons.videocam_off_outlined);
    }
    final idx = _index.clamp(0, list.length - 1);
    final exhausted = _index >= list.length - 1 && _attempt > 0;

    if (exhausted) {
      return _emptyBox(Icons.videocam_off_outlined);
    }

    return CardVideoPreview(
      key: ValueKey('${list[idx]}#$idx'),
      videoUrl: list[idx],
      height: widget.height,
      borderRadius: widget.borderRadius,
      onPlaybackFailed: _onFailed,
    );
  }

  Widget _emptyBox(IconData icon) {
    return ClipRRect(
      borderRadius: widget.borderRadius,
      child: ColoredBox(
        color: const Color(0xFF1A1A1E),
        child: widget.height != null
            ? SizedBox(
                height: widget.height,
                width: double.infinity,
                child: Center(child: Icon(icon, color: Colors.white38, size: 40)),
              )
            : const Center(child: Icon(Icons.videocam_off_outlined, color: Colors.white38, size: 40)),
      ),
    );
  }
}
