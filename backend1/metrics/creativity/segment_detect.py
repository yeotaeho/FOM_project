"""
동작 단위(segment) 경계 검출.

연속 N프레임(기본 3) 이상 거의 움직임 없음 → 동작 경계(시작/끝).
"""

from __future__ import annotations

from typing import Any

import numpy as np

_DEFAULT_IDLE_MIN_FRAMES = 3
_DEFAULT_NUM_MOTION_UNITS = 3
_MIN_ACTIVE_FRAMES = 4
_MIN_SEGMENT_SEC = 0.2

_MOTION_KEYPOINTS = (
    "left_wrist",
    "right_wrist",
    "left_ankle",
    "right_ankle",
    "left_shoulder",
    "right_shoulder",
)


def _velocity_signal(frames: list[dict[str, Any]], keypoints: tuple[str, ...]) -> np.ndarray:
    positions: list[np.ndarray] = []
    for frame in frames:
        lm = frame.get("normalized_landmarks") or {}
        coords: list[float] = []
        for kp in keypoints:
            pt = lm.get(kp)
            if pt:
                coords.extend([float(pt["x"]), float(pt["y"])])
        positions.append(
            np.array(coords, dtype=float) if coords else np.zeros(len(keypoints) * 2)
        )
    if len(positions) < 2:
        return np.zeros(max(len(positions), 1))
    pos_arr = np.array(positions)
    diffs = np.linalg.norm(np.diff(pos_arr, axis=0), axis=1)
    return np.concatenate([[0.0], diffs])


def _pool_frames_in_window(
    frames: list[dict[str, Any]],
    start_sec: float,
    end_sec: float,
) -> list[dict[str, Any]]:
    return [
        f
        for f in frames
        if start_sec <= float(f.get("time_sec", 0.0)) <= end_sec
    ]


def _auto_velocity_threshold(velocity: np.ndarray) -> float:
    if len(velocity) < 2:
        return 0.01
    nz = velocity[velocity > 1e-9]
    if len(nz) == 0:
        return 0.01
    # 하위 25% 구간 상한 + 절대 하한 — "거의 안 움직임"
    p25 = float(np.percentile(nz, 25))
    return max(0.006, min(0.02, p25 * 0.45))


def _idle_mask(velocity: np.ndarray, threshold: float) -> np.ndarray:
    return velocity < threshold


