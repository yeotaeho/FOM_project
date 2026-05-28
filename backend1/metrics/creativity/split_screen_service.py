"""
단일 분할 화면 영상 — 좌/우 두 댄서 창의성 비교 + 결과 영상 렌더.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from .service import analyze_extraction_pair, ensure_output_dirs
from .split_screen_extract import extract_split_screen_video
from .split_screen_render import render_split_screen_video

_OUTPUT_ROOT = Path(__file__).resolve().parent / "output"
_DEFAULT_RENDER = _OUTPUT_ROOT / "split_screen_creativity.mp4"


def analyze_split_screen_video(
    video_path: str | Path,
    *,
    split_ratio: float = 0.5,
    left_role: Literal["user", "reference"] = "user",
    music_align: bool = True,
    baseline: bool = True,
    with_accuracy: bool = False,
    with_llm_adjustment: bool = False,
    alignment: Literal["index", "time", "dtw"] = "index",
    apply_mirror: bool = True,
    visibility_threshold: float = 0.5,
    num_motion_units: int = 3,
    idle_min_frames: int = 3,
    motion_velocity_threshold: float | None = None,
    render_output: str | Path | None = None,
    left_label: str = "기준",
    right_label: str = "창의성",
    save_extractions: bool = False,
) -> dict[str, Any]:
    """
    한 영상(좌/우 분할)에서 두 포즈 시퀀스를 추출해 기존 창의성 로직으로 비교.

    동일 타임라인이므로 기본 정렬은 index 권장.
    """
    video_p = Path(video_path)
    if not video_p.is_file():
        raise FileNotFoundError(f"영상이 없습니다: {video_p}")

    user_raw, ref_raw, meta = extract_split_screen_video(
        str(video_p),
        split_ratio=split_ratio,
        left_role=left_role,
    )

    src = str(video_p)
    result = analyze_extraction_pair(
        user_raw,
        ref_raw,
        user_source=src,
        ref_source=src,
        music_align=music_align,
        baseline=baseline,
        with_accuracy=with_accuracy,
        with_llm_adjustment=with_llm_adjustment,
        alignment=alignment,
        apply_mirror=apply_mirror,
        visibility_threshold=visibility_threshold,
        num_motion_units=num_motion_units,
        idle_min_frames=idle_min_frames,
        motion_velocity_threshold=motion_velocity_threshold,
        save_extractions=save_extractions,
        extra_inputs={
            "mode": "split_screen",
            "split_ratio": split_ratio,
            "left_role": left_role,
            "segment_mode": True,
            "num_motion_units": num_motion_units,
        },
    )

    result["split_screen"] = meta
    result["extractions_full"] = {
        "user_frame_count": len(user_raw.get("frames") or []),
        "reference_frame_count": len(ref_raw.get("frames") or []),
    }

    out_video = Path(render_output) if render_output else _DEFAULT_RENDER
    ensure_output_dirs()
    out_video = out_video.with_stem(out_video.stem + "_live")
    rendered = render_split_screen_video(
        str(video_p),
        user_raw,
        ref_raw,
        result,
        out_video,
        split_meta=meta,
        left_label=left_label,
        right_label=right_label,
    )
    result["render"] = {
        "output_video": str(rendered),
        "left_label": left_label,
        "right_label": right_label,
    }
    return result
