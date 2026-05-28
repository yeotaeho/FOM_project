"""추출 JSON을 영상 프레임에 오버레이하여 video_data에 저장."""

from pathlib import Path
from typing import Dict, List, Tuple

import cv2
import numpy as np

from .pose_geometry import BONE_SEGMENTS
from .storage_paths import VIDEO_DATA_DIR, build_annotated_video_meta, ensure_storage_dirs

# MediaPipe Pose landmark index pairs (solutions.pose.POSE_CONNECTIONS)
_MP_POSE_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8),
    (9, 10),
    (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21), (17, 19),
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
    (11, 23), (12, 24), (23, 24), (23, 25), (24, 26), (25, 27), (26, 28),
    (27, 29), (28, 30), (29, 31), (30, 32), (27, 31), (28, 32),
)

# 화면에 각도 숫자를 붙일 관절 (landmark 이름)
ANGLE_LABEL_JOINTS = {
    "left_elbow": "left_elbow",
    "right_elbow": "right_elbow",
    "left_knee": "left_knee",
    "right_knee": "right_knee",
    "left_shoulder": "left_shoulder",
    "right_shoulder": "right_shoulder",
}

PANEL_WIDTH = 340
COLOR_LM = (0, 255, 128)
COLOR_NORM = (255, 180, 0)
COLOR_BONE = (255, 220, 0)
COLOR_ANGLE = (0, 255, 255)
COLOR_TEXT = (240, 240, 240)
COLOR_PANEL_BG = (24, 24, 28)


def ensure_video_data_dir() -> Path:
    ensure_storage_dirs()
    return VIDEO_DATA_DIR


MAX_ANNOTATED_WIDTH = 854
MAX_ANNOTATED_HEIGHT = 480
# 이전 avc1 기본 출력은 ~75MB/2초 수준으로 모바일 스트리밍·재생에 불리함.
MAX_ANNOTATED_CACHE_BYTES = 15 * 1024 * 1024


def _open_video_writer(
    output_path: Path, fps: float, size: tuple[int, int]
) -> cv2.VideoWriter | None:
    """용량·호환: mp4v 우선(기존 ~7MB 수준), 이후 H.264."""
    for codec in ("mp4v", "avc1", "H264"):
        fourcc = cv2.VideoWriter_fourcc(*codec)
        writer = cv2.VideoWriter(str(output_path), fourcc, fps, size)
        if writer.isOpened():
            return writer
        writer.release()
    return None


def _annotated_output_fps(
    cap: cv2.VideoCapture,
    frames_data: List[dict],
    extraction_result: dict,
) -> float:
    """샘플 프레임 수에 맞춰 원본 영상 길이와 동일하게 재생되도록 fps 산출."""
    src_fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    total = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1.0)
    src_dur = total / src_fps if src_fps > 0 else 1.0
    n = max(1, len(frames_data))
    if src_dur > 0:
        return max(1.0, min(30.0, n / src_dur))
    target = extraction_result.get("extraction_target_fps")
    if target is not None and float(target) > 0:
        return float(target)
    stride = int(extraction_result.get("sample_stride") or 1)
    if stride > 1 and src_fps > 0:
        return max(1.0, src_fps / stride)
    return 15.0


def _scale_output_size(width: int, height: int) -> tuple[int, int]:
    """출력 annotated MP4 — 최대 854×480 (480p) 유지."""
    scale = min(
        MAX_ANNOTATED_WIDTH / width,
        MAX_ANNOTATED_HEIGHT / height,
        1.0,
    )
    if scale >= 1.0:
        return width, height
    return max(2, int(width * scale)), max(2, int(height * scale))


def _resize_frame(frame: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    h, w = frame.shape[:2]
    if w == out_w and h == out_h:
        return frame
    return cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA)


def _lm_pixel(lm: dict, w: int, h: int) -> Tuple[int, int]:
    return int(lm["x"] * w), int(lm["y"] * h)


def _mid_pixel(
    lms: Dict[str, dict], a: str, b: str, w: int, h: int
) -> Tuple[int, int]:
    mx = (lms[a]["x"] + lms[b]["x"]) / 2
    my = (lms[a]["y"] + lms[b]["y"]) / 2
    return int(mx * w), int(my * h)


def _resolve_lm_pixel(
    name: str, lms: Dict[str, dict], w: int, h: int
) -> Tuple[int, int]:
    if name == "mid_hip":
        return _mid_pixel(lms, "left_hip", "right_hip", w, h)
    if name == "mid_shoulder":
        return _mid_pixel(lms, "left_shoulder", "right_shoulder", w, h)
    return _lm_pixel(lms[name], w, h)


