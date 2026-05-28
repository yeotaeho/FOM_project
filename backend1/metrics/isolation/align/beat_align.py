"""user/ref — beat(박자) 그리드 기준 aligned_pairs."""

from __future__ import annotations

import bisect
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from metrics.isolation.align.beat_detect import (
    beats_for_extraction,
    beats_from_music_start,
    estimate_beat_lag_sec,
    save_beat_map,
)
from metrics.isolation.align.time_align import (
    DUPLICATE_RATIO_WARN_THRESHOLD,
    MAX_LENGTH_RATIO,
    compute_duplicate_ratio,
    detect_dance_start,
)
from metrics.isolation.align.compare_window import (
    prepare_ref_compare_window,
    prepare_user_compare_window,
)
from metrics.isolation.config import (
    ALIGN_TO_MUSIC_START,
    DATA_ARTIFACTS,
    DATA_RAW,
    REF_VIDEO_NAME,
)
from metrics.isolation.pipeline.io import get_frames, load_extraction_json, save_json

REF_BEATS_PATH = DATA_ARTIFACTS / "ref_beats.json"
DEFAULT_REF_VIDEO = DATA_RAW / REF_VIDEO_NAME


def _beat_index_for_time(beat_times: List[float], t: float) -> int:
    idx = bisect.bisect_right(beat_times, t) - 1
    return max(0, min(idx, len(beat_times) - 1))


def _nearest_frame_index(frames: List[Dict[str, Any]], t: float) -> int:
    times = [float(f.get("time_sec", 0.0)) for f in frames]
    if not times:
        return 0
    idx = bisect.bisect_left(times, t)
    if idx == 0:
        return 0
    if idx >= len(times):
        return len(times) - 1
    if abs(times[idx] - t) < abs(times[idx - 1] - t):
        return idx
    return idx - 1


def _median_beat_gap(beats: List[float]) -> float:
    import numpy as np

    if len(beats) < 2:
        return 0.5
    return float(np.median(np.diff(beats[: min(len(beats), 64)])))


