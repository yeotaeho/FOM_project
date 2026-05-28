"""
영상 → metric별 추출 병렬 조율 (ARCHITECTURE §1.1).

- 오케스트레이터(services/orchestrator.py)는 추출하지 않음.
- ROM domain1 video_json/ 에 canonical JSON 저장 후 파일명 반환.
- 채점은 routers/video → run_analyze_from_json 이 담당.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Literal, Optional

from domain.domain1.hub.services.extraction_pipeline import run_extraction_and_save
from domain.domain1.hub.services.storage_paths import (
    make_extraction_basename,
    save_extraction_json,
)

ExtractPipeline = Literal["rom", "rhythm", "power", "creativity", "isolation"]

DEFAULT_EXTRACT_PIPELINES: tuple[ExtractPipeline, ...] = (
    "rom",
    "power",
    "creativity",
)

# _pipeline_fn 이 구현한 파이프라인 — 검증·오류 메시지용
# 통합 analyze 기본은 isolation(YOLO) 미실행 — 채점은 orchestrator가 ROM aligned_pairs 사용
# YOLO 추출이 필요하면 run_user_extractions_parallel(pipelines=[..., "isolation"]) 명시
SUPPORTED_EXTRACT_PIPELINES: tuple[ExtractPipeline, ...] = DEFAULT_EXTRACT_PIPELINES + (
    "isolation",
)

_executor = ThreadPoolExecutor(max_workers=len(SUPPORTED_EXTRACT_PIPELINES))

_CREATIVITY_NUM_FRAMES = 30


def _needs_full_rom_extraction(scoring_metrics: List[str]) -> bool:
    """accuracy·creativity 등은 full_v1 JSON 필요."""
    return bool(
        set(scoring_metrics)
        & {"accuracy", "creativity", "isolation", "power", "rhythm"}
    )


def _extract_error(name: str, exc: BaseException) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": str(exc),
        "metric": name,
    }


def _run_rom_extract(
    video_path: str,
    *,
    mode: Literal["rom", "full"],
    target_fps: Optional[float],
    frame_stride: Optional[int],
) -> Dict[str, Any]:
    meta = run_extraction_and_save(
        video_path,
        mode=mode,
        target_fps=target_fps,
        frame_stride=frame_stride,
    )
    return {
        "ok": True,
        "metric": "rom",
        "json_filename": meta["json_filename"],
        "canonical": True,
        "meta": {
            "extraction_id": meta.get("extraction_id"),
            "extraction_json": meta.get("extraction_json"),
            "annotated_video": meta.get("annotated_video"),
            "fps": meta.get("fps"),
            "total_frames": meta.get("total_frames"),
            "schema": meta.get("schema"),
        },
    }


def _run_rhythm_extract(video_path: str) -> Dict[str, Any]:
    from metrics.rhythm.services.extraction_service import extract_rhythm_data
    from metrics.rhythm.services.beat_service import extract_beats

    data = extract_rhythm_data(video_path)

    has_beats = False
    try:
        data["beat_data"] = extract_beats(video_path)
        has_beats = True
    except Exception:
        pass

    base = make_extraction_basename()
    filename = f"{base}_rhythm.json"
    save_extraction_json(data, filename)
    return {
        "ok": True,
        "metric": "rhythm",
        "json_filename": filename,
        "canonical": False,
        "meta": {
            "fps": data.get("fps"),
            "total_frames": data.get("total_frames"),
            "has_beat_data": has_beats,
        },
    }


def _run_power_extract(video_path: str) -> Dict[str, Any]:
    from metrics.power.extraction import extract_power_data

    data = extract_power_data(video_path)
    base = make_extraction_basename()
    filename = f"{base}_power.json"
    save_extraction_json(data, filename)
    return {
        "ok": True,
        "metric": "power",
        "json_filename": filename,
        "canonical": False,
        "meta": {"fps": data.get("fps"), "total_frames": len(data.get("frames", []))},
    }


def _run_isolation_extract(video_path: str) -> Dict[str, Any]:
    from metrics.isolation.integration import extract_isolation_to_video_json

    return extract_isolation_to_video_json(video_path)


def _run_creativity_extract(video_path: str) -> Dict[str, Any]:
    from metrics.creativity.extract import extract_from_media
    from metrics.creativity.preprocess import preprocess_extraction

    raw = extract_from_media(video_path)
    processed = preprocess_extraction(
        raw,
        _CREATIVITY_NUM_FRAMES,
        offset_sec=0.0,
        apply_mirror=True,
        visibility_threshold=0.5,
    )
    base = make_extraction_basename()
    filename = f"{base}_creativity.json"
    save_extraction_json(processed, filename)
    return {
        "ok": True,
        "metric": "creativity",
        "json_filename": filename,
        "canonical": False,
        "meta": {
            "frames_after_visibility": (
                (processed.get("preprocess") or {}).get("frames_after_visibility")
            ),
        },
    }


def _pipeline_fn(
    name: str,
    video_path: str,
    *,
    rom_mode: Literal["rom", "full"],
    target_fps: Optional[float],
    frame_stride: Optional[int],
) -> Callable[[], Dict[str, Any]]:
    if name == "rom":
        return lambda: _run_rom_extract(
            video_path,
            mode=rom_mode,
            target_fps=target_fps,
            frame_stride=frame_stride,
        )
    if name == "rhythm":
        return lambda: _run_rhythm_extract(video_path)
    if name == "power":
        return lambda: _run_power_extract(video_path)
    if name == "creativity":
        return lambda: _run_creativity_extract(video_path)
    if name == "isolation":
        return lambda: _run_isolation_extract(video_path)
    raise ValueError(
        f"지원하지 않는 추출 파이프라인: {name}. "
        f"허용: {list(SUPPORTED_EXTRACT_PIPELINES)}"
    )


async def _run_in_executor(fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, fn)


async def run_user_extractions_parallel(
    video_path: str,
    *,
    pipelines: Optional[List[str]] = None,
    scoring_metrics: Optional[List[str]] = None,
    extraction_mode: Literal["rom", "full"] = "rom",
    target_fps: Optional[float] = 15.0,
    frame_stride: Optional[int] = None,
    fail_fast: bool = False,
) -> Dict[str, Any]:
    """
    사용자 영상에 대해 metric별 extract_* 를 병렬 실행.

    Returns
    -------
    dict
        canonical_json: 채점용 ROM JSON 파일명 (video_json/)
        extractions: 파이프라인별 결과
        user: ROM 추출 공개 메타 (analyze 응답용)
    """
    if scoring_metrics and _needs_full_rom_extraction(scoring_metrics):
        rom_mode: Literal["rom", "full"] = "full"
    else:
        rom_mode = extraction_mode if extraction_mode == "full" else "rom"

    active = list(pipelines) if pipelines else list(DEFAULT_EXTRACT_PIPELINES)
    invalid = [p for p in active if p not in SUPPORTED_EXTRACT_PIPELINES]
    if invalid:
        raise ValueError(
            f"지원하지 않는 추출 파이프라인: {invalid}. "
            f"허용: {list(SUPPORTED_EXTRACT_PIPELINES)}"
        )
    if "rom" not in active:
        active = ["rom", *active]

    tasks: Dict[str, asyncio.Task] = {}
    for name in active:
        fn = _pipeline_fn(
            name,
            video_path,
            rom_mode=rom_mode,
            target_fps=target_fps,
            frame_stride=frame_stride,
        )
        tasks[name] = asyncio.create_task(_run_in_executor(fn))

    results: Dict[str, Dict[str, Any]] = {}
    if fail_fast:
        gathered = await asyncio.gather(*tasks.values())
        for key, value in zip(tasks.keys(), gathered):
            results[key] = value
    else:
        for key, task in tasks.items():
            try:
                results[key] = await task
            except Exception as exc:
                results[key] = _extract_error(key, exc)

    rom_block = results.get("rom") or {}
    if not rom_block.get("ok"):
        err = rom_block.get("error", "ROM 추출 실패")
        raise ValueError(f"canonical ROM 추출 실패: {err}")

    canonical = rom_block["json_filename"]
    return {
        "canonical_json": canonical,
        "extractions": results,
        "user": rom_block.get("meta") or {},
        "rom_mode": rom_mode,
        "pipelines_run": active,
    }
