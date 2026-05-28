"""Rhythm scorer: 사용자 동작의 리듬 규칙성 채점 + 레퍼런스 비교 + 음악 비트 비교."""

from typing import Any, Dict, List

import numpy as np
from scipy.signal import find_peaks

# ── 장르별 키포인트 정의 ────────────────────────────────────────
# 걸그룹: 섬세한 손동작 + 팔 라인(어깨) + 발동작
# 보이그룹: 골반 아이솔레이션 + 어깨 파워 + 발동작 + 손목
# 기본: 현재 동작 (손목 + 발목)
GENRE_KEYPOINTS: Dict[str, List[str]] = {
    "girl_idol": [
        "left_wrist", "right_wrist",
        "left_shoulder", "right_shoulder",
        "left_ankle", "right_ankle",
    ],
    "boy_idol": [
        "left_hip", "right_hip",
        "left_shoulder", "right_shoulder",
        "left_ankle", "right_ankle",
        "left_wrist", "right_wrist",
    ],
    "default": [
        "left_wrist", "right_wrist",
        "left_ankle", "right_ankle",
    ],
}

VALID_GENRES = set(GENRE_KEYPOINTS.keys())

_RHYTHM_KEYPOINTS = GENRE_KEYPOINTS["girl_idol"]  # 현재 프로젝트 기본값
_MIN_PEAK_DISTANCE = 5
# 신호를 단위분산으로 정규화한 뒤 사용하는 고정 prominence — 진폭과 무관하게 동일한 기준 적용
_NORMALIZED_PROMINENCE = 0.25
_CV_SCALE = 2.0

# 에너지 윈도우 파라미터
_ENERGY_WINDOW_SEC = 0.5     # 구간 크기 (초)

# 음악 비트 비교 파라미터
_BEAT_TOLERANCE_SEC = 0.2    # 비트와 동작 피크 간 허용 오차 (초)
_BEAT_HIT_WEIGHT = 0.7       # 비트 적중률 가중치
_BEAT_PRECISION_WEIGHT = 0.3 # 타이밍 정밀도 가중치

# 통합 채점 (레퍼런스 영상 + 비트) 가중치: beat 70%, wow 30%
_FULL_WOW_WEIGHT = 0.3
_FULL_BEAT_WEIGHT = 0.7

# 와우 포인트 비교 파라미터
_WOW_TOLERANCE_SEC = 0.25   # 와우 포인트 허용 오차 (초)
_WOW_HIT_WEIGHT = 0.7       # 적중률 가중치
_WOW_PRECISION_WEIGHT = 0.3 # 타이밍 정밀도 가중치

# 레퍼런스만 있을 때 가중치 (비트 없음): 에너지 60% + 와우포인트 40%
_REF_ONLY_ENERGY_WEIGHT = 0.6
_REF_ONLY_WOW_WEIGHT = 0.4

# 레퍼런스 + 비트 통합 채점 가중치: 에너지 40% + 와우포인트 20% + 비트 40%
_COMBINED_ENERGY_WEIGHT = 0.4
_COMBINED_WOW_WEIGHT = 0.2
_COMBINED_BEAT_WEIGHT = 0.4


def _resolve_keypoints(genre: str) -> List[str]:
    return GENRE_KEYPOINTS.get(genre, GENRE_KEYPOINTS["girl_idol"])


