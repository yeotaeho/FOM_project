"""
6-metric analyze 오케스트레이터 — ARCHITECTURE.md §3.

저장된 추출 JSON 2개 → 정렬 → score_* 병렬 실행 → scores 병합.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Literal, Optional

from domain.domain1.hub.services.scoring.accuracy_scorer import score_accuracy, score_to_grade
from domain.domain1.hub.services.scoring.alignment import (
    align_by_dtw,
    align_by_time,
    alignment_warning,
    compute_duplicate_ratio,
    detect_dance_start,
)
from domain.domain1.hub.services.scoring.rom_scorer import score_rom
from domain.domain1.hub.services.storage_paths import load_comparison_fields, load_extraction_json

from metrics.creativity.creativity import score_creativity
from metrics.isolation.integration import score_isolation_for_fom
from metrics.isolation.config import REF_ISOLATION_JSON_FILENAME
from metrics.isolation.score import score_isolation
from metrics.power import score_power
from metrics.rhythm.services.scoring.rhythm_scorer import (
    score_rhythm_combined,
    score_rhythm_from_extraction,
    score_rhythm_vs_reference,
)

MetricKey = Literal[
    "accuracy", "creativity", "isolation", "power", "rhythm", "rom"
]

DEFAULT_METRICS: tuple[MetricKey, ...] = (
    "accuracy",
    "creativity",
    "isolation",
    "power",
    "rhythm",
    "rom",
)

METRIC_WEIGHTS: Dict[str, float] = {
    "accuracy": 1.0,
    "creativity": 1.0,
    "isolation": 1.0,
    "power": 1.0,
    "rhythm": 1.0,
    "rom": 1.0,
}

_executor = ThreadPoolExecutor(max_workers=6)


def _frames_after_offset(
    frames: List[Dict[str, Any]], offset_sec: float
) -> List[Dict[str, Any]]:
    return [f for f in frames if float(f.get("time_sec", 0.0)) >= offset_sec]


def _resolve_offsets(
    user_frames: List[Dict[str, Any]],
    ref_frames: List[Dict[str, Any]],
    user_offset_sec: float,
    ref_offset_sec: float,
    auto_detect_start: bool,
) -> tuple[float, float]:
    if auto_detect_start:
        return (
            detect_dance_start(user_frames),
            detect_dance_start(ref_frames),
        )
    return user_offset_sec, ref_offset_sec


def build_aligned_pairs(
    user_frames: List[Dict[str, Any]],
    ref_frames: List[Dict[str, Any]],
    *,
    alignment_method: str = "time",
    user_offset_sec: float = 0.0,
    ref_offset_sec: float = 0.0,
    auto_detect_start: bool = False,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """프레임 정렬 + alignment 메타."""
    effective_user, effective_ref = _resolve_offsets(
        user_frames, ref_frames, user_offset_sec, ref_offset_sec, auto_detect_start
    )
    if alignment_method == "dtw":
        pairs = align_by_dtw(
            user_frames,
            ref_frames,
            user_offset=effective_user,
            ref_offset=effective_ref,
        )
    else:
        pairs = align_by_time(
            user_frames,
            ref_frames,
            user_offset=effective_user,
            ref_offset=effective_ref,
        )
    dup = compute_duplicate_ratio(pairs)
    meta = {
        "method": alignment_method,
        "pair_count": len(pairs),
        "duplicate_ref_ratio": dup,
        "user_offset_sec": round(effective_user, 4),
        "ref_offset_sec": round(effective_ref, 4),
        "auto_detect_start": auto_detect_start,
        "warning": alignment_warning(dup, alignment_method),
    }
    return pairs, meta


def _metric_error(name: str, exc: BaseException) -> Dict[str, Any]:
    return {
        "score": 0.0,
        "breakdown": {"error": str(exc), "metric": name},
        "frame_diffs": [],
    }


def _run_accuracy(
    aligned_pairs: List[Dict[str, Any]],
    *,
    detail_level: str,
    scoring_mode: str,
) -> Dict[str, Any]:
    if not aligned_pairs:
        raise ValueError("accuracy: 정렬된 프레임 쌍이 없습니다.")
    return score_accuracy(
        aligned_pairs,
        detail_level=detail_level,  # type: ignore[arg-type]
        scoring_mode=scoring_mode,  # type: ignore[arg-type]
    )


def _run_creativity(aligned_pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not aligned_pairs:
        raise ValueError("creativity: 정렬된 프레임 쌍이 없습니다.")
    return score_creativity(aligned_pairs)


def _run_isolation(
    *,
    aligned_pairs: List[Dict[str, Any]],
    user_isolation_json: Optional[str] = None,
    reference_isolation_json: str = REF_ISOLATION_JSON_FILENAME,
    user_video_path: Optional[str] = None,
    user_offset_sec: float = 0.0,
    ref_offset_sec: float = 0.0,
    auto_detect_start: bool = False,
) -> Dict[str, Any]:
    """
    isolation 채점.

    - user_isolation_json 있음: YOLO sidecar + beat 정렬 (무거운 추출 후)
    - 없음: ROM time/dtw aligned_pairs 로 score_isolation (통합 analyze 기본)
    """
    if user_isolation_json:
        return score_isolation_for_fom(
            user_isolation_json,
            reference_isolation_json,
            user_video_path=user_video_path,
            user_offset_sec=user_offset_sec,
            ref_offset_sec=ref_offset_sec,
            auto_detect_start=auto_detect_start,
        )
    if not aligned_pairs:
        raise ValueError(
            "isolation: aligned_pairs 또는 user isolation JSON이 필요합니다."
        )
    result = score_isolation(aligned_pairs)
    breakdown = dict(result.get("breakdown") or {})
    breakdown["scoring_source"] = "rom_aligned_pairs"
    result["breakdown"] = breakdown
    return result


def _run_rom(
    user_frames: List[Dict[str, Any]],
    ref_frames: List[Dict[str, Any]],
    *,
    user_offset_sec: float,
    ref_offset_sec: float,
    auto_detect_start: bool,
) -> Dict[str, Any]:
    u_off, r_off = _resolve_offsets(
        user_frames, ref_frames, user_offset_sec, ref_offset_sec, auto_detect_start
    )
    user_active = _frames_after_offset(user_frames, u_off)
    ref_active = _frames_after_offset(ref_frames, r_off)
    if not user_active or not ref_active:
        raise ValueError("rom: 활성 프레임이 없습니다.")
    return score_rom(user_active, ref_active)


def _run_power(user_extraction: Dict[str, Any]) -> Dict[str, Any]:
    return score_power(user_extraction)


def _run_rhythm(
    user_extraction: Dict[str, Any],
    ref_extraction: Dict[str, Any],
    user_video_path: Optional[str] = None,
) -> Dict[str, Any]:
    user_frames = user_extraction.get("frames") or []
    ref_frames = ref_extraction.get("frames") or []
    ref_has_landmarks = bool(ref_frames and ref_frames[0].get("normalized_landmarks"))

    if not (len(user_frames) >= 2 and len(ref_frames) >= 2 and ref_has_landmarks):
        result = score_rhythm_from_extraction(user_extraction)
        if ref_frames and not ref_has_landmarks:
            result.setdefault("breakdown", {})["warning"] = (
                "ref_no_normalized_landmarks: reference JSON이 rom 모드 — 자기일관성으로만 채점"
            )
        return result

    # 음악 비트 추출 시도 — 성공하면 에너지+와우+비트 통합 채점, 실패하면 에너지+와우만
    beat_data = None
    if user_video_path:
        try:
            from metrics.rhythm.services.beat_service import extract_beats
            beat_data = extract_beats(user_video_path)
        except Exception:
            pass

    if beat_data:
        return score_rhythm_combined(user_extraction, ref_extraction, beat_data)
    return score_rhythm_vs_reference(user_extraction, ref_extraction)


def compute_total_score(scores: Dict[str, Dict[str, Any]]) -> tuple[float, str]:
    """6 metric 평균 → total_score, grade."""
    usable: List[float] = []
    for key, block in scores.items():
        if block.get("breakdown", {}).get("error"):
            continue
        s = block.get("score")
        if s is not None:
            usable.append(float(s))
    if not usable:
        return 0.0, "D"
    avg = round(sum(usable) / len(usable), 2)
    return avg, score_to_grade(avg)


async def _run_metric_in_executor(
    fn: Callable[[], Dict[str, Any]],
) -> Dict[str, Any]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, fn)


async def run_all_scores(
    *,
    aligned_pairs: List[Dict[str, Any]],
    user_extraction: Dict[str, Any],
    ref_extraction: Dict[str, Any],
    user_frames: List[Dict[str, Any]],
    ref_frames: List[Dict[str, Any]],
    enabled_metrics: List[str],
    detail_level: str = "summary",
    scoring_mode: str = "dance",
    user_offset_sec: float = 0.0,
    ref_offset_sec: float = 0.0,
    auto_detect_start: bool = False,
    fail_fast: bool = False,
    user_isolation_json: Optional[str] = None,
    reference_isolation_json: Optional[str] = None,
    user_video_path: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    ref_iso_name = reference_isolation_json or REF_ISOLATION_JSON_FILENAME
    """
    ARCHITECTURE §3.2 — asyncio.gather + run_in_executor.

    fail_fast=True 이면 첫 예외 시 전체 실패 (ARCHITECTURE 기본).
    fail_fast=False 이면 실패 metric 은 breakdown.error 로 기록.
    """
    tasks: Dict[str, asyncio.Task] = {}

    if "accuracy" in enabled_metrics:
        tasks["accuracy"] = asyncio.create_task(
            _run_metric_in_executor(
                lambda: _run_accuracy(
                    aligned_pairs,
                    detail_level=detail_level,
                    scoring_mode=scoring_mode,
                )
            )
        )
    if "creativity" in enabled_metrics:
        tasks["creativity"] = asyncio.create_task(
            _run_metric_in_executor(lambda: _run_creativity(aligned_pairs))
        )
    if "isolation" in enabled_metrics:
        tasks["isolation"] = asyncio.create_task(
            _run_metric_in_executor(
                lambda: _run_isolation(
                    aligned_pairs=aligned_pairs,
                    user_isolation_json=user_isolation_json or None,
                    reference_isolation_json=ref_iso_name,
                    user_video_path=user_video_path,
                    user_offset_sec=user_offset_sec,
                    ref_offset_sec=ref_offset_sec,
                    auto_detect_start=auto_detect_start,
                )
            )
        )
    if "rom" in enabled_metrics:
        tasks["rom"] = asyncio.create_task(
            _run_metric_in_executor(
                lambda: _run_rom(
                    user_frames,
                    ref_frames,
                    user_offset_sec=user_offset_sec,
                    ref_offset_sec=ref_offset_sec,
                    auto_detect_start=auto_detect_start,
                )
            )
        )
    if "power" in enabled_metrics:
        tasks["power"] = asyncio.create_task(
            _run_metric_in_executor(lambda: _run_power(user_extraction))
        )
    if "rhythm" in enabled_metrics:
        _uvp = user_video_path
        tasks["rhythm"] = asyncio.create_task(
            _run_metric_in_executor(
                lambda: _run_rhythm(user_extraction, ref_extraction, _uvp)
            )
        )

    results: Dict[str, Dict[str, Any]] = {}
    if fail_fast:
        gathered = await asyncio.gather(*tasks.values())
        for key, value in zip(tasks.keys(), gathered):
            results[key] = value
        return results

    for key, task in tasks.items():
        try:
            results[key] = await task
        except Exception as exc:
            results[key] = _metric_error(key, exc)
    return results


def resolve_metrics_list(
    metrics: Optional[List[str]],
    *,
    enable_accuracy: bool = False,
    enable_rom: bool = True,
) -> List[str]:
    """
    요청 metrics → 실행 목록.

    metrics 가 None/비어 있으면 6개 전체(기본).
    ROM만 등 부분 채점: metrics=["rom"] 등으로 명시.
    enable_accuracy / enable_rom 은 metrics 미지정 시에는 사용하지 않음(하위 호환용 인자).
    """
    if metrics:
        invalid = [m for m in metrics if m not in DEFAULT_METRICS]
        if invalid:
            raise ValueError(
                f"지원하지 않는 metric: {invalid}. 허용: {list(DEFAULT_METRICS)}"
            )
        return list(metrics)
    return list(DEFAULT_METRICS)


async def run_analyze_from_json(
    user_json_filename: str,
    reference_json_filename: str,
    *,
    alignment_method: str = "time",
    user_offset_sec: float = 0.0,
    ref_offset_sec: float = 0.0,
    auto_detect_start: bool = False,
    detail_level: str = "summary",
    scoring_mode: str = "dance",
    metrics: Optional[List[str]] = None,
    enable_accuracy: bool = False,
    enable_rom: bool = True,
    fail_fast: bool = False,
    user_isolation_json: Optional[str] = None,
    reference_isolation_json: Optional[str] = None,
    user_video_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    POST /video/analyze/json 오케스트레이터 진입점.
    """
    ref_iso_name = reference_isolation_json or REF_ISOLATION_JSON_FILENAME
    if alignment_method not in ("time", "dtw"):
        raise ValueError(
            f"지원하지 않는 alignment: {alignment_method}. 허용: time, dtw"
        )

    enabled = resolve_metrics_list(
        metrics,
        enable_accuracy=enable_accuracy,
        enable_rom=enable_rom,
    )

    user_cmp = load_comparison_fields(user_json_filename)
    ref_cmp = load_comparison_fields(reference_json_filename)
    user_frames = user_cmp.get("frames") or []
    ref_frames = ref_cmp.get("frames") or []

    if not user_frames:
        raise ValueError("user_json: 프레임 데이터가 비어 있습니다.")
    if not ref_frames:
        raise ValueError("reference_json: 프레임 데이터가 비어 있습니다.")

    ratio = len(user_frames) / max(len(ref_frames), 1)
    if ratio > 10 or ratio < 0.1:
        raise ValueError(
            f"두 영상 길이 차이가 큽니다. user={len(user_frames)}, ref={len(ref_frames)}"
        )

    aligned_pairs, align_meta = build_aligned_pairs(
        user_frames,
        ref_frames,
        alignment_method=alignment_method,
        user_offset_sec=user_offset_sec,
        ref_offset_sec=ref_offset_sec,
        auto_detect_start=auto_detect_start,
    )

    needs_pairs = bool(set(enabled) & {"accuracy", "creativity"})
    if needs_pairs and not aligned_pairs:
        raise ValueError("정렬된 프레임 쌍이 없습니다. 오프셋·영상 길이를 확인하세요.")

    user_full = load_extraction_json(user_json_filename)
    ref_full = load_extraction_json(reference_json_filename)

    metric_scores = await run_all_scores(
        aligned_pairs=aligned_pairs,
        user_extraction=user_full,
        ref_extraction=ref_full,
        user_frames=user_frames,
        ref_frames=ref_frames,
        enabled_metrics=enabled,
        detail_level=detail_level,
        scoring_mode=scoring_mode,
        user_offset_sec=user_offset_sec,
        ref_offset_sec=ref_offset_sec,
        auto_detect_start=auto_detect_start,
        fail_fast=fail_fast,
        user_isolation_json=user_isolation_json,
        reference_isolation_json=ref_iso_name,
        user_video_path=user_video_path,
    )

    total_score, grade = compute_total_score(metric_scores)
    warnings: List[str] = []
    if align_meta.get("warning"):
        warnings.append(align_meta["warning"])

    return {
        "user_json": user_json_filename,
        "reference_json": reference_json_filename,
        "alignment": align_meta,
        "scores": {
            **metric_scores,
            "total_score": total_score,
            "grade": grade,
        },
        "meta": {
            "metrics_run": enabled,
            "user_isolation_json": user_isolation_json,
            "reference_isolation_json": ref_iso_name,
            "user_fps": user_cmp.get("fps"),
            "user_total_frames": user_cmp.get("total_frames"),
            "user_schema": user_cmp.get("schema"),
            "reference_fps": ref_cmp.get("fps"),
            "reference_total_frames": ref_cmp.get("total_frames"),
            "reference_schema": ref_cmp.get("schema"),
            "detail_level": detail_level,
            "scoring_mode": scoring_mode,
            "warnings": warnings,
        },
    }
