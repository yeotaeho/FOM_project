"""
FOM 통합 /video/analyze 와 동일한 isolation 채점 (YOLO 추출 + beat 정렬).

전용 POST /isolation/analyze 와 같은 진입점 — 점수 일치용 단일 소스.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from metrics.isolation.config import (
    DATA_ARTIFACTS,
    DATA_RAW,
    DEFAULT_ALIGNMENT_METHOD,
    REF_COMPARE_DURATION_SEC,
    REF_ISOLATION_JSON_FILENAME,
    REF_VIDEO_NAME,
)
from metrics.isolation.pipeline.extract import extract_from_video
from metrics.isolation.score import score_from_paths

DEFAULT_REF_VIDEO = DATA_RAW / REF_VIDEO_NAME
LOCAL_REF_JSON = DATA_ARTIFACTS / "ref.json"
_BACKEND1_ROOT = Path(__file__).resolve().parents[2]
_ROM_SYS_PATH = _BACKEND1_ROOT / "metrics" / "rom"
_VIDEO_JSON_DIR = (
    _BACKEND1_ROOT
    / "metrics"
    / "rom"
    / "domain"
    / "domain1"
    / "video_data"
    / "video_json"
)


def _ensure_rom_sys_path() -> None:
    import sys

    rom = str(_ROM_SYS_PATH)
    if rom not in sys.path:
        sys.path.append(rom)


def _storage():
    _ensure_rom_sys_path()
    from domain.domain1.hub.services.storage_paths import (
        json_path,
        make_extraction_basename,
        save_extraction_json,
    )

    return json_path, make_extraction_basename, save_extraction_json


def ensure_ref_isolation_json_in_video_json() -> str:
    """
    video_json/ref_isolation.json 이 없으면 data/artifacts/ref.json 을 복사해 생성.
    """
    json_path, _, save_extraction_json = _storage()
    target = REF_ISOLATION_JSON_FILENAME
    dest = json_path(target)
    if dest.is_file():
        return target
    if not LOCAL_REF_JSON.is_file():
        raise FileNotFoundError(
            "isolation 기준 JSON이 없습니다. "
            "python -m metrics.isolation.cli extract 후 "
            f"{LOCAL_REF_JSON} 또는 video_json/{target} 를 준비하세요."
        )
    data = json.loads(LOCAL_REF_JSON.read_text(encoding="utf-8"))
    save_extraction_json(data, target)
    return target


def ref_isolation_video_path() -> Path:
    """beat 정렬용 ref mp4 (로컬 data/raw)."""
    if DEFAULT_REF_VIDEO.is_file():
        return DEFAULT_REF_VIDEO
    raise FileNotFoundError(
        f"기준 영상이 없습니다: {DEFAULT_REF_VIDEO}. "
        "python -m metrics.isolation.cli download 실행"
    )


def extract_isolation_to_video_json(video_path: str | Path) -> Dict[str, Any]:
    """
    유저 영상 → video_json/{base}_isolation.json (extract_coordinator sidecar).
    """
    json_path, make_extraction_basename, save_extraction_json = _storage()
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"영상 없음: {path}")

    data = extract_from_video(
        path,
        tracks_json_path=None,
        reuse_yolo=True,
        progress_every=0,
    )
    base = make_extraction_basename()
    filename = f"{base}_isolation.json"
    save_extraction_json(data, filename)
    frames = data.get("frames") or []
    return {
        "ok": True,
        "metric": "isolation",
        "json_filename": filename,
        "canonical": False,
        "meta": {
            "fps": data.get("fps"),
            "total_frames": len(frames),
            "source_video": data.get("source_video"),
            "schema": data.get("schema"),
        },
    }


def _resolve_json_path(filename: str) -> Path:
    """video_json 파일명 또는 절대/상대 경로."""
    p = Path(filename)
    if p.is_file():
        return p.resolve()
    json_path, _, _ = _storage()
    return json_path(filename)


def score_isolation_for_fom(
    user_isolation_json: str,
    reference_isolation_json: Optional[str] = None,
    *,
    user_video_path: Optional[str | Path] = None,
    ref_video_path: Optional[str | Path] = None,
    user_offset_sec: float = 0.0,
    ref_offset_sec: float = 0.0,
    auto_detect_start: bool = False,
    alignment_method: str = DEFAULT_ALIGNMENT_METHOD,
    ref_compare_duration_sec: Optional[float] = None,
) -> Dict[str, Any]:
    """
    beat(기본) 정렬 + score_isolation — ARCHITECTURE §5 반환 형태.

    user_isolation_json: video_json/ 파일명 (예: 20260521_xxx_isolation.json)
    """
    ref_name = reference_isolation_json or ensure_ref_isolation_json_in_video_json()
    user_path = _resolve_json_path(user_isolation_json)
    ref_path = _resolve_json_path(ref_name)

    method = (alignment_method or DEFAULT_ALIGNMENT_METHOD).strip().lower()
    if method not in ("beat", "time"):
        raise ValueError("alignment_method 는 'beat' 또는 'time' 이어야 합니다.")

    ref_vid = Path(ref_video_path) if ref_video_path else ref_isolation_video_path()
    user_vid = Path(user_video_path) if user_video_path else None

    raw = score_from_paths(
        str(user_path),
        str(ref_path),
        alignment_method=method,
        ref_compare_duration_sec=ref_compare_duration_sec,
        user_offset_sec=user_offset_sec,
        ref_offset_sec=ref_offset_sec,
        auto_detect_start=auto_detect_start,
        user_video_path=user_vid,
        ref_video_path=ref_vid,
    )

    alignment = raw.pop("alignment", None)
    breakdown = dict(raw.get("breakdown") or {})
    if alignment is not None:
        breakdown["alignment"] = alignment
    return {
        "score": raw.get("score", 0.0),
        "breakdown": breakdown,
        "frame_diffs": raw.get("frame_diffs") or [],
    }


def publish_local_ref_to_video_json() -> Path:
    """CLI extract 후 video_json/ref_isolation.json 배포 (서버 없이 CLI 가능)."""
    target = REF_ISOLATION_JSON_FILENAME
    try:
        json_path_fn, _, _ = _storage()
        return json_path_fn(ensure_ref_isolation_json_in_video_json())
    except ModuleNotFoundError:
        if not LOCAL_REF_JSON.is_file():
            raise FileNotFoundError(f"ref.json 없음: {LOCAL_REF_JSON}") from None
        _VIDEO_JSON_DIR.mkdir(parents=True, exist_ok=True)
        dest = _VIDEO_JSON_DIR / target
        shutil.copy2(LOCAL_REF_JSON, dest)
        return dest
