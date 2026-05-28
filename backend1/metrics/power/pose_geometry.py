"""Power metric 전용 — 정규화 좌표에서 뼈 방향 벡터·관절 각도 계산."""

import math
from typing import Dict, Tuple

import numpy as np

# (뼈 이름, 시작 관절, 끝 관절)
_BONE_SEGMENTS: Tuple[Tuple[str, str, str], ...] = (
    ("torso",          "mid_hip",       "mid_shoulder"),
    ("left_upper_arm", "left_shoulder", "left_elbow"),
    ("left_forearm",   "left_elbow",    "left_wrist"),
    ("right_upper_arm","right_shoulder","right_elbow"),
    ("right_forearm",  "right_elbow",   "right_wrist"),
    ("left_thigh",     "left_hip",      "left_knee"),
    ("left_shin",      "left_knee",     "left_ankle"),
    ("right_thigh",    "right_hip",     "right_knee"),
    ("right_shin",     "right_knee",    "right_ankle"),
    ("left_foot",      "left_ankle",    "left_foot_index"),
    ("right_foot",     "right_ankle",   "right_foot_index"),
)

# (각도 이름, 점A, 꼭짓점B, 점C) → ∠ABC
_JOINT_ANGLE_TRIPLES: Tuple[Tuple[str, str, str, str], ...] = (
    ("left_elbow",    "left_shoulder",  "left_elbow",   "left_wrist"),
    ("right_elbow",   "right_shoulder", "right_elbow",  "right_wrist"),
    ("left_knee",     "left_hip",       "left_knee",    "left_ankle"),
    ("right_knee",    "right_hip",      "right_knee",   "right_ankle"),
    ("left_shoulder", "left_elbow",     "left_shoulder","left_hip"),
    ("right_shoulder","right_elbow",    "right_shoulder","right_hip"),
    ("left_hip",      "left_shoulder",  "left_hip",     "left_knee"),
    ("right_hip",     "right_shoulder", "right_hip",    "right_knee"),
    ("left_ankle",    "left_knee",      "left_ankle",   "left_foot_index"),
    ("right_ankle",   "right_knee",     "right_ankle",  "right_foot_index"),
)

_EPS = 1e-8


def _resolve(name: str, lms: Dict[str, dict]) -> np.ndarray:
    """mid_hip / mid_shoulder 가상 관절 포함 좌표 반환."""
    if name == "mid_hip":
        return np.array([
            (lms["left_hip"]["x"] + lms["right_hip"]["x"]) / 2,
            (lms["left_hip"]["y"] + lms["right_hip"]["y"]) / 2,
            (lms["left_hip"]["z"] + lms["right_hip"]["z"]) / 2,
        ], dtype=np.float64)
    if name == "mid_shoulder":
        return np.array([
            (lms["left_shoulder"]["x"] + lms["right_shoulder"]["x"]) / 2,
            (lms["left_shoulder"]["y"] + lms["right_shoulder"]["y"]) / 2,
            (lms["left_shoulder"]["z"] + lms["right_shoulder"]["z"]) / 2,
        ], dtype=np.float64)
    p = lms[name]
    return np.array([p["x"], p["y"], p["z"]], dtype=np.float64)


def compute_bone_vectors(normalized_landmarks: Dict[str, dict]) -> Dict[str, dict]:
    """정규화 좌표 → 뼈 단위 방향 벡터 + 상대 길이."""
    out: Dict[str, dict] = {}
    for bone_name, start, end in _BONE_SEGMENTS:
        v = _resolve(end, normalized_landmarks) - _resolve(start, normalized_landmarks)
        mag = float(np.linalg.norm(v))
        if mag < _EPS:
            out[bone_name] = {"x": 0.0, "y": 0.0, "z": 0.0, "magnitude": 0.0}
        else:
            u = v / mag
            out[bone_name] = {
                "x": float(u[0]),
                "y": float(u[1]),
                "z": float(u[2]),
                "magnitude": mag,
            }
    return out


def compute_joint_angles(normalized_landmarks: Dict[str, dict]) -> Dict[str, float]:
    """정규화 좌표 → 관절 각도(도)."""
    out: Dict[str, float] = {}
    for angle_name, pt_a, vertex, pt_c in _JOINT_ANGLE_TRIPLES:
        a = _resolve(pt_a, normalized_landmarks)
        b = _resolve(vertex, normalized_landmarks)
        c = _resolve(pt_c, normalized_landmarks)
        v1 = a - b
        v2 = c - b
        n1, n2 = float(np.linalg.norm(v1)), float(np.linalg.norm(v2))
        if n1 < _EPS or n2 < _EPS:
            out[angle_name] = 0.0
        else:
            cos_t = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
            out[angle_name] = round(math.degrees(math.acos(cos_t)), 4)
    return out
