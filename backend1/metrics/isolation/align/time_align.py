"""user/ref 추출 JSON — time 기준 aligned_pairs."""

from __future__ import annotations

import bisect
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from metrics.isolation.align.beat_detect import beats_for_extraction
from metrics.isolation.align.compare_window import (
    prepare_ref_compare_window,
    prepare_user_compare_window,
)
from metrics.isolation.config import ALIGN_TO_MUSIC_START, DATA_RAW, REF_VIDEO_NAME
from metrics.isolation.pipeline.io import get_frames, load_extraction_json, save_json

DEFAULT_REF_VIDEO = DATA_RAW / REF_VIDEO_NAME

MOTION_JOINTS = ("left_shoulder", "right_shoulder", "left_hip", "right_hip")
MAX_LENGTH_RATIO = 10.0
DUPLICATE_RATIO_WARN_THRESHOLD = 0.3


def detect_dance_start(
    frames: List[Dict[str, Any]],
    motion_threshold: float = 0.01,
) -> float:
    """normalized_landmarks 변화량이 threshold 를 넘는 첫 time_sec."""
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
    ref_max_sec: Optional[float] = None,
) -> List[Dict[str, Any]]:
    if not user_frames or not ref_frames:
        return []

    user_active = [
        f for f in user_frames if float(f.get("time_sec", 0.0)) >= user_offset
    ]
    ref_active = [
        f
        for f in ref_frames
        if float(f.get("time_sec", 0.0)) >= ref_offset
        and (
            ref_max_sec is None
            or ref_max_sec <= 0
            or float(f.get("time_sec", 0.0)) <= ref_max_sec
        )
    ]
    if not user_active or not ref_active:
        return []

    ref_times = [float(rf.get("time_sec", 0.0)) - ref_offset for rf in ref_active]

    pairs: List[Dict[str, Any]] = []
    for uf in user_active:
        u_t = float(uf.get("time_sec", 0.0)) - user_offset
        best_idx = _nearest_ref_index(ref_times, u_t)
        best_rf = ref_active[best_idx]
        pairs.append(
            {
                "user_frame": int(uf["frame_index"]),
                "ref_frame": int(best_rf["frame_index"]),
                "user": uf,
                "ref": best_rf,
            }
        )
    return pairs


def compute_duplicate_ratio(pairs: List[Dict[str, Any]]) -> float:
    if not pairs:
        return 0.0
    ref_counts = Counter(p["ref_frame"] for p in pairs)
    duplicated = sum(1 for count in ref_counts.values() if count > 1)
    return round(duplicated / max(len(ref_counts), 1), 3)


def _resolve_offsets(
    user_frames: List[Dict[str, Any]],
    ref_frames: List[Dict[str, Any]],
    user_offset_sec: float,
    ref_offset_sec: float,
    auto_detect_start: bool,
) -> Tuple[float, float]:
    if auto_detect_start:
        return (
            detect_dance_start(user_frames),
            detect_dance_start(ref_frames),
        )
    return user_offset_sec, ref_offset_sec


def align_extractions(
    user_data: Dict[str, Any],
    ref_data: Dict[str, Any],
    user_offset_sec: float = 0.0,
    ref_offset_sec: float = 0.0,
    auto_detect_start: bool = False,
    ref_compare_duration_sec: Optional[float] = None,
    ref_video_path: Optional[Path] = None,
    user_video_path: Optional[Path] = None,
) -> Dict[str, Any]:
    user_frames = get_frames(user_data)
    ref_frames = get_frames(ref_data)

    ref_music_start = 0.0
    user_music_start = 0.0
    if ALIGN_TO_MUSIC_START:
        ref_bd = beats_for_extraction(
            ref_data, video_override=ref_video_path or DEFAULT_REF_VIDEO
        )
        user_bd = beats_for_extraction(
            user_data, video_override=user_video_path
        )
        ref_music_start = float(ref_bd.get("music_start_sec") or 0.0)
        user_music_start = float(user_bd.get("music_start_sec") or 0.0)

    ref_frames, _, ref_window_sec, ref_music_start = prepare_ref_compare_window(
        ref_frames,
        None,
        duration_sec=ref_compare_duration_sec,
        music_start_sec=ref_music_start,
    )

    ratio = len(user_frames) / max(len(ref_frames), 1)
    if ratio > MAX_LENGTH_RATIO or ratio < 1.0 / MAX_LENGTH_RATIO:
        raise ValueError(
            f"영상 길이 차이가 큽니다 (user/ref 프레임 비율 {ratio:.2f}). "
            f"오프셋 조정 또는 더 비슷한 길이의 영상을 사용하세요."
        )

    u_off, r_off = _resolve_offsets(
        user_frames, ref_frames, user_offset_sec, ref_offset_sec, auto_detect_start
    )
    u_off = max(u_off, user_music_start)
    r_off = max(r_off, ref_music_start)
    user_frames_cmp = prepare_user_compare_window(
        user_frames,
        ref_window_sec,
        music_start_sec=user_music_start,
    )
    ref_end = (
        ref_music_start + ref_window_sec if ref_window_sec > 0 else None
    )
    pairs = align_by_time(
        user_frames_cmp,
        ref_frames,
        u_off,
        r_off,
        ref_max_sec=ref_end,
    )
    if not pairs:
        raise ValueError("정렬된 프레임 쌍이 없습니다. 오프셋을 확인하세요.")

    dup_ratio = compute_duplicate_ratio(pairs)
    warning = None
    if dup_ratio > DUPLICATE_RATIO_WARN_THRESHOLD:
        warning = (
            f"레퍼런스 프레임 중복 매칭 {int(dup_ratio * 100)}%. "
            "오프셋(auto_detect_start) 조정을 권장합니다."
        )

    return {
        "alignment": {
            "method": "time",
            "align_to_music_start": ALIGN_TO_MUSIC_START,
            "ref_music_start_sec": round(ref_music_start, 4),
            "user_music_start_sec": round(user_music_start, 4),
            "ref_compare_duration_sec": ref_window_sec if ref_window_sec > 0 else None,
            "user_offset_sec": round(u_off, 4),
            "ref_offset_sec": round(r_off, 4),
            "auto_detect_start": auto_detect_start,
            "pair_count": len(pairs),
            "duplicate_ref_ratio": dup_ratio,
            "warning": warning,
        },
        "pairs": pairs,
    }


def align_from_paths(
    user_json: str | Path,
    ref_json: str | Path,
    **kwargs: Any,
) -> Dict[str, Any]:
    return align_extractions(
        load_extraction_json(user_json),
        load_extraction_json(ref_json),
        **kwargs,
    )


def align_and_save(
    user_json: str | Path,
    ref_json: str | Path,
    out_path: str | Path,
    **kwargs: Any,
) -> Dict[str, Any]:
    result = align_from_paths(user_json, ref_json, **kwargs)
    save_json(result, out_path)
    return result