def score_rhythm_from_extraction(
    user_extraction: Dict[str, Any],
    genre: str = "girl_idol",
) -> Dict[str, Any]:
    """추출 데이터만으로 자기일관성(리듬 규칙성) 채점."""
    fps: float = float(user_extraction.get("fps") or 30.0)
    frames: List[Dict[str, Any]] = user_extraction.get("frames") or []
    keypoints = _resolve_keypoints(genre)

    if not frames:
        return {"score": 0.0, "breakdown": {"error": "no_frames"}, "frame_diffs": []}

    signal = _velocity_signal(frames, keypoints)
    stats = _detect_peaks(signal, fps)

    peak_count = len(stats["peak_indices"])
    cv = stats["cv"]

    consistency_score = round(float(np.clip(100.0 * (1.0 - cv * _CV_SCALE), 0.0, 100.0)), 2)

    if peak_count < 4:
        reliability_penalty = (4 - peak_count) * 10.0
        consistency_score = max(0.0, consistency_score - reliability_penalty)

    tempo_bpm = round(60.0 / stats["mean_sec"], 2) if stats["mean_sec"] > 0 else 0.0

    breakdown = {
        "genre": genre,
        "keypoints_used": keypoints,
        "tempo_bpm_estimate": tempo_bpm,
        "peak_count": peak_count,
        "beat_interval_mean_sec": stats["mean_sec"],
        "beat_interval_std_sec": stats["std_sec"],
        "beat_interval_cv": cv,
        "rhythm_consistency": consistency_score,
    }
    return {"score": consistency_score, "breakdown": breakdown, "frame_diffs": []}


def score_rhythm_vs_reference(
    user_extraction: Dict[str, Any],
    ref_extraction: Dict[str, Any],
    genre: str = "girl_idol",
) -> Dict[str, Any]:
    """
    사용자 vs 레퍼런스: 에너지 패턴 상관관계(60%) + 와우포인트 매칭(40%) 채점.
    음악 비트 데이터가 없을 때 사용. 비트까지 필요하면 score_rhythm_combined 사용.

    반환: {"score": float, "breakdown": dict, "frame_diffs": list}
    """
    keypoints = _resolve_keypoints(genre)
    user_fps = float(user_extraction.get("fps") or 30.0)
    ref_fps = float(ref_extraction.get("fps") or 30.0)
    user_frames = user_extraction.get("frames") or []
    ref_frames = ref_extraction.get("frames") or []

    if len(user_frames) < 2 or len(ref_frames) < 2:
        return {"score": 0.0, "breakdown": {"error": "insufficient_frames"}, "frame_diffs": []}

    user_sig = _velocity_signal(user_frames, keypoints)
    ref_sig = _velocity_signal(ref_frames, keypoints)

    energy_score = _energy_correlation_score(user_sig, ref_sig, user_fps, ref_fps)
    wow_result = score_wow_points_vs_reference(user_extraction, ref_extraction, genre=genre)
    wow_score = wow_result["score"]

    combined = round(
        _REF_ONLY_ENERGY_WEIGHT * energy_score + _REF_ONLY_WOW_WEIGHT * wow_score, 2
    )

    breakdown = {
        "genre": genre,
        "keypoints_used": keypoints,
        "energy_score": round(energy_score, 2),
        "wow_score": wow_score,
        "energy_weight": _REF_ONLY_ENERGY_WEIGHT,
        "wow_weight": _REF_ONLY_WOW_WEIGHT,
        "wow_detail": wow_result["breakdown"],
    }
    return {"score": combined, "breakdown": breakdown, "frame_diffs": []}


