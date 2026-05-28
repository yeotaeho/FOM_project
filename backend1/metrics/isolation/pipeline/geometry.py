"""정규화 좌표에서 bone_vectors · joint_angles (rom 스키마 호환)."""

import math
from typing import Dict, Tuple

import numpy as np

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
    ("left_foot", "left_ankle", "left_foot_index"),
    ("right_foot", "right_ankle", "right_foot_index"),
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
    ("left_ankle", "left_knee", "left_ankle", "left_foot_index"),
    ("right_ankle", "right_knee", "right_ankle", "right_foot_index"),
)

_EPS = 1e-8


def _resolve_point(name: str, lms: Dict[str, dict]) -> np.ndarray:
    if name == "mid_hip":
        return np.array(
            [
                (lms["left_hip"]["x"] + lms["right_hip"]["x"]) / 2,
                (lms["left_hip"]["y"] + lms["right_hip"]["y"]) / 2,
                (lms["left_hip"]["z"] + lms["right_hip"]["z"]) / 2,
            ],
            dtype=np.float64,
        )
    if name == "mid_shoulder":
        return np.array(
            [
                (lms["left_shoulder"]["x"] + lms["right_shoulder"]["x"]) / 2,
                (lms["left_shoulder"]["y"] + lms["right_shoulder"]["y"]) / 2,
                (lms["left_shoulder"]["z"] + lms["right_shoulder"]["z"]) / 2,
            ],
            dtype=np.float64,
        )
    p = lms[name]
    return np.array([p["x"], p["y"], p["z"]], dtype=np.float64)


def _bone_vector(from_pt: np.ndarray, to_pt: np.ndarray) -> Dict[str, float]:
    v = to_pt - from_pt
    mag = float(np.linalg.norm(v))
    if mag < _EPS:
        return {"x": 0.0, "y": 0.0, "z": 0.0, "magnitude": 0.0}
    u = v / mag
    return {
        "x": float(u[0]),
        "y": float(u[1]),
        "z": float(u[2]),
        "magnitude": mag,
    }


def _joint_angle_deg(a: np.ndarray, vertex: np.ndarray, c: np.ndarray) -> float:
    v1 = a - vertex
    v2 = c - vertex
    n1 = float(np.linalg.norm(v1))
    n2 = float(np.linalg.norm(v2))
    if n1 < _EPS or n2 < _EPS:
        return 0.0
    cos_theta = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
    return math.degrees(math.acos(cos_theta))


def compute_bone_vectors(normalized_landmarks: Dict[str, dict]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for bone_name, start, end in BONE_SEGMENTS:
        from_pt = _resolve_point(start, normalized_landmarks)
        to_pt = _resolve_point(end, normalized_landmarks)
        out[bone_name] = _bone_vector(from_pt, to_pt)
    return out


def compute_joint_angles(normalized_landmarks: Dict[str, dict]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for angle_name, pt_a, vertex, pt_c in JOINT_ANGLE_TRIPLES:
        a = _resolve_point(pt_a, normalized_landmarks)
        b = _resolve_point(vertex, normalized_landmarks)
        c = _resolve_point(pt_c, normalized_landmarks)
        out[angle_name] = round(_joint_angle_deg(a, b, c), 4)
    return out
