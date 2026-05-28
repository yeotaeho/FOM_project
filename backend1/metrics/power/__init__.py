# architecture를 보고 육각형 지표 중 power 지표를 구현하세요.
# 다른 부분은 절대 건들지 않는다. 오직 __init__.py에서만 해결
"""Power metric: 관절 속도·가속도로 댄서의 폭발력·운동 강도 채점."""

import math
from typing import Any, Dict, List

import numpy as np

# 파워 측정 핵심 관절 (말단 관절 중심)
_POWER_JOINTS = [
    "left_wrist", "right_wrist",
    "left_elbow", "right_elbow",
    "left_ankle", "right_ankle",
    "left_knee", "right_knee",
    "left_hip", "right_hip",
]

# 말단 관절일수록 큰 가중치 (손목·발목이 폭발력 표현에 핵심)
_JOINT_WEIGHT: Dict[str, float] = {
    "left_wrist": 1.5, "right_wrist": 1.5,
    "left_elbow": 1.0, "right_elbow": 1.0,
    "left_ankle": 1.5, "right_ankle": 1.5,
    "left_knee": 1.0, "right_knee": 1.0,
    "left_hip": 0.8,  "right_hip": 0.8,
}

# sigmoid 파라미터 (torso_length/sec 기준)
# composite=2.0 → 50점, composite=3.0 → 73점, composite=4.0 → 88점
_SIGMOID_K = 1.0
_SIGMOID_V0 = 2.0

# 속도·가속도 합산 비율
_VEL_WEIGHT = 0.7
_ACC_WEIGHT = 0.3


def _extract_positions(frames: List[Dict[str, Any]], joint: str) -> np.ndarray:
    """프레임 시퀀스에서 관절 (x, y, z) 배열 반환. shape: (n_frames, 3)"""
    pos = []
    for frame in frames:
        lm = frame.get("normalized_landmarks", {}).get(joint)
        if lm is None:
            pos.append([0.0, 0.0, 0.0])
        else:
            pos.append([float(lm["x"]), float(lm["y"]), float(lm["z"])])
    return np.array(pos)


def _sigmoid_score(composite: float) -> float:
    return 100.0 / (1.0 + math.exp(-_SIGMOID_K * (composite - _SIGMOID_V0)))


def score_power(user_extraction: Dict[str, Any]) -> Dict[str, Any]:
    """
    파워 점수 계산.
    입력: user_extraction 전체 dict (fps, frames 키 포함)
    반환: {"score": 0~100, "breakdown": {...}, "frame_diffs": []}
    """
    frames: List[Dict[str, Any]] = user_extraction.get("frames", [])
    fps: float = float(user_extraction.get("fps", 30.0))

    if len(frames) < 2:
        return {
            "score": 0.0,
            "breakdown": {"error": "insufficient_frames", "total_frames": len(frames)},
            "frame_diffs": [],
        }

    joint_stats: Dict[str, Dict[str, float]] = {}
    w_vel_mean = w_vel_p75 = w_vel_p95 = 0.0
    w_acc_mean = w_acc_p75 = w_acc_p95 = 0.0
    total_w = 0.0

    for joint in _POWER_JOINTS:
        pos = _extract_positions(frames, joint)          # (n, 3)
        w = _JOINT_WEIGHT.get(joint, 1.0)

        # 속도: 연속 프레임 간 이동 거리 × fps (torso_length/sec)
        vel = np.linalg.norm(np.diff(pos, axis=0), axis=1) * fps

        # 가속도: 속도 변화량의 절댓값 (torso_length/sec²)
        acc = np.abs(np.diff(vel)) if len(vel) >= 2 else np.array([0.0])

        v_mean  = float(np.mean(vel))
        v_p75   = float(np.percentile(vel, 75))
        v_p95   = float(np.percentile(vel, 95))
        a_mean  = float(np.mean(acc))
        a_p75   = float(np.percentile(acc, 75))
        a_p95   = float(np.percentile(acc, 95))

        joint_stats[joint] = {
            "mean_velocity":     round(v_mean, 4),
            "p75_velocity":      round(v_p75,  4),
            "p95_velocity":      round(v_p95,  4),
            "mean_acceleration": round(a_mean, 4),
            "p75_acceleration":  round(a_p75,  4),
            "p95_acceleration":  round(a_p95,  4),
        }

        w_vel_mean += v_mean * w
        w_vel_p75  += v_p75  * w
        w_vel_p95  += v_p95  * w
        w_acc_mean += a_mean * w
        w_acc_p75  += a_p75  * w
        w_acc_p95  += a_p95  * w
        total_w    += w

    if total_w == 0.0:
        return {
            "score": 0.0,
            "breakdown": {"error": "no_landmark_data"},
            "frame_diffs": [],
        }

    g_vel_mean = w_vel_mean / total_w
    g_vel_p75  = w_vel_p75  / total_w
    g_vel_p95  = w_vel_p95  / total_w
    g_acc_mean = w_acc_mean / total_w
    g_acc_p75  = w_acc_p75  / total_w
    g_acc_p95  = w_acc_p95  / total_w

    # 속도 composite: mean 50% + p75 30% + p95 20%
    vel_composite = 0.5 * g_vel_mean + 0.3 * g_vel_p75 + 0.2 * g_vel_p95
    # 가속도 composite: 가속도를 동일 sigmoid 스케일로 맞추기 위해 fps로 정규화
    acc_composite = (0.5 * g_acc_mean + 0.3 * g_acc_p75 + 0.2 * g_acc_p95) / max(fps, 1.0)

    # 최종 composite: 속도 70% + 가속도 30%
    composite = _VEL_WEIGHT * vel_composite + _ACC_WEIGHT * acc_composite
    final_score = round(_sigmoid_score(composite), 2)

    return {
        "score": final_score,
        "breakdown": {
            "fps": fps,
            "total_frames": len(frames),
            "composite_velocity": round(vel_composite, 4),
            "composite_acceleration": round(acc_composite, 4),
            "final_composite": round(composite, 4),
            "global_mean_velocity":     round(g_vel_mean, 4),
            "global_p75_velocity":      round(g_vel_p75,  4),
            "global_p95_velocity":      round(g_vel_p95,  4),
            "global_mean_acceleration": round(g_acc_mean, 4),
            "global_p75_acceleration":  round(g_acc_p75,  4),
            "global_p95_acceleration":  round(g_acc_p95,  4),
            "joint_stats": joint_stats,
        },
        "frame_diffs": [],
    }
