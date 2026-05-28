"""
Isolation 전용 HTTP API.

통합 POST /video/analyze(6 metric)과 분리 — 오케스트레이터 미사용.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from metrics.isolation.service import analyze_user_video, ensure_reference_ready

router = APIRouter(prefix="/isolation", tags=["isolation"])

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
MAX_MB = 500


@router.get("/ready")
def isolation_ready() -> dict:
    """기준 ref.json 존재 여부 (프론트 사전 체크용)."""
    try:
        path = ensure_reference_ready()
        return {"ready": True, "reference_json": path.name}
    except FileNotFoundError as e:
        return {"ready": False, "detail": str(e)}


@router.post(
    "/analyze",
    summary="사용자 영상 업로드 → isolation 점수",
    description=(
        "YOLO11 track + MediaPipe Heavy 추출 후 기준 ref.json 과 beat(박자) 정렬·채점. "
        "alignment_method=time 으로 시각 정렬만 사용 가능. "
        "통합 POST /video/analyze 의 scores.isolation 과 동일 파이프라인(beat·YOLO)."
    ),
)
async def analyze_isolation(
    user_video: UploadFile = File(..., description="사용자 댄스 영상"),
    user_offset_sec: float = Form(0.0),
    ref_offset_sec: float = Form(0.0),
    auto_detect_start: bool = Form(False),
    alignment_method: str = Form("beat"),
):
    ext = os.path.splitext(user_video.filename or "")[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 형식: {ext}. 허용: {sorted(ALLOWED_EXTENSIONS)}",
        )

    content = await user_video.read()
    if len(content) > MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"파일 크기 {MAX_MB}MB 초과")

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(content)

        method = (alignment_method or "beat").strip().lower()
        if method not in ("beat", "time"):
            raise HTTPException(
                status_code=400,
                detail="alignment_method 는 'beat' 또는 'time' 이어야 합니다.",
            )
        result = analyze_user_video(
            tmp_path,
            user_offset_sec=user_offset_sec,
            ref_offset_sec=ref_offset_sec,
            auto_detect_start=auto_detect_start,
            alignment_method=method,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"isolation 분석 오류: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    return JSONResponse(content=result)