def score_rhythm_combined(
    user_extraction: Dict[str, Any],
    ref_extraction: Dict[str, Any],
    beat_data: Dict[str, Any],
    genre: str = "girl_idol",
) -> Dict[str, Any]:
    """
    레퍼런스 영상 + 음악 비트 통합 채점.

    - energy_score (40%): 레퍼런스 대비 구간별 운동에너지 패턴 일치도
    - wow_score    (20%): 강조·정지 포인트 타이밍 일치도
    - beat_score   (40%): 동작 피크가 음악 비트에 얼마나 맞는가

    반환: {"score": float, "breakdown": dict, "frame_diffs": list, "judgment": dict}
    """
    keypoints = _resolve_keypoints(genre)
    user_fps = float(user_extraction.get("fps") or 30.0)
    ref_fps = float(ref_extraction.get("fps") or 30.0)
    user_frames = user_extraction.get("frames") or []
    ref_frames = ref_extraction.get("frames") or []

    if len(user_frames) < 2 or len(ref_frames) < 2:
        return {"score": 0.0, "breakdown": {"error": "insufficient_frames"}, "frame_diffs": []}

    user_sig = _velocity_signal(user_frames, keypoints)
    ref_sig = _velocity_signal(ref_frames, keypoints)

    energy_score = _energy_correlation_score(user_sig, ref_sig, user_fps, ref_fps)
    wow_result = score_wow_points_vs_reference(user_extraction, ref_extraction, genre=genre)
    beat_result = score_motion_vs_beats(user_extraction, beat_data, genre=genre)

    wow_score = wow_result["score"]
    beat_score = beat_result["score"]

    combined = round(
        _COMBINED_ENERGY_WEIGHT * energy_score
        + _COMBINED_WOW_WEIGHT * wow_score
        + _COMBINED_BEAT_WEIGHT * beat_score,
        2,
    )

    breakdown = {
        "genre": genre,
        "keypoints_used": keypoints,
        "music_tempo_bpm": beat_data.get("tempo_bpm"),
        "energy_score": round(energy_score, 2),
        "wow_score": wow_score,
        "beat_score": beat_score,
        "energy_weight": _COMBINED_ENERGY_WEIGHT,
        "wow_weight": _COMBINED_WOW_WEIGHT,
        "beat_weight": _COMBINED_BEAT_WEIGHT,
        "wow_detail": wow_result["breakdown"],
        "beat_detail": beat_result["breakdown"],
    }
    return {
        "score": combined,
        "breakdown": breakdown,
        "frame_diffs": [],
        "judgment": beat_result.get("judgment"),
    }


def score_motion_vs_beats(
    user_extraction: Dict[str, Any],
    beat_data: Dict[str, Any],
    genre: str = "girl_idol",
) -> Dict[str, Any]:
    """
    사용자 동작 피크 타임과 음악 비트 타임을 비교해 채점.

    - beat_hit_rate : 비트 중 동작 피크가 허용 오차 내에 있는 비율
    - timing_precision: 적중된 비트의 평균 오차를 정밀도로 변환
    - score = 70% × hit_rate + 30% × precision

    반환: {"score": float, "breakdown": dict, "frame_diffs": list}
    """
    keypoints = _resolve_keypoints(genre)
    fps = float(user_extraction.get("fps") or 30.0)
    frames = user_extraction.get("frames") or []

    if not frames:
        return {"score": 0.0, "breakdown": {"error": "no_frames"}, "frame_diffs": []}

    beat_times: List[float] = beat_data.get("beat_times_sec") or []
    if not beat_times:
        return {"score": 0.0, "breakdown": {"error": "no_beats_detected"}, "frame_diffs": []}

    signal = _velocity_signal(frames, keypoints)
    stats = _detect_peaks(signal, fps)
    peak_times = [idx / fps for idx in stats["peak_indices"]]

    if not peak_times:
        return {
            "score": 0.0,
            "breakdown": {
                "error": "no_motion_peaks",
                "music_tempo_bpm": beat_data.get("tempo_bpm"),
                "total_beats": len(beat_times),
            },
            "frame_diffs": [],
        }

    # 각 비트에서 가장 가까운 동작 피크까지의 오차 계산
    matched = 0
    total_error = 0.0
    errors: List[float] = []

    for bt in beat_times:
        nearest_err = min(abs(bt - pt) for pt in peak_times)
        errors.append(round(nearest_err, 4))
        if nearest_err <= _BEAT_TOLERANCE_SEC:
            matched += 1
            total_error += nearest_err

    beat_hit_rate = matched / len(beat_times)
    mean_error = total_error / matched if matched > 0 else _BEAT_TOLERANCE_SEC
    precision = max(0.0, 1.0 - mean_error / _BEAT_TOLERANCE_SEC)

    score = float(np.clip(
        100.0 * (_BEAT_HIT_WEIGHT * beat_hit_rate + _BEAT_PRECISION_WEIGHT * precision),
        0.0, 100.0,
    ))

    judgment = _compute_judgment(beat_times, stats["peak_indices"], fps)

    breakdown = {
        "genre": genre,
        "keypoints_used": keypoints,
        "music_tempo_bpm": beat_data.get("tempo_bpm"),
        "total_beats": len(beat_times),
        "matched_beats": matched,
        "beat_hit_rate": round(beat_hit_rate, 4),
        "mean_timing_error_sec": round(mean_error, 4),
        "timing_precision": round(precision, 4),
        "motion_peaks_detected": len(peak_times),
        "beat_tolerance_sec": _BEAT_TOLERANCE_SEC,
        "per_beat_errors_sec": errors,
    }
    return {"score": round(score, 2), "breakdown": breakdown, "frame_diffs": [], "judgment": judgment}


