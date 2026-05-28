"""Accuracy: joint_angles + bone_vectors 코사인 (VIEWPOINT_INVARIANCE 기준)."""

from typing import Any, Dict, List, Literal, Tuple

ANGLE_WEIGHT = 0.6
BONE_WEIGHT = 0.4
MAX_ANGLE_DIFF_DEG = 180.0
WORST_FRAMES_COUNT = 10

ScoringMode = Literal["linear", "dance"]
DetailLevel = Literal["summary", "full"]


def _angle_similarity(
    user_deg: float,
    ref_deg: float,
    scoring_mode: ScoringMode = "dance",
) -> float:
    diff = abs(float(user_deg) - float(ref_deg))
    if scoring_mode == "linear":
        return max(0.0, 100.0 - (diff / MAX_ANGLE_DIFF_DEG) * 100.0)
    if diff <= 10:
        return 100.0 - diff * 0.5
    if diff <= 30:
        return 95.0 - (diff - 10) * 1.5
    if diff <= 60:
        return 65.0 - (diff - 30) * 1.5
    return max(0.0, 20.0 - (diff - 60) * 0.33)


def _bone_cosine_score(user_bv: Dict[str, float], ref_bv: Dict[str, float]) -> float:
    dot = (
        user_bv["x"] * ref_bv["x"]
        + user_bv["y"] * ref_bv["y"]
        + user_bv["z"] * ref_bv["z"]
    )
    dot = max(-1.0, min(1.0, float(dot)))
    return (dot + 1.0) / 2.0 * 100.0


def score_frame_pair(
    user_frame: Dict[str, Any],
    ref_frame: Dict[str, Any],
    scoring_mode: ScoringMode = "dance",
) -> Tuple[float, Dict[str, Any]]:
    u_angles = user_frame.get("joint_angles") or {}
    r_angles = ref_frame.get("joint_angles") or {}
    u_bones = user_frame.get("bone_vectors") or {}
    r_bones = ref_frame.get("bone_vectors") or {}

    angle_sims: List[float] = []
    joint_angle_diffs: Dict[str, float] = {}
    for key in u_angles:
        if key not in r_angles:
            continue
        diff = abs(float(u_angles[key]) - float(r_angles[key]))
        joint_angle_diffs[key] = round(diff, 4)
        angle_sims.append(_angle_similarity(u_angles[key], r_angles[key], scoring_mode))

    bone_sims: List[float] = []
    bone_vector_cosines: Dict[str, float] = {}
    for key in u_bones:
        if key not in r_bones:
            continue
        u = u_bones[key]
        r = r_bones[key]
        dot = u["x"] * r["x"] + u["y"] * r["y"] + u["z"] * r["z"]
        dot = max(-1.0, min(1.0, float(dot)))
        bone_vector_cosines[key] = round(dot, 4)
        bone_sims.append(_bone_cosine_score(u, r))

    angle_score = sum(angle_sims) / len(angle_sims) if angle_sims else 0.0
    bone_score = sum(bone_sims) / len(bone_sims) if bone_sims else 0.0

    if angle_sims and bone_sims:
        total = ANGLE_WEIGHT * angle_score + BONE_WEIGHT * bone_score
    elif angle_sims:
        total = angle_score
    elif bone_sims:
        total = bone_score
    else:
        total = 0.0

    detail = {
        "frame_score": round(total, 4),
        "joint_angle_diffs": joint_angle_diffs,
        "bone_vector_cosines": bone_vector_cosines,
        "angle_score": round(angle_score, 4),
        "bone_score": round(bone_score, 4),
    }
    return total, detail


def score_accuracy(
    aligned_pairs: List[Dict[str, Any]],
    detail_level: DetailLevel = "summary",
    scoring_mode: ScoringMode = "dance",
) -> Dict[str, Any]:
    if not aligned_pairs:
        empty: Dict[str, Any] = {
            "score": 0.0,
            "breakdown": {
                "joint_angles_similarity": 0.0,
                "bone_vectors_cosine": 0.0,
            },
        }
        if detail_level == "full":
            empty["frame_diffs"] = []
        else:
            empty["worst_frames"] = []
        return empty

    frame_scores: List[float] = []
    frame_diffs: List[Dict[str, Any]] = []
    angle_scores: List[float] = []
    bone_scores: List[float] = []

    for pair in aligned_pairs:
        score, detail = score_frame_pair(
            pair["user"], pair["ref"], scoring_mode=scoring_mode
        )
        frame_scores.append(score)
        angle_scores.append(detail["angle_score"])
        bone_scores.append(detail["bone_score"])
        frame_diffs.append({
            "user_frame": pair["user_frame"],
            "ref_frame": pair["ref_frame"],
            "frame_score": detail["frame_score"],
            "joint_angle_diffs": detail["joint_angle_diffs"],
            "bone_vector_cosines": detail["bone_vector_cosines"],
        })

    final = sum(frame_scores) / len(frame_scores)
    result: Dict[str, Any] = {
        "score": round(final, 2),
        "breakdown": {
            "joint_angles_similarity": round(
                sum(angle_scores) / len(angle_scores) if angle_scores else 0.0, 2
            ),
            "bone_vectors_cosine": round(
                sum(bone_scores) / len(bone_scores) if bone_scores else 0.0, 2
            ),
        },
    }

    if detail_level == "full":
        result["frame_diffs"] = frame_diffs
    else:
        worst = sorted(frame_diffs, key=lambda x: x["frame_score"])[:WORST_FRAMES_COUNT]
        result["worst_frames"] = worst

    return result


def score_to_grade(score: float) -> str:
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    return "D"