def _draw_skeleton_by_names(
    canvas: np.ndarray,
    lms: Dict[str, dict],
    connections: List[Tuple[str, str]],
    w: int,
    h: int,
    color: Tuple[int, int, int],
    thickness: int = 2,
) -> None:
    for a, b in connections:
        if a not in lms or b not in lms:
            continue
        p1 = _lm_pixel(lms[a], w, h)
        p2 = _lm_pixel(lms[b], w, h)
        cv2.line(canvas, p1, p2, color, thickness, cv2.LINE_AA)


# MediaPipe 인덱스 → 이름 (extraction_service.LANDMARK_NAMES 순서와 동일)
_LANDMARK_BY_INDEX = [
    "nose", "left_eye_inner", "left_eye", "left_eye_outer",
    "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear", "mouth_left", "mouth_right",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_pinky", "right_pinky",
    "left_index", "right_index", "left_thumb", "right_thumb",
    "left_hip", "right_hip", "left_knee", "right_knee",
    "left_ankle", "right_ankle", "left_heel", "right_heel",
    "left_foot_index", "right_foot_index",
]

_SCREEN_CONNECTIONS: List[Tuple[str, str]] = [
    (_LANDMARK_BY_INDEX[i], _LANDMARK_BY_INDEX[j])
    for i, j in _MP_POSE_CONNECTIONS
    if i < len(_LANDMARK_BY_INDEX) and j < len(_LANDMARK_BY_INDEX)
]


def _draw_landmarks_overlay(
    frame: np.ndarray,
    frame_data: dict,
) -> np.ndarray:
    h, w = frame.shape[:2]
    lms = frame_data["landmarks"]
    out = frame.copy()

    _draw_skeleton_by_names(out, lms, _SCREEN_CONNECTIONS, w, h, COLOR_LM, 2)
    for name, lm in lms.items():
        if lm.get("visibility", 1.0) < 0.3:
            continue
        cv2.circle(out, _lm_pixel(lm, w, h), 4, COLOR_LM, -1, cv2.LINE_AA)

    # bone_vectors — 화면 좌표(landmarks)로 화살표
    for _bone_name, start, end in BONE_SEGMENTS:
        p1 = _resolve_lm_pixel(start, lms, w, h)
        p2 = _resolve_lm_pixel(end, lms, w, h)
        cv2.arrowedLine(out, p1, p2, COLOR_BONE, 2, tipLength=0.2, line_type=cv2.LINE_AA)

    joint_angles = frame_data.get("joint_angles", {})
    for angle_key, joint_name in ANGLE_LABEL_JOINTS.items():
        if angle_key not in joint_angles or joint_name not in lms:
            continue
        pt = _lm_pixel(lms[joint_name], w, h)
        label = f"{angle_key}: {joint_angles[angle_key]:.1f}"
        cv2.putText(
            out, label, (pt[0] + 8, pt[1] - 8),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_ANGLE, 1, cv2.LINE_AA,
        )

    idx = frame_data.get("frame_index", 0)
    t = frame_data.get("time_sec", 0.0)
    cv2.putText(
        out, f"frame {idx}  t={t:.2f}s", (12, 28),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, COLOR_TEXT, 2, cv2.LINE_AA,
    )
    return out


def _draw_normalized_mini(
    panel: np.ndarray,
    norm_lms: Dict[str, dict],
    ox: int,
    oy: int,
    pw: int,
    ph: int,
) -> None:
    """패널 안에 정규화 스켈레톤 2D 미니맵 (x,y 투영)."""
    xs = [p["x"] for p in norm_lms.values()]
    ys = [p["y"] for p in norm_lms.values()]
    if not xs:
        return
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span = max(max_x - min_x, max_y - min_y, 0.01)
    pad = 20
    scale = min((pw - 2 * pad) / span, (ph - 2 * pad) / span)

    def to_panel(name: str) -> Tuple[int, int]:
        if name == "mid_hip":
            nx = (norm_lms["left_hip"]["x"] + norm_lms["right_hip"]["x"]) / 2
            ny = (norm_lms["left_hip"]["y"] + norm_lms["right_hip"]["y"]) / 2
        elif name == "mid_shoulder":
            nx = (norm_lms["left_shoulder"]["x"] + norm_lms["right_shoulder"]["x"]) / 2
            ny = (norm_lms["left_shoulder"]["y"] + norm_lms["right_shoulder"]["y"]) / 2
        else:
            nx, ny = norm_lms[name]["x"], norm_lms[name]["y"]
        cx = ox + pw // 2
        cy = oy + ph // 2
        px = int(cx + (nx - (min_x + max_x) / 2) * scale)
        py = int(cy + (ny - (min_y + max_y) / 2) * scale)
        return px, py

    for _name, start, end in BONE_SEGMENTS:
        try:
            p1 = to_panel(start)
            p2 = to_panel(end)
        except KeyError:
            continue
        cv2.line(panel, p1, p2, COLOR_NORM, 2, cv2.LINE_AA)

    for name in ("left_shoulder", "right_shoulder", "left_hip", "right_hip", "nose"):
        if name in norm_lms:
            cv2.circle(panel, to_panel(name), 3, COLOR_NORM, -1, cv2.LINE_AA)