def score_wow_points_vs_reference(
    user_extraction: Dict[str, Any],
    ref_extraction: Dict[str, Any],
    genre: str = "girl_idol",
) -> Dict[str, Any]:
    """
    레퍼런스 영상의 와우 포인트(강조 동작·급정지)와 사용자 와우 포인트를 비교해 채점.

    - hit_rate  : 레퍼런스 포인트 중 허용 오차 내에 사용자 포인트가 있는 비율
    - precision : 적중된 포인트의 평균 오차를 정밀도로 변환
    - score = 70% × hit_rate + 30% × precision

    반환: {"score": float, "breakdown": dict, "frame_diffs": list}
    """
    keypoints = _resolve_keypoints(genre)
    user_fps = float(user_extraction.get("fps") or 30.0)
    ref_fps = float(ref_extraction.get("fps") or 30.0)
    user_frames = user_extraction.get("frames") or []
    ref_frames = ref_extraction.get("frames") or []

    if len(user_frames) < 2 or len(ref_frames) < 2:
        return {"score": 0.0, "breakdown": {"error": "insufficient_frames"}, "frame_diffs": []}

    user_sig = _velocity_signal(user_frames, keypoints)
    ref_sig = _velocity_signal(ref_frames, keypoints)

    user_wow = _detect_wow_points(user_sig, user_fps)
    ref_wow = _detect_wow_points(ref_sig, ref_fps)

    if not ref_wow:
        return {"score": 0.0, "breakdown": {"error": "no_ref_wow_points"}, "frame_diffs": []}

    if not user_wow:
        return {
            "score": 0.0,
            "breakdown": {"error": "no_user_wow_points", "ref_wow_count": len(ref_wow)},
            "frame_diffs": [],
        }

    matched = 0
    total_error = 0.0
    missed: List[float] = []

    for rt in ref_wow:
        nearest_err = min(abs(rt - ut) for ut in user_wow)
        if nearest_err <= _WOW_TOLERANCE_SEC:
            matched += 1
            total_error += nearest_err
        else:
            missed.append(round(rt, 3))

    hit_rate = matched / len(ref_wow)
    mean_error = total_error / matched if matched > 0 else _WOW_TOLERANCE_SEC
    precision = max(0.0, 1.0 - mean_error / _WOW_TOLERANCE_SEC)

    score = float(np.clip(
        100.0 * (_WOW_HIT_WEIGHT * hit_rate + _WOW_PRECISION_WEIGHT * precision),
        0.0, 100.0,
    ))

    breakdown = {
        "genre": genre,
        "keypoints_used": keypoints,
        "ref_wow_count": len(ref_wow),
        "user_wow_count": len(user_wow),
        "matched": matched,
        "hit_rate": round(hit_rate, 4),
        "mean_timing_error_sec": round(mean_error, 4),
        "timing_precision": round(precision, 4),
        "missed_ref_timestamps_sec": missed,
        "wow_tolerance_sec": _WOW_TOLERANCE_SEC,
    }
    return {"score": round(score, 2), "breakdown": breakdown, "frame_diffs": []}


