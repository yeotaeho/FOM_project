"""리듬 분석 결과를 원본 영상에 오버레이하여 시각화."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from scipy.signal import find_peaks

from .storage_paths import VIDEO_DATA_DIR, ensure_storage_dirs
from .video_audio import render_with_audio

# ── 레이아웃 상수 ──────────────────────────────────────────────────
PANEL_W = 300          # 오른쪽 사이드 패널 너비
TIMELINE_H = 60        # 하단 타임라인 높이
GRAPH_WIN_SEC = 4.0    # 속도 그래프 표시 구간 (초)

# ── 색상 ───────────────────────────────────────────────────────────
C_WRIST   = (0,   255, 128)   # 손목 – 초록
C_ANKLE   = (255, 140,   0)   # 발목 – 주황
C_BEAT    = (0,   220, 255)   # 비트 플래시 – 하늘색
C_PEAK    = (80,   80, 255)   # 동작 피크 – 파랑
C_TEXT    = (240, 240, 240)
C_PANEL   = (20,   20,  26)
C_BAR_BG  = (45,   45,  50)
C_BAR_FG  = (80,  200, 120)
C_BEAT_MK = (0,   200, 255)
C_PEAK_MK = (80,   80, 255)

BEAT_FLASH  = 5   # 비트 발생 후 강조 프레임 수
PEAK_FLASH  = 4   # 동작 피크 발생 후 강조 프레임 수
OFFSET_WIN_MS = 400.0  # Beat vs Peak 오프셋 그래프 표시 범위 (±ms)
_BEAT_TOL_VIZ = 0.2    # 비트 적중 판정 허용 오차 (초) — rhythm_scorer와 동일

# ── 키포인트 설정 ──────────────────────────────────────────────────
_KP_COLORS = {
    "left_wrist":  C_WRIST,
    "right_wrist": C_WRIST,
    "left_ankle":  C_ANKLE,
    "right_ankle": C_ANKLE,
}
_KP_RADIUS = 10


def render_rhythm_video(
    source_video_path: str,
    extraction_result: Dict[str, Any],
    beat_data: Optional[Dict[str, Any]] = None,
    score_result: Optional[Dict[str, Any]] = None,
    output_filename: Optional[str] = None,
) -> Path:
    """
    원본 영상에 리듬 분석 결과를 오버레이한 영상을 생성한다.

    오버레이 내용:
      - 손목(초록)·발목(주황) 키포인트
      - 비트 발생 시 테두리 하늘색 플래시
      - 동작 피크 발생 시 파란 플래시
      - 하단 타임라인: 비트·피크 마커 + 현재 위치
      - 우측 패널: 속도 그래프, BPM, 점수, 통계

    반환: 저장된 영상 Path
    """
    ensure_storage_dirs()

    if output_filename is None:
        from .storage_paths import make_extraction_basename
        output_filename = f"{make_extraction_basename()}_rhythm.mp4"

    output_path = VIDEO_DATA_DIR / output_filename

    frames_data: List[Dict[str, Any]] = extraction_result.get("frames") or []
    fps = float(extraction_result.get("fps") or 30.0)
    total_frames = len(frames_data)

    if total_frames == 0:
        raise ValueError("시각화할 프레임 데이터가 없습니다.")

    # ── 사전 계산: 속도 신호 + 피크 ─────────────────────────────
    velocity = _compute_velocity(frames_data)
    peak_indices = _compute_peaks(velocity)
    peak_set = set(peak_indices)

    # ── 비트 프레임 집합 ─────────────────────────────────────────
    beat_times: List[float] = []
    tempo_bpm: float = 0.0
    if beat_data:
        beat_times = beat_data.get("beat_times_sec") or []
        tempo_bpm = beat_data.get("tempo_bpm") or 0.0
    beat_frames = {int(round(t * fps)) for t in beat_times}

    # ── 비트별 적중 여부 사전 계산 ────────────────────────────────
    # (beat_frame, hit: bool, offset_ms: float)
    beat_results: List[Tuple[int, bool, float]] = []
    if beat_times and peak_indices:
        for bt in beat_times:
            bf = int(round(bt * fps))
            nearest_pi = min(peak_indices, key=lambda p: abs(p - bf))
            off_sec = (nearest_pi - bf) / fps
            beat_results.append((bf, abs(off_sec) <= _BEAT_TOL_VIZ, round(off_sec * 1000.0, 1)))

    # ── 점수 정보 ────────────────────────────────────────────────
    score_val: Optional[float] = None
    hit_rate: Optional[float] = None
    judgment: Optional[Dict[str, Any]] = None
    if score_result:
        score_val = score_result.get("score")
        bd = score_result.get("breakdown") or {}
        hit_rate = bd.get("beat_hit_rate") or bd.get("dtw_score")
        judgment = score_result.get("judgment")

    # ── 영상 열기 ────────────────────────────────────────────────
    cap = cv2.VideoCapture(source_video_path)
    if not cap.isOpened():
        raise ValueError(f"영상을 열 수 없습니다: {source_video_path}")

    vid_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vid_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out_w = vid_w + PANEL_W
    out_h = vid_h + TIMELINE_H

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (out_w, out_h))
    if not writer.isOpened():
        cap.release()
        raise ValueError("VideoWriter를 열 수 없습니다 (코덱 mp4v).")

    # ── 프레임 루프 ──────────────────────────────────────────────
    for fi, frame_data in enumerate(frames_data):
        ret, frame = cap.read()
        if not ret:
            break

        is_beat = any(
            abs(fi - bf) < BEAT_FLASH for bf in beat_frames
        )
        is_peak = any(
            abs(fi - pi) < PEAK_FLASH for pi in peak_set
        )

        # 키포인트 오버레이
        annotated = _draw_keypoints(frame, frame_data, vid_w, vid_h, velocity[fi])

        # 비트·피크 테두리 플래시
        if is_beat:
            cv2.rectangle(annotated, (0, 0), (vid_w - 1, vid_h - 1), C_BEAT, 6)
        if is_peak:
            cv2.rectangle(annotated, (3, 3), (vid_w - 4, vid_h - 4), C_PEAK, 3)

        # 현재 시간 표시
        t_sec = frame_data.get("time_sec", fi / fps)
        cv2.putText(
            annotated, f"t={t_sec:.2f}s  fr={fi}",
            (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, C_TEXT, 2, cv2.LINE_AA,
        )

        # 사이드 패널
        panel = _build_panel(
            fi, fps, velocity, peak_indices,
            beat_times, tempo_bpm, score_val, hit_rate, judgment, vid_h,
            beat_results,
        )

        # 하단 타임라인
        timeline = _build_timeline(
            fi, total_frames, fps, beat_frames, peak_set, out_w,
        )

        # 합성
        top = np.hstack([annotated, panel])                     # (vid_h, out_w)
        canvas = np.vstack([top, timeline])                     # (out_h, out_w)
        writer.write(canvas)

    cap.release()
    writer.release()

    try:
        render_with_audio(output_path, source_video_path, output_path)
    except RuntimeError:
        pass  # 오디오 트랙이 없는 영상이면 무음으로 유지

    return output_path


# ── 드로잉 헬퍼 ───────────────────────────────────────────────────

def _draw_keypoints(
    frame: np.ndarray,
    frame_data: Dict[str, Any],
    w: int,
    h: int,
    vel: float,
) -> np.ndarray:
    out = frame.copy()
    raw = frame_data.get("raw_landmarks") or {}

    # 속도에 따라 원 크기 변화 (최소 8 ~ 최대 18)
    radius = int(np.clip(_KP_RADIUS + vel * 40, 8, 18))

    for kp, color in _KP_COLORS.items():
        pt = raw.get(kp)
        if pt is None:
            continue
        cx, cy = int(pt["x"] * w), int(pt["y"] * h)
        cv2.circle(out, (cx, cy), radius, color, -1, cv2.LINE_AA)
        cv2.circle(out, (cx, cy), radius + 2, (255, 255, 255), 1, cv2.LINE_AA)

    return out


def _build_panel(
    fi: int,
    fps: float,
    velocity: np.ndarray,
    peak_indices: List[int],
    beat_times: List[float],
    tempo_bpm: float,
    score_val: Optional[float],
    hit_rate: Optional[float],
    judgment: Optional[Dict[str, Any]],
    panel_h: int,
    beat_results: Optional[List[Tuple[int, bool, float]]] = None,
) -> np.ndarray:
    panel = np.full((panel_h, PANEL_W, 3), C_PANEL, dtype=np.uint8)
    y = 30
    step = 22

    def put(text: str, color: Tuple = C_TEXT, scale: float = 0.48) -> None:
        nonlocal y
        cv2.putText(panel, text, (12, y),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)
        y += step

    put("Rhythm Analysis", C_WRIST, 0.58)
    y += 4

    if tempo_bpm:
        put(f"BPM : {tempo_bpm:.1f}", C_BEAT_MK)

    # 점수 + 프로그레스 바
    if score_val is not None:
        color = _score_color(score_val)
        put(f"Score: {score_val:.1f}", color, 0.55)
        _draw_score_bar(panel, score_val, 12, y - 4, PANEL_W - 24)
        y += 18

    # 누적 Hit/Miss 카운터 (프레임 진행에 따라 실시간 업데이트)
    passed = [r for r in (beat_results or []) if r[0] <= fi]
    if passed:
        n_hit = sum(1 for _, h, _ in passed)
        n_total = len(passed)
        running_pct = n_hit / n_total * 100
        h_color = _score_color(running_pct)
        put(f"Hit  : {n_hit}/{n_total}  ({running_pct:.0f}%)", h_color)
        # 최근 비트 적중 여부 dot 표시
        _draw_beat_dots(panel, passed, 12, y, PANEL_W - 24)
        y += 20
    elif hit_rate is not None:
        put(f"Hit  : {hit_rate*100:.1f}%")

    # 판정 결과
    if judgment:
        tendency = judgment.get("timing_tendency", "")
        consistency = judgment.get("consistency", "")
        avg_ms = judgment.get("avg_offset_ms")
        t_color = {
            "early":   (40, 200, 255),
            "on_time": (60, 220, 60),
            "late":    (40, 40, 220),
        }.get(tendency, C_TEXT)
        c_color = {
            "high":     (60, 220, 60),
            "moderate": (40, 200, 255),
            "low":      (40, 40, 220),
        }.get(consistency, C_TEXT)
        t_label = {"early": "EARLY", "on_time": "ON TIME", "late": "LATE"}.get(tendency, "?")
        c_label = {"high": "HIGH", "moderate": "MID", "low": "LOW"}.get(consistency, "?")
        offset_str = f"({avg_ms:+.0f}ms)" if avg_ms is not None else ""
        put(f"Timing:{t_label} {offset_str}", t_color, 0.43)
        put(f"Consist:{c_label}", c_color, 0.43)

    peaks_so_far = sum(1 for p in peak_indices if p <= fi)
    put(f"Peaks: {peaks_so_far}")
    put(f"Vel  : {velocity[fi]:.3f}")
    y += 6

    # 속도 그래프
    put("── velocity ──", (150, 150, 150), 0.40)
    graph_h = min(100, panel_h - y - 130)
    if graph_h > 20:
        _draw_velocity_graph(panel, velocity, fi, fps, 8, y, PANEL_W - 16, graph_h)
        y += graph_h + 8

    # Beat vs Peak 오프셋 그래프
    if beat_times and peak_indices:
        put("── beat offset ──", (150, 150, 150), 0.40)
        offset_h = min(70, panel_h - y - 70)
        if offset_h > 20:
            bfl = [int(round(t * fps)) for t in beat_times]
            off_list: List[float] = []
            for bf in bfl:
                if bf <= fi:
                    nearest = min(peak_indices, key=lambda p: abs(p - bf))
                    off_list.append((nearest - bf) / fps * 1000.0)
            if off_list:
                _draw_offset_graph(panel, off_list[-6:], 8, y, PANEL_W - 16, offset_h)
            y += offset_h + 8

    # 범례
    if y < panel_h - 55:
        y = panel_h - 55
    cv2.circle(panel, (18, y + 6), 7, C_WRIST, -1, cv2.LINE_AA)
    cv2.putText(panel, "wrist", (30, y + 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, C_TEXT, 1, cv2.LINE_AA)
    cv2.circle(panel, (18, y + 26), 7, C_ANKLE, -1, cv2.LINE_AA)
    cv2.putText(panel, "ankle", (30, y + 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, C_TEXT, 1, cv2.LINE_AA)
    cv2.rectangle(panel, (10, y + 40), (22, y + 50), C_BEAT, -1)
    cv2.putText(panel, "beat", (30, y + 50),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, C_TEXT, 1, cv2.LINE_AA)

    return panel


def _draw_velocity_graph(
    panel: np.ndarray,
    velocity: np.ndarray,
    fi: int,
    fps: float,
    ox: int, oy: int, gw: int, gh: int,
) -> None:
    cv2.rectangle(panel, (ox, oy), (ox + gw, oy + gh), C_BAR_BG, -1)

    win = int(GRAPH_WIN_SEC * fps)
    start = max(0, fi - win)
    end = fi + 1
    seg = velocity[start:end]
    if len(seg) == 0:
        return

    v_max = float(velocity.max()) if velocity.max() > 1e-9 else 1.0
    n = len(seg)

    pts = []
    for i, v in enumerate(seg):
        x = ox + int(i / max(n - 1, 1) * gw)
        y = oy + gh - int(v / v_max * gh)
        pts.append((x, y))

    if len(pts) > 1:
        cv2.polylines(panel, [np.array(pts, dtype=np.int32)],
                      False, C_BAR_FG, 1, cv2.LINE_AA)

    # 현재 위치 수직선
    cv2.line(panel, (ox + gw - 1, oy), (ox + gw - 1, oy + gh), C_TEXT, 1)


def _build_timeline(
    fi: int,
    total_frames: int,
    fps: float,
    beat_frames: set,
    peak_set: set,
    width: int,
) -> np.ndarray:
    tl = np.full((TIMELINE_H, width, 3), (30, 30, 35), dtype=np.uint8)

    # 배경 바
    bar_y1, bar_y2 = 20, 38
    cv2.rectangle(tl, (0, bar_y1), (width - 1, bar_y2), (60, 60, 65), -1)

    if total_frames > 1:
        # 비트 마커
        for bf in beat_frames:
            x = int(bf / (total_frames - 1) * (width - 1))
            cv2.line(tl, (x, bar_y1 - 6), (x, bar_y2 + 6), C_BEAT_MK, 2)

        # 동작 피크 마커
        for pi in peak_set:
            x = int(pi / (total_frames - 1) * (width - 1))
            cv2.line(tl, (x, bar_y1), (x, bar_y2), C_PEAK_MK, 1)

        # 현재 재생 위치
        cx = int(fi / (total_frames - 1) * (width - 1))
        cv2.line(tl, (cx, 5), (cx, TIMELINE_H - 5), (255, 255, 255), 2)
        cv2.circle(tl, (cx, (bar_y1 + bar_y2) // 2), 5, (255, 255, 255), -1)

    # 라벨
    cv2.putText(tl, "BEAT", (4, 14), cv2.FONT_HERSHEY_SIMPLEX,
                0.35, C_BEAT_MK, 1, cv2.LINE_AA)
    cv2.putText(tl, "PEAK", (4, TIMELINE_H - 6), cv2.FONT_HERSHEY_SIMPLEX,
                0.35, C_PEAK_MK, 1, cv2.LINE_AA)

    return tl


# ── 신호 처리 헬퍼 ─────────────────────────────────────────────────

def _compute_velocity(frames: List[Dict[str, Any]]) -> np.ndarray:
    _KPS = ["left_wrist", "right_wrist", "left_ankle", "right_ankle"]
    positions: List[np.ndarray] = []
    for f in frames:
        lm = f.get("normalized_landmarks") or {}
        coords = []
        for kp in _KPS:
            pt = lm.get(kp)
            if pt:
                coords.extend([pt["x"], pt["y"]])
        positions.append(
            np.array(coords, dtype=float) if coords else np.zeros(len(_KPS) * 2)
        )
    if len(positions) < 2:
        return np.zeros(max(len(positions), 1))
    arr = np.array(positions)
    diffs = np.linalg.norm(np.diff(arr, axis=0), axis=1)
    return np.concatenate([[0.0], diffs])


def _compute_peaks(velocity: np.ndarray) -> List[int]:
    if velocity.std() < 1e-9:
        return []
    norm = velocity / (velocity.std() + 1e-9)
    peaks, _ = find_peaks(norm, distance=5, prominence=0.25)
    return peaks.tolist()


def _draw_offset_graph(
    panel: np.ndarray,
    offsets: List[float],
    ox: int, oy: int, gw: int, gh: int,
) -> None:
    """Beat-vs-Peak 오프셋 바: 중앙=0, 오른쪽=늦음(late), 왼쪽=빠름(early)."""
    cv2.rectangle(panel, (ox, oy), (ox + gw, oy + gh), C_BAR_BG, -1)
    if not offsets:
        return

    n = len(offsets)
    row_h = max(6, gh // n)
    cx = ox + gw // 2
    cv2.line(panel, (cx, oy), (cx, oy + gh), (100, 100, 110), 1)

    for i, off_ms in enumerate(offsets):
        y_row = oy + i * row_h
        t = float(np.clip(off_ms / OFFSET_WIN_MS, -1.0, 1.0))
        bar_x = cx + int(t * (gw // 2))
        abs_off = abs(off_ms)
        if abs_off < 100:
            color = (60, 220, 60)
        elif abs_off < 250:
            color = (40, 200, 255)
        else:
            color = (40, 40, 220)
        y1 = y_row + 1
        y2 = min(y_row + row_h - 1, oy + gh - 1)
        if bar_x >= cx:
            cv2.rectangle(panel, (cx, y1), (max(cx + 1, bar_x), y2), color, -1)
        else:
            cv2.rectangle(panel, (min(cx - 1, bar_x), y1), (cx, y2), color, -1)


def _score_color(score: float) -> Tuple:
    if score >= 80:
        return (80, 220, 80)     # 초록
    if score >= 60:
        return (80, 200, 255)    # 노랑
    return (80, 80, 255)         # 파랑 (낮음)


def _draw_score_bar(
    panel: np.ndarray,
    score: float,
    ox: int, oy: int, w: int,
    h: int = 10,
) -> None:
    """점수를 가로 프로그레스 바로 표시."""
    cv2.rectangle(panel, (ox, oy), (ox + w, oy + h), C_BAR_BG, -1)
    fill = int(score / 100.0 * w)
    if fill > 0:
        cv2.rectangle(panel, (ox, oy), (ox + fill, oy + h), _score_color(score), -1)
    # 점수 텍스트를 바 오른쪽 끝에 작게 표시
    cv2.putText(panel, f"{score:.0f}", (ox + w + 4, oy + h),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, C_TEXT, 1, cv2.LINE_AA)


def _draw_beat_dots(
    panel: np.ndarray,
    passed_results: List[Tuple[int, bool, float]],
    ox: int, oy: int, w: int,
    max_dots: int = 14,
) -> None:
    """최근 비트 적중 여부를 컬러 dot으로 표시. 초록=hit, 파랑=miss."""
    recent = passed_results[-max_dots:]
    r = 5
    spacing = w // max_dots
    for i, (_, hit, _) in enumerate(recent):
        cx = ox + i * spacing + r
        cy = oy + r
        color = (60, 220, 60) if hit else (60, 60, 220)
        cv2.circle(panel, (cx, cy), r, color, -1, cv2.LINE_AA)
        cv2.circle(panel, (cx, cy), r, (180, 180, 180), 1, cv2.LINE_AA)
