"""
통합 /video API — HTTP 진입점.
구현: metrics/rom/domain/domain1 (ROM metric, ARCHITECTURE.md §1).
"""

import os
import time
from pathlib import Path
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from services.orchestrator import run_analyze_from_json
from services.extract_coordinator import run_user_extractions_parallel
from services.llm_feedback import get_llm_feedback_service
from domain.domain1.hub.services.extraction_pipeline import (
    build_reference_meta,
    run_extraction_and_save,
)
from domain.domain1.hub.services.video_input import acquire_video_to_temp
from domain.domain1.hub.services.storage_paths import (
    load_extraction_json,
    save_reference_json_bytes,
    validate_filename,
    video_path,
)
from domain.domain1.hub.services.comparison_service import compute_comparison
from domain.domain1.models.transfer.compare_request import CompareRequest

router = APIRouter(prefix="/video", tags=["video"])


def _remove_temp_video(path: Optional[str]) -> None:
    """업로드 임시 mp4 삭제 (Windows: VideoCapture 해제 대기)."""
    if not path or not os.path.exists(path):
        return
    for attempt in range(5):
        try:
            os.remove(path)
            return
        except PermissionError:
            if attempt < 4:
                time.sleep(0.15 * (attempt + 1))
            else:
                pass


class AnalyzeJsonRequest(BaseModel):
    """ARCHITECTURE.md §2.1 — 저장된 추출 JSON 2개로 채점 (영상 업로드 없음)."""

    user_json: str = Field(..., description="video_json/ 사용자 추출 JSON 파일명")
    reference_json: str = Field(..., description="video_json/ 레퍼런스 추출 JSON 파일명")
    alignment_method: Literal["time", "dtw"] = Field("time")
    user_offset_sec: float = Field(0.0, ge=0.0)
    ref_offset_sec: float = Field(0.0, ge=0.0)
    auto_detect_start: bool = Field(False)
    detail_level: Literal["summary", "full"] = Field("summary")
    scoring_mode: Literal["linear", "dance"] = Field("dance")
    enable_accuracy: bool = Field(
        False,
        description="(metrics 지정 시 무시) 레거시 플래그",
    )
    enable_rom: bool = Field(
        True,
        description="(metrics 지정 시 무시) 레거시 플래그",
    )
    metrics: Optional[list[str]] = Field(
        None,
        description=(
            "채점할 metric 목록. None이면 6개 전체: "
            "accuracy, creativity, isolation, power, rhythm, rom. "
            "ROM만: [\"rom\"]"
        ),
    )
    fail_fast: bool = Field(
        False,
        description="True면 첫 metric 예외 시 전체 실패. False면 해당 metric만 error",
    )
    user_isolation_json: Optional[str] = Field(
        None,
        description="video_json/ isolation sidecar (예: *_isolation.json). isolation 채점 시 필수",
    )
    reference_isolation_json: Optional[str] = Field(
        None,
        description="기본 ref_isolation.json (video_json/)",
    )
    user_video_path: Optional[str] = Field(
        None,
        description="beat 정렬용 유저 mp4 절대경로 또는 video_data/ 파일명",
    )


def _parse_metrics_form(metrics: Optional[str]) -> Optional[list[str]]:
    if not metrics or not str(metrics).strip():
        return None
    return [m.strip() for m in metrics.split(",") if m.strip()]


def _basename_json_name(upload_filename: Optional[str]) -> str:
    base = os.path.basename((upload_filename or "").strip())
    if not base:
        raise ValueError("reference_json_file 파일명이 비어 있습니다.")
    if not base.endswith(".json"):
        base = f"{base}.json"
    return base


async def resolve_reference_json_for_analyze(
    reference_json: str,
    reference_json_file: Optional[UploadFile],
) -> str:
    """
    레퍼런스 JSON 확보: multipart 업로드 우선, 없으면 video_json/ 기존 파일.
    dance_app video_data/cardN/*.json 업로드용.
    """
    name = (reference_json or "").strip()

    if reference_json_file is not None:
        raw = await reference_json_file.read()
        if not name:
            name = _basename_json_name(reference_json_file.filename)
        validate_filename(name)
        return save_reference_json_bytes(raw, name)

    if not name:
        raise ValueError(
            "reference_json 파일명 또는 reference_json_file 업로드가 필요합니다."
        )
    validate_filename(name)
    load_extraction_json(name)
    return name