def score_motion_full(
    user_extraction: Dict[str, Any],
    ref_extraction: Dict[str, Any],
    beat_data: Dict[str, Any],
    genre: str = "girl_idol",
) -> Dict[str, Any]:
    """
    레퍼런스 영상 기반 통합 채점.

    - wow_score  (30%): 레퍼런스의 강조·정지 포인트를 사용자가 맞히는가
    - beat_score (70%): 사용자 동작 피크가 레퍼런스 영상의 음악 비트와 얼마나 맞는가

    반환: {"score": float, "breakdown": dict, "frame_diffs": list}
    """
    wow_result = score_wow_points_vs_reference(user_extraction, ref_extraction, genre=genre)
    beat_result = score_motion_vs_beats(user_extraction, beat_data, genre=genre)

    wow_score = wow_result["score"]
    beat_score = beat_result["score"]

    combined = round(
        _FULL_WOW_WEIGHT * wow_score + _FULL_BEAT_WEIGHT * beat_score, 2
    )

    breakdown = {
        "genre": genre,
        "wow_score": wow_score,
        "beat_score": beat_score,
        "wow_weight": _FULL_WOW_WEIGHT,
        "beat_weight": _FULL_BEAT_WEIGHT,
        "wow_detail": wow_result["breakdown"],
        "beat_detail": beat_result["breakdown"],
    }
    return {"score": combined, "breakdown": breakdown, "frame_diffs": [], "judgment": beat_result.get("judgment")}


# ──────────────────────────── 내부 유틸 ────────────────────────────

def _windowed_energy_profile(
    signal: np.ndarray, fps: float, window_sec: float = _ENERGY_WINDOW_SEC
) -> np.ndarray:
    """속도 신호를 윈도우로 분할해 각 구간 RMS 에너지 반환."""
    window_size = max(1, int(round(fps * window_sec)))
    n_windows = max(1, len(signal) // window_size)
    return np.array([
        float(np.sqrt(np.mean(signal[i * window_size:(i + 1) * window_size] ** 2)))
        for i in range(n_windows)
    ])


def _energy_correlation_score(
    user_sig: np.ndarray,
    ref_sig: np.ndarray,
    user_fps: float,
    ref_fps: float,
) -> float:
    """구간별 에너지 프로파일 Pearson 상관관계 → 0~100점."""
    user_rms = _windowed_energy_profile(user_sig, user_fps)
    ref_rms = _windowed_energy_profile(ref_sig, ref_fps)

    n = min(len(user_rms), len(ref_rms))
    if n < 2:
        return 0.0

    u = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(user_rms)), user_rms)
    r = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(ref_rms)), ref_rms)

    corr = np.corrcoef(u, r)[0, 1]
    if not np.isfinite(corr):
        corr = -1.0
    return float(np.clip((corr + 1) / 2 * 100, 0.0, 100.0))


def _compute_judgment(
    beat_times: List[float],
    peak_indices: List[int],
    fps: float,
) -> Dict[str, Any]:
    """비트 vs 동작 피크 오프셋 → 타이밍 경향 + 일관성 + 피드백 문구."""
    if not beat_times or not peak_indices:
        return {
            "timing_tendency": "unknown",
            "consistency": "unknown",
            "avg_offset_ms": None,
            "std_offset_ms": None,
            "feedback": "판정을 위한 데이터가 부족합니다.",
        }

    peak_times = [idx / fps for idx in peak_indices]
    offsets_ms = [
        (min(peak_times, key=lambda pt: abs(pt - bt)) - bt) * 1000.0
        for bt in beat_times
    ]

    avg_ms = float(np.mean(offsets_ms))
    std_ms = float(np.std(offsets_ms))

    if avg_ms < -100:
        tendency = "early"
    elif avg_ms > 100:
        tendency = "late"
    else:
        tendency = "on_time"

    if std_ms < 80:
        consistency = "high"
    elif std_ms < 180:
        consistency = "moderate"
    else:
        consistency = "low"

    _tendency_text = {
        "early":   f"동작이 평균적으로 비트보다 {abs(avg_ms):.0f}ms 빠릅니다. 동작을 조금 늦게 시작하세요.",
        "late":    f"동작이 평균적으로 비트보다 {abs(avg_ms):.0f}ms 늦습니다. 반응 속도를 높이세요.",
        "on_time": "비트 타이밍이 양호합니다.",
    }
    _consistency_text = {
        "high":     "박자가 일관적입니다.",
        "moderate": "박자 일관성이 보통 수준입니다.",
        "low":      "박자가 불규칙합니다. 꾸준한 연습이 필요합니다.",
    }

    feedback = _tendency_text[tendency] + " " + _consistency_text[consistency]

    return {
        "timing_tendency": tendency,
        "consistency": consistency,
        "avg_offset_ms": round(avg_ms, 1),
        "std_offset_ms": round(std_ms, 1),
        "feedback": feedback.strip(),
    }


