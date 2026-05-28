"""사용자 영상 추출 후 리듬 채점."""

import os
import tempfile
import time
from typing import Any, Dict

from fastapi import UploadFile

from .beat_service import extract_beats
from .comparison_visualizer import render_comparison_video
from .extraction_service import extract_rhythm_data
from .rhythm_visualizer import render_rhythm_video
from .scoring.rhythm_scorer import (
    score_motion_full,
    score_motion_vs_beats,
    score_rhythm_from_extraction,
    score_rhythm_vs_reference,
)
from .storage_paths import (
    build_annotated_video_meta,
    build_json_meta,
    ensure_storage_dirs,
    make_extraction_basename,
    save_extraction_json,
)

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
MAX_FILE_SIZE_MB = 500


def validate_video_extension(filename: str | None) -> str:
    ext = os.path.splitext(filename or "")[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"지원하지 않는 형식입니다. 허용: {sorted(ALLOWED_EXTENSIONS)}")
    return ext


async def save_upload_to_temp(file: UploadFile) -> tuple[str, str]:
    """업로드 파일을 임시 경로에 저장. (tmp_path, ext) 반환."""
    ext = validate_video_extension(file.filename)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise ValueError(f"파일 크기가 {MAX_FILE_SIZE_MB}MB를 초과합니다.")
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        return tmp.name, ext


def run_extraction_and_save(video_path: str) -> Dict[str, Any]:
    """영상 경로 → 추출 후 JSON 저장. 추출 메타 반환."""
    result = extract_rhythm_data(video_path)
    ensure_storage_dirs()
    base = make_extraction_basename()
    json_name = f"{base}.json"
    save_extraction_json(result, json_name)
    result["extraction_id"] = base
    result["extraction_json"] = build_json_meta(json_name)
    result["json_filename"] = json_name
    return result


def run_analyze(user_video_path: str, genre: str = "girl_idol") -> Dict[str, Any]:
    """영상 경로 → 추출 → 리듬 채점 → 결과 반환."""
    t0 = time.perf_counter()
    extraction = run_extraction_and_save(user_video_path)
    t1 = time.perf_counter()

    score_result = score_rhythm_from_extraction(extraction, genre=genre)
    t2 = time.perf_counter()

    return {
        "extraction_id": extraction["extraction_id"],
        "extraction_json": extraction["extraction_json"],
        "fps": extraction.get("fps"),
        "total_frames": extraction.get("total_frames"),
        "scores": {"rhythm": score_result},
        "timing_sec": {
            "extraction": round(t1 - t0, 3),
            "scoring": round(t2 - t1, 3),
            "total": round(t2 - t0, 3),
        },
    }


def run_analyze_with_beats(user_video_path: str, genre: str = "girl_idol") -> Dict[str, Any]:
    """영상 경로 → 포즈 추출 + 비트 추출 → 음악 비트 대비 동작 채점."""
    t0 = time.perf_counter()
    extraction = run_extraction_and_save(user_video_path)
    t1 = time.perf_counter()

    beat_data = extract_beats(user_video_path)
    t2 = time.perf_counter()

    score_result = score_motion_vs_beats(extraction, beat_data, genre=genre)
    t3 = time.perf_counter()

    base = make_extraction_basename()
    out_name = f"{base}_rhythm.mp4"
    render_rhythm_video(user_video_path, extraction, beat_data, score_result, out_name)
    t4 = time.perf_counter()

    return {
        "extraction_id": extraction["extraction_id"],
        "extraction_json": extraction["extraction_json"],
        "fps": extraction.get("fps"),
        "total_frames": extraction.get("total_frames"),
        "music_tempo_bpm": beat_data["tempo_bpm"],
        "video": build_annotated_video_meta(out_name),
        "scores": {"rhythm": score_result},
        "timing_sec": {
            "pose_extraction": round(t1 - t0, 3),
            "beat_extraction": round(t2 - t1, 3),
            "scoring": round(t3 - t2, 3),
            "render": round(t4 - t3, 3),
            "total": round(t4 - t0, 3),
        },
    }


def run_visualize(user_video_path: str, beat: bool = False, genre: str = "girl_idol") -> Dict[str, Any]:
    """영상 → 추출 (+ 선택적 비트) → 시각화 영상 생성."""
    t0 = time.perf_counter()
    extraction = run_extraction_and_save(user_video_path)
    t1 = time.perf_counter()

    beat_data = None
    score_result = None
    if beat:
        beat_data = extract_beats(user_video_path)
        score_result = score_motion_vs_beats(extraction, beat_data, genre=genre)
    t2 = time.perf_counter()

    base = make_extraction_basename()
    out_name = f"{base}_rhythm.mp4"
    render_rhythm_video(user_video_path, extraction, beat_data, score_result, out_name)
    t3 = time.perf_counter()

    timing: Dict[str, Any] = {
        "extraction": round(t1 - t0, 3),
        "render": round(t3 - t2, 3),
        "total": round(t3 - t0, 3),
    }
    if beat:
        timing["beat_and_scoring"] = round(t2 - t1, 3)

    return {
        "extraction_id": extraction["extraction_id"],
        "video": build_annotated_video_meta(out_name),
        "music_tempo_bpm": beat_data["tempo_bpm"] if beat_data else None,
        "scores": {"rhythm": score_result} if score_result else None,
        "timing_sec": timing,
    }


