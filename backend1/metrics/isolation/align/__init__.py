"""정렬: beat(기본) 또는 time."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Literal, Optional

from metrics.isolation.align.beat_align import align_extractions_beat
from metrics.isolation.align.beat_detect import detect_beats_from_video, save_beat_map
from metrics.isolation.align.time_align import (
    align_extractions as _align_extractions_time,
    detect_dance_start,
)
from metrics.isolation.pipeline.io import load_extraction_json, save_json

AlignmentMethod = Literal["beat", "time"]


def align_extractions(
    user_data: Dict[str, Any],
    ref_data: Dict[str, Any],
    *,
    method: AlignmentMethod = "beat",
    user_offset_sec: float = 0.0,
    ref_offset_sec: float = 0.0,
    auto_detect_start: bool = False,
    user_video_path: Optional[Path] = None,
    ref_video_path: Optional[Path] = None,
    save_user_beats_to: Optional[Path] = None,
    ref_compare_duration_sec: Optional[float] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    if method == "beat":
        return align_extractions_beat(
            user_data,
            ref_data,
            user_offset_sec=user_offset_sec,
            ref_offset_sec=ref_offset_sec,
            auto_detect_start=auto_detect_start,
            user_video_path=user_video_path,
            ref_video_path=ref_video_path,
            save_user_beats_to=save_user_beats_to,
            ref_compare_duration_sec=ref_compare_duration_sec,
            **kwargs,
        )
    return _align_extractions_time(
        user_data,
        ref_data,
        user_offset_sec=user_offset_sec,
        ref_offset_sec=ref_offset_sec,
        auto_detect_start=auto_detect_start,
        ref_compare_duration_sec=ref_compare_duration_sec,
    )


def align_from_paths(
    user_json: str | Path,
    ref_json: str | Path,
    *,
    method: AlignmentMethod = "beat",
    **kwargs: Any,
) -> Dict[str, Any]:
    return align_extractions(
        load_extraction_json(user_json),
        load_extraction_json(ref_json),
        method=method,
        **kwargs,
    )


def align_and_save(
    user_json: str | Path,
    ref_json: str | Path,
    out_path: str | Path,
    *,
    method: AlignmentMethod = "beat",
    **kwargs: Any,
) -> Dict[str, Any]:
    result = align_from_paths(user_json, ref_json, method=method, **kwargs)
    save_json(result, out_path)
    return result


__all__ = [
    "AlignmentMethod",
    "align_extractions",
    "align_from_paths",
    "align_and_save",
    "detect_dance_start",
    "detect_beats_from_video",
    "save_beat_map",
]
