"""영상 파일 → 추출·저장 공통 파이프라인."""

from typing import Any, Dict, Literal, Optional

from .extraction_service import (
    DEFAULT_TARGET_FPS_ROM,
    extract_dance_data,
    extract_rom_data,
)
from .storage_paths import (
    build_annotated_video_meta,
    build_json_meta,
    ensure_storage_dirs,
    json_path,
    make_extraction_basename,
    save_extraction_json,
)
from .video_visualizer import render_annotated_video
from .video_input import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_MB,
    acquire_video_to_temp,
    download_url_to_temp,
    save_upload_to_temp,
)

ExtractionMode = Literal["rom", "full"]


def run_extraction_and_save(
    video_path: str,
    *,
    mode: ExtractionMode = "rom",
    target_fps: Optional[float] = DEFAULT_TARGET_FPS_ROM,
    frame_stride: Optional[int] = None,
    include_annotated_video: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    로컬 영상 경로에서 추출 후 JSON 저장.
    mode=rom: joint_angles만, 기본 15fps 샘플링, annotated MP4 생략.
    mode=full: Accuracy용 full JSON, annotated MP4 생성(기본).
    """
    if mode == "rom":
        result = extract_rom_data(
            video_path,
            target_fps=target_fps,
            frame_stride=frame_stride,
        )
        if include_annotated_video is None:
            include_annotated_video = False
    else:
        result = extract_dance_data(
            video_path,
            target_fps=target_fps,
            frame_stride=frame_stride,
        )
        if include_annotated_video is None:
            include_annotated_video = True

    ensure_storage_dirs()
    base = make_extraction_basename()
    json_name = f"{base}.json"
    save_extraction_json(result, json_name)

    result["extraction_id"] = base
    result["extraction_json"] = build_json_meta(json_name)
    result["json_filename"] = json_name

    if include_annotated_video:
        mp4_name = f"{base}_annotated.mp4"
        render_annotated_video(video_path, result, mp4_name)
        result["annotated_video"] = build_annotated_video_meta(mp4_name)
    else:
        result["annotated_video"] = None

    return result


def build_reference_meta(
    reference_json_filename: str,
    *,
    reference_video_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """저장된 레퍼런스 JSON 메타 (파일 존재 검증). 선택 시 annotated MP4."""
    path = json_path(reference_json_filename)
    if not path.is_file():
        raise FileNotFoundError(
            f"레퍼런스 추출 JSON을 찾을 수 없습니다: {reference_json_filename}"
        )
    meta: Dict[str, Any] = {
        "extraction_json": build_json_meta(reference_json_filename),
        "annotated_video": None,
    }
    if reference_video_filename:
        from .reference_visualizer import ensure_reference_annotated_video

        meta["annotated_video"] = ensure_reference_annotated_video(
            reference_json_filename,
            reference_video_filename,
        )
    return meta
