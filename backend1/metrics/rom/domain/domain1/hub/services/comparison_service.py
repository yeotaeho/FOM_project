"""저장된 추출 JSON 2개를 로드해 비교·채점."""

from typing import Any, Dict, List, Literal

from .scoring.accuracy_scorer import score_accuracy, score_to_grade
from .scoring.alignment import (
    align_by_dtw,
    align_by_time,
    alignment_warning,
    compute_duplicate_ratio,
    detect_dance_start,
)
from .scoring.rom_scorer import score_rom
from .storage_paths import load_comparison_fields

SUPPORTED_ALIGNMENT = frozenset({"time", "dtw"})
DetailLevel = Literal["summary", "full"]
ScoringMode = Literal["linear", "dance"]

WEIGHT_ACCURACY = 0.30
WEIGHT_ROM = 0.15


def _validate_extraction(data: Dict[str, Any], label: str) -> None:
    if "frames" not in data or not isinstance(data["frames"], list):
        raise ValueError(f"{label}: 유효하지 않은 추출 JSON (frames 없음)")
    if not data["frames"]:
        raise ValueError(f"{label}: 프레임 데이터가 비어 있습니다.")


def _frames_after_offset(
    frames: List[Dict[str, Any]],
    offset_sec: float,
) -> List[Dict[str, Any]]:
    return [
        f
        for f in frames
        if float(f.get("time_sec", 0.0)) >= offset_sec
    ]


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


def _compute_total_score(
    accuracy_score: float | None,
    rom_score: float | None,
    *,
    enable_accuracy: bool,
    enable_rom: bool,
) -> float:
    if enable_accuracy and enable_rom and rom_score is not None and accuracy_score is not None:
        total_weight = WEIGHT_ACCURACY + WEIGHT_ROM
        blended = (
            accuracy_score * WEIGHT_ACCURACY + rom_score * WEIGHT_ROM
        ) / total_weight
        return round(blended, 2)
    if enable_rom and rom_score is not None:
        return round(rom_score, 2)
    if enable_accuracy and accuracy_score is not None:
        return round(accuracy_score, 2)
    raise ValueError("enable_accuracy 또는 enable_rom 중 하나는 True여야 합니다.")


def compute_comparison(
    user_json_filename: str,
    reference_json_filename: str,
    alignment_method: str = "time",
    user_offset_sec: float = 0.0,
    ref_offset_sec: float = 0.0,
    auto_detect_start: bool = False,
    detail_level: DetailLevel = "summary",
    scoring_mode: ScoringMode = "dance",
    enable_accuracy: bool = False,
    enable_rom: bool = True,
) -> Dict[str, Any]:
    """
    video_json에 저장된 두 파일을 로드해 Accuracy·ROM 비교 결과 반환.
    ROM metric 기본: enable_accuracy=False, enable_rom=True.
    """
    if not enable_accuracy and not enable_rom:
        raise ValueError("enable_accuracy 또는 enable_rom 중 하나는 True여야 합니다.")

    if alignment_method not in SUPPORTED_ALIGNMENT:
        raise ValueError(
            f"지원하지 않는 정렬 방식: {alignment_method}. "
            f"허용: {sorted(SUPPORTED_ALIGNMENT)}"
        )

    user_data = load_comparison_fields(user_json_filename)
    ref_data = load_comparison_fields(reference_json_filename)
    _validate_extraction(user_data, "user_json")
    _validate_extraction(ref_data, "reference_json")

    user_frames: List[Dict[str, Any]] = user_data["frames"]
    ref_frames: List[Dict[str, Any]] = ref_data["frames"]

    ratio = len(user_frames) / max(len(ref_frames), 1)
    if ratio > 10 or ratio < 0.1:
        raise ValueError(
            "두 영상의 길이(프레임 수) 차이가 너무 큽니다. "
            f"user={len(user_frames)}, ref={len(ref_frames)}"
        )

    effective_user_offset, effective_ref_offset = _resolve_offsets(
        user_frames,
        ref_frames,
        user_offset_sec,
        ref_offset_sec,
        auto_detect_start,
    )

    user_active = _frames_after_offset(user_frames, effective_user_offset)
    ref_active = _frames_after_offset(ref_frames, effective_ref_offset)

    aligned_pairs: List[Dict[str, Any]] = []
    duplicate_ratio = 0.0
    accuracy = None

    if enable_accuracy:
        if alignment_method == "dtw":
            aligned_pairs = align_by_dtw(
                user_frames,
                ref_frames,
                user_offset=effective_user_offset,
                ref_offset=effective_ref_offset,
            )
        else:
            aligned_pairs = align_by_time(
                user_frames,
                ref_frames,
                user_offset=effective_user_offset,
                ref_offset=effective_ref_offset,
            )

        if not aligned_pairs:
            raise ValueError(
                "정렬된 프레임 쌍이 없습니다. 오프셋·영상 길이를 확인하세요."
            )

        duplicate_ratio = compute_duplicate_ratio(aligned_pairs)
        accuracy = score_accuracy(
            aligned_pairs,
            detail_level=detail_level,
            scoring_mode=scoring_mode,
        )

    rom_result = None
    if enable_rom:
        if not user_active or not ref_active:
            raise ValueError(
                "ROM 계산용 활성 프레임이 없습니다. 오프셋을 확인하세요."
            )
        rom_result = score_rom(user_active, ref_active)

    warnings: List[str] = []
    if enable_accuracy:
        warn_msg = alignment_warning(duplicate_ratio, alignment_method)
        if warn_msg:
            warnings.append(warn_msg)

    alignment_block: Dict[str, Any] = {
        "method": alignment_method if enable_accuracy else None,
        "pair_count": len(aligned_pairs) if enable_accuracy else 0,
        "duplicate_ratio": duplicate_ratio if enable_accuracy else None,
        "user_offset_sec": round(effective_user_offset, 4),
        "ref_offset_sec": round(effective_ref_offset, 4),
        "auto_detect_start": auto_detect_start,
    }
    if enable_accuracy and detail_level == "full":
        alignment_block["aligned_pairs"] = [
            {"user_frame": p["user_frame"], "ref_frame": p["ref_frame"]}
            for p in aligned_pairs
        ]

    rom_score = rom_result["score"] if rom_result else None
    accuracy_score = accuracy["score"] if accuracy else None
    total_score = _compute_total_score(
        accuracy_score,
        rom_score,
        enable_accuracy=enable_accuracy,
        enable_rom=enable_rom,
    )

    scores_block: Dict[str, Any] = {
        "total_score": total_score,
        "grade": score_to_grade(total_score),
    }
    if accuracy is not None:
        scores_block["accuracy"] = accuracy
    if rom_result is not None:
        scores_block["rom"] = rom_result

    return {
        "user_json": user_json_filename,
        "reference_json": reference_json_filename,
        "alignment": alignment_block,
        "scores": scores_block,
        "meta": {
            "user_fps": user_data.get("fps"),
            "user_total_frames": user_data.get("total_frames"),
            "user_schema": user_data.get("schema"),
            "reference_fps": ref_data.get("fps"),
            "reference_total_frames": ref_data.get("total_frames"),
            "reference_schema": ref_data.get("schema"),
            "detail_level": detail_level,
            "scoring_mode": scoring_mode,
            "enable_accuracy": enable_accuracy,
            "enable_rom": enable_rom,
            "score_weights": {
                "accuracy": WEIGHT_ACCURACY if enable_accuracy else 0.0,
                "rom": WEIGHT_ROM if enable_rom and enable_accuracy else 0.0,
            },
            "warnings": warnings,
        },
    }
