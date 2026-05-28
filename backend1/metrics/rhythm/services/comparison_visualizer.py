"""원본 vs 사용자 영상 나란히 비교 — 싱크 불일치 구간 검은 화면 처리."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .scoring.rhythm_scorer import (
    GENRE_KEYPOINTS,
    _downsample,
    _dtw_align,
    _velocity_signal,
)
from .storage_paths import VIDEO_DATA_DIR, ensure_storage_dirs, make_extraction_basename
from .video_audio import render_with_audio

# ── 레이아웃 ───────────────────────────────────────────────────────
TARGET_H = 480          # 각 패널 높이 (px)
INDICATOR_H = 50        # 하단 싱크 인디케이터 높이
DIVIDER_W = 4           # 가운데 구분선 너비

# ── 싱크 판정 파라미터 ─────────────────────────────────────────────
SYNC_THRESHOLD = 1.2    # DTW 정규화 신호 기준 로컬 비용 임계값
SMOOTH_FRAMES = 12      # 블랙 처리 적용 전 이동 평균 창 크기 (프레임)
BLACK_ALPHA = 0.92      # 싱크 불일치 시 어두워지는 비율 (0=원본, 1=완전검정)
DOWNSAMPLE_FPS = 5.0

# ── 색상 ──────────────────────────────────────────────────────────
C_SYNC_GOOD = (60, 220, 60)     # 초록
C_SYNC_MID  = (40, 200, 255)    # 노랑
C_SYNC_BAD  = (40,  40, 220)    # 빨강
C_DIVIDER   = (200, 200, 200)
C_TEXT      = (240, 240, 240)
C_LABEL_REF = (100, 220, 100)
C_LABEL_USR = (100, 180, 255)
C_PANEL_BG  = (20, 20, 26)

_KP_COLORS = {
    "left_wrist":  (0, 255, 128),
    "right_wrist": (0, 255, 128),
    "left_ankle":  (255, 140,   0),
    "right_ankle": (255, 140,   0),
    "left_hip":    (180, 100, 255),
    "right_hip":   (180, 100, 255),
    "left_shoulder":  (255, 220, 80),
    "right_shoulder": (255, 220, 80),
}


def render_comparison_video(
    user_video_path: str,
    ref_video_path: str,
    user_extraction: Dict[str, Any],
    ref_extraction: Dict[str, Any],
    genre: str = "girl_idol",
    output_filename: Optional[str] = None,
) -> Path:
    """
    원본(왼쪽)·사용자(오른쪽) 나란히 비교 영상 생성.

    싱크가 맞지 않는 구간은 양쪽 모두 검은 화면 처리.
    하단 인디케이터 바: 초록(싱크 양호) → 노랑 → 빨강(싱크 불량).
    """
    ensure_storage_dirs()
    if output_filename is None:
        output_filename = f"{make_extraction_basename()}_compare.mp4"
    output_path = VIDEO_DATA_DIR / output_filename

    keypoints = GENRE_KEYPOINTS.get(genre, GENRE_KEYPOINTS["girl_idol"])
    user_fps = float(user_extraction.get("fps") or 30.0)
    ref_fps  = float(ref_extraction.get("fps") or 30.0)

    user_frames_data: List[Dict] = user_extraction.get("frames") or []
    ref_frames_data:  List[Dict] = ref_extraction.get("frames") or []

    if not user_frames_data or not ref_frames_data:
        raise ValueError("프레임 데이터가 없습니다.")

    # ── DTW 정렬 경로 계산 ───────────────────────────────────────
    user_sig = _velocity_signal(user_frames_data, keypoints)
    ref_sig  = _velocity_signal(ref_frames_data,  keypoints)

    user_ds = _downsample(user_sig, user_fps, DOWNSAMPLE_FPS)
    ref_ds  = _downsample(ref_sig,  ref_fps,  DOWNSAMPLE_FPS)
    user_norm = user_ds / (user_ds.std() + 1e-9)
    ref_norm  = ref_ds  / (ref_ds.std()  + 1e-9)

    _, path = _dtw_align(user_norm, ref_norm, radius=max(50, abs(len(user_norm) - len(ref_norm)) + 1))

    # ── 원본 프레임 인덱스 ↔ 레퍼런스 프레임 인덱스 매핑 ────────
    ds_step_u = max(1, int(round(user_fps / DOWNSAMPLE_FPS)))
    ds_step_r = max(1, int(round(ref_fps  / DOWNSAMPLE_FPS)))

    # DTW path: (user_ds_idx, ref_ds_idx) 쌍
    # user 원본 프레임 fi → user_ds_idx = fi // ds_step_u → ref_ds_idx → ref 원본 프레임
    user_ds_to_ref_ds: Dict[int, int] = {}
    local_cost: Dict[int, float] = {}   # key = user_ds_idx
    for (u, r) in path:
        user_ds_to_ref_ds[u] = r
        local_cost[u] = abs(float(user_norm[u]) - float(ref_norm[r]))

    n_user = len(user_frames_data)
    n_ref  = len(ref_frames_data)

    # user 원본 프레임별 로컬 비용 배열 → 이동 평균으로 스무딩
    raw_costs = np.array([
        local_cost.get(min(fi // ds_step_u, len(user_norm) - 1), 0.0)
        for fi in range(n_user)
    ], dtype=float)
    kernel = np.ones(SMOOTH_FRAMES) / SMOOTH_FRAMES
    smoothed_costs = np.convolve(raw_costs, kernel, mode="same")

    # ── 영상 열기 ────────────────────────────────────────────────
    cap_u = cv2.VideoCapture(user_video_path)
    cap_r = cv2.VideoCapture(ref_video_path)
    if not cap_u.isOpened() or not cap_r.isOpened():
        raise ValueError("비교 영상을 열 수 없습니다.")

    u_w = int(cap_u.get(cv2.CAP_PROP_FRAME_WIDTH))
    u_h = int(cap_u.get(cv2.CAP_PROP_FRAME_HEIGHT))
    r_w = int(cap_r.get(cv2.CAP_PROP_FRAME_WIDTH))
    r_h = int(cap_r.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # 두 패널 모두 TARGET_H로 맞춤, 가로는 비율 유지
    u_panel_w = int(u_w * TARGET_H / u_h)
    r_panel_w = int(r_w * TARGET_H / r_h)
    out_w = r_panel_w + DIVIDER_W + u_panel_w
    out_h = TARGET_H + INDICATOR_H

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, user_fps, (out_w, out_h))
    if not writer.isOpened():
        cap_u.release(); cap_r.release()
        raise ValueError("VideoWriter를 열 수 없습니다.")

    # ── 레퍼런스 프레임 전체 미리 로드 (seek 비용 절감) ──────────
    ref_video_frames: List[np.ndarray] = []
    while True:
        ret, fr = cap_r.read()
        if not ret:
            break
        ref_video_frames.append(cv2.resize(fr, (r_panel_w, TARGET_H)))
    cap_r.release()

    # ── 프레임 루프 ──────────────────────────────────────────────
    for fi in range(n_user):
        ret, u_frame = cap_u.read()
        if not ret:
            break

        # 대응 레퍼런스 프레임 인덱스
        u_ds_idx = min(fi // ds_step_u, len(user_norm) - 1)
        r_ds_idx = user_ds_to_ref_ds.get(u_ds_idx, 0)
        ref_fi   = min(r_ds_idx * ds_step_r, len(ref_video_frames) - 1)

        u_panel = cv2.resize(u_frame, (u_panel_w, TARGET_H))
        r_panel = ref_video_frames[ref_fi].copy()

        # 키포인트 오버레이
        u_panel = _draw_kp(u_panel, user_frames_data[fi], u_panel_w, TARGET_H, keypoints)
        r_panel = _draw_kp(r_panel, ref_frames_data[min(ref_fi, n_ref - 1)],
                           r_panel_w, TARGET_H, keypoints)

        # 싱크 비용 → 검은 화면 처리
        cost = float(smoothed_costs[fi])
        is_bad = cost > SYNC_THRESHOLD
        if is_bad:
            fade = min(BLACK_ALPHA, (cost - SYNC_THRESHOLD) / SYNC_THRESHOLD * BLACK_ALPHA + 0.5)
            black = np.zeros_like(u_panel)
            u_panel = cv2.addWeighted(u_panel, 1.0 - fade, black, fade, 0)
            r_panel = cv2.addWeighted(r_panel, 1.0 - fade, black, fade, 0)

        # 레이블 및 타임스탬프
        t_u = fi / user_fps
        _put(r_panel, "ORIGINAL", (8, 28), C_LABEL_REF, scale=0.65)
        _put(u_panel, "USER",     (8, 28), C_LABEL_USR, scale=0.65)
        _put(r_panel, f"t={t_u:.2f}s", (8, 54), C_TEXT, scale=0.50)

        # 싱크 상태 텍스트
        sync_label = "IN SYNC" if not is_bad else "OUT OF SYNC"
        sync_color = C_SYNC_GOOD if not is_bad else C_SYNC_BAD
        _put(u_panel, sync_label, (u_panel_w // 2 - 60, TARGET_H - 12), sync_color, scale=0.58)

        # 가운데 구분선
        divider = np.full((TARGET_H, DIVIDER_W, 3), C_DIVIDER, dtype=np.uint8)

        top_row = np.hstack([r_panel, divider, u_panel])

        # 하단 싱크 인디케이터 바
        indicator = _build_indicator(fi, n_user, smoothed_costs, out_w)

        canvas = np.vstack([top_row, indicator])
        writer.write(canvas)

    cap_u.release()
    writer.release()

    # 레퍼런스 영상의 오디오 트랙을 합성
    try:
        render_with_audio(output_path, ref_video_path, output_path)
    except RuntimeError:
        pass  # 오디오 트랙이 없는 영상이면 무음으로 유지

    return output_path


# ── 드로잉 헬퍼 ───────────────────────────────────────────────────

def _draw_kp(
    frame: np.ndarray,
    frame_data: Dict,
    w: int,
    h: int,
    keypoints: List[str],
) -> np.ndarray:
    raw = frame_data.get("raw_landmarks") or {}
    out = frame.copy()
    for kp in keypoints:
        pt = raw.get(kp)
        if pt is None:
            continue
        cx, cy = int(pt["x"] * w), int(pt["y"] * h)
        color = _KP_COLORS.get(kp, (255, 255, 255))
        cv2.circle(out, (cx, cy), 9, color, -1, cv2.LINE_AA)
        cv2.circle(out, (cx, cy), 11, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def _build_indicator(
    fi: int,
    total: int,
    costs: np.ndarray,
    width: int,
) -> np.ndarray:
    bar = np.full((INDICATOR_H, width, 3), C_PANEL_BG, dtype=np.uint8)

    # 전체 구간 싱크 컬러 그라데이션 바
    bar_y1, bar_y2 = 12, 32
    if total > 1:
        for x in range(width):
            ci = int(x / (width - 1) * (total - 1))
            c = float(costs[ci])
            color = _sync_color(c)
            cv2.line(bar, (x, bar_y1), (x, bar_y2), color, 1)

        # 현재 위치 포인터
        cx = int(fi / (total - 1) * (width - 1))
        cv2.line(bar, (cx, 4), (cx, INDICATOR_H - 4), (255, 255, 255), 2)
        cv2.circle(bar, (cx, (bar_y1 + bar_y2) // 2), 5, (255, 255, 255), -1)

    cv2.putText(bar, "SYNC", (4, INDICATOR_H - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, C_TEXT, 1, cv2.LINE_AA)
    return bar


def _sync_color(cost: float) -> Tuple[int, int, int]:
    """비용 → BGR 색상: 낮을수록 초록, 높을수록 빨강."""
    t = min(cost / SYNC_THRESHOLD, 1.0)
    if t < 0.5:
        r = int(t * 2 * 200)
        g = 220
    else:
        r = 220
        g = int((1 - t) * 2 * 200)
    return (40, g, r)


def _put(
    img: np.ndarray,
    text: str,
    pos: Tuple[int, int],
    color: Tuple[int, int, int],
    scale: float = 0.5,
) -> None:
    cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX,
                scale, color, 1, cv2.LINE_AA)
