"""
정확도(accuracy) — creativity 와 동일 파이프라인·divergence, 점수는 유사도(낮은 이탈) 기준.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .pose_compare import (
    DIV_FRAME_CAP,
    DIV_GOOD_MIN,
    DIV_GOOD_PEAK,
    DIV_HIGH_END,
    DIV_LOW_START,
    DTW_COST_GOOD,
    DTW_COST_HIGH,
    DTW_PENALTY_FLOOR,
    clamp,
    collect_pair_metrics,
    dtw_penalty_factor,
)

_W_MEAN_SIM = 0.55
_W_FRAME_SIM = 0.30
_W_CONSISTENCY = 0.15
_K_CONSISTENCY = 12.0
_ACC_FLOOR = 0.05


def _divergence_similarity_factor(mean_d: float) -> float:
    d = max(0.0, mean_d)
    if d <= DIV_LOW_START:
        return 1.0
    if d < DIV_GOOD_MIN:
        return 1.0 - 0.08 * (d - DIV_LOW_START) / (DIV_GOOD_MIN - DIV_LOW_START)
    if d <= DIV_GOOD_PEAK:
        t = (d - DIV_GOOD_MIN) / (DIV_GOOD_PEAK - DIV_GOOD_MIN)
        return 0.92 - 0.47 * t
    if d < DIV_HIGH_END:
        t = (d - DIV_GOOD_PEAK) / (DIV_HIGH_END - DIV_GOOD_PEAK)
        return 0.45 - 0.32 * t
    return _ACC_FLOOR


def _consistency_factor(std_div: float, mean_div: float) -> float:
    if mean_div <= DIV_LOW_START:
        return 1.0
    return clamp(math.exp(-std_div * _K_CONSISTENCY), 0.35, 1.0)


def _evaluate_accuracy(
    aligned_pairs: Sequence[Mapping[str, Any]],
    *,
    dtw_mean_cost: float | None = None,
) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    metrics, frame_diffs = collect_pair_metrics(aligned_pairs)
    if metrics.get("reason"):
        return 0.0, metrics, frame_diffs

    mean_div = float(metrics["mean_divergence"])
    std_div = float(metrics["divergence_std"])
    mean_sim = float(metrics["mean_similarity"])

    sim_factor = _divergence_similarity_factor(mean_div)
    consistency = _consistency_factor(std_div, mean_div)
    dtw_trust = dtw_penalty_factor(dtw_mean_cost)
    effective = sim_factor * dtw_trust

    w_sum = _W_MEAN_SIM + _W_FRAME_SIM + _W_CONSISTENCY
    combined = (
        _W_MEAN_SIM * sim_factor
        + _W_FRAME_SIM * mean_sim
        + _W_CONSISTENCY * consistency
    ) / w_sum * effective

    breakdown: dict[str, Any] = {
        **metrics,
        "similarity_factor": round(sim_factor, 4),
        "consistency_factor": round(consistency, 4),
        "dtw_trust_factor": round(dtw_trust, 4),
        "effective_accuracy_factor": round(effective, 4),
        "combined_raw": round(combined, 6),
        "scoring_note": "creativity 와 동일 divergence·DTW; 유사도(낮은 이탈) 기준",
        "weights": {
            "mean_similarity_curve": _W_MEAN_SIM,
            "mean_frame_similarity": _W_FRAME_SIM,
            "consistency": _W_CONSISTENCY,
        },
    }
    if dtw_mean_cost is not None:
        breakdown["dtw_mean_cost"] = round(float(dtw_mean_cost), 4)

    return clamp(combined, 0.0, 1.0), breakdown, frame_diffs


def score_accuracy(
    aligned_pairs: Sequence[Mapping[str, Any]],
    *,
    dtw_mean_cost: float | None = None,
    reference_pairs: Sequence[Mapping[str, Any]] | None = None,
    reference_dtw_mean_cost: float | None = None,
) -> dict[str, Any]:
    combined_raw, breakdown, frame_diffs = _evaluate_accuracy(
        aligned_pairs,
        dtw_mean_cost=dtw_mean_cost,
    )

    if reference_pairs is not None:
        ref_raw, ref_bd, _ = _evaluate_accuracy(
            reference_pairs,
            dtw_mean_cost=reference_dtw_mean_cost,
        )
        breakdown["reference_self_combined_raw"] = round(ref_raw, 6)
        breakdown["reference_self_mean_divergence"] = ref_bd.get("mean_divergence")
        breakdown["reference_self_score"] = round(100.0 * ref_raw, 2)

    return {
        "score": round(100.0 * combined_raw, 2),
        "breakdown": breakdown,
        "frame_diffs": frame_diffs,
    }
