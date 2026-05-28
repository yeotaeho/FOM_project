"""Power metric 전용 — 영상에서 파워 측정에 필요한 데이터 추출 파이프라인."""

import math
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    PoseLandmarker,
    PoseLandmarkerOptions,
    RunningMode,
)
import numpy as np
import pandas as pd

from .pose_geometry import compute_bone_vectors, compute_joint_angles

# MediaPipe 33개 랜드마크 이름 (인덱스 순서 고정)
_LANDMARK_NAMES: List[str] = [
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

# pose_landmarker_full = 기존 model_complexity=1 에 해당
_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task"
)
_MODEL_PATH = Path(__file__).resolve().parent / "pose_landmarker_full.task"


def _ensure_model() -> str:
    if not _MODEL_PATH.exists():
        urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
    return str(_MODEL_PATH)


def _safe_fps(raw: object, default: float = 30.0) -> float:
    try:
        v = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v) or v <= 0:
        return default
    return v


def extract_power_data(video_path: str) -> dict:
    """
    영상 파일에서 파워 채점에 필요한 데이터를 추출해 dict로 반환.

    처리 단계:
      1) 메타데이터 추출 (fps, total_frames)
      2) MediaPipe Tasks API로 프레임별 랜드마크 추출
      3) 선형 보간 + 이동평균 스무딩 (NaN 처리)
      4) 정규화
           Step A — Mid-Hip을 원점(0,0,0)으로 이동
           Step B — Torso Length(Mid-Shoulder↔Mid-Hip)로 나눠 체형 스케일 제거
      5) bone_vectors / joint_angles 계산
    """
    # ── Step 1: 메타데이터 ────────────────────────────────────────────────────
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"영상을 열 수 없습니다: {video_path}")

    fps: float = _safe_fps(cap.get(cv2.CAP_PROP_FPS))

    # ── Step 2: MediaPipe Tasks API 랜드마크 추출 ─────────────────────────────
    cols = [
        f"{name}_{coord}"
        for name in _LANDMARK_NAMES
        for coord in ("x", "y", "z", "vis")
    ]
    raw_rows: List[Optional[List[float]]] = []

    options = PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=_ensure_model()),
        running_mode=RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    frame_index = 0
    with PoseLandmarker.create_from_options(options) as landmarker:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            timestamp_ms = int(frame_index * 1000 / fps)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = landmarker.detect_for_video(mp_image, timestamp_ms)

            if result.pose_landmarks:
                row: List[float] = []
                for lm in result.pose_landmarks[0]:
                    row.extend([lm.x, lm.y, lm.z, lm.visibility])
                raw_rows.append(row)
            else:
                # 랜드마크 미검출 프레임 → NaN 삽입 (이후 보간)
                raw_rows.append([np.nan] * len(cols))
            frame_index += 1

    cap.release()

    # ── Step 3: 보간 + 이동평균 스무딩 ───────────────────────────────────────
    df = pd.DataFrame(raw_rows, columns=cols)
    df = df.interpolate(method="linear", limit_direction="both")
    df = df.ffill().bfill()
    df = df.rolling(window=3, min_periods=1, center=True).mean()

    # ── Step 4 & 5: 정규화 + 기하 계산 → 프레임 JSON 조립 ───────────────────
    frames_output: List[dict] = []

    for fi, row in df.iterrows():
        # 원시 랜드마크 읽기
        landmarks: Dict[str, dict] = {}
        for name in _LANDMARK_NAMES:
            landmarks[name] = {
                "x": float(row[f"{name}_x"]),
                "y": float(row[f"{name}_y"]),
                "z": float(row[f"{name}_z"]),
                "visibility": float(row[f"{name}_vis"]),
            }

        # Step A: Mid-Hip을 원점으로 이동
        mid_hip_x = (landmarks["left_hip"]["x"] + landmarks["right_hip"]["x"]) / 2
        mid_hip_y = (landmarks["left_hip"]["y"] + landmarks["right_hip"]["y"]) / 2
        mid_hip_z = (landmarks["left_hip"]["z"] + landmarks["right_hip"]["z"]) / 2

        # Step B: Torso Length로 나눠 체형 스케일 제거
        mid_shoulder_x = (landmarks["left_shoulder"]["x"] + landmarks["right_shoulder"]["x"]) / 2
        mid_shoulder_y = (landmarks["left_shoulder"]["y"] + landmarks["right_shoulder"]["y"]) / 2
        mid_shoulder_z = (landmarks["left_shoulder"]["z"] + landmarks["right_shoulder"]["z"]) / 2

        torso_length = float(np.sqrt(
            (mid_shoulder_x - mid_hip_x) ** 2 +
            (mid_shoulder_y - mid_hip_y) ** 2 +
            (mid_shoulder_z - mid_hip_z) ** 2
        ))
        if torso_length < 1e-6:
            torso_length = 1.0

        normalized_landmarks: Dict[str, dict] = {}
        for name in _LANDMARK_NAMES:
            normalized_landmarks[name] = {
                "x": float((landmarks[name]["x"] - mid_hip_x) / torso_length),
                "y": float((landmarks[name]["y"] - mid_hip_y) / torso_length),
                "z": float((landmarks[name]["z"] - mid_hip_z) / torso_length),
            }

        frames_output.append({
            "frame_index":          int(fi),
            "time_sec":             round(int(fi) / fps, 4),
            "landmarks":            landmarks,
            "normalized_landmarks": normalized_landmarks,
            "bone_vectors":         compute_bone_vectors(normalized_landmarks),
            "joint_angles":         compute_joint_angles(normalized_landmarks),
        })

    return {
        "fps":          fps,
        "total_frames": len(frames_output),
        "frames":       frames_output,
    }
