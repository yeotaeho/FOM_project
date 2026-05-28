"""추출 후·채점 전 보정: 미러, visibility, 영상 전체 균등 샘플."""

from __future__ import annotations

from typing import Any, Optional

from .geometry import pose_center_score

MOTION_JOINTS = ("left_shoulder", "right_shoulder", "left_hip", "right_hip")


def sample_frame_indices(total_frames: int, num_frames: int) -> list[int]:
    if num_frames < 1:
        raise ValueError("num_frames 는 1 이상이어야 합니다.")
    if total_frames <= 0:
        return []
    if num_frames == 1:
        return [max(0, total_frames // 2)]
    if num_frames >= total_frames:
        return list(range(total_frames))
    return [
        round(i * (total_frames - 1) / (num_frames - 1))
        for i in range(num_frames)
    ]


CORE_JOINTS = (
    "left_shoulder",
    "right_shoulder",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
)

LEFT_RIGHT_LANDMARK_PAIRS = (
    ("left_shoulder", "right_shoulder"),
    ("left_elbow", "right_elbow"),
    ("left_wrist", "right_wrist"),
    ("left_hip", "right_hip"),
    ("left_knee", "right_knee"),
    ("left_ankle", "right_ankle"),
    ("left_heel", "right_heel"),
    ("left_foot_index", "right_foot_index"),
    ("left_eye", "right_eye"),
    ("left_ear", "right_ear"),
)

DEFAULT_VISIBILITY_THRESHOLD = 0.5


def detect_dance_start(
    frames: list[dict[str, Any]],
    motion_threshold: float = 0.01,
) -> float:
    """normalized_landmarks 변화량이 threshold를 넘는 첫 time_sec."""
    prev: Optional[dict[str, Any]] = None
    for frame in frames:
        lms = frame.get("normalized_landmarks") or {}
        if prev is None:
            prev = lms
            continue
        diffs: list[float] = []
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


def resolve_offset_sec(
    frames: list[dict[str, Any]],
    manual_offset_sec: float,
    auto_detect_start: bool,
) -> float:
    if auto_detect_start:
        return detect_dance_start(frames)
    return max(0.0, manual_offset_sec)


def sample_frames_uniform(
    frames: list[dict[str, Any]],
    num_frames: int,
    offset_sec: float = 0.0,
    end_sec: float | None = None,
) -> list[dict[str, Any]]:
    """[offset_sec, end_sec] 구간(또는 offset 이후 전체)에서 num_frames 개를 균등 샘플."""
    pool = frames
    if offset_sec > 0 or end_sec is not None:
        pool = []
        for f in frames:
            t = float(f.get("time_sec", 0.0))
            if t < offset_sec:
                continue
            if end_sec is not None and t > end_sec:
                continue
            pool.append(f)
    if not pool:
        return []
    if num_frames >= len(pool):
        sampled = pool
    else:
        idxs = sample_frame_indices(len(pool), num_frames)
        sampled = [pool[i] for i in idxs]
    out: list[dict[str, Any]] = []
    for i, fr in enumerate(sampled):
        copy = dict(fr)
        copy["frame_index"] = i
        out.append(copy)
    return out


def detect_mirror(frames: list[dict[str, Any]]) -> bool:
    """
    정면 기준: left_shoulder.x < right_shoulder.x 가 일반적.
    과반수 프레임에서 반대면 미러로 판단.
    """
    if not frames:
        return False
    mirrored_votes = 0
    valid = 0
    for frame in frames:
        lms = frame.get("normalized_landmarks") or {}
        ls = lms.get("left_shoulder")
        rs = lms.get("right_shoulder")
        if not ls or not rs:
            continue
        valid += 1
        if float(ls["x"]) > float(rs["x"]):
            mirrored_votes += 1
    if valid == 0:
        return False
    return mirrored_votes > valid / 2


def _swap_dict_lr(d: dict[str, Any]) -> dict[str, Any]:
    if not d:
        return d
    out = dict(d)
    for left, right in LEFT_RIGHT_LANDMARK_PAIRS:
        if left in out and right in out:
            out[left], out[right] = out[right], out[left]
    return out


def apply_mirror_to_frame(frame: dict[str, Any]) -> dict[str, Any]:
    out = dict(frame)
    for key in ("normalized_landmarks", "landmarks"):
        if key in out and isinstance(out[key], dict):
            out[key] = _swap_dict_lr(out[key])
    if "bone_vectors" in out and isinstance(out["bone_vectors"], dict):
        out["bone_vectors"] = _swap_dict_lr(out["bone_vectors"])
    if "joint_angles" in out and isinstance(out["joint_angles"], dict):
        out["joint_angles"] = _swap_dict_lr(out["joint_angles"])
    return out


def apply_mirror_to_frames(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [apply_mirror_to_frame(f) for f in frames]


def frame_visibility_ok(
    frame: dict[str, Any],
    threshold: float = DEFAULT_VISIBILITY_THRESHOLD,
) -> bool:
    """원본 landmarks visibility로 핵심 관절 검출 여부."""
    lms = frame.get("landmarks") or frame.get("normalized_landmarks") or {}
    ok = 0
    for name in CORE_JOINTS:
        p = lms.get(name)
        if p and float(p.get("visibility", 1.0)) >= threshold:
            ok += 1
    return ok >= 4


def filter_frames_by_visibility(
    frames: list[dict[str, Any]],
    threshold: float = DEFAULT_VISIBILITY_THRESHOLD,
) -> list[dict[str, Any]]:
    return [f for f in frames if frame_visibility_ok(f, threshold)]


def prepare_mirrored_frames(
    extraction: dict[str, Any],
    *,
    apply_mirror: bool = True,
) -> tuple[list[dict[str, Any]], bool]:
    """전체 시퀀스에 미러 보정 1회 적용 (segment 루프에서 재사용)."""
    all_frames: list[dict[str, Any]] = list(extraction.get("frames") or [])
    if apply_mirror and all_frames and detect_mirror(all_frames):
        return apply_mirror_to_frames(all_frames), True
    return all_frames, False


def preprocess_window(
    extraction: dict[str, Any],
    start_sec: float,
    end_sec: float | None,
    num_frames: int,
    *,
    apply_mirror: bool = True,
    visibility_threshold: float = DEFAULT_VISIBILITY_THRESHOLD,
    mirrored_frames: list[dict[str, Any]] | None = None,
    mirror_applied: bool = False,
) -> dict[str, Any]:
    """[start_sec, end_sec] 구간만 균등 샘플·visibility (미러는 mirrored_frames 재사용)."""
    if mirrored_frames is not None:
        all_frames = mirrored_frames
        m_applied = mirror_applied
    else:
        all_frames, m_applied = prepare_mirrored_frames(extraction, apply_mirror=apply_mirror)

    pool = []
    for f in all_frames:
        t = float(f.get("time_sec", 0.0))
        if t < start_sec:
            continue
        if end_sec is not None and t > end_sec:
            continue
        pool.append(f)
    sampled = sample_frames_uniform(pool, num_frames, offset_sec=0.0, end_sec=None)
    visible = filter_frames_by_visibility(sampled, visibility_threshold)

    center_scores = [
        pose_center_score(f.get("landmarks") or f.get("normalized_landmarks") or {})
        for f in visible
    ]
    avg_center = sum(center_scores) / len(center_scores) if center_scores else 0.0

    out = dict(extraction)
    out["frames"] = visible
    out["preprocess"] = {
        "offset_sec": start_sec,
        "end_sec": end_sec,
        "window_start_sec": start_sec,
        "window_end_sec": end_sec,
        "num_frames_requested": num_frames,
        "frames_in_window": len(pool),
        "frames_after_sample": len(sampled),
        "frames_after_visibility": len(visible),
        "mirror_applied": m_applied,
        "avg_main_dancer_center_score": round(avg_center, 4),
        "visibility_threshold": visibility_threshold,
    }
    return out


def preprocess_extraction(
    extraction: dict[str, Any],
    num_frames: int,
    *,
    offset_sec: float = 0.0,
    end_sec: float | None = None,
    apply_mirror: bool = True,
    visibility_threshold: float = DEFAULT_VISIBILITY_THRESHOLD,
) -> dict[str, Any]:
    """전체 프레임 시퀀스에서 [offset, end] 구간 균등 샘플·미러·visibility 적용."""
    all_frames, mirror_applied = prepare_mirrored_frames(extraction, apply_mirror=apply_mirror)
    if not all_frames:
        extraction["frames"] = []
        return extraction

    return preprocess_window(
        extraction,
        offset_sec,
        end_sec,
        num_frames,
        apply_mirror=apply_mirror,
        visibility_threshold=visibility_threshold,
        mirrored_frames=all_frames,
        mirror_applied=mirror_applied,
    )