def _runs_of_true(mask: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    """연속 True 구간 [start, end) 인덱스 (end exclusive)."""
    runs: list[tuple[int, int]] = []
    i = 0
    n = len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i + 1
        while j < n and mask[j]:
            j += 1
        if j - i >= min_len:
            runs.append((i, j))
        i = j
    return runs


def detect_motion_unit_segments(
    ref_frames: list[dict[str, Any]],
    *,
    window_start_sec: float,
    window_end_sec: float,
    fps: float = 30.0,
    idle_min_frames: int = _DEFAULT_IDLE_MIN_FRAMES,
    num_motion_units: int = _DEFAULT_NUM_MOTION_UNITS,
    motion_velocity_threshold: float | None = None,
    min_active_frames: int = _MIN_ACTIVE_FRAMES,
) -> dict[str, Any]:
    """
    연속 idle_min_frames 이상 저속도 → 동작 경계.
    활성 구간 중 상위 num_motion_units 개를 비교 단위로 선택 (길이 우선).
    """
    if window_end_sec <= window_start_sec:
        raise ValueError("segment 구간: window_end_sec 가 window_start_sec 보다 커야 합니다.")

    idle_min_frames = max(1, int(idle_min_frames))
    num_motion_units = max(1, int(num_motion_units))
    min_active_frames = max(2, int(min_active_frames))

    pool = _pool_frames_in_window(ref_frames, window_start_sec, window_end_sec)
    if len(pool) < idle_min_frames + min_active_frames:
        return {
            "method": "motion_idle",
            "segment_count": 0,
            "segments": [],
            "error": "too_few_frames",
            "idle_min_frames": idle_min_frames,
        }

    velocity = _velocity_signal(pool, _MOTION_KEYPOINTS)
    threshold = (
        float(motion_velocity_threshold)
        if motion_velocity_threshold is not None
        else _auto_velocity_threshold(velocity)
    )
    idle = _idle_mask(velocity, threshold)
    idle_runs = _runs_of_true(idle, idle_min_frames)

    # 활성 구간 = idle 사이 (또는 선두/말미 비-idle)
    bounds = [0, len(pool)]
    for s, e in idle_runs:
        bounds.append(s)
        bounds.append(e)
    bounds = sorted(set(bounds))

    raw_active: list[tuple[int, int]] = []
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        if b <= a:
            continue
        # idle run 자체는 제외
        if any(a >= s and b <= e for s, e in idle_runs):
            continue
        if b - a < min_active_frames:
            continue
        raw_active.append((a, b))

    if not raw_active:
        # 전 구간이 한 덩어리 동작일 수 있음
        if len(pool) >= min_active_frames and float(idle.mean()) < 0.85:
            raw_active = [(0, len(pool))]

    candidates: list[dict[str, Any]] = []
    for a, b in raw_active:
        t0 = float(pool[a].get("time_sec", window_start_sec))
        t1 = float(pool[b - 1].get("time_sec", window_end_sec))
        if t1 <= t0:
            continue
        mean_v = float(np.mean(velocity[a:b]))
        peak_v = float(np.max(velocity[a:b]))
        candidates.append(
            {
                "start_sec": round(t0, 4),
                "end_sec": round(t1, 4),
                "duration_sec": round(t1 - t0, 4),
                "frame_count": b - a,
                "start_index": a,
                "end_index": b,
                "mean_velocity": round(mean_v, 6),
                "peak_velocity": round(peak_v, 6),
            }
        )

    # 길이(프레임 수) 우선 상위 n개
    candidates.sort(key=lambda c: (c["frame_count"], c["peak_velocity"]), reverse=True)
    selected = candidates[:num_motion_units]
    selected.sort(key=lambda c: c["start_sec"])

    segments: list[dict[str, Any]] = []
    for i, c in enumerate(selected):
        segments.append(
            {
                "index": i,
                "start_sec": c["start_sec"],
                "end_sec": c["end_sec"],
                "duration_sec": c["duration_sec"],
                "frame_count": c["frame_count"],
                "mean_velocity": c["mean_velocity"],
                "peak_velocity": c["peak_velocity"],
            }
        )

    return {
        "method": "motion_idle",
        "idle_min_frames": idle_min_frames,
        "num_motion_units_requested": num_motion_units,
        "num_motion_units_selected": len(segments),
        "motion_velocity_threshold": round(threshold, 6),
        "idle_run_count": len(idle_runs),
        "candidate_motion_units": len(candidates),
        "fps": fps,
        "segment_count": len(segments),
        "segments": segments,
    }


def detect_ref_segments(
    ref_frames: list[dict[str, Any]],
    *,
    window_start_sec: float,
    window_end_sec: float,
    fps: float = 30.0,
    idle_min_frames: int = _DEFAULT_IDLE_MIN_FRAMES,
    num_motion_units: int = _DEFAULT_NUM_MOTION_UNITS,
    motion_velocity_threshold: float | None = None,
) -> dict[str, Any]:
    """레퍼 포즈에서 motion_idle 동작 단위 분할."""
    return detect_motion_unit_segments(
        ref_frames,
        window_start_sec=window_start_sec,
        window_end_sec=window_end_sec,
        fps=fps,
        idle_min_frames=idle_min_frames,
        num_motion_units=num_motion_units,
        motion_velocity_threshold=motion_velocity_threshold,
    )


def count_frames_in_time_window(
    frames: list[dict[str, Any]],
    start_sec: float,
    end_sec: float,
) -> int:
    return len(_pool_frames_in_window(frames, start_sec, end_sec))


def map_segment_to_user_time(
    ref_start: float,
    ref_end: float,
    *,
    ref_window_start: float,
    user_window_start: float,
    user_window_end: float | None,
) -> tuple[float, float]:
    """음악 정렬 오프셋 기준으로 user 타임라인에 매핑."""
    delta = user_window_start - ref_window_start
    u0 = ref_start + delta
    u1 = ref_end + delta
    u0 = max(user_window_start, u0)
    if user_window_end is not None:
        u1 = min(user_window_end, u1)
    if u1 <= u0:
        u1 = min(user_window_end or u1, u0 + _MIN_SEGMENT_SEC)
    return u0, u1


def aggregate_segment_creativity_scores(
    segment_results: list[dict[str, Any]],
    *,
    min_blend_weight: float = 0.15,
) -> dict[str, Any]:
    """구간별 창의성 점수 → 가중 평균 + 최저 구간 블렌드."""
    scored = [s for s in segment_results if s.get("creativity", {}).get("score") is not None]
    if not scored:
        return {
            "score": 0.0,
            "breakdown": {"reason": "no_segment_scores"},
            "frame_diffs": [],
        }

    weights = [max(1e-9, float(s.get("duration_sec") or 1.0)) for s in scored]
    scores = [float(s["creativity"]["score"]) for s in scored]
    w_sum = sum(weights)
    weighted = sum(s * w for s, w in zip(scores, weights)) / w_sum
    seg_min = min(scores)
    w = max(0.0, min(1.0, float(min_blend_weight)))
    final = (1.0 - w) * weighted + w * seg_min

    breakdown: dict[str, Any] = {
        "segment_mode": True,
        "segment_count": len(scored),
        "weighted_mean_score": round(weighted, 2),
        "min_segment_score": round(seg_min, 2),
        "min_blend_weight": round(w, 4),
        "per_segment_scores": [
            {
                "index": s.get("index"),
                "score": s["creativity"]["score"],
                "duration_sec": s.get("duration_sec"),
                "frame_count": s.get("frame_count"),
                "mean_divergence": (s.get("creativity", {}).get("breakdown") or {}).get(
                    "mean_divergence"
                ),
            }
            for s in scored
        ],
    }
    all_frame_diffs: list[dict[str, Any]] = []
    for s in scored:
        for fd in s.get("creativity", {}).get("frame_diffs") or []:
            copy = dict(fd)
            copy["segment_index"] = s.get("index")
            all_frame_diffs.append(copy)

    return {
        "score": round(final, 2),
        "breakdown": breakdown,
        "frame_diffs": all_frame_diffs,
    }
