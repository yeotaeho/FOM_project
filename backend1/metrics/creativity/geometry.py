"""창의성 채점용 포즈 기하 (bone_vectors, joint_angles)."""

from __future__ import annotations

import math
from typing import Dict, Tuple

_EPS = 1e-8

BONE_SEGMENTS: Tuple[Tuple[str, str, str], ...] = (
    ("torso", "mid_hip", "mid_shoulder"),
    ("left_upper_arm", "left_shoulder", "left_elbow"),
    ("left_forearm", "left_elbow", "left_wrist"),
    ("right_upper_arm", "right_shoulder", "right_elbow"),
    ("right_forearm", "right_elbow", "right_wrist"),
    ("left_thigh", "left_hip", "left_knee"),
    ("left_shin", "left_knee", "left_ankle"),
    ("right_thigh", "right_hip", "right_knee"),
    ("right_shin", "right_knee", "right_ankle"),
)

JOINT_ANGLE_TRIPLES: Tuple[Tuple[str, str, str, str], ...] = (
    ("left_elbow", "left_shoulder", "left_elbow", "left_wrist"),
    ("right_elbow", "right_shoulder", "right_elbow", "right_wrist"),
    ("left_knee", "left_hip", "left_knee", "left_ankle"),
    ("right_knee", "right_hip", "right_knee", "right_ankle"),
    ("left_shoulder", "left_elbow", "left_shoulder", "left_hip"),
    ("right_shoulder", "right_elbow", "right_shoulder", "right_hip"),
    ("left_hip", "left_shoulder", "left_hip", "left_knee"),
    ("right_hip", "right_shoulder", "right_hip", "right_knee"),
)


def _point(name: str, lms: Dict[str, dict]) -> tuple[float, float, float]:
    if name == "mid_hip":
        return (
            (lms["left_hip"]["x"] + lms["right_hip"]["x"]) / 2,
            (lms["left_hip"]["y"] + lms["right_hip"]["y"]) / 2,
            (lms["left_hip"]["z"] + lms["right_hip"]["z"]) / 2,
        )
    if name == "mid_shoulder":
        return (
            (lms["left_shoulder"]["x"] + lms["right_shoulder"]["x"]) / 2,
            (lms["left_shoulder"]["y"] + lms["right_shoulder"]["y"]) / 2,
            (lms["left_shoulder"]["z"] + lms["right_shoulder"]["z"]) / 2,
        )
    p = lms[name]
    return (p["x"], p["y"], p["z"])


def compute_bone_vectors(normalized_landmarks: Dict[str, dict]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for bone_name, start, end in BONE_SEGMENTS:
        fx, fy, fz = _point(start, normalized_landmarks)
        tx, ty, tz = _point(end, normalized_landmarks)
        vx, vy, vz = tx - fx, ty - fy, tz - fz
        mag = math.sqrt(vx * vx + vy * vy + vz * vz)
        if mag < _EPS:
            out[bone_name] = {"x": 0.0, "y": 0.0, "z": 0.0, "magnitude": 0.0}
        else:
            out[bone_name] = {
                "x": vx / mag,
                "y": vy / mag,
                "z": vz / mag,
                "magnitude": mag,
            }
    return out


CORE_JOINTS_FOR_CENTER = (
    "left_shoulder",
    "right_shoulder",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
)


def pose_center_score(
    landmarks: Dict[str, dict],
    visibility_threshold: float = 0.5,
) -> float:
    """화면 중앙(0.5,0.5)에 가까울수록 1에 가깝게."""
    xs: list[float] = []
    ys: list[float] = []
    for name in CORE_JOINTS_FOR_CENTER:
        p = landmarks.get(name)
        if not p:
            continue
        if float(p.get("visibility", 1.0)) < visibility_threshold:
            continue
        xs.append(float(p["x"]))
        ys.append(float(p["y"]))
    if not xs:
        return 0.0
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    dist = ((cx - 0.5) ** 2 + (cy - 0.5) ** 2) ** 0.5
    return max(0.0, 1.0 - dist * 2.0)


def compute_joint_angles(normalized_landmarks: Dict[str, dict]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for angle_name, a_name, vertex_name, c_name in JOINT_ANGLE_TRIPLES:
        ax, ay, az = _point(a_name, normalized_landmarks)
        vx, vy, vz = _point(vertex_name, normalized_landmarks)
        cx, cy, cz = _point(c_name, normalized_landmarks)
        v1x, v1y, v1z = ax - vx, ay - vy, az - vz
        v2x, v2y, v2z = cx - vx, cy - vy, cz - vz
        n1 = math.sqrt(v1x * v1x + v1y * v1y + v1z * v1z)
        n2 = math.sqrt(v2x * v2x + v2y * v2y + v2z * v2z)
        if n1 < _EPS or n2 < _EPS:
            out[angle_name] = 0.0
            continue
        cos_t = max(-1.0, min(1.0, (v1x * v2x + v1y * v2y + v1z * v2z) / (n1 * n2)))
        out[angle_name] = math.degrees(math.acos(cos_t))
    return out
