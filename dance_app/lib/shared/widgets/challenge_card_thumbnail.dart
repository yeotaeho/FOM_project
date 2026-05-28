import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';

/// 챌린지 목록·바텀시트용 정적 썸네일 (VideoPlayer 없음 — 에뮬 리소스 절약).
class ChallengeCardThumbnail extends StatelessWidget {
  final String genre;
  final Color accentColor;
  final String? imageAsset;
  final double? height;
  final BorderRadius borderRadius;

  const ChallengeCardThumbnail({
    super.key,
    required this.genre,
    required this.accentColor,
    this.imageAsset,
    this.height,
    this.borderRadius = const BorderRadius.vertical(top: Radius.circular(16)),
  });

  Widget _gradientFallback() {
    return DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: borderRadius,
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            accentColor.withValues(alpha: 0.35),
            AppColors.neonPurple.withValues(alpha: 0.2),
            AppColors.background,
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final hasImage = imageAsset != null && imageAsset!.isNotEmpty;

    final content = Stack(
      fit: StackFit.expand,
      children: [
        if (hasImage)
          ClipRRect(
            borderRadius: borderRadius,
            child: Image.asset(
              imageAsset!,
              fit: BoxFit.cover,
              width: double.infinity,
              height: double.infinity,
              errorBuilder: (context, error, stackTrace) => _gradientFallback(),
            ),
          )
        else
          _gradientFallback(),
        DecoratedBox(
          decoration: BoxDecoration(
            borderRadius: borderRadius,
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [
                Colors.black.withValues(alpha: 0.08),
                Colors.black.withValues(alpha: 0.5),
              ],
            ),
          ),
        ),
        Center(
          child: Icon(
            Icons.play_circle_outline,
            size: height != null && height! < 140 ? 48 : 64,
            color: accentColor.withValues(alpha: 0.85),
          ),
        ),
        Positioned(
          left: 16,
          bottom: 16,
          child: Text(
            genre,
            style: TextStyle(
              color: accentColor,
              fontSize: 14,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.5,
            ),
          ),
        ),
      ],
    );

    if (height != null) {
      return SizedBox(height: height, width: double.infinity, child: content);
    }
    return content;
  }
}