async def _run_video_analyze_pipeline(
    video_path: str,
    reference_json: str,
    *,
    reference_video_filename: Optional[str] = None,
    user_server_video_filename: Optional[str] = None,
    alignment_method: str,
    user_offset_sec: float,
    ref_offset_sec: float,
    auto_detect_start: bool,
    detail_level: str,
    scoring_mode: str,
    extraction_mode: str,
    target_fps: Optional[float],
    frame_stride: Optional[int],
    metrics_list: Optional[list[str]],
    enable_accuracy: bool,
    enable_rom: bool,
    fail_fast: bool,
) -> dict:
    from services.orchestrator import resolve_metrics_list

    effective_target = target_fps if target_fps and target_fps > 0 else None
    scoring_metrics = resolve_metrics_list(
        metrics_list,
        enable_accuracy=enable_accuracy,
        enable_rom=enable_rom,
    )

    extract_result = await run_user_extractions_parallel(
        video_path,
        scoring_metrics=scoring_metrics,
        extraction_mode=extraction_mode,
        target_fps=effective_target,
        frame_stride=frame_stride,
        fail_fast=fail_fast,
    )

    iso_block = (extract_result.get("extractions") or {}).get("isolation") or {}
    user_iso_json = (
        iso_block.get("json_filename") if iso_block.get("ok") else None
    )
    from metrics.isolation.config import REF_ISOLATION_JSON_FILENAME

    score_result = await run_analyze_from_json(
        extract_result["canonical_json"],
        reference_json,
        alignment_method=alignment_method,
        user_offset_sec=user_offset_sec,
        ref_offset_sec=ref_offset_sec,
        auto_detect_start=auto_detect_start,
        detail_level=detail_level,
        scoring_mode=scoring_mode,
        metrics=metrics_list,
        enable_accuracy=enable_accuracy,
        enable_rom=enable_rom,
        fail_fast=fail_fast,
        user_isolation_json=user_iso_json,
        reference_isolation_json=REF_ISOLATION_JSON_FILENAME,
        user_video_path=video_path,
    )

    user_public = {
        "extraction_id": extract_result["user"].get("extraction_id"),
        "extraction_json": extract_result["user"].get("extraction_json"),
        "annotated_video": extract_result["user"].get("annotated_video"),
        "fps": extract_result["user"].get("fps"),
        "total_frames": extract_result["user"].get("total_frames"),
    }

    return {
        "user": user_public,
        "reference": build_reference_meta(
            reference_json,
            reference_video_filename=reference_video_filename,
        ),
        "extractions": extract_result.get("extractions"),
        "alignment": score_result.get("alignment"),
        "scores": score_result.get("scores"),
        "meta": {
            **(score_result.get("meta") or {}),
            "user_json": extract_result["canonical_json"],
            "reference_json": reference_json,
            "user_server_video_filename": user_server_video_filename,
            "reference_video_filename": reference_video_filename,
            "rom_extraction_mode": extract_result.get("rom_mode"),
            "pipelines_run": extract_result.get("pipelines_run"),
        },
    }


