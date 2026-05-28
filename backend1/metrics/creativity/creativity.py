"""
창의성(creativity) metric — ARCHITECTURE.md §4·§5.

1) 이탈 band (양쪽 감쇠)  2) DTW 패널티  3) ref vs ref 기준선
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .pose_compare import (
    DIV_BAND_FLOOR as _DIV_BAND_FLOOR,
    DIV_FRAME_CAP as _DIV_FRAME_CAP,
    DIV_GOOD_MIN as _DIV_GOOD_MIN,
    DIV_GOOD_PEAK as _DIV_GOOD_PEAK,
    DIV_HIGH_END as _DIV_HIGH_END,
    DIV_LOW_START as _DIV_LOW_START,
    DTW_COST_GOOD as _DTW_COST_GOOD,
    DTW_COST_HIGH as _DTW_COST_HIGH,
    DTW_PENALTY_FLOOR as _DTW_PENALTY_FLOOR,
    clamp as _clamp,
    collect_pair_metrics,
    dtw_penalty_factor as _dtw_penalty_factor,
)

_W_MEAN_DIV = 0.35
_W_STD_DIV = 0.25
_W_MOTION = 0.40
_K_STD = 15.0
_K_MOTION = 10.0
_BASELINE_EPS = 1e-6


def _divergence_band_factor(mean_d: float) -> float:
    d = max(0.0, mean_d)
    if d <= _DIV_LOW_START:
        return 0.0
    if d < _DIV_GOOD_MIN:
        return (d - _DIV_LOW_START) / (_DIV_GOOD_MIN - _DIV_LOW_START)
    if d <= _DIV_GOOD_PEAK:
        return 1.0
    if d < _DIV_HIGH_END:
        t = (d - _DIV_GOOD_PEAK) / (_DIV_HIGH_END - _DIV_GOOD_PEAK)
        return 1.0 - t * (1.0 - _DIV_BAND_FLOOR)
    return _DIV_BAND_FLOOR


def _evaluate_pairs(
    aligned_pairs: Sequence[Mapping[str, Any]],
    *,
    dtw_mean_cost: float | None = None,
) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    metrics, frame_diffs = collect_pair_metrics(aligned_pairs)
    if metrics.get("reason"):
        return 0.0, metrics, frame_diffs

    mean_div = float(metrics["mean_divergence"])
    std_div = float(metrics["divergence_std"])
    motion_intensity = float(metrics["motion_intensity"])

    band_factor = _divergence_band_factor(mean_div)
    dtw_penalty = _dtw_penalty_factor(dtw_mean_cost)
    effective_band = band_factor * dtw_penalty

    t_m = effective_band
    t_s = math.tanh(std_div * _K_STD) * effective_band
    t_o = math.tanh(motion_intensity * _K_MOTION) * effective_band
    static_factor = 1.0 if motion_intensity >= 1e-9 else 0.5

    w_sum = _W_MEAN_DIV + _W_STD_DIV + _W_MOTION
    combined = (
        _W_MEAN_DIV * t_m + _W_STD_DIV * t_s + _W_MOTION * t_o
    ) * static_factor / w_sum

    breakdown: dict[str, Any] = {
        **metrics,
        "divergence_band_factor": round(band_factor, 4),
        "dtw_penalty_factor": round(dtw_penalty, 4),
        "effective_band_factor": round(effective_band, 4),
        "combined_raw": round(combined, 6),
        "divergence_thresholds": {
            "low_start": _DIV_LOW_START,
            "good_min": _DIV_GOOD_MIN,
            "good_peak": _DIV_GOOD_PEAK,
            "high_end": _DIV_HIGH_END,
            "band_floor": _DIV_BAND_FLOOR,
            "frame_cap": _DIV_FRAME_CAP,
        },
        "dtw_thresholds": {
            "cost_good": _DTW_COST_GOOD,
            "cost_high": _DTW_COST_HIGH,
            "penalty_floor": _DTW_PENALTY_FLOOR,
        },
        "weights": {
            "mean_divergence": _W_MEAN_DIV,
            "divergence_std": _W_STD_DIV,
            "motion": _W_MOTION,
        },
    }
    if dtw_mean_cost is not None:
        breakdown["dtw_mean_cost"] = round(float(dtw_mean_cost), 4)

    return _clamp(combined, 0.0, 1.0), breakdown, frame_diffs


def _apply_baseline(combined_raw: float, baseline_raw: float) -> float:
    if baseline_raw >= 1.0 - _BASELINE_EPS:
        return 0.0
    if combined_raw <= baseline_raw:
        return 0.0
    return _clamp(
        (combined_raw - baseline_raw) / (1.0 - baseline_raw),
        0.0,
        1.0,
    )


def score_creativity(
    aligned_pairs: Sequence[Mapping[str, Any]],
    *,
    dtw_mean_cost: float | None = None,
    baseline_pairs: Sequence[Mapping[str, Any]] | None = None,
    baseline_dtw_mean_cost: float | None = None,
) -> dict[str, Any]:
    combined_raw, breakdown, frame_diffs = _evaluate_pairs(
        aligned_pairs,
        dtw_mean_cost=dtw_mean_cost,
    )

    baseline_raw: float | None = None
    if baseline_pairs is not None:
        baseline_raw, baseline_bd, _ = _evaluate_pairs(
            baseline_pairs,
            dtw_mean_cost=baseline_dtw_mean_cost,
        )
        breakdown["baseline_combined_raw"] = round(baseline_raw, 6)
        breakdown["baseline_mean_divergence"] = baseline_bd.get("mean_divergence")
        if baseline_dtw_mean_cost is not None:
            breakdown["baseline_dtw_mean_cost"] = round(float(baseline_dtw_mean_cost), 4)
        elif baseline_bd.get("dtw_mean_cost") is not None:
            breakdown["baseline_dtw_mean_cost"] = baseline_bd.get("dtw_mean_cost")

    if baseline_raw is not None:
        combined_final = _apply_baseline(combined_raw, baseline_raw)
        breakdown["combined_after_baseline"] = round(combined_final, 6)
        breakdown["baseline_subtracted"] = True
    else:
        combined_final = combined_raw
        breakdown["baseline_subtracted"] = False

    return {
        "score": round(100.0 * combined_final, 2),
        "breakdown": breakdown,
        "frame_diffs": frame_diffs,
    }
