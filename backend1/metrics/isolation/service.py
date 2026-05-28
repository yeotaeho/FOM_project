"""업로드 영상 → isolation 추출·정렬·채점 (HTTP·CLI 공용)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from metrics.isolation.config import DATA_ARTIFACTS, DEFAULT_ALIGNMENT_METHOD
from metrics.isolation.integration import (
    ensure_ref_isolation_json_in_video_json,
    extract_isolation_to_video_json,
    score_isolation_for_fom,
)

REF_JSON = DATA_ARTIFACTS / "ref.json"
MAX_FRAME_DIFFS_IN_RESPONSE = 20


def ensure_reference_ready() -> Path:
    """로컬 ref.json + 통합용 video_json/ref_isolation.json."""
    if not REF_JSON.is_file():
        raise FileNotFoundError(
            "기준 추출 JSON(ref.json)이 없습니다. "
            "서버에서 한 번 실행: python -m metrics.isolation.cli extract"
        )
    ensure_ref_isolation_json_in_video_json()
    return REF_JSON


def analyze_user_video(
    user_video_path: str | Path,
    *,
    user_offset_sec: float = 0.0,
    ref_offset_sec: float = 0.0,
    auto_detect_start: bool = False,
    alignment_method: str = DEFAULT_ALIGNMENT_METHOD,
    keep_user_json: bool = False,
) -> Dict[str, Any]:
    """
    사용자 mp4 → isolation 점수 dict.

    통합 POST /video/analyze 의 scores.isolation 과 동일 파이프라인.
    """
    ensure_reference_ready()
    video_path = Path(user_video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"영상 없음: {video_path}")

    work = Path(tempfile.mkdtemp(prefix="iso_upload_"))
    persisted_json: Optional[Path] = None
    try:
        extracted = extract_isolation_to_video_json(video_path)
        user_iso_name = extracted["json_filename"]
        if keep_user_json:
            from domain.domain1.hub.services.storage_paths import json_path

            src = json_path(user_iso_name)
            DATA_ARTIFACTS.mkdir(parents=True, exist_ok=True)
            persisted_json = DATA_ARTIFACTS / src.name
            shutil.copy2(src, persisted_json)

        raw = score_isolation_for_fom(
            user_iso_name,
            user_video_path=video_path,
            user_offset_sec=user_offset_sec,
            ref_offset_sec=ref_offset_sec,
            auto_detect_start=auto_detect_start,
            alignment_method=alignment_method,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)

    frame_diffs = raw.get("frame_diffs") or []
    if len(frame_diffs) > MAX_FRAME_DIFFS_IN_RESPONSE:
        worst = sorted(frame_diffs, key=lambda x: x.get("score", 100))[
            :MAX_FRAME_DIFFS_IN_RESPONSE
        ]
        raw["frame_diffs"] = worst
        raw.setdefault("breakdown", {})["frame_diffs_truncated"] = True

    out: Dict[str, Any] = {
        "metric": "isolation",
        "score": raw.get("score", 0.0),
        "breakdown": raw.get("breakdown", {}),
        "frame_diffs": raw.get("frame_diffs", []),
    }
    align = (raw.get("breakdown") or {}).get("alignment")
    if align is not None:
        out["alignment"] = align
    if persisted_json is not None:
        out["user_json_path"] = str(persisted_json)
    return out
