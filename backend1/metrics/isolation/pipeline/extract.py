"""
영상 + YOLO bbox → rom 호환 추출 JSON (bone_vectors, joint_angles).

1) track (또는 기존 tracks JSON)
2) crop + MediaPipe Heavy
3) 보간·스무딩·mid-hip/torso 정규화
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
import pandas as pd

from metrics.isolation.config import CROP_PADDING_RATIO, DATA_ARTIFACTS, MP_SMOOTH_WINDOW
from metrics.isolation.pipeline.geometry import compute_bone_vectors, compute_joint_angles
from mediapipe_pose_tasks import frame_timestamp_ms
from metrics.isolation.pipeline.pose_extract import (
    LANDMARK_NAMES,
    CropPoseExtractor,
    nan_row,
    raw_row_from_landmarks,
    track_frame_to_bbox,
)
from metrics.isolation.pipeline.tracker import PersonTracker, TrackFrame


def _load_tracks_json(
    path: Path,
    frame_width: int,
    frame_height: int,
) -> Dict[int, TrackFrame]:
    data = json.loads(path.read_text(encoding="utf-8"))
    by_idx: Dict[int, TrackFrame] = {}
    for item in data:
        idx = int(item["frame_index"])
        bbox = tuple(int(v) for v in item["bbox_xyxy"])
        by_idx[idx] = TrackFrame(
            frame_index=idx,
            time_sec=float(item["time_sec"]),
            bbox_xyxy=bbox,  # type: ignore[arg-type]
            track_id=item.get("track_id"),
            confidence=float(item.get("confidence", 0.0)),
            frame_width=frame_width,
            frame_height=frame_height,
        )
    return by_idx


def _tracks_from_yolo(video_path: Path, **tracker_kw: Any) -> Dict[int, TrackFrame]:
    tracker = PersonTracker(padding_ratio=0.0, **tracker_kw)
    return {t.frame_index: t for t in tracker.track_all(video_path)}


def _build_frames_output(df: pd.DataFrame, fps: float) -> List[dict]:
    frames_output: List[dict] = []
    for fi, row in df.iterrows():
        landmarks: Dict[str, dict] = {}
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

        mid_shoulder_x = (
            landmarks["left_shoulder"]["x"] + landmarks["right_shoulder"]["x"]
        ) / 2
        mid_shoulder_y = (
            landmarks["left_shoulder"]["y"] + landmarks["right_shoulder"]["y"]
        ) / 2
        mid_shoulder_z = (
            landmarks["left_shoulder"]["z"] + landmarks["right_shoulder"]["z"]
        ) / 2

        torso_length = float(
            np.sqrt(
                (mid_shoulder_x - mid_hip_x) ** 2
                + (mid_shoulder_y - mid_hip_y) ** 2
                + (mid_shoulder_z - mid_hip_z) ** 2
            )
        )
        if torso_length < 1e-6:
            torso_length = 1.0

        normalized_landmarks: Dict[str, dict] = {}
        for name in LANDMARK_NAMES:
            normalized_landmarks[name] = {
                "x": float((landmarks[name]["x"] - mid_hip_x) / torso_length),
                "y": float((landmarks[name]["y"] - mid_hip_y) / torso_length),
                "z": float((landmarks[name]["z"] - mid_hip_z) / torso_length),
            }

        bone_vectors = compute_bone_vectors(normalized_landmarks)
        joint_angles = compute_joint_angles(normalized_landmarks)

        frames_output.append(
            {
                "frame_index": int(fi),
                "time_sec": round(int(fi) / fps, 4),
                "landmarks": landmarks,
                "normalized_landmarks": normalized_landmarks,
                "bone_vectors": bone_vectors,
                "joint_angles": joint_angles,
            }
        )
    return frames_output


def extract_from_video(
    video_path: str | Path,
    tracks_by_frame: Optional[Dict[int, TrackFrame]] = None,
    tracks_json_path: Optional[str | Path] = None,
    reuse_yolo: bool = True,
    progress_every: int = 50,
    **tracker_kw: Any,
) -> dict:
    """
    YOLO bbox + MediaPipe Heavy → 추출 dict.

    tracks_json_path 가 있으면 YOLO 재실행 생략.
    """
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"영상 없음: {path}")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"영상을 열 수 없습니다: {path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if tracks_by_frame is None and tracks_json_path:
        tp = Path(tracks_json_path)
        if tp.is_file():
            tracks_by_frame = _load_tracks_json(tp, frame_w, frame_h)

    if tracks_by_frame is None:
        if not reuse_yolo:
            raise ValueError("tracks 없음 — tracks_json_path 지정 또는 reuse_yolo=True")
        cap.release()
        tracks_by_frame = _tracks_from_yolo(path, **tracker_kw)
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise ValueError(f"영상을 열 수 없습니다: {path}")

    if not tracks_by_frame:
        cap.release()
        raise ValueError("트래킹 결과가 비어 있습니다.")

    cols = [
        f"{name}_{coord}"
        for name in LANDMARK_NAMES
        for coord in ("x", "y", "z", "vis")
    ]
    raw_rows: List[List[float]] = []
    row_frame_indices: List[int] = []

    track_indices = sorted(tracks_by_frame.keys())
    n_track = len(track_indices)

    with CropPoseExtractor() as pose:
        for processed, frame_index in enumerate(track_indices, start=1):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ret, frame = cap.read()
            if not ret:
                continue

            track = tracks_by_frame[frame_index]
            bbox = track_frame_to_bbox(track)
            ts_ms = frame_timestamp_ms(frame_index, fps)
            full_lms = pose.process_frame_with_bbox(
                frame, bbox, timestamp_ms=ts_ms, padding_ratio=0.0
            )
            if full_lms is not None:
                raw_rows.append(raw_row_from_landmarks(full_lms))
                row_frame_indices.append(frame_index)
            else:
                raw_rows.append(nan_row())
                row_frame_indices.append(frame_index)

            if progress_every and processed % progress_every == 0:
                print(
                    f"  pose extract: {processed}/{n_track} tracked frames "
                    f"(video {frame_index}/{total_frames})"
                )

    cap.release()

    if not raw_rows:
        raise ValueError("포즈 추출된 프레임이 없습니다.")

    df = pd.DataFrame(raw_rows, columns=cols)
    df = df.interpolate(method="linear", limit_direction="both")
    df = df.ffill().bfill()
    df = df.rolling(
        window=MP_SMOOTH_WINDOW, min_periods=1, center=True
    ).mean()

    # frame_index 열을 실제 비디오 인덱스로 복원
    df.index = row_frame_indices
    df = df.sort_index()

    frames_output = _build_frames_output(df, fps)

    return {
        "source_video": path.name,
        "metric": "isolation",
        "pipeline": "yolo11_track+crop_mediapipe_tasks_heavy",
        "crop_padding_ratio": CROP_PADDING_RATIO,
        "fps": fps,
        "total_frames": len(frames_output),
        "frames": frames_output,
    }


def save_extraction_json(data: dict, out_path: str | Path) -> Path:
    from metrics.isolation.pipeline.io import save_json

    return save_json(data, out_path)


def extract_and_save(
    video_path: str | Path,
    out_path: str | Path,
    tracks_json_path: Optional[str | Path] = None,
    **kwargs: Any,
) -> dict:
    """추출 후 JSON 저장."""
    data = extract_from_video(
        video_path,
        tracks_json_path=tracks_json_path,
        **kwargs,
    )
    save_extraction_json(data, out_path)
    return data
