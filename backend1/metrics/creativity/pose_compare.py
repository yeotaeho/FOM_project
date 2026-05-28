"""creativity·accuracy 공통 포즈 비교 (aligned_pairs, divergence)."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

DIV_FRAME_CAP = 1.05

DTW_COST_GOOD = 28.0
DTW_COST_HIGH = 42.0
DTW_PENALTY_FLOOR = 0.25

DIV_LOW_START = 0.08
DIV_GOOD_MIN = 0.22
DIV_GOOD_PEAK = 0.55
DIV_HIGH_END = 0.85
DIV_BAND_FLOOR = 0.15


def flatten_numbers(obj: Any, out: list[float]) -> None:
    if obj is None or isinstance(obj, (str, bytes, bytearray)):
        return
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        if math.isfinite(obj):
            out.append(float(obj))
        return
    if isinstance(obj, Sequence):
        for x in obj:
            flatten_numbers(x, out)
        return
    if isinstance(obj, Mapping):
        for k in sorted(obj.keys(), key=lambda x: str(x)):
            flatten_numbers(obj[k], out)


def pose_vector(pose: Mapping[str, Any]) -> list[float]:
    for key in ("normalized_landmarks", "joint_angles", "bone_vectors"):
        block = pose.get(key)
        if not block:
            continue
        vals: list[float] = []
        flatten_numbers(block, vals)
        if vals:
            return vals
    return []


def l2_mean_sq_diff(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    s = 0.0
    for i in range(n):
        d = a[i] - b[i]
        s += d * d
    return math.sqrt(s / n)


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def pstdev(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(var) if var > 0 else 0.0


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def cap_frame_divergence(d: float) -> float:
    return min(max(0.0, d), DIV_FRAME_CAP)


def frame_similarity(divergence: float) -> float:
    return clamp(1.0 - divergence / DIV_FRAME_CAP, 0.0, 1.0)


def dtw_penalty_factor(dtw_mean_cost: float | None) -> float:
    if dtw_mean_cost is None:
        return 1.0
    c = max(0.0, float(dtw_mean_cost))
    if c <= DTW_COST_GOOD:
        return 1.0
    if c >= DTW_COST_HIGH:
        return DTW_PENALTY_FLOOR
    t = (c - DTW_COST_GOOD) / (DTW_COST_HIGH - DTW_COST_GOOD)
    return 1.0 - t * (1.0 - DTW_PENALTY_FLOOR)


def collect_pair_metrics(
    aligned_pairs: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pairs = list(aligned_pairs)
    if not pairs:
        return {"reason": "empty_aligned_pairs"}, []

    divergences: list[float] = []
    similarities: list[float] = []
    frame_diffs: list[dict[str, Any]] = []
    prev_user_vec: list[float] | None = None
    motions: list[float] = []

    for pair in pairs:
        user = pair.get("user") or {}
        ref = pair.get("ref") or {}
        uf = pair.get("user_frame")
        rf = pair.get("ref_frame")
        u = pose_vector(user)
        r = pose_vector(ref)

        if u and r:
            d_raw = l2_mean_sq_diff(u, r)
            d = cap_frame_divergence(d_raw)
            sim = frame_similarity(d)
            divergences.append(d)
            similarities.append(sim)
            frame_diffs.append({
                "user_frame": uf,
                "ref_frame": rf,
                "divergence": round(d, 6),
                "divergence_raw": round(d_raw, 6),
                "similarity": round(sim, 6),
            })
        else:
            frame_diffs.append({
                "user_frame": uf,
                "ref_frame": rf,
                "divergence": None,
                "similarity": None,
                "skipped": True,
            })

        if u:
            if prev_user_vec is not None and prev_user_vec:
                motions.append(l2_mean_sq_diff(u, prev_user_vec))
            prev_user_vec = u

    if not divergences:
        return {
            "reason": "no_comparable_pose_vectors",
            "pairs_evaluated": len(pairs),
        }, frame_diffs

    return {
        "mean_divergence": round(mean(divergences), 6),
        "divergence_std": round(pstdev(divergences), 6),
        "mean_similarity": round(mean(similarities), 6),
        "motion_intensity": round(mean(motions) if motions else 0.0, 6),
        "pairs_evaluated": len(pairs),
        "pairs_used": len(divergences),
        "motion_segments": len(motions),
    }, frame_diffs
