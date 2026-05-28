"""기준(ref) 영상 비교 구간 — 앞 N초만 사용."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from metrics.isolation.config import REF_COMPARE_DURATION_SEC


def trim_frames_to_duration(
    frames: List[Dict[str, Any]],
    max_sec: float,
    *,
    min_sec: float = 0.0,
) -> List[Dict[str, Any]]:
    if max_sec <= 0:
        return list(frames)
    out: List[Dict[str, Any]] = []
    for f in frames:
        t = float(f.get("time_sec", 0.0))
        if min_sec <= t <= max_sec:
            out.append(f)
    return out


def trim_beats_to_duration(beats: List[float], max_sec: float) -> List[float]:
    if max_sec <= 0:
        return list(beats)
    return [float(b) for b in beats if float(b) <= max_sec]


def prepare_ref_compare_window(
    ref_frames: List[Dict[str, Any]],
    ref_beats: Optional[List[float]] = None,
    *,
    duration_sec: Optional[float] = None,
    music_start_sec: float = 0.0,
) -> Tuple[List[Dict[str, Any]], Optional[List[float]], float, float]:
    """
    ref 프레임·비트를 [music_start, music_start + duration_sec] 로 제한.
    반환: (trimmed_frames, trimmed_beats|None, duration_used, music_start_sec)
    """
    d = REF_COMPARE_DURATION_SEC if duration_sec is None else duration_sec
    start = max(0.0, float(music_start_sec))
    if d is None or d <= 0:
        return ref_frames, ref_beats, 0.0, start

    end = start + float(d)
    rf = trim_frames_to_duration(ref_frames, end, min_sec=start)
    rb = None
    if ref_beats is not None:
        rb = [float(b) for b in ref_beats if start - 0.02 <= float(b) <= end + 0.05]
    return rf, rb, float(d), start


def prepare_user_compare_window(
    user_frames: List[Dict[str, Any]],
    ref_duration_sec: float,
    *,
    music_start_sec: float = 0.0,
    beat_lag_sec: float = 0.0,
    margin_sec: float = 2.0,
) -> List[Dict[str, Any]]:
    """ref 음악 구간 [start, start+N] 에 맞출 user 프레임 (여유 margin)."""
    if ref_duration_sec <= 0:
        return user_frames
    start = max(0.0, float(music_start_sec))
    user_max = start + ref_duration_sec + margin_sec + max(0.0, float(beat_lag_sec))
    return trim_frames_to_duration(user_frames, user_max, min_sec=start)
