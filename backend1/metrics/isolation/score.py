"""
Isolation 채점 — aligned_pairs 기준.

프레임 간 bone 움직임: ref 대비 user의 비목표 부위 연동(coupling) 페널티.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from metrics.isolation.align import align_and_save, align_from_paths
from metrics.isolation.pipeline.geometry import BONE_SEGMENTS
from metrics.isolation.pipeline.io import load_extraction_json, save_json

ALL_BONES: Tuple[str, ...] = tuple(name for name, _, _ in BONE_SEGMENTS)

REGION_BONES: Dict[str, Tuple[str, ...]] = {
    "torso": ("torso",),
    "arms": (
        "left_upper_arm",
        "left_forearm",
        "right_upper_arm",
        "right_forearm",
    ),
    "legs": (
        "left_thigh",
        "left_shin",
        "right_thigh",
        "right_shin",
        "left_foot",
        "right_foot",
    ),
}

_MOTION_EPS = 0.015
_RATIO_FLOOR = 0.08


def _bone_unit(bone: Dict[str, float]) -> np.ndarray:
    return np.array(
        [float(bone.get("x", 0)), float(bone.get("y", 0)), float(bone.get("z", 0))],
        dtype=np.float64,
    )


def _bone_motion(
    frame_a: Dict[str, Any],
    frame_b: Dict[str, Any],
    bone: str,
) -> float:
    """연속 프레임 bone 방향 변화량 (0~2 스케일)."""
    bv_a = (frame_a.get("bone_vectors") or {}).get(bone)
    bv_b = (frame_b.get("bone_vectors") or {}).get(bone)
    if not bv_a or not bv_b:
        return 0.0
    u0 = _bone_unit(bv_a)
    u1 = _bone_unit(bv_b)
    n0 = float(np.linalg.norm(u0))
    n1 = float(np.linalg.norm(u1))
    if n0 < 1e-8 or n1 < 1e-8:
        return 0.0
    u0 /= n0
    u1 /= n1
    cos_sim = float(np.clip(np.dot(u0, u1), -1.0, 1.0))
    angle_term = 1.0 - cos_sim
    mag_a = float(bv_a.get("magnitude", 0.0))
    mag_b = float(bv_b.get("magnitude", 0.0))
    mag_term = abs(mag_b - mag_a) / max(mag_a, mag_b, 1e-6)
    return angle_term + 0.5 * mag_term


def _coupling_ratio(motions: Dict[str, float], target_bone: str) -> float:
    target = motions.get(target_bone, 0.0)
    if target < _MOTION_EPS:
        return 0.0
    non_target = sum(v for k, v in motions.items() if k != target_bone)
    return non_target / (target + 1e-8)


def _frame_pair_isolation_score(
    ref_prev: Dict[str, Any],
    ref_curr: Dict[str, Any],
    user_prev: Dict[str, Any],
    user_curr: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    ref_motions = {b: _bone_motion(ref_prev, ref_curr, b) for b in ALL_BONES}
    user_motions = {b: _bone_motion(user_prev, user_curr, b) for b in ALL_BONES}

    target_bone = max(ref_motions, key=ref_motions.get)
    if ref_motions[target_bone] < _MOTION_EPS:
        return None

    ref_ratio = _coupling_ratio(ref_motions, target_bone)
    user_ratio = _coupling_ratio(user_motions, target_bone)

    # ref 대비 user coupling 초과분 페널티
    excess = max(0.0, user_ratio - ref_ratio)
    denom = max(ref_ratio, _RATIO_FLOOR)
    frame_score = 100.0 * max(0.0, 1.0 - excess / denom)
    frame_score = min(100.0, frame_score)

    # 정적 순간: 비목표 bone 방향이 ref 와 얼마나 같은지
    static_scores: List[float] = []
    for bone in ALL_BONES:
        if bone == target_bone:
            continue
        rb = (ref_curr.get("bone_vectors") or {}).get(bone)
        ub = (user_curr.get("bone_vectors") or {}).get(bone)
        if not rb or not ub:
            continue
        ur = _bone_unit(rb)
        uu = _bone_unit(ub)
        if np.linalg.norm(ur) < 1e-8 or np.linalg.norm(uu) < 1e-8:
            continue
        cos = float(np.clip(np.dot(ur, uu), -1.0, 1.0))
        static_scores.append((cos + 1.0) / 2.0 * 100.0)

    static_score = float(np.mean(static_scores)) if static_scores else frame_score
    combined = 0.65 * frame_score + 0.35 * static_score

    return {
        "score": round(combined, 2),
        "target_bone": target_bone,
        "ref_coupling": round(ref_ratio, 4),
        "user_coupling": round(user_ratio, 4),
        "motion_score": round(frame_score, 2),
        "static_score": round(static_score, 2),
    }


def score_isolation(aligned_pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    ARCHITECTURE §5 반환 형태.

    aligned_pairs: align_by_time 결과 (user/ref 프레임 dict 포함).
    """
    if not aligned_pairs:
        raise ValueError("aligned_pairs 가 비어 있습니다.")

    sorted_pairs = sorted(aligned_pairs, key=lambda p: (p["user_frame"], p["ref_frame"]))

    frame_diffs: List[Dict[str, Any]] = []
    region_scores: Dict[str, List[float]] = {k: [] for k in REGION_BONES}

    for i in range(1, len(sorted_pairs)):
        prev = sorted_pairs[i - 1]
        curr = sorted_pairs[i]
        detail = _frame_pair_isolation_score(
            prev["ref"], curr["ref"], prev["user"], curr["user"]
        )
        if detail is None:
            continue

        frame_diffs.append(
            {
                "user_frame": int(curr["user_frame"]),
                "ref_frame": int(curr["ref_frame"]),
                **detail,
            }
        )

        target = detail["target_bone"]
        for region, bones in REGION_BONES.items():
            if target in bones:
                region_scores[region].append(detail["score"])

    if not frame_diffs:
        return {
            "score": 0.0,
            "breakdown": {"error": "움직임 구간이 감지되지 않았습니다."},
            "frame_diffs": [],
        }

    scores = [f["score"] for f in frame_diffs]
    overall = float(np.mean(scores))

    ref_couplings = [f["ref_coupling"] for f in frame_diffs]
    user_couplings = [f["user_coupling"] for f in frame_diffs]

    by_region = {
        region: round(float(np.mean(vals)), 2) if vals else None
        for region, vals in region_scores.items()
    }

    worst = sorted(frame_diffs, key=lambda x: x["score"])[:5]

    return {
        "score": round(overall, 2),
        "breakdown": {
            "mean_frame_score": round(overall, 2),
            "scored_transitions": len(frame_diffs),
            "mean_ref_coupling": round(float(np.mean(ref_couplings)), 4),
            "mean_user_coupling": round(float(np.mean(user_couplings)), 4),
            "by_region": by_region,
            "worst_frames": worst,
        },
        "frame_diffs": frame_diffs,
    }


