"""두 추출 결과 → ARCHITECTURE aligned_pairs (index | time | dtw)."""

from __future__ import annotations

import bisect
from collections import Counter
from typing import Any, Literal

import numpy as np

AlignmentMethod = Literal["index", "time", "dtw"]

DTW_ANGLE_KEYS = [
    "left_elbow",
    "right_elbow",
    "left_knee",
    "right_knee",
    "left_shoulder",
    "right_shoulder",
    "left_hip",
    "right_hip",
    "left_ankle",
    "right_ankle",
]

DUPLICATE_RATIO_WARN_THRESHOLD = 0.3


def _frame_for_score(frame: dict[str, Any]) -> dict[str, Any]:
    return {
        "frame_index": int(frame.get("frame_index", 0)),
        "joint_angles": frame.get("joint_angles") or {},
        "bone_vectors": frame.get("bone_vectors") or {},
        "normalized_landmarks": frame.get("normalized_landmarks") or {},
    }


def compute_duplicate_ratio(pairs: list[dict[str, Any]]) -> float:
    if not pairs:
        return 0.0
    ref_counts = Counter(p["ref_frame"] for p in pairs)
    duplicated = sum(1 for count in ref_counts.values() if count > 1)
    return round(duplicated / max(len(ref_counts), 1), 3)


def alignment_warning(duplicate_ratio: float, method: str) -> str | None:
    if duplicate_ratio <= DUPLICATE_RATIO_WARN_THRESHOLD:
        return None
    pct = int(duplicate_ratio * 100)
    if method == "time":
        return (
            f"레퍼런스 프레임이 중복 매칭됨 ({pct}%). "
            "DTW 정렬(--alignment dtw) 또는 오프셋 조정을 권장합니다."
        )
    return f"레퍼런스 프레임 중복 매칭 비율이 높습니다 ({pct}%)."