def align_by_beat(
    user_frames: List[Dict[str, Any]],
    ref_frames: List[Dict[str, Any]],
    user_beats: List[float],
    ref_beats: List[float],
    *,
    beat_lag_sec: float = 0.0,
    motion_trim: bool = False,
    ref_max_sec: Optional[float] = None,
    ref_music_start_sec: float = 0.0,
    user_music_start_sec: float = 0.0,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    같은 비트 인덱스끼리 user/ref 프레임 매칭.
    beat_lag_sec: user 비트 시각 + lag ≈ ref 비트 시각 (같은 박 번호).
    """
    if not user_frames or not ref_frames or len(user_beats) < 2 or len(ref_beats) < 2:
        return [], {"beat_lag_sec": beat_lag_sec}

    u_start = max(
        user_music_start_sec,
        detect_dance_start(user_frames) if motion_trim else user_music_start_sec,
    )
    r_start = max(
        ref_music_start_sec,
        detect_dance_start(ref_frames) if motion_trim else ref_music_start_sec,
    )
    ref_end = (
        (ref_music_start_sec + ref_max_sec)
        if ref_max_sec is not None and ref_max_sec > 0
        else None
    )
    max_k = min(len(user_beats), len(ref_beats)) - 1

    pairs: List[Dict[str, Any]] = []
    for uf in user_frames:
        t_u = float(uf.get("time_sec", 0.0))
        if t_u < u_start:
            continue
        k = _beat_index_for_time(user_beats, t_u + beat_lag_sec)
        k = min(k, max_k)
        target_ref_t = float(ref_beats[k])
        if ref_end is not None and target_ref_t > ref_end + 0.05:
            continue
        if target_ref_t < r_start:
            continue
        ri = _nearest_frame_index(ref_frames, target_ref_t)
        rf = ref_frames[ri]
        pairs.append(
            {
                "user_frame": int(uf["frame_index"]),
                "ref_frame": int(rf["frame_index"]),
                "beat_index": int(k),
                "user": uf,
                "ref": rf,
            }
        )

    meta = {
        "beat_lag_sec": round(float(beat_lag_sec), 4),
        "ref_bpm_approx": round(60.0 / max(_median_beat_gap(ref_beats), 1e-6), 2)
        if len(ref_beats) >= 2
        else None,
        "user_beat_count": len(user_beats),
        "ref_beat_count": len(ref_beats),
    }
    return pairs, meta


def align_extractions_beat(
    user_data: Dict[str, Any],
    ref_data: Dict[str, Any],
    *,
    user_offset_sec: float = 0.0,
    ref_offset_sec: float = 0.0,
    auto_detect_start: bool = False,
    ref_beats_path: Optional[Path] = None,
    save_user_beats_to: Optional[Path] = None,
    user_video_path: Optional[Path] = None,
    ref_video_path: Optional[Path] = None,
    ref_compare_duration_sec: Optional[float] = None,
) -> Dict[str, Any]:
    user_frames = get_frames(user_data)
    ref_frames = get_frames(ref_data)

    ref_cache = ref_beats_path or REF_BEATS_PATH
    ref_beat_data = beats_for_extraction(
        ref_data,
        cache_path=ref_cache,
        video_override=ref_video_path or DEFAULT_REF_VIDEO,
    )
    user_cache = Path(save_user_beats_to) if save_user_beats_to else None
    user_beat_data = beats_for_extraction(
        user_data,
        cache_path=user_cache,
        video_override=user_video_path,
    )

    ref_music_start = (
        float(ref_beat_data.get("music_start_sec") or 0.0) if ALIGN_TO_MUSIC_START else 0.0
    )
    user_music_start = (
        float(user_beat_data.get("music_start_sec") or 0.0) if ALIGN_TO_MUSIC_START else 0.0
    )

    ref_beats = list(ref_beat_data["beat_times_sec"])
    user_beats = list(user_beat_data["beat_times_sec"])
    from metrics.isolation.config import REF_COMPARE_DURATION_SEC

    compare_dur = (
        ref_compare_duration_sec
        if ref_compare_duration_sec is not None
        else REF_COMPARE_DURATION_SEC
    )
    if ALIGN_TO_MUSIC_START:
        ref_music_start, ref_beats = beats_from_music_start(
            ref_beat_data, max_duration_sec=compare_dur
        )
        user_music_start, user_beats = beats_from_music_start(
            user_beat_data,
            max_duration_sec=compare_dur + 6.0 if compare_dur > 0 else None,
        )

    ref_frames, ref_beats, ref_window_sec, ref_music_start = prepare_ref_compare_window(
        ref_frames,
        ref_beats,
        duration_sec=ref_compare_duration_sec,
        music_start_sec=ref_music_start,
    )

    if len(ref_frames) == 0:
        raise ValueError(
            f"음악 시작({ref_music_start:.2f}s) 이후 ref 프레임이 없습니다. "
            "영상·추출 JSON 을 확인하세요."
        )

    ratio = len(user_frames) / max(len(ref_frames), 1)
    if ratio > MAX_LENGTH_RATIO or ratio < 1.0 / MAX_LENGTH_RATIO:
        raise ValueError(
            f"영상 길이 차이가 큽니다 (user/ref 프레임 비율 {ratio:.2f}). "
            "같은 곡·비슷한 편집 길이를 사용하세요."
        )

    if len(ref_beats) < 2:
        raise ValueError(
            f"음악 시작 후 {ref_window_sec}s 구간에 비트가 부족합니다. "
            "REF_COMPARE_DURATION_SEC 를 늘리거나 ref 영상을 확인하세요."
        )

    beat_lag = estimate_beat_lag_sec(ref_beats, user_beats)
    beat_lag += float(user_offset_sec) - float(ref_offset_sec)

    user_frames_cmp = prepare_user_compare_window(
        user_frames,
        ref_window_sec,
        music_start_sec=user_music_start,
        beat_lag_sec=beat_lag,
    )

    pairs, beat_meta = align_by_beat(
        user_frames_cmp,
        ref_frames,
        user_beats,
        ref_beats,
        beat_lag_sec=beat_lag,
        motion_trim=auto_detect_start,
        ref_max_sec=ref_window_sec if ref_window_sec > 0 else None,
        ref_music_start_sec=ref_music_start,
        user_music_start_sec=user_music_start,
    )
    if not pairs:
        raise ValueError(
            "비트 정렬된 프레임 쌍이 없습니다. 같은 곡인지, 음량/비트가 검출되는지 확인하세요."
        )

    dup_ratio = compute_duplicate_ratio(pairs)
    warning = None
    if dup_ratio > DUPLICATE_RATIO_WARN_THRESHOLD:
        warning = (
            f"레퍼런스 프레임 중복 매칭 {int(dup_ratio * 100)}%. "
            "곡/템포 차이 또는 beat_lag 조정이 필요할 수 있습니다."
        )
    ref_bpm = float(ref_beat_data.get("bpm") or 0)
    user_bpm = float(user_beat_data.get("bpm") or 0)
    if ref_bpm and user_bpm and abs(ref_bpm - user_bpm) > 8:
        tempo_warn = (
            f"BPM 차이: ref≈{ref_bpm} user≈{user_bpm}. 같은 곡인지 확인하세요."
        )
        warning = f"{warning} {tempo_warn}" if warning else tempo_warn

    return {
        "alignment": {
            "method": "beat",
            "align_to_music_start": ALIGN_TO_MUSIC_START,
            "ref_music_start_sec": round(ref_music_start, 4),
            "user_music_start_sec": round(user_music_start, 4),
            "ref_compare_duration_sec": ref_window_sec if ref_window_sec > 0 else None,
            "beat_lag_sec": round(beat_lag, 4),
            "ref_bpm": ref_beat_data.get("bpm"),
            "user_bpm": user_beat_data.get("bpm"),
            "user_offset_sec": float(user_offset_sec),
            "ref_offset_sec": float(ref_offset_sec),
            "auto_detect_start": auto_detect_start,
            "pair_count": len(pairs),
            "duplicate_ref_ratio": dup_ratio,
            "warning": warning,
            **beat_meta,
        },
        "pairs": pairs,
    }


def align_from_paths_beat(
    user_json: str | Path,
    ref_json: str | Path,
    **kwargs: Any,
) -> Dict[str, Any]:
    return align_extractions_beat(
        load_extraction_json(user_json),
        load_extraction_json(ref_json),
        **kwargs,
    )


def align_and_save_beat(
    user_json: str | Path,
    ref_json: str | Path,
    out_path: str | Path,
    **kwargs: Any,
) -> Dict[str, Any]:
    result = align_from_paths_beat(user_json, ref_json, **kwargs)
    save_json(result, out_path)
    return result