def score_from_alignment(alignment_result: Dict[str, Any]) -> Dict[str, Any]:
    pairs = alignment_result.get("pairs") or []
    result = score_isolation(pairs)
    result["alignment"] = alignment_result.get("alignment")
    return result


def score_from_json_files(
    user_json: str,
    ref_json: str,
    user_offset_sec: float = 0.0,
    ref_offset_sec: float = 0.0,
    auto_detect_start: bool = False,
    alignment_method: str = "beat",
    **align_kw: Any,
) -> Dict[str, Any]:
    aligned = align_from_paths(
        user_json,
        ref_json,
        user_offset_sec=user_offset_sec,
        ref_offset_sec=ref_offset_sec,
        auto_detect_start=auto_detect_start,
        method=alignment_method,  # type: ignore[arg-type]
        **align_kw,
    )
    return score_from_alignment(aligned)


def score_from_paths(
    user_json: str,
    ref_json: str,
    aligned_out: Optional[str] = None,
    score_out: Optional[str] = None,
    alignment_method: str = "beat",
    ref_compare_duration_sec: Optional[float] = None,
    **align_kw: Any,
) -> Dict[str, Any]:
    """align + score + 선택 저장."""
    from metrics.isolation.config import REF_COMPARE_DURATION_SEC

    if ref_compare_duration_sec is None and "ref_compare_duration_sec" not in align_kw:
        align_kw["ref_compare_duration_sec"] = REF_COMPARE_DURATION_SEC
    align_kw = {**align_kw, "method": alignment_method}
    if aligned_out:
        aligned = align_and_save(user_json, ref_json, aligned_out, **align_kw)
    else:
        aligned = align_from_paths(user_json, ref_json, **align_kw)
    result = score_from_alignment(aligned)
    if score_out:
        save_json(result, score_out)
    return result
