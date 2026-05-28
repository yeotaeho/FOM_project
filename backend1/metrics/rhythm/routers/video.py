# 실제 rhythm 채점 (dance_app · 통합 API):
#   POST /video/analyze  — backend1/routers/video.py
#   → extract_coordinator._run_rhythm_extract()
#   → orchestrator._run_rhythm() → score_rhythm_vs_reference | score_rhythm_from_extraction
#
# 아래 /rhythm/* 는 레거시·개발용 HTTP — 현재 서비스 경로에서 미사용.

from fastapi import APIRouter

router = APIRouter(prefix="/rhythm", tags=["rhythm"])

# ── legacy endpoints (disabled) ─────────────────────────────────────────────
# import os
# import time
# from typing import Annotated, Dict, Any, Optional
#
# from fastapi import APIRouter, File, Form, HTTPException, UploadFile
# from fastapi.responses import FileResponse, JSONResponse
#
# from metrics.rhythm.services.scoring.rhythm_scorer import VALID_GENRES
# from metrics.rhythm.services.analyze_service import (
#     run_analyze,
#     run_analyze_full,
#     run_analyze_with_beats,
#     run_analyze_with_reference,
#     run_compare_visualize,
#     run_extraction_and_save,
#     run_visualize,
#     run_visualize_full,
#     save_upload_to_temp,
# )
# from metrics.rhythm.services.storage_paths import VIDEO_DATA_DIR, load_extraction_json
#
#
# def _inject_upload_timing(result: Dict[str, Any], upload_sec: float, t0: float) -> Dict[str, Any]:
#     timing = result.setdefault("timing_sec", {})
#     timing["upload_sec"] = round(upload_sec, 3)
#     timing["request_total_sec"] = round(time.perf_counter() - t0, 3)
#     return result
#
#
# @router.get("/video-data/{filename}", summary="생성된 시각화 영상 다운로드")
# def download_video(filename: str):
#     ...
#
# @router.post("/compare-visualize", ...)
# async def compare_visualize(...):
#     ...
#
# @router.post("/visualize", ...)
# async def visualize_video(...):
#     ...
#
# @router.post("/visualize-full", ...)
# async def visualize_full(...):
#     ...
#
# @router.get("/json/{filename}", ...)
# def get_extraction_json(filename: str):
#     ...
#
# @router.post("/extract", ...)
# async def extract_video(file: UploadFile = File(...)):
#     ...
#
# @router.post("/analyze-full", ...)
# async def analyze_full(...):
#     ...
#
# @router.post("/analyze-beats", ...)
# async def analyze_beats(...):
#     ...
#
# @router.post("/analyze", ...)
# async def analyze_video(...):
#     ...
#
# def _validate_genre(genre: str) -> None:
#     ...