def align_by_index(
    user_frames: list[dict[str, Any]],
    ref_frames: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    n = min(len(user_frames), len(ref_frames))
    if n == 0:
        return []
    pairs: list[dict[str, Any]] = []
    for i in range(n):
        uf = user_frames[i]
        rf = ref_frames[i]
        pairs.append({
            "user_frame": int(uf.get("frame_index", i)),
            "ref_frame": int(rf.get("frame_index", i)),
            "user": _frame_for_score(uf),
            "ref": _frame_for_score(rf),
        })
    return pairs


def align_by_time(
    user_frames: list[dict[str, Any]],
    ref_frames: list[dict[str, Any]],
    user_offset_sec: float = 0.0,
    ref_offset_sec: float = 0.0,
) -> list[dict[str, Any]]:
    if not user_frames or not ref_frames:
        return []

    user_active = [
        f for f in user_frames if float(f.get("time_sec", 0.0)) >= user_offset_sec
    ]
    ref_active = [
        f for f in ref_frames if float(f.get("time_sec", 0.0)) >= ref_offset_sec
    ]
    if not user_active or not ref_active:
        return []

    ref_times = [float(rf.get("time_sec", 0.0)) - ref_offset_sec for rf in ref_active]

    pairs: list[dict[str, Any]] = []
    for uf in user_active:
        u_t = float(uf.get("time_sec", 0.0)) - user_offset_sec
        idx = bisect.bisect_left(ref_times, u_t)
        if idx == 0:
            best = 0
        elif idx >= len(ref_times):
            best = len(ref_times) - 1
        else:
            left = u_t - ref_times[idx - 1]
            right = ref_times[idx] - u_t
            best = idx - 1 if left <= right else idx
        rf = ref_active[best]
        pairs.append({
            "user_frame": int(uf.get("frame_index", 0)),
            "ref_frame": int(rf.get("frame_index", 0)),
            "user": _frame_for_score(uf),
            "ref": _frame_for_score(rf),
        })
    return pairs


def _frame_angle_vector(frame: dict[str, Any]) -> np.ndarray:
    angles = frame.get("joint_angles") or {}
    return np.array(
        [float(angles.get(k, 0.0)) for k in DTW_ANGLE_KEYS],
        dtype=np.float64,
    )


def _dtw_path_with_cost(
    seq_a: list[np.ndarray],
    seq_b: list[np.ndarray],
) -> tuple[list[tuple[int, int]], float]:
    """DTW 경로와 경로 상 평균 스텝 비용(L2)."""
    n, m = len(seq_a), len(seq_b)
    if n == 0 or m == 0:
        return [], 0.0
    inf = float("inf")
    dp = [[inf] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = float(np.linalg.norm(seq_a[i - 1] - seq_b[j - 1]))
            dp[i][j] = cost + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    path: list[tuple[int, int]] = []
    step_costs: list[float] = []
    i, j = n, m
    while i > 0 and j > 0:
        step_costs.append(float(np.linalg.norm(seq_a[i - 1] - seq_b[j - 1])))
        path.append((i - 1, j - 1))
        candidates = [
            (dp[i - 1][j], i - 1, j),
            (dp[i][j - 1], i, j - 1),
            (dp[i - 1][j - 1], i - 1, j - 1),
        ]
        _, i, j = min(candidates, key=lambda x: x[0])
    path.reverse()
    step_costs.reverse()
    mean_cost = sum(step_costs) / len(step_costs) if step_costs else 0.0
    return path, mean_cost


def align_by_dtw(
    user_frames: list[dict[str, Any]],
    ref_frames: list[dict[str, Any]],
    user_offset_sec: float = 0.0,
    ref_offset_sec: float = 0.0,
) -> tuple[list[dict[str, Any]], float]:
    user_active = [
        f for f in user_frames if float(f.get("time_sec", 0.0)) >= user_offset_sec
    ]
    ref_active = [
        f for f in ref_frames if float(f.get("time_sec", 0.0)) >= ref_offset_sec
    ]
    if not user_active or not ref_active:
        return [], 0.0

    user_seq = [_frame_angle_vector(f) for f in user_active]
    ref_seq = [_frame_angle_vector(f) for f in ref_active]
    path, mean_cost = _dtw_path_with_cost(user_seq, ref_seq)

    pairs: list[dict[str, Any]] = []
    seen_user: set[int] = set()
    for u_idx, r_idx in path:
        if u_idx in seen_user:
            continue
        seen_user.add(u_idx)
        uf = user_active[u_idx]
        rf = ref_active[r_idx]
        pairs.append({
            "user_frame": int(uf.get("frame_index", 0)),
            "ref_frame": int(rf.get("frame_index", 0)),
            "user": _frame_for_score(uf),
            "ref": _frame_for_score(rf),
        })
    return pairs, mean_cost


def align_extractions(
    user_extraction: dict[str, Any],
    ref_extraction: dict[str, Any],
    method: AlignmentMethod = "index",
    user_offset_sec: float = 0.0,
    ref_offset_sec: float = 0.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    user_frames = user_extraction.get("frames") or []
    ref_frames = ref_extraction.get("frames") or []
    dtw_mean_cost: float | None = None

    if method == "index":
        pairs = align_by_index(user_frames, ref_frames)
    elif method == "time":
        pairs = align_by_time(
            user_frames, ref_frames, user_offset_sec, ref_offset_sec
        )
    elif method == "dtw":
        pairs, dtw_mean_cost = align_by_dtw(
            user_frames, ref_frames, user_offset_sec, ref_offset_sec
        )
    else:
        raise ValueError(f"지원하지 않는 alignment: {method}")

    dup = compute_duplicate_ratio(pairs)
    meta: dict[str, Any] = {
        "method": method,
        "pair_count": len(pairs),
        "duplicate_ref_ratio": dup,
        "warning": alignment_warning(dup, method),
    }
    if dtw_mean_cost is not None:
        meta["dtw_mean_cost"] = round(dtw_mean_cost, 4)
    return pairs, meta