@router.post(
    "/analyze",
    summary="유저 영상 업로드 + 레퍼런스 JSON 채점 (권장)",
    description=(
        "사용자 동영상: multipart file 또는 video_url(HTTP(S) 직링크) 중 하나. "
        "reference_json: 저장 파일명. reference_json_file: 앱 asset 등 JSON 업로드(우선). "
        "둘 중 하나 이상 필요. 업로드 시 video_json/에 저장 후 채점. "
        "Phase A: metric별 추출 병렬(rom/rhythm/power/creativity). "
        "Phase B: 오케스트레이터 6 metric 채점. "
        "metrics 생략 시 6개 metric 전체 채점. "
        "저장 JSON만 채점: POST /video/analyze/json."
    ),
)
async def analyze_video(
    user_video: Optional[UploadFile] = File(
        None, description="사용자 댄스 영상 (video_url과 택1)"
    ),
    video_url: Optional[str] = Form(
        None,
        description="사용자 영상 HTTP(S) URL (user_video와 택1, mp4/mov 등 직링크)",
    ),
    reference_json: str = Form(
        "",
        description="video_json/ 저장 파일명 (reference_json_file 업로드 시 동일 이름 권장)",
    ),
    reference_json_file: Optional[UploadFile] = File(
        None,
        description="dance_app video_data/cardN 레퍼런스 추출 JSON (multipart)",
    ),
    alignment_method: Literal["time", "dtw"] = Form("time"),
    user_offset_sec: float = Form(0.0),
    ref_offset_sec: float = Form(0.0),
    auto_detect_start: bool = Form(False),
    detail_level: Literal["summary", "full"] = Form("summary"),
    scoring_mode: Literal["linear", "dance"] = Form("dance"),
    enable_accuracy: bool = Form(False),
    enable_rom: bool = Form(True),
    extraction_mode: Literal["rom", "full"] = Form(
        "full",
        description="사용자 영상 추출: full=6 metric용(full_v1), rom=경량(rom_v1)",
    ),
    target_fps: Optional[float] = Form(
        15.0,
        description="ROM 샘플링 목표 fps. 0 이하면 전체 프레임",
    ),
    frame_stride: Optional[int] = Form(
        None,
        description="지정 시 target_fps보다 우선",
    ),
    metrics: Optional[str] = Form(
        None,
        description=(
            "채점 metric (쉼표 구분). 비우면 6개 전체. "
            "예: accuracy,creativity,isolation,power,rhythm,rom. ROM만: rom"
        ),
    ),
    fail_fast: bool = Form(False),
    reference_video_filename: Optional[str] = Form(
        None,
        description="전문가 오버레이용 video_data/ MP4 (reference_json과 쌍)",
    ),
):
    tmp_path = None
    try:
        ref_json_name = await resolve_reference_json_for_analyze(
            reference_json, reference_json_file
        )
        tmp_path, _ = await acquire_video_to_temp(
            upload=user_video, video_url=video_url
        )
        metrics_list = _parse_metrics_form(metrics)
        effective_target = target_fps if target_fps and target_fps > 0 else None

        content = await _run_video_analyze_pipeline(
            tmp_path,
            ref_json_name,
            reference_video_filename=reference_video_filename,
            alignment_method=alignment_method,
            user_offset_sec=user_offset_sec,
            ref_offset_sec=ref_offset_sec,
            auto_detect_start=auto_detect_start,
            detail_level=detail_level,
            scoring_mode=scoring_mode,
            extraction_mode=extraction_mode,
            target_fps=effective_target,
            frame_stride=frame_stride,
            metrics_list=metrics_list,
            enable_accuracy=enable_accuracy,
            enable_rom=enable_rom,
            fail_fast=fail_fast,
        )
        return JSONResponse(content=content)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=422, detail=f"영상 URL 다운로드 오류: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"채점 중 오류: {e}") from e
    finally:
        _remove_temp_video(tmp_path)


@router.post(
    "/analyze/by-name",
    summary="[개발] video_data/ 서버 MP4 + reference_json 채점",
    description=(
        "에뮬레이터·로컬 개발용. user_video_filename은 "
        "metrics/rom/domain/domain1/video_data/ 아래 파일명만 허용. "
        "reference_json_file 로 앱 asset JSON 업로드 가능. "
        "상세: metrics/docs/DEV_VIDEO_DATASET.md"
    ),
)
async def analyze_video_by_name(
    user_video_filename: str = Form(
        "Video Project 1 (2).mp4",
        description="video_data/ 사용자(개발) MP4 파일명",
    ),
    reference_json: str = Form(
        "",
        description="video_json/ 저장 파일명 (reference_json_file 과 쌍)",
    ),
    reference_json_file: Optional[UploadFile] = File(
        None,
        description="dance_app video_data/cardN 레퍼런스 JSON",
    ),
    alignment_method: Literal["time", "dtw"] = Form("time"),
    user_offset_sec: float = Form(0.0),
    ref_offset_sec: float = Form(0.0),
    auto_detect_start: bool = Form(True),
    detail_level: Literal["summary", "full"] = Form("summary"),
    scoring_mode: Literal["linear", "dance"] = Form("dance"),
    enable_accuracy: bool = Form(False),
    enable_rom: bool = Form(True),
    extraction_mode: Literal["rom", "full"] = Form("full"),
    target_fps: Optional[float] = Form(15.0),
    frame_stride: Optional[int] = Form(None),
    metrics: Optional[str] = Form(None),
    fail_fast: bool = Form(False),
    reference_video_filename: Optional[str] = Form(
        None,
        description="전문가 오버레이용 MP4. 비우면 user_video_filename과 동일 시도",
    ),
):
    try:
        validate_filename(user_video_filename)
        local_path = video_path(user_video_filename)
        if not local_path.is_file():
            raise FileNotFoundError(
                f"video_data에 영상이 없습니다: {user_video_filename}"
            )
        ref_json_name = await resolve_reference_json_for_analyze(
            reference_json, reference_json_file
        )
        ref_video = (reference_video_filename or "").strip() or user_video_filename
        metrics_list = _parse_metrics_form(metrics)
        effective_target = target_fps if target_fps and target_fps > 0 else None
        content = await _run_video_analyze_pipeline(
            str(local_path),
            ref_json_name,
            reference_video_filename=ref_video,
            user_server_video_filename=user_video_filename,
            alignment_method=alignment_method,
            user_offset_sec=user_offset_sec,
            ref_offset_sec=ref_offset_sec,
            auto_detect_start=auto_detect_start,
            detail_level=detail_level,
            scoring_mode=scoring_mode,
            extraction_mode=extraction_mode,
            target_fps=effective_target,
            frame_stride=frame_stride,
            metrics_list=metrics_list,
            enable_accuracy=enable_accuracy,
            enable_rom=enable_rom,
            fail_fast=fail_fast,
        )
        content["meta"] = {
            **(content.get("meta") or {}),
            "dev_user_video_filename": user_video_filename,
            "dev_mode": "analyze_by_name",
        }
        return JSONResponse(content=content)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"채점 중 오류: {e}") from e


