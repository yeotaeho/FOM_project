"""ROM (Range of Motion): 관절 가동 범위 — 전문가 대비 커버리지."""

from typing import Any, Dict, List, Optional

# 레퍼런스 ROM이 이보다 작으면 해당 안무에서 거의 움직이지 않는 관절로 간주
STATIC_ROM_THRESHOLD_DEG = 10.0


def compute_joint_rom(frames: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    각 관절의 최대·최소 각도 차이(ROM, 도) 반환.
    입력 프레임: joint_angles 포함 dict 리스트.
    """
    angle_sequences: Dict[str, List[float]] = {}

    for frame in frames:
        angles = frame.get("joint_angles") or {}
        for joint, value in angles.items():
            if joint not in angle_sequences:
                angle_sequences[joint] = []
            angle_sequences[joint].append(float(value))

    rom: Dict[str, float] = {}
    for joint, values in angle_sequences.items():
        if not values:
            rom[joint] = 0.0
        else:
            rom[joint] = round(max(values) - min(values), 2)
    return rom


def _joint_angle_extrema(frames: List[Dict[str, Any]], joint: str) -> tuple[float, float]:
    values: List[float] = []
    for frame in frames:
        angles = frame.get("joint_angles") or {}
        if joint in angles:
            values.append(float(angles[joint]))
    if not values:
        return 0.0, 0.0
    return round(min(values), 2), round(max(values), 2)


def score_rom_coverage(
    user_rom: Dict[str, float],
    ref_rom: Dict[str, float],
    user_frames: Optional[List[Dict[str, Any]]] = None,
    ref_frames: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    사용자 ROM / 레퍼런스 ROM 비율로 관절별·전체 커버리지 점수 산출.
    """
    coverages: List[float] = []
    joint_details: Dict[str, Any] = {}

    all_joints = set(user_rom.keys()) | set(ref_rom.keys())
    for joint in sorted(all_joints):
        u_rom = float(user_rom.get(joint, 0.0))
        r_rom = float(ref_rom.get(joint, 0.0))

        detail: Dict[str, Any] = {
            "user_rom": round(u_rom, 2),
            "ref_rom": round(r_rom, 2),
        }

        if user_frames is not None:
            u_min, u_max = _joint_angle_extrema(user_frames, joint)
            detail["min_angle_user"] = u_min
            detail["max_angle_user"] = u_max
        if ref_frames is not None:
            r_min, r_max = _joint_angle_extrema(ref_frames, joint)
            detail["min_angle_ref"] = r_min
            detail["max_angle_ref"] = r_max

        if r_rom < STATIC_ROM_THRESHOLD_DEG:
            detail["coverage"] = 100.0
            detail["note"] = "static_joint"
            joint_details[joint] = detail
            continue

        if r_rom <= 0.0:
            coverage_pct = 100.0 if u_rom <= 0.0 else 0.0
        else:
            coverage_pct = min(u_rom / r_rom, 1.0) * 100.0

        detail["coverage"] = round(coverage_pct, 2)
        coverages.append(coverage_pct)
        joint_details[joint] = detail

    final_score = round(sum(coverages) / len(coverages), 2) if coverages else 0.0

    return {
        "score": final_score,
        "joint_details": joint_details,
        "active_joint_count": len(coverages),
    }


def score_rom(
    user_frames: List[Dict[str, Any]],
    ref_frames: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """사용자·전문가 프레임 시퀀스에서 ROM 점수 계산."""
    user_rom = compute_joint_rom(user_frames)
    ref_rom = compute_joint_rom(ref_frames)
    result = score_rom_coverage(
        user_rom,
        ref_rom,
        user_frames=user_frames,
        ref_frames=ref_frames,
    )
    result["grade"] = score_to_grade_rom(result["score"])
    return result


def score_to_grade_rom(score: float) -> str:
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    return "D"
