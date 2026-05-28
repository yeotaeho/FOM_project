"""
Creativity 전용 HTTP API — 통합 POST /video/analyze 와 분리.

전체 파이프라인: 음악 구간 정렬 → 동작 단위 분할 → 구간별 비교 → 창의성 점수.
"""

from __future__ import annotations

import os
import tempfile
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from metrics.creativity.service import analyze_media_pair
from metrics.creativity.split_screen_service import analyze_split_screen_video

router = APIRouter(prefix="/creativity", tags=["creativity"])

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".webp"}
MAX_MB = 500


def _ext(filename: str | None) -> str:
    return os.path.splitext(filename or "")[-1].lower()


@router.get(
    "/ready",
    summary="creativity API 준비 상태",
)
def creativity_ready() -> dict:
    return {
        "ready": True,
        "metric": "creativity",
        "pipeline": (
            "music_align → motion_idle segments (default n=3) → "
            "per-unit full frames → align → score_creativity [→ llm hybrid]"
        ),
        "analyze_endpoint": "POST /creativity/analyze",
        "split_screen_endpoint": "POST /creativity/analyze-split-screen",
    }


@router.post(
    "/analyze",
    summary="사용자·레퍼런스 영상/이미지 쌍 → 창의성 점수 (전체 파이프라인)",
    description=(
        "영상: 동작 단위(motion_idle, 연속 N프레임 정지=경계) 분할 후 n개(기본 3) 구간 전프레임 비교. "
        "이미지: 1프레임. 음악 구간 정렬·DTW·baseline 기본 on. "
        "with_llm_adjustment=true 시 수식 점수 × Ollama 보정(0.8~1.2). "
        "6 metric 통합 POST /video/analyze 와 별도 — CLI와 동일 파이프라인입니다."
    ),
)
async def analyze_creativity(
    user_video: UploadFile = File(..., description="사용자 영상 또는 이미지"),
    reference_video: UploadFile = File(..., description="레퍼런스 영상 또는 이미지"),
    user_offset_sec: float = Form(
        0.0,
        ge=0.0,
        description="사용자 샘플 시작(초). 0이 아니면 음악 정렬 스킵",
    ),
    ref_offset_sec: float = Form(
        0.0,
        ge=0.0,
        description="레퍼런스 샘플 시작(초). 0이 아니면 음악 정렬 스킵",
    ),
    auto_detect_start: bool = Form(
        False,
        description="포즈 움직임으로 춤 시작 추정 (음악 정렬과 동시 사용 안 함)",
    ),
    music_align: bool = Form(
        True,
        description="동일 BGM 크로마 구간 [시작,끝] 정렬 후 샘플",
    ),
    baseline: bool = Form(
        True,
        description="ref vs ref 기준선 보정",
    ),
    with_accuracy: bool = Form(
        False,
        description="동일 파이프라인 정확도 점수 함께 반환",
    ),
    alignment: Literal["index", "time", "dtw"] = Form(
        "dtw",
        description="프레임 정렬 (이미지 쌍은 index 고정)",
    ),
    apply_mirror: bool = Form(True, description="미러 감지 시 좌우 관절 스왑"),
    visibility_threshold: float = Form(
        0.5,
        ge=0.0,
        le=1.0,
        description="핵심 관절 visibility 최소값",
    ),
    save_extractions: bool = Form(
        False,
        description="metrics/creativity/output/extractions/ 에 추출 JSON 저장",
    ),
    with_llm_adjustment: bool = Form(
        False,
        description="수식 점수 × LLM 보정(0.8~1.2). Ollama 필요 (localhost:11434)",
    ),
    num_motion_units: int = Form(3, ge=1, le=12, description="비교 동작 단위 수"),
    idle_min_frames: int = Form(
        3, ge=1, le=15, description="연속 정지 프레임 수 (동작 경계)"
    ),
    motion_velocity_threshold: float | None = Form(
        None,
        description="정지 속도 상한 (None=자동)",
    ),
    min_blend_weight: float = Form(
        0.15,
        ge=0.0,
        le=0.5,
        description="최저 구간 점수 블렌드 비율 (0=가중평균만)",
    ),
):
    user_ext = _ext(user_video.filename)
    ref_ext = _ext(reference_video.filename)
    for label, ext in (("사용자", user_ext), ("레퍼런스", ref_ext)):
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"{label} 지원하지 않는 형식: {ext}. 허용: {sorted(ALLOWED_EXTENSIONS)}",
            )

    user_content = await user_video.read()
    ref_content = await reference_video.read()
    for label, content in (("사용자", user_content), ("레퍼런스", ref_content)):
        if len(content) > MAX_MB * 1024 * 1024:
            raise HTTPException(status_code=400, detail=f"{label} 파일 크기 {MAX_MB}MB 초과")

    user_tmp: str | None = None
    ref_tmp: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=user_ext, delete=False) as u:
            user_tmp = u.name
            u.write(user_content)
        with tempfile.NamedTemporaryFile(suffix=ref_ext, delete=False) as r:
            ref_tmp = r.name
            r.write(ref_content)

        result = analyze_media_pair(
            user_tmp,
            ref_tmp,
            user_offset_sec=user_offset_sec,
            ref_offset_sec=ref_offset_sec,
            auto_detect_start=auto_detect_start,
            music_align=music_align,
            baseline=baseline,
            with_accuracy=with_accuracy,
            alignment=alignment,
            apply_mirror=apply_mirror,
            visibility_threshold=visibility_threshold,
            save_extractions=save_extractions,
            with_llm_adjustment=with_llm_adjustment,
            num_motion_units=num_motion_units,
            idle_min_frames=idle_min_frames,
            motion_velocity_threshold=motion_velocity_threshold,
            min_blend_weight=min_blend_weight,
        )
        result["meta"] = {
            "user_filename": user_video.filename,
            "reference_filename": reference_video.filename,
            "endpoint": "POST /creativity/analyze",
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"creativity 분석 오류: {e}") from e
    finally:
        for p in (user_tmp, ref_tmp):
            if p and os.path.exists(p):
                os.remove(p)

    return JSONResponse(content=result)


