"""사용자 영상 추출 + 저장된 레퍼런스 JSON과 비교·채점."""

from typing import Any, Dict, Literal, Optional

from .comparison_service import compute_comparison
from .extraction_pipeline import build_reference_meta, run_extraction_and_save
DetailLevel = Literal["summary", "full"]
ScoringMode = Literal["linear", "dance"]


def run_analyze(
    user_video_path: str,
    reference_json_filename: str,
    alignment_method: str = "time",
    user_offset_sec: float = 0.0,
    ref_offset_sec: float = 0.0,
    auto_detect_start: bool = False,
    detail_level: DetailLevel = "summary",
    scoring_mode: ScoringMode = "dance",
    enable_accuracy: bool = False,
    enable_rom: bool = True,
    extraction_mode: Literal["rom", "full"] = "rom",
    target_fps: Optional[float] = None,
    frame_stride: Optional[int] = None,
) -> Dict[str, Any]:
    """
    1) 사용자 영상 추출·저장
    2) reference_json(이미 video_json/에 있음)과 compare
    """
    user_meta = run_extraction_and_save(
        user_video_path,
        mode=extraction_mode,
        target_fps=target_fps,
        frame_stride=frame_stride,
    )
    user_json_name = user_meta["json_filename"]

    reference_meta = build_reference_meta(reference_json_filename)

    comparison = compute_comparison(
        user_json_filename=user_json_name,
        reference_json_filename=reference_json_filename,
        alignment_method=alignment_method,
        user_offset_sec=user_offset_sec,
        ref_offset_sec=ref_offset_sec,
        auto_detect_start=auto_detect_start,
        detail_level=detail_level,
        scoring_mode=scoring_mode,
        enable_accuracy=enable_accuracy,
        enable_rom=enable_rom,
    )

    public_user = {
        "extraction_id": user_meta["extraction_id"],
        "extraction_json": user_meta["extraction_json"],
        "annotated_video": user_meta["annotated_video"],
        "fps": user_meta.get("fps"),
        "total_frames": user_meta.get("total_frames"),
    }

    return {
        "user": public_user,
        "reference": reference_meta,
        "alignment": comparison["alignment"],
        "scores": comparison["scores"],
        "meta": {
            **comparison["meta"],
            "user_json": user_json_name,
            "reference_json": reference_json_filename,
        },
    }
