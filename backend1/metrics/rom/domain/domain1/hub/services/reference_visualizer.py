"""레퍼런스 추출 JSON + 전문가 MP4 → 캐시된 annotated MP4."""

from __future__ import annotations

from pathlib import Path

import cv2

from .storage_paths import (
    EXTRACTION_SCHEMA_ROM,
    build_annotated_video_meta,
    load_extraction_json,
    video_path,
)
from .video_visualizer import (
    MAX_ANNOTATED_CACHE_BYTES,
    ensure_video_data_dir,
    render_annotated_video,
)


def _cache_filename(reference_json_filename: str) -> str:
    stem = Path(reference_json_filename).stem
    return f"ref_{stem}_annotated.mp4"


def _source_matches_reference_json(src: Path, ref_data: dict) -> bool:
    """캐시가 다른 MP4(예: 사용자 영상)로 만들어진 경우 재생성."""
    expected = ref_data.get("source_total_frames") or ref_data.get("total_frames")
    if not expected:
        return True
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        return False
    actual = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    return abs(actual - int(expected)) <= 3


def ensure_reference_annotated_video(
    reference_json_filename: str,
    reference_video_filename: str,
    *,
    force_regenerate: bool = False,
) -> dict | None:
    """
    reference_json(full_v1) + video_data/ MP4 로 전문가 오버레이 MP4 생성·캐시.

    Returns annotated_video meta dict or None (rom_v1·파일 없음·렌더 실패).
    """
    ref_data = load_extraction_json(reference_json_filename)
    if ref_data.get("schema") == EXTRACTION_SCHEMA_ROM:
        return None

    src = video_path(reference_video_filename)
    if not src.is_file():
        return None

    if not _source_matches_reference_json(src, ref_data):
        force_regenerate = True

    ensure_video_data_dir()
    out_name = _cache_filename(reference_json_filename)
    out_path = video_path(out_name)

    if out_path.is_file():
        size = out_path.stat().st_size
        if size > MAX_ANNOTATED_CACHE_BYTES:
            force_regenerate = True
        elif not force_regenerate and size > 10_000:
            # annotated 길이가 소스 MP4와 크게 다르면 잘못된 캐시(구: user MP4로 생성)
            cap = cv2.VideoCapture(str(out_path))
            ann_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) if cap.isOpened() else 0
            cap.release()
            expected = ref_data.get("source_total_frames") or ref_data.get("total_frames")
            if expected and ann_frames and abs(ann_frames - int(expected)) > 3:
                force_regenerate = True
            elif not force_regenerate:
                return build_annotated_video_meta(out_name)

    if force_regenerate and out_path.is_file():
        try:
            out_path.unlink()
        except OSError:
            pass

    try:
        render_annotated_video(str(src), ref_data, out_name)
    except (ValueError, OSError):
        if out_path.is_file() and out_path.stat().st_size > 10_000:
            return build_annotated_video_meta(out_name)
        return None

    if not out_path.is_file() or out_path.stat().st_size < 1000:
        return None
    return build_annotated_video_meta(out_name)