def run_compare_visualize(
    user_video_path: str,
    ref_video_path: str,
    genre: str = "girl_idol",
) -> Dict[str, Any]:
    """원본·사용자 나란히 비교 영상 생성 — 싱크 불일치 구간 검은 화면."""
    t0 = time.perf_counter()
    user_extraction = run_extraction_and_save(user_video_path)
    t1 = time.perf_counter()

    ref_extraction = extract_rhythm_data(ref_video_path)
    t2 = time.perf_counter()

    base = make_extraction_basename()
    out_name = f"{base}_compare.mp4"
    render_comparison_video(
        user_video_path, ref_video_path,
        user_extraction, ref_extraction,
        genre=genre, output_filename=out_name,
    )
    t3 = time.perf_counter()

    return {
        "extraction_id": user_extraction["extraction_id"],
        "video": build_annotated_video_meta(out_name),
        "genre": genre,
        "timing_sec": {
            "user_extraction": round(t1 - t0, 3),
            "ref_extraction": round(t2 - t1, 3),
            "render": round(t3 - t2, 3),
            "total": round(t3 - t0, 3),
        },
    }


def run_visualize_full(user_video_path: str, ref_video_path: str, genre: str = "girl_idol") -> Dict[str, Any]:
    """원본 + 사용자 나란히 비교 영상 + 통합 채점 (DTW·비트) 결과 반환."""
    t0 = time.perf_counter()
    user_extraction = run_extraction_and_save(user_video_path)
    t1 = time.perf_counter()

    ref_extraction = extract_rhythm_data(ref_video_path)
    beat_data = extract_beats(ref_video_path)
    t2 = time.perf_counter()

    score_result = score_motion_full(user_extraction, ref_extraction, beat_data, genre=genre)
    t3 = time.perf_counter()

    base = make_extraction_basename()
    out_name = f"{base}_full_compare.mp4"
    # 원본(왼쪽)·사용자(오른쪽) 나란히 비교 — 싱크 불일치 구간 검은 화면
    render_comparison_video(
        user_video_path, ref_video_path,
        user_extraction, ref_extraction,
        genre=genre, output_filename=out_name,
    )
    t4 = time.perf_counter()

    return {
        "extraction_id": user_extraction["extraction_id"],
        "video": build_annotated_video_meta(out_name),
        "music_tempo_bpm": beat_data["tempo_bpm"],
        "scores": {"rhythm": score_result},
        "timing_sec": {
            "user_extraction": round(t1 - t0, 3),
            "ref_extraction_and_beats": round(t2 - t1, 3),
            "scoring": round(t3 - t2, 3),
            "render": round(t4 - t3, 3),
            "total": round(t4 - t0, 3),
        },
    }


def run_analyze_full(
    user_video_path: str,
    ref_video_path: str,
    genre: str = "girl_idol",
) -> Dict[str, Any]:
    """레퍼런스 영상 + 사용자 영상 → 통합 채점 (와우포인트 30% + 비트 70%)."""
    t0 = time.perf_counter()
    user_extraction = run_extraction_and_save(user_video_path)
    t1 = time.perf_counter()

    ref_extraction = extract_rhythm_data(ref_video_path)
    t2 = time.perf_counter()

    beat_data = extract_beats(ref_video_path)
    t3 = time.perf_counter()

    score_result = score_motion_full(user_extraction, ref_extraction, beat_data, genre=genre)
    t4 = time.perf_counter()

    base = make_extraction_basename()
    out_name = f"{base}_full_compare.mp4"
    render_comparison_video(
        user_video_path, ref_video_path,
        user_extraction, ref_extraction,
        genre=genre, output_filename=out_name,
    )
    t5 = time.perf_counter()

    return {
        "extraction_id": user_extraction["extraction_id"],
        "extraction_json": user_extraction["extraction_json"],
        "fps": user_extraction.get("fps"),
        "total_frames": user_extraction.get("total_frames"),
        "ref_total_frames": ref_extraction.get("total_frames"),
        "music_tempo_bpm": beat_data["tempo_bpm"],
        "video": build_annotated_video_meta(out_name),
        "scores": {"rhythm": score_result},
        "timing_sec": {
            "user_pose_extraction": round(t1 - t0, 3),
            "ref_pose_extraction": round(t2 - t1, 3),
            "ref_beat_extraction": round(t3 - t2, 3),
            "scoring": round(t4 - t3, 3),
            "render": round(t5 - t4, 3),
            "total": round(t5 - t0, 3),
        },
    }


def run_analyze_with_reference(
    user_video_path: str,
    ref_video_path: str,
    genre: str = "girl_idol",
) -> Dict[str, Any]:
    """사용자 영상 + 레퍼런스 영상 → DTW 기반 리듬 비교 채점."""
    t0 = time.perf_counter()
    user_extraction = run_extraction_and_save(user_video_path)
    t1 = time.perf_counter()

    ref_extraction = extract_rhythm_data(ref_video_path)
    t2 = time.perf_counter()

    score_result = score_rhythm_vs_reference(user_extraction, ref_extraction, genre=genre)
    t3 = time.perf_counter()

    return {
        "extraction_id": user_extraction["extraction_id"],
        "extraction_json": user_extraction["extraction_json"],
        "fps": user_extraction.get("fps"),
        "total_frames": user_extraction.get("total_frames"),
        "ref_total_frames": ref_extraction.get("total_frames"),
        "scores": {"rhythm": score_result},
        "timing_sec": {
            "user_extraction": round(t1 - t0, 3),
            "ref_extraction": round(t2 - t1, 3),
            "scoring": round(t3 - t2, 3),
            "total": round(t3 - t0, 3),
        },
    }
