"""
분할 화면 비교 결과 영상 — 좌=기준, 우=관절별 실시간 창의성 + 강조.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from .joint_live_viz import (
    DISPLAY_JOINTS,
    JointScoreSmoother,
    analyze_frame_joints,
)

_SKELETON_EDGES = (
    ("left_shoulder", "right_shoulder"),
    ("left_shoulder", "left_elbow"),
    ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"),
    ("right_elbow", "right_wrist"),
    ("left_shoulder", "left_hip"),
    ("right_shoulder", "right_hip"),
    ("left_hip", "right_hip"),
    ("left_hip", "left_knee"),
    ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"),
    ("right_knee", "right_ankle"),
)

# BGR — 사람 위에 선명하게 덮는 고채도 색
_COLOR_OUTLINE = (0, 0, 0)
_COLOR_REF_LINE = (0, 255, 255)       # 시안
_COLOR_REF_JOINT = (255, 255, 0)      # 노랑
_COLOR_RIGHT_SKEL = (255, 0, 255)     # 마젠타
_COLOR_HIGH = (0, 255, 0)             # 라임 (강조)
_COLOR_HIGH_RING = (0, 255, 128)
_COLOR_LOW = (255, 80, 180)           # 핑크
_COLOR_MID = (0, 165, 255)            # 오렌지
_COLOR_TEXT = (255, 255, 255)
_COLOR_BOX = (40, 20, 60)

_LINE_REF = 4
_LINE_SCORE = 5
_LINE_SCORE_HI = 7
_JOINT_REF = 8
_JOINT_SCORE = 10
_JOINT_SCORE_HI = 14


def _resolve_ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _attach_audio(silent_path: Path, source_video: str, out_path: Path) -> None:
    ffmpeg = _resolve_ffmpeg()
    if not ffmpeg:
        shutil.copy2(silent_path, out_path)
        return
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(silent_path),
        "-i",
        str(source_video),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0?",
        "-shortest",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        shutil.copy2(silent_path, out_path)


def _frames_by_source(frames: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for fr in frames:
        src = int(fr.get("source_frame_index", fr.get("frame_index", 0)))
        out[src] = fr
    return out


def _joint_color(score: float, highlight: bool) -> tuple[int, int, int]:
    if highlight:
        return _COLOR_HIGH
    if score >= 70:
        return (0, 255, 128)
    if score >= 45:
        return _COLOR_MID
    return _COLOR_LOW


def _stroke_line(
    img: np.ndarray,
    p1: tuple[int, int],
    p2: tuple[int, int],
    color: tuple[int, int, int],
    thickness: int,
) -> None:
    import cv2

    outline = thickness + 3
    cv2.line(img, p1, p2, _COLOR_OUTLINE, outline, cv2.LINE_AA)
    cv2.line(img, p1, p2, color, thickness, cv2.LINE_AA)


def _stroke_circle(
    img: np.ndarray,
    center: tuple[int, int],
    radius: int,
    color: tuple[int, int, int],
    *,
    ring: tuple[int, int, int] | None = None,
) -> None:
    import cv2

    if ring is not None:
        cv2.circle(img, center, radius + 5, _COLOR_OUTLINE, 4, cv2.LINE_AA)
        cv2.circle(img, center, radius + 4, ring, 3, cv2.LINE_AA)
    cv2.circle(img, center, radius + 2, _COLOR_OUTLINE, -1, cv2.LINE_AA)
    cv2.circle(img, center, radius, color, -1, cv2.LINE_AA)
    cv2.circle(img, center, radius + 1, (255, 255, 255), 1, cv2.LINE_AA)


def _draw_score_text(
    img: np.ndarray,
    text: str,
    pos: tuple[int, int],
    color: tuple[int, int, int],
    *,
    large: bool = False,
) -> None:
    import cv2

    scale = 0.72 if large else 0.58
    thick_fg = 2 if large else 2
    thick_bg = 5 if large else 4
    cv2.putText(
        img,
        text,
        pos,
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        _COLOR_OUTLINE,
        thick_bg,
        cv2.LINE_AA,
    )
    cv2.putText(
        img,
        text,
        pos,
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        color,
        thick_fg,
        cv2.LINE_AA,
    )


def _landmark_px(
    lm: dict[str, float],
    x0: int,
    y0: int,
    pw: int,
    ph: int,
) -> tuple[int, int] | None:
    px = int(x0 + float(lm["x"]) * pw)
    py = int(y0 + float(lm["y"]) * ph)
    return px, py


def _draw_ref_skeleton(
    img: np.ndarray,
    landmarks: dict[str, dict],
    x0: int,
    y0: int,
    pw: int,
    ph: int,
) -> dict[str, tuple[int, int]]:
    import cv2

    pts: dict[str, tuple[int, int]] = {}
    for name, _ in DISPLAY_JOINTS:
        lm = landmarks.get(name)
        if not lm or float(lm.get("visibility", 1)) < 0.35:
            continue
        p = _landmark_px(lm, x0, y0, pw, ph)
        if p and 0 <= p[0] < img.shape[1] and 0 <= p[1] < img.shape[0]:
            pts[name] = p

    for a, b in _SKELETON_EDGES:
        if a in pts and b in pts:
            _stroke_line(img, pts[a], pts[b], _COLOR_REF_LINE, _LINE_REF)
    for p in pts.values():
        _stroke_circle(img, p, _JOINT_REF, _COLOR_REF_JOINT)
    return pts


def _draw_scored_skeleton(
    img: np.ndarray,
    landmarks: dict[str, dict],
    joint_info: list[dict[str, Any]],
    x0: int,
    y0: int,
    pw: int,
    ph: int,
) -> None:
    import cv2

    score_by_name = {
        j["joint"]: j for j in joint_info if j.get("joint") and not j.get("skipped")
    }
    pts: dict[str, tuple[int, int]] = {}
    for name, _ in DISPLAY_JOINTS:
        lm = landmarks.get(name)
        if not lm or float(lm.get("visibility", 1)) < 0.35:
            continue
        p = _landmark_px(lm, x0, y0, pw, ph)
        if p and 0 <= p[0] < img.shape[1] and 0 <= p[1] < img.shape[0]:
            pts[name] = p

    for a, b in _SKELETON_EDGES:
        if a not in pts or b not in pts:
            continue
        ja = score_by_name.get(a, {})
        jb = score_by_name.get(b, {})
        sa = float(ja.get("creativity_score") or 0)
        sb = float(jb.get("creativity_score") or 0)
        ha = ja.get("highlight") or sa >= 62
        hb = jb.get("highlight") or sb >= 62
        col = _COLOR_HIGH if (ha or hb) else _COLOR_RIGHT_SKEL
        thick = _LINE_SCORE_HI if (ha and hb) else (_LINE_SCORE if (ha or hb) else _LINE_SCORE - 1)
        _stroke_line(img, pts[a], pts[b], col, thick)

    for name, p in pts.items():
        ji = score_by_name.get(name, {})
        sc = float(ji.get("creativity_score") or 0)
        hi = bool(ji.get("highlight"))
        col = _joint_color(sc, hi)
        radius = _JOINT_SCORE_HI if hi else _JOINT_SCORE
        ring = _COLOR_HIGH_RING if hi else None
        _stroke_circle(img, p, radius, col, ring=ring)

        txt = f"{sc:.0f}"
        tx = min(p[0] + 10, img.shape[1] - 48)
        ty = max(p[1] - 8, 20)
        _draw_score_text(img, txt, (tx, ty), col, large=hi)


def _draw_panel_header(
    img: np.ndarray,
    x: int,
    y: int,
    w: int,
    title: str,
    sub: str,
    *,
    accent: tuple[int, int, int],
) -> None:
    import cv2

    overlay = img.copy()
    cv2.rectangle(overlay, (x, y), (x + w, y + 44), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.55, img, 0.45, 0, img)
    _draw_score_text(img, title, (x + 10, y + 26), accent, large=True)
    if sub:
        _draw_score_text(img, sub, (x + 10, y + 42), _COLOR_TEXT)


def _draw_bottom_panel(
    img: np.ndarray,
    x: int,
    y: int,
    w: int,
    lines: list[str],
    *,
    accent: tuple[int, int, int],
) -> None:
    import cv2

    h = 28 + 22 * len(lines)
    overlay = img.copy()
    cv2.rectangle(overlay, (x, y), (x + w, y + h), _COLOR_BOX, -1)
    cv2.addWeighted(overlay, 0.5, img, 0.5, 0, img)
    ty = y + 22
    for i, line in enumerate(lines):
        col = accent if i == 0 else _COLOR_TEXT
        _draw_score_text(
            img,
            line,
            (x + 10, ty),
            col,
            large=(i == 0),
        )
        ty += 22


def render_split_screen_video(
    video_path: str,
    user_raw: dict[str, Any],
    ref_raw: dict[str, Any],
    analysis: dict[str, Any],
    output_path: str | Path,
    *,
    split_meta: dict[str, Any],
    left_label: str = "기준",
    right_label: str = "창의성",
) -> Path:
    """
    좌측=레퍼런스(기준), 우측=비교 대상 — 매 프레임 대표 관절 창의성 수치·고득점 강조.
    """
    import cv2

    path = Path(video_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"영상을 열 수 없습니다: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    split_x = int(split_meta.get("split_x_px", int(w * split_meta.get("split_ratio", 0.5))))

    creativity = analysis.get("creativity") or {}
    total_score = float(creativity.get("score") or 0.0)

    ref_by_src = _frames_by_source(ref_raw.get("frames") or [])
    user_by_src = _frames_by_source(user_raw.get("frames") or [])

    # 화면은 항상 좌=기준(ref), 우=비교(user)
    user_panel = split_meta.get("user_panel", "left")

    silent = out.with_suffix(".silent.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(silent), fourcc, fps, (w, h))
    smoother = JointScoreSmoother()

    fi = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        left_w = split_x
        right_w = w - split_x

        if user_panel == "left":
            user_fr = user_by_src.get(fi)
            ref_fr = ref_by_src.get(fi)
        else:
            ref_fr = user_by_src.get(fi)
            user_fr = ref_by_src.get(fi)

        if ref_fr:
            _draw_ref_skeleton(
                frame,
                ref_fr.get("landmarks") or {},
                0,
                0,
                left_w,
                h,
            )
            _draw_panel_header(
                frame,
                8,
                8,
                left_w - 16,
                left_label,
                "REFERENCE",
                accent=_COLOR_REF_JOINT,
            )

        frame_analysis: dict[str, Any] = {}
        fs = 0.0
        if ref_fr and user_fr:
            frame_analysis = analyze_frame_joints(ref_fr, user_fr)
            joints = smoother.smooth(frame_analysis.get("joints") or [])
            frame_analysis["joints"] = joints
            frame_analysis["frame_score"] = round(
                sum(float(j["creativity_score"]) for j in joints if j.get("creativity_score"))
                / max(1, sum(1 for j in joints if j.get("creativity_score"))),
                1,
            )
            top = sorted(
                [j for j in joints if j.get("creativity_score") is not None],
                key=lambda x: float(x["creativity_score"]),
                reverse=True,
            )[:3]
            frame_analysis["top_joints"] = top

        if user_fr and frame_analysis:
            _draw_scored_skeleton(
                frame,
                user_fr.get("landmarks") or {},
                frame_analysis.get("joints") or [],
                split_x,
                0,
                right_w,
                h,
            )
            fs = frame_analysis.get("frame_score", 0)
            top_txt = ", ".join(
                f"{t.get('label')}{t.get('creativity_score')}"
                for t in (frame_analysis.get("top_joints") or [])[:3]
            )
            _draw_panel_header(
                frame,
                split_x + 8,
                8,
                right_w - 16,
                f"{right_label}  {fs:.0f}점",
                "관절별 실시간",
                accent=_COLOR_HIGH if fs >= 62 else _COLOR_MID,
            )

        hi_names = [
            j.get("label")
            for j in (frame_analysis.get("joints") or [])
            if j.get("highlight")
        ]
        box_y = h - 100
        _draw_bottom_panel(
            frame,
            8,
            box_y,
            left_w - 16,
            [left_label, "기준 포즈"],
            accent=_COLOR_REF_JOINT,
        )
        right_lines = [
            right_label,
            f"프레임 {fs:.0f} / 전체 {total_score:.1f}" if user_fr else right_label,
        ]
        if hi_names:
            right_lines.append(f"강조: {', '.join(hi_names[:5])}")
        _draw_bottom_panel(
            frame,
            split_x + 8,
            box_y,
            right_w - 16,
            right_lines,
            accent=_COLOR_HIGH if hi_names else _COLOR_RIGHT_SKEL,
        )

        cv2.line(frame, (split_x, 0), (split_x, h), _COLOR_OUTLINE, 5, cv2.LINE_AA)
        cv2.line(frame, (split_x, 0), (split_x, h), (255, 255, 255), 2, cv2.LINE_AA)
        writer.write(frame)
        fi += 1

    cap.release()
    writer.release()

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        _attach_audio(silent, str(path), tmp_path)
        shutil.copy2(tmp_path, out)
    finally:
        if silent.exists():
            silent.unlink()
        if tmp_path.exists():
            tmp_path.unlink()

    return out
