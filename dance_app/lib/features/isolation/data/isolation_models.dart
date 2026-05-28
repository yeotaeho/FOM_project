class IsolationAnalyzeResult {
  final double score;
  final Map<String, dynamic> breakdown;
  final Map<String, dynamic>? alignment;

  const IsolationAnalyzeResult({
    required this.score,
    required this.breakdown,
    this.alignment,
  });

  factory IsolationAnalyzeResult.fromJson(Map<String, dynamic> json) {
    final breakdown = json['breakdown'];
    final alignment = json['alignment'];
    return IsolationAnalyzeResult(
      score: (json['score'] as num?)?.toDouble() ?? 0.0,
      breakdown: breakdown is Map<String, dynamic>
          ? breakdown
          : Map<String, dynamic>.from(breakdown as Map? ?? {}),
      alignment: alignment is Map<String, dynamic>
          ? alignment
          : alignment is Map
              ? Map<String, dynamic>.from(alignment)
              : null,
    );
  }

  double get scoreNormalized => (score / 100).clamp(0.0, 1.0);

  String? get couplingSummary {
    final user = breakdown['mean_user_coupling'];
    final ref = breakdown['mean_ref_coupling'];
    if (user == null || ref == null) return null;
    return '연동(user/ref): $user / $ref';
  }
}
