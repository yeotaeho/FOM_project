"""
MediaPipe Tasks API (0.10.31+) 포즈 추출.
legacy mp.solutions.pose 는 제거된 버전용.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Any, Optional

import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

from .geometry import pose_center_score

_MODEL_DIR = Path(__file__).resolve().parent / "models"
_MODEL_PATH = _MODEL_DIR / "pose_landmarker_lite.task"
_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
)

# BlazePose 33 landmark index order (Tasks API 동일)
LANDMARK_NAMES = [
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


def ensure_pose_model() -> Path:
    if _MODEL_PATH.is_file():
        return _MODEL_PATH
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"포즈 모델 다운로드 중: {_MODEL_URL}", flush=True)
    urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
    return _MODEL_PATH


def _landmarks_dict_from_normalized_list(landmark_list: Any) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i, name in enumerate(LANDMARK_NAMES):
        if i >= len(landmark_list):
            break
        lm = landmark_list[i]
        vis = getattr(lm, "visibility", None)
        if vis is None:
            vis = getattr(lm, "presence", 1.0)
        out[name] = {
            "x": float(lm.x),
            "y": float(lm.y),
            "z": float(lm.z),
            "visibility": float(vis),
        }
    return out


def _pick_main_pose_landmarks(detection: Any) -> Optional[Any]:
    poses = getattr(detection, "pose_landmarks", None) or []
    if not poses:
        return None
    if len(poses) == 1:
        return poses[0]
    best_list = None
    best_score = -1.0
    for pose_lms in poses:
        d = _landmarks_dict_from_normalized_list(pose_lms)
        sc = pose_center_score(d)
        if sc > best_score:
            best_score = sc
            best_list = pose_lms
    return best_list


def landmarks_row_from_bgr(
    landmarker: vision.PoseLandmarker,
    frame_bgr: Any,
    cols: list[str],
    *,
    timestamp_ms: int = 0,
    video_mode: bool = False,
    prefer_center_crop: bool = True,
    crop_ratio: float = 0.72,
) -> Optional[list[float]]:
    import cv2

    attempts: list[Any] = []
    if prefer_center_crop:
        h, w = frame_bgr.shape[:2]
        cw = max(32, int(w * crop_ratio))
        ch = max(32, int(h * crop_ratio))
        x0 = (w - cw) // 2
        y0 = (h - ch) // 2
        attempts.append(frame_bgr[y0 : y0 + ch, x0 : x0 + cw])
    attempts.append(frame_bgr)

    for img in attempts:
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        if video_mode:
            detection = landmarker.detect_for_video(mp_image, timestamp_ms)
        else:
            detection = landmarker.detect(mp_image)
        pose_lms = _pick_main_pose_landmarks(detection)
        if pose_lms is None:
            continue
        row: list[float] = []
        for i, name in enumerate(LANDMARK_NAMES):
            if i >= len(pose_lms):
                row.extend([float("nan")] * 4)
                continue
            lm = pose_lms[i]
            vis = getattr(lm, "visibility", None)
            if vis is None:
                vis = getattr(lm, "presence", 1.0)
            row.extend([float(lm.x), float(lm.y), float(lm.z), float(vis)])
        return row
    return None


class PoseLandmarkerSession:
    """IMAGE / VIDEO 모드 PoseLandmarker 래퍼."""

    def __init__(self, *, video_mode: bool = False) -> None:
        model_path = ensure_pose_model()
        mode = (
            vision.RunningMode.VIDEO if video_mode else vision.RunningMode.IMAGE
        )
        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=mode,
            num_poses=3,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)
        self._video_mode = video_mode

    def close(self) -> None:
        self._landmarker.close()

    def process_bgr(
        self,
        frame_bgr: Any,
        cols: list[str],
        *,
        timestamp_ms: int = 0,
        prefer_center_crop: bool = True,
    ) -> Optional[list[float]]:
        return landmarks_row_from_bgr(
            self._landmarker,
            frame_bgr,
            cols,
            timestamp_ms=timestamp_ms,
            video_mode=self._video_mode,
            prefer_center_crop=prefer_center_crop,
        )
