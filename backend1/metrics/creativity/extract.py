"""
영상·이미지 → 창의성 채점용 추출 JSON (전체 프레임).
보정·샘플링은 preprocess.py 에서 offset 이후 수행.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .geometry import compute_bone_vectors, compute_joint_angles, pose_center_score
from .pose_backend import LANDMARK_NAMES, PoseLandmarkerSession

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

CENTER_CROP_RATIO = 0.72


def is_image_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_SUFFIXES


def _frame_from_landmarks_row(
    row: Any,
    cols: list[str],
    frame_index: int,
    time_sec: float,
    source_frame_index: int,
) -> dict[str, Any]:
    landmarks: dict[str, dict] = {}
    for name in LANDMARK_NAMES:
        landmarks[name] = {
            "x": float(row[f"{name}_x"]),
            "y": float(row[f"{name}_y"]),
            "z": float(row[f"{name}_z"]),
            "visibility": float(row[f"{name}_vis"]),
        }

    mid_hip_x = (landmarks["left_hip"]["x"] + landmarks["right_hip"]["x"]) / 2
    mid_hip_y = (landmarks["left_hip"]["y"] + landmarks["right_hip"]["y"]) / 2
    mid_hip_z = (landmarks["left_hip"]["z"] + landmarks["right_hip"]["z"]) / 2
    mid_shoulder_x = (landmarks["left_shoulder"]["x"] + landmarks["right_shoulder"]["x"]) / 2
    mid_shoulder_y = (landmarks["left_shoulder"]["y"] + landmarks["right_shoulder"]["y"]) / 2
    mid_shoulder_z = (landmarks["left_shoulder"]["z"] + landmarks["right_shoulder"]["z"]) / 2

    import numpy as np

    torso = float(
        np.sqrt(
            (mid_shoulder_x - mid_hip_x) ** 2
            + (mid_shoulder_y - mid_hip_y) ** 2
            + (mid_shoulder_z - mid_hip_z) ** 2
        )
    )
    if torso < 1e-6:
        torso = 1.0

    normalized: dict[str, dict] = {}
    for name in LANDMARK_NAMES:
        normalized[name] = {
            "x": float((landmarks[name]["x"] - mid_hip_x) / torso),
            "y": float((landmarks[name]["y"] - mid_hip_y) / torso),
            "z": float((landmarks[name]["z"] - mid_hip_z) / torso),
        }

    return {
        "frame_index": frame_index,
        "source_frame_index": source_frame_index,
        "time_sec": round(time_sec, 4),
        "landmarks": landmarks,
        "normalized_landmarks": normalized,
        "bone_vectors": compute_bone_vectors(normalized),
        "joint_angles": compute_joint_angles(normalized),
        "main_dancer_center_score": round(pose_center_score(landmarks), 4),
    }


def extract_from_image(image_path: str) -> dict[str, Any]:
    import cv2

    path = Path(image_path)
    if not path.is_file():
        raise ValueError(f"이미지를 찾을 수 없습니다: {image_path}")

    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"이미지를 읽을 수 없습니다: {image_path}")

    cols = [f"{name}_{c}" for name in LANDMARK_NAMES for c in ("x", "y", "z", "vis")]
    session = PoseLandmarkerSession(video_mode=False)
    try:
        row = session.process_bgr(img, cols)
    finally:
        session.close()

    if row is None:
        raise ValueError(f"포즈를 검출하지 못했습니다: {image_path}")

    import pandas as pd

    series = pd.Series(row, index=cols)
    frame = _frame_from_landmarks_row(series, cols, 0, 0.0, 0)

    return {
        "metric": "creativity",
        "source": str(path),
        "media_type": "image",
        "fps": 0.0,
        "total_frames_decoded": 1,
        "frames": [frame],
    }


def extract_from_video(video_path: str) -> dict[str, Any]:
    """영상 전체 프레임 포즈 추출 (샘플링은 preprocess 단계)."""
    import cv2
    import pandas as pd

    path = Path(video_path)
    if not path.is_file():
        raise ValueError(f"영상을 찾을 수 없습니다: {video_path}")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"영상을 열 수 없습니다: {video_path}")

    fps: float = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    total_in_file = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cols = [f"{name}_{c}" for name in LANDMARK_NAMES for c in ("x", "y", "z", "vis")]
    all_rows: list[list[float] | None] = []
    source_indices: list[int] = []

    # IMAGE 모드: 프레임마다 독립 검출 (VIDEO 모드는 timestamp 단조 증가 제약 있음)
    session = PoseLandmarkerSession(video_mode=False)
    try:
        fi = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            row = session.process_bgr(frame, cols)
            if row is not None:
                all_rows.append(row)
            else:
                all_rows.append([float("nan")] * len(cols))
            source_indices.append(fi)
            fi += 1
    finally:
        session.close()
        cap.release()

    decoded = len(all_rows)
    if decoded == 0:
        raise ValueError(f"영상에 프레임이 없습니다: {video_path}")

    df_full = pd.DataFrame(all_rows, columns=cols)
    df_full = df_full.interpolate(method="linear", limit_direction="both").ffill().bfill()
    df_full = df_full.rolling(window=3, min_periods=1, center=True).mean()

    frames_out: list[dict[str, Any]] = []
    for i, src_i in enumerate(source_indices):
        row = df_full.iloc[i]
        time_sec = float(src_i) / fps if fps > 0 else float(i)
        frames_out.append(
            _frame_from_landmarks_row(row, cols, i, time_sec, src_i)
        )

    return {
        "metric": "creativity",
        "source": str(path),
        "media_type": "video",
        "fps": fps,
        "total_frames_decoded": decoded,
        "total_frames_reported": total_in_file,
        "center_crop_ratio": CENTER_CROP_RATIO,
        "frames": frames_out,
    }


def extract_from_media(media_path: str) -> dict[str, Any]:
    if is_image_path(media_path):
        return extract_from_image(media_path)
    return extract_from_video(media_path)


def save_extraction(data: dict[str, Any], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
