"""두 추출 시퀀스의 프레임 정렬."""

import bisect
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# joint_angles DTW 특징 벡터 키 (pose_geometry와 동일 순서 권장)
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

MOTION_JOINTS = ("left_shoulder", "right_shoulder", "left_hip", "right_hip")
DUPLICATE_RATIO_WARN_THRESHOLD = 0.3


def detect_dance_start_from_joint_angles(
    frames: List[Dict[str, Any]],
    angle_delta_threshold_deg: float = 3.0,
) -> float:
    """rom_v1 등 joint_angles만 있을 때 — 주요 관절 각 변화로 시작 시점 추정."""
    prev_angles: Optional[Dict[str, float]] = None
    for frame in frames:
        angles = frame.get("joint_angles") or {}
        if not angles:
            continue
        if prev_angles is None:
            prev_angles = {k: float(v) for k, v in angles.items()}
            continue
        deltas: List[float] = []
        for key in DTW_ANGLE_KEYS:
            if key not in angles or key not in prev_angles:
                continue
            deltas.append(abs(float(angles[key]) - prev_angles[key]))
        if deltas and sum(deltas) / len(deltas) > angle_delta_threshold_deg:
            return float(frame.get("time_sec", 0.0))
        prev_angles = {k: float(v) for k, v in angles.items()}
    return 0.0


def detect_dance_start(
    frames: List[Dict[str, Any]],
    motion_threshold: float = 0.01,
) -> float:
    """
    춤 시작 시점(초). normalized_landmarks가 있으면 위치 변화,
    없으면 joint_angles 변화(rom_v1)로 추정.
    """
    if frames and not frames[0].get("normalized_landmarks"):
        return detect_dance_start_from_joint_angles(frames)

    prev: Optional[Dict[str, Any]] = None
    for frame in frames:
        lms = frame.get("normalized_landmarks") or {}
        if prev is None:
            prev = lms
            continue
        diffs: List[float] = []
        for joint in MOTION_JOINTS:
            if joint not in lms or joint not in prev:
                continue
            dx = float(lms[joint]["x"]) - float(prev[joint]["x"])
            dy = float(lms[joint]["y"]) - float(prev[joint]["y"])
            diffs.append((dx * dx + dy * dy) ** 0.5)
        if diffs and sum(diffs) / len(diffs) > motion_threshold:
            return float(frame.get("time_sec", 0.0))
        prev = lms
    return 0.0


def compute_duplicate_ratio(pairs: List[Dict[str, Any]]) -> float:
    """같은 ref_frame에 여러 user가 매칭된 ref 인덱스 비율."""
    if not pairs:
        return 0.0
    ref_counts = Counter(p["ref_frame"] for p in pairs)
    duplicated = sum(1 for count in ref_counts.values() if count > 1)
    return round(duplicated / max(len(ref_counts), 1), 3)


def _nearest_ref_index(ref_times: List[float], u_t: float) -> int:
    idx = bisect.bisect_left(ref_times, u_t)
    if idx == 0:
        return 0
    if idx >= len(ref_times):
        return len(ref_times) - 1
    left_diff = u_t - ref_times[idx - 1]
    right_diff = ref_times[idx] - u_t
    return idx - 1 if left_diff <= right_diff else idx


def align_by_time(
    user_frames: List[Dict[str, Any]],
    ref_frames: List[Dict[str, Any]],
    user_offset: float = 0.0,
    ref_offset: float = 0.0,
) -> List[Dict[str, Any]]:
    """
    오프셋 이후 활성 구간에서 user time_sec(상대) ↔ 가장 가까운 ref 프레임 매칭.
    ref_frames는 frame_index/time_sec 순 정렬 가정 → bisect O(n log m).
    """
    if not user_frames or not ref_frames:
        return []

    user_active = [
        f
        for f in user_frames
        if float(f.get("time_sec", 0.0)) >= user_offset
    ]
    ref_active = [
        f
        for f in ref_frames
        if float(f.get("time_sec", 0.0)) >= ref_offset
    ]
    if not user_active or not ref_active:
        return []

    ref_times = [
        float(rf.get("time_sec", 0.0)) - ref_offset for rf in ref_active
    ]

    pairs: List[Dict[str, Any]] = []
    for uf in user_active:
        u_t = float(uf.get("time_sec", 0.0)) - user_offset
        best_idx = _nearest_ref_index(ref_times, u_t)
        best_rf = ref_active[best_idx]
        pairs.append({
            "user_frame": int(uf["frame_index"]),
            "ref_frame": int(best_rf["frame_index"]),
            "user": uf,
            "ref": best_rf,
        })
    return pairs


def align_by_dtw(
    user_frames: List[Dict[str, Any]],
    ref_frames: List[Dict[str, Any]],
    user_offset: float = 0.0,
    ref_offset: float = 0.0,
) -> List[Dict[str, Any]]:
    """joint_angles 벡터 시퀀스 fastdtw 정렬 (템포·오프셋에 강건)."""
    from fastdtw import fastdtw
    from scipy.spatial.distance import euclidean

    user_active = [
        f
        for f in user_frames
        if float(f.get("time_sec", 0.0)) >= user_offset
    ]
    ref_active = [
        f
        for f in ref_frames
        if float(f.get("time_sec", 0.0)) >= ref_offset
    ]
    if not user_active or not ref_active:
        return []

    def frame_to_vec(frame: Dict[str, Any]) -> np.ndarray:
        angles = frame.get("joint_angles") or {}
        return np.array(
            [float(angles.get(k, 0.0)) for k in DTW_ANGLE_KEYS],
            dtype=np.float64,
        )

    user_seq = [frame_to_vec(f) for f in user_active]
    ref_seq = [frame_to_vec(f) for f in ref_active]

    _, path = fastdtw(user_seq, ref_seq, dist=euclidean)

    pairs: List[Dict[str, Any]] = []
    seen_user: set = set()
    for u_idx, r_idx in path:
        if u_idx in seen_user:
            continue
        seen_user.add(u_idx)
        pairs.append({
            "user_frame": int(user_active[u_idx]["frame_index"]),
            "ref_frame": int(ref_active[r_idx]["frame_index"]),
            "user": user_active[u_idx],
            "ref": ref_active[r_idx],
        })
    return pairs


def alignment_warning(duplicate_ratio: float, method: str) -> Optional[str]:
    if duplicate_ratio <= DUPLICATE_RATIO_WARN_THRESHOLD:
        return None
    pct = int(duplicate_ratio * 100)
    if method == "time":
        return (
            f"레퍼런스 프레임이 중복 매칭됨 ({pct}%). "
            "DTW 정렬(alignment_method=dtw) 또는 오프셋 조정을 권장합니다."
        )
    return f"레퍼런스 프레임 중복 매칭 비율이 높습니다 ({pct}%)."