@router.post(
    "/analyze-split-screen",
    summary="분할 화면 단일 영상 — 좌/우 두 사람 창의성 비교 + 결과 영상",
    description=(
        "세로 분할(좌/우) 숏폼·비교 영상에서 각 패널 포즈 추출 후 "
        "기존 창의성 파이프라인(음악 구간·샘플·DTW·baseline) 적용. "
        "스켈레톤·이탈 수치·총점이 오버레이된 mp4를 output 경로에 생성합니다."
    ),
)
async def analyze_split_screen(
    video: UploadFile = File(..., description="좌/우 분할 단일 영상"),
    split_ratio: float = Form(0.5, ge=0.35, le=0.65),
    left_role: Literal["user", "reference"] = Form("user"),
    music_align: bool = Form(True),
    baseline: bool = Form(True),
    alignment: Literal["index", "time", "dtw"] = Form(
        "index",
        description="동일 타임라인 — index 권장",
    ),
    apply_mirror: bool = Form(True),
    visibility_threshold: float = Form(0.5, ge=0.0, le=1.0),
    num_motion_units: int = Form(3, ge=1, le=12),
    idle_min_frames: int = Form(3, ge=1, le=15),
    motion_velocity_threshold: float | None = Form(None),
    left_label: str = Form("기준"),
    right_label: str = Form("창의성"),
    with_accuracy: bool = Form(False),
    with_llm_adjustment: bool = Form(False),
):
    ext = _ext(video.filename)
    if ext not in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 형식: {ext}. 영상만 업로드하세요.",
        )

    content = await video.read()
    if len(content) > MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"파일 크기 {MAX_MB}MB 초과")

    tmp: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            tmp = f.name
            f.write(content)

        from pathlib import Path as P

        out_render = (
            P(__file__).resolve().parent
            / "output"
            / f"split_{P(video.filename or 'video').stem}.mp4"
        )
        result = analyze_split_screen_video(
            tmp,
            split_ratio=split_ratio,
            left_role=left_role,
            music_align=music_align,
            baseline=baseline,
            alignment=alignment,
            apply_mirror=apply_mirror,
            visibility_threshold=visibility_threshold,
            num_motion_units=num_motion_units,
            idle_min_frames=idle_min_frames,
            motion_velocity_threshold=motion_velocity_threshold,
            render_output=out_render,
            left_label=left_label,
            right_label=right_label,
        )
        result["meta"] = {
            "filename": video.filename,
            "endpoint": "POST /creativity/analyze-split-screen",
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"split-screen 분석 오류: {e}",
        ) from e
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)

    return JSONResponse(content=result)