@router.post(
    "/analyze/json",
    summary="저장 JSON 2개로 채점 (ARCHITECTURE §2.1)",
    description=(
        "이미 추출·저장된 user_json / reference_json으로만 채점합니다. "
        "metrics 로 6개 전체 지정 가능: accuracy, creativity, isolation, power, rhythm, rom. "
        "유저 영상 업로드는 POST /video/analyze 를 사용하세요."
    ),
)
async def analyze_video_from_json(body: AnalyzeJsonRequest) -> dict:
    try:
        ref_iso = body.reference_isolation_json
        user_vid = body.user_video_path
        if user_vid and not Path(user_vid).is_absolute():
            from domain.domain1.hub.services.storage_paths import video_path as rom_video_path

            user_vid = str(rom_video_path(user_vid))

        result = await run_analyze_from_json(
            body.user_json,
            body.reference_json,
            alignment_method=body.alignment_method,
            user_offset_sec=body.user_offset_sec,
            ref_offset_sec=body.ref_offset_sec,
            auto_detect_start=body.auto_detect_start,
            detail_level=body.detail_level,
            scoring_mode=body.scoring_mode,
            metrics=body.metrics,
            enable_accuracy=body.enable_accuracy,
            enable_rom=body.enable_rom,
            fail_fast=body.fail_fast,
            user_isolation_json=body.user_isolation_json,
            reference_isolation_json=ref_iso or None,
            user_video_path=user_vid,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"채점 중 오류: {e}") from e

    return result


@router.post(
    "/extract",
    summary="영상 추출 (ROM domain1 위임)",
    description=(
        "동영상 file 또는 video_url(HTTP(S)) → 추출 JSON을 video_json/에 저장. "
        "기본 extraction_mode=full (full_v1, annotated MP4 생성). "
        "경량만 필요하면 extraction_mode=rom."
    ),
)
async def extract_video(
    file: Optional[UploadFile] = File(None, description="업로드 영상 (video_url과 택1)"),
    video_url: Optional[str] = Form(
        None,
        description="영상 HTTP(S) URL (file과 택1)",
    ),
    extraction_mode: Literal["rom", "full"] = Form(
        "rom",
        description="rom=경량 joint_angles, full=Accuracy용 전체 필드",
    ),
    target_fps: Optional[float] = Form(
        15.0,
        description="MediaPipe 샘플링 목표 fps (rom 기본 15). 0 이하면 전체 프레임",
    ),
    frame_stride: Optional[int] = Form(
        None,
        description="지정 시 target_fps보다 우선 (N프레임마다 1회 처리)",
    ),
    include_annotated_video: Optional[bool] = Form(
        None,
        description="None=rom이면 생략, full이면 생성. True/False로 강제",
    ),
):
    tmp_path = None
    try:
        tmp_path, _ = await acquire_video_to_temp(upload=file, video_url=video_url)
        effective_target = target_fps if target_fps and target_fps > 0 else None
        result = run_extraction_and_save(
            tmp_path,
            mode=extraction_mode,
            target_fps=effective_target,
            frame_stride=frame_stride,
            include_annotated_video=include_annotated_video,
        )
        return JSONResponse(content=result)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=422, detail=f"영상 URL 다운로드 오류: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"추출 중 오류: {e}") from e
    finally:
        _remove_temp_video(tmp_path)