def _velocity_signal(frames: List[Dict[str, Any]], keypoints: List[str]) -> np.ndarray:
    positions: List[np.ndarray] = []
    for frame in frames:
        lm = frame.get("normalized_landmarks") or {}
        coords: List[float] = []
        for kp in keypoints:
            pt = lm.get(kp)
            if pt:
                coords.extend([pt["x"], pt["y"]])
        positions.append(
            np.array(coords, dtype=float) if coords else np.zeros(len(keypoints) * 2)
        )

    if len(positions) < 2:
        return np.zeros(max(len(positions), 1))

    pos_arr = np.array(positions)
    diffs = np.linalg.norm(np.diff(pos_arr, axis=0), axis=1)
    return np.concatenate([[0.0], diffs])


def _detect_peaks(signal: np.ndarray, fps: float) -> Dict[str, Any]:
    if signal.std() < 1e-9:
        return {"peak_indices": [], "intervals_sec": [], "mean_sec": 0.0, "std_sec": 0.0, "cv": 1.0}

    # 가속도(속도 변화량) 절댓값 사용 — 빠른 동작(속도 peak)과 멈춤(속도 trough) 모두 감지
    # 멈추는 동작은 속도 신호에서는 trough이지만 가속도에서는 peak로 나타남
    accel = np.abs(np.diff(signal, prepend=signal[0]))
    norm_signal = accel / (accel.std() + 1e-9)
    peaks, _ = find_peaks(norm_signal, distance=_MIN_PEAK_DISTANCE, prominence=_NORMALIZED_PROMINENCE)

    if len(peaks) < 2:
        return {
            "peak_indices": peaks.tolist(),
            "intervals_sec": [],
            "mean_sec": 0.0,
            "std_sec": 0.0,
            "cv": 1.0,
        }

    intervals_sec = np.diff(peaks).astype(float) / fps
    mean_sec = float(intervals_sec.mean())
    std_sec = float(intervals_sec.std())
    cv = std_sec / mean_sec if mean_sec > 1e-9 else 1.0

    return {
        "peak_indices": peaks.tolist(),
        "intervals_sec": [round(v, 4) for v in intervals_sec.tolist()],
        "mean_sec": round(mean_sec, 4),
        "std_sec": round(std_sec, 4),
        "cv": round(cv, 4),
    }


def _detect_wow_points(signal: np.ndarray, fps: float) -> List[float]:
    """강조 동작(피크) + 급정지(밸리)를 와우 포인트로 감지, 타임스탬프(초) 반환."""
    if signal.std() < 1e-9:
        return []

    norm = signal / (signal.std() + 1e-9)
    mean_val = float(norm.mean())

    peaks, _ = find_peaks(norm, distance=_MIN_PEAK_DISTANCE, prominence=_NORMALIZED_PROMINENCE)

    # 급정지: 반전 신호의 피크 = 원래 신호의 밸리
    # 평균 이하인 경우만 인정 — 이미 정적인 구간의 노이즈 제거
    valleys, _ = find_peaks(-norm, distance=_MIN_PEAK_DISTANCE, prominence=_NORMALIZED_PROMINENCE)
    valid_valleys = [v for v in valleys if float(norm[v]) < mean_val]

    all_indices = sorted(set(peaks.tolist()) | set(valid_valleys))
    return [round(int(idx) / fps, 4) for idx in all_indices]


