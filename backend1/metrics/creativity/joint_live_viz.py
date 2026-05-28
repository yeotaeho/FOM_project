"""
분할 화면 실시간 관절별 창의성 — 좌=기준(레퍼), 우=비교 대상 + 수치·강조.
"""

from __future__ import annotations

import math
from typing import Any

from .creativity import _divergence_band_factor
from .pose_compare import DIV_FRAME_CAP, cap_frame_divergence

# 대표 관절 (댄스 비교용)
DISPLAY_JOINTS: tuple[tuple[str, str], ...] = (
    ("left_shoulder", "어깨L"),
    ("right_shoulder", "어깨R"),
    ("left_elbow", "팔꿈L"),
    ("right_elbow", "팔꿈R"),
    ("left_wrist", "손목L"),
    ("right_wrist", "손목R"),
    ("left_hip", "골반L"),
    ("right_hip", "골반R"),
    ("left_knee", "무릎L"),
    ("right_knee", "무릎R"),
    ("left_ankle", "발목L"),
    ("right_ankle", "발목R"),
)

_HIGHLIGHT_SCORE = 62.0  # 관절 점수 이 이상 강조
_EMA_ALPHA = 0.45


def _joint_xy(lms: dict[str, dict], name: str) -> tuple[float, float] | None:
    p = lms.get(name)
    if not p or float(p.get("visibility", 0)) < 0.35:
        return None
    return float(p["x"]), float(p["y"])


def joint_divergence(
    ref_norm: dict[str, dict],
    user_norm: dict[str, dict],
    joint: str,
) -> float | None:
    a = _joint_xy(ref_norm, joint)
    b = _joint_xy(user_norm, joint)
    if a is None or b is None:
        return None
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return cap_frame_divergence(math.sqrt(dx * dx + dy * dy))


def joint_creativity_score(divergence: float) -> float:
    """이탈 band 와 동일 스케일 → 0~100 (높을수록 '창의적' 구간)."""
    return round(100.0 * _divergence_band_factor(divergence), 1)


def analyze_frame_joints(
    ref_frame: dict[str, Any],
    user_frame: dict[str, Any],
) -> dict[str, Any]:
    ref_n = ref_frame.get("normalized_landmarks") or {}
    user_n = user_frame.get("normalized_landmarks") or {}
    joints_out: list[dict[str, Any]] = []
    divs: list[float] = []
    scores: list[float] = []

    for name, short in DISPLAY_JOINTS:
        d = joint_divergence(ref_n, user_n, name)
        if d is None:
            joints_out.append({"joint": name, "label": short, "skipped": True})
            continue
        sc = joint_creativity_score(d)
        joints_out.append(
            {
                "joint": name,
                "label": short,
                "divergence": round(d, 4),
                "creativity_score": sc,
                "highlight": sc >= _HIGHLIGHT_SCORE,
            }
        )
        divs.append(d)
        scores.append(sc)

    frame_score = 0.0
    if scores:
        frame_score = round(sum(scores) / len(scores), 1)
    elif divs:
        frame_score = joint_creativity_score(sum(divs) / len(divs))

    top = sorted(
        [j for j in joints_out if j.get("creativity_score") is not None],
        key=lambda j: float(j["creativity_score"]),
        reverse=True,
    )[:3]

    return {
        "frame_score": frame_score,
        "mean_divergence": round(sum(divs) / len(divs), 4) if divs else None,
        "joints": joints_out,
        "top_joints": top,
    }


class JointScoreSmoother:
    """프레임 간 관절 점수 EMA — 깜빡임 완화."""

    def __init__(self) -> None:
        self._state: dict[str, float] = {}

    def smooth(self, joints: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for j in joints:
            copy = dict(j)
            name = j.get("joint")
            sc = j.get("creativity_score")
            if name and sc is not None:
                prev = self._state.get(name, float(sc))
                sm = _EMA_ALPHA * float(sc) + (1.0 - _EMA_ALPHA) * prev
                self._state[name] = sm
                copy["creativity_score"] = round(sm, 1)
                copy["highlight"] = sm >= _HIGHLIGHT_SCORE
            out.append(copy)
        return out