@router.post(
    "/compare",
    summary="저장 JSON 2개 비교·채점 (ROM domain1)",
    description="video_json/ 파일명 2개. ROM 기본: enable_accuracy=false.",
)
async def compare_videos(body: CompareRequest):
    try:
        result = compute_comparison(
            user_json_filename=body.user_json,
            reference_json_filename=body.reference_json,
            alignment_method=body.alignment_method,
            user_offset_sec=body.user_offset_sec,
            ref_offset_sec=body.ref_offset_sec,
            auto_detect_start=body.auto_detect_start,
            detail_level=body.detail_level,
            scoring_mode=body.scoring_mode,
            enable_accuracy=body.enable_accuracy,
            enable_rom=body.enable_rom,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"비교 중 오류: {e}") from e
    return JSONResponse(content=result)


@router.get(
    "/data/{filename}",
    summary="분석 오버레이 영상 다운로드",
    response_class=FileResponse,
)
def get_annotated_video(filename: str):
    try:
        validate_filename(filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    path = video_path(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")
    return FileResponse(path, media_type="video/mp4", filename=filename)


@router.get(
    "/json/{filename}",
    summary="저장된 추출 JSON 다운로드",
)
def get_extraction_json(filename: str):
    try:
        data = load_extraction_json(filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return JSONResponse(content=data)


@router.post(
    "/analyze/feedback",
    summary="분석 결과 기반 LLM 피드백 생성",
    description=(
        "저장된 사용자·전문가 JSON으로 비교 분석 후 LLM 피드백 생성. "
        "Ollama qwen2.5:7b-instruct-q4_K_M 모델 사용. "
        "분석 결과 + AI 생성 피드백 반환."
    ),
)
async def generate_analysis_feedback(
    user_json: str = Form(..., description="저장된 사용자 추출 JSON 파일명"),
    reference_json: str = Form(..., description="저장된 전문가 추출 JSON 파일명"),
    alignment_method: Literal["time", "dtw"] = Form("time"),
    user_offset_sec: float = Form(0.0),
    ref_offset_sec: float = Form(0.0),
    auto_detect_start: bool = Form(False),
    detail_level: Literal["summary", "full"] = Form("summary"),
    scoring_mode: Literal["linear", "dance"] = Form("dance"),
    enable_accuracy: bool = Form(True),
    enable_rom: bool = Form(True),
    enable_creativity: bool = Form(True),
    enable_isolation: bool = Form(True),
    enable_power: bool = Form(True),
    enable_rhythm: bool = Form(True),
):
    """
    기존 저장된 JSON으로 분석 후 LLM 피드백 생성.
    """
    # 1. 비교 분석 실행
    # metrics 리스트 구성
    metrics = []
    if enable_accuracy:
        metrics.append("accuracy")
    if enable_rom:
        metrics.append("rom")
    if enable_creativity:
        metrics.append("creativity")
    if enable_isolation:
        metrics.append("isolation")
    if enable_power:
        metrics.append("power")
    if enable_rhythm:
        metrics.append("rhythm")
    
    try:
        analysis_result = await run_analyze_from_json(
            user_json_filename=user_json,
            reference_json_filename=reference_json,
            alignment_method=alignment_method,
            user_offset_sec=user_offset_sec,
            ref_offset_sec=ref_offset_sec,
            auto_detect_start=auto_detect_start,
            detail_level=detail_level,
            scoring_mode=scoring_mode,
            metrics=metrics if metrics else None,
            enable_accuracy=enable_accuracy,
            enable_rom=enable_rom,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"분석 중 오류: {e}") from e
    
    # 2. LLM 피드백 생성
    llm_service = get_llm_feedback_service()
    feedback_result = await llm_service.generate_feedback(analysis_result)
    
    return JSONResponse(content={
        "analysis": {
            "user_json": analysis_result.get("user_json"),
            "reference_json": analysis_result.get("reference_json"),
            "scores": analysis_result.get("scores"),
            "alignment": analysis_result.get("alignment"),
            "meta": analysis_result.get("meta"),
        },
        "feedback": feedback_result,
    })