def _build_side_panel(frame_data: dict, panel_h: int) -> np.ndarray:
    panel = np.full((panel_h, PANEL_WIDTH, 3), COLOR_PANEL_BG, dtype=np.uint8)
    y = 28
    line_h = 22

    def put(line: str, color=COLOR_TEXT, scale=0.48) -> None:
        nonlocal y
        cv2.putText(
            panel, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX,
            scale, color, 1, cv2.LINE_AA,
        )
        y += line_h

    put("Analysis Panel", COLOR_LM, 0.55)
    y += 4
    put("--- joint_angles (deg) ---", (180, 180, 180), 0.42)
    for k, v in frame_data.get("joint_angles", {}).items():
        put(f"  {k}: {v:.1f}")

    y += 6
    put("--- bone_vectors ---", (180, 180, 180), 0.42)
    for k, v in frame_data.get("bone_vectors", {}).items():
        put(
            f"  {k}: ({v['x']:.2f},{v['y']:.2f},{v['z']:.2f})"
            f" L={v['magnitude']:.2f}",
            scale=0.38,
        )

    y += 6
    put("--- normalized (mini) ---", (180, 180, 180), 0.42)
    mini_h = min(220, panel_h - y - 20)
    if mini_h > 40:
        _draw_normalized_mini(
            panel,
            frame_data.get("normalized_landmarks", {}),
            0, y, PANEL_WIDTH, mini_h,
        )

    y = panel_h - 80
    put("--- landmarks (sample) ---", (180, 180, 180), 0.42)
    lms = frame_data.get("landmarks", {})
    for name in ("nose", "left_wrist", "right_wrist"):
        if name in lms:
            p = lms[name]
            put(
                f"  {name}: x={p['x']:.3f} y={p['y']:.3f}"
                f" z={p['z']:.3f}",
                scale=0.38,
            )

    return panel


def render_annotated_video(
    source_video_path: str,
    extraction_result: dict,
    output_filename: str,
) -> Path:
    """
    원본 영상 + 프레임별 분석 오버레이 → domain1/video_data/{output_filename}
  """
    ensure_video_data_dir()
    output_path = VIDEO_DATA_DIR / output_filename

    if extraction_result.get("schema") == "rom_v1":
        raise ValueError(
            "rom_v1 추출본은 annotated MP4를 생성하지 않습니다. "
            "include_annotated_video=True 또는 extraction_mode=full 로 추출하세요."
        )

    frames_data: List[dict] = extraction_result["frames"]

    cap = cv2.VideoCapture(source_video_path)
    if not cap.isOpened():
        raise ValueError(f"시각화용 영상을 열 수 없습니다: {source_video_path}")

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out_w, out_h = _scale_output_size(w + PANEL_WIDTH, h)
    fps = _annotated_output_fps(cap, frames_data, extraction_result)

    writer = _open_video_writer(output_path, fps, (out_w, out_h))
    if writer is None:
        cap.release()
        raise ValueError(
            "annotated 영상 Writer를 열 수 없습니다 (H.264/avc1/mp4v 코덱)"
        )

    for frame_data in frames_data:
        src_idx = frame_data.get("source_frame_index")
        if src_idx is not None:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(src_idx))
        ret, frame = cap.read()
        if not ret:
            break
        vis = _draw_landmarks_overlay(frame, frame_data)
        panel = _build_side_panel(frame_data, h)
        combined = np.hstack([vis, panel])
        combined = _resize_frame(combined, out_w, out_h)
        writer.write(combined)

    cap.release()
    writer.release()
    return output_path


# build_annotated_video_meta → storage_paths에서 re-export
