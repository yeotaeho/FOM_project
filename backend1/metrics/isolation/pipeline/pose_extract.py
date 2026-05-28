"""YOLO bbox crop 위에서 MediaPipe Pose Landmarker Tasks API (Heavy) 추출."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from mediapipe_pose_tasks import (
    LANDMARK_NAMES,
    POSE_LANDMARKER_HEAVY_URL,
    VideoPoseLandmarker,
)
from metrics.isolation.config import (
    CROP_PADDING_RATIO,
    MP_MIN_DETECTION_CONFIDENCE,
    MP_MIN_TRACKING_CONFIDENCE,
    MP_POSE_MODEL,
)
from metrics.isolation.pipeline.tracker import TrackFrame, _clip_bbox_with_padding


def map_crop_landmarks_to_full_frame(
    crop_landmarks: Dict[str, dict],
    bbox_xyxy: Tuple[int, int, int, int],
    frame_width: int,
    frame_height: int,
) -> Dict[str, dict]:
    x1, y1, x2, y2 = bbox_xyxy
    cw = max(1, x2 - x1)
    ch = max(1, y2 - y1)
    out: Dict[str, dict] = {}
    for name in LANDMARK_NAMES:
        lm = crop_landmarks[name]
        out[name] = {
            "x": float((x1 + lm["x"] * cw) / frame_width),
            "y": float((y1 + lm["y"] * ch) / frame_height),
            "z": float(lm["z"]),
            "visibility": float(lm.get("visibility", 1.0)),
        }
    return out


class CropPoseExtractor:
    """PoseLandmarker Heavy — YOLO crop ROI, VIDEO 모드."""

    def __init__(
        self,
        model_path: str = MP_POSE_MODEL,
        min_detection_confidence: float = MP_MIN_DETECTION_CONFIDENCE,
        min_tracking_confidence: float = MP_MIN_TRACKING_CONFIDENCE,
    ) -> None:
        self._landmarker = VideoPoseLandmarker(
            model_path,
            download_url=POSE_LANDMARKER_HEAVY_URL,
            min_pose_detection_confidence=min_detection_confidence,
            min_pose_presence_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

    def close(self) -> None:
        self._landmarker.close()

    def __enter__(self) -> "CropPoseExtractor":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def process_crop(
        self, bgr_crop: np.ndarray, timestamp_ms: int
    ) -> Optional[Dict[str, dict]]:
        if bgr_crop.size == 0 or bgr_crop.shape[0] < 32 or bgr_crop.shape[1] < 32:
            return None
        rgb = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2RGB)
        return self._landmarker.detect_rgb(rgb, timestamp_ms)

    def process_frame_with_bbox(
        self,
        bgr_frame: np.ndarray,
        bbox_xyxy: Tuple[int, int, int, int],
        timestamp_ms: int,
        padding_ratio: float = CROP_PADDING_RATIO,
    ) -> Optional[Dict[str, dict]]:
        h, w = bgr_frame.shape[:2]
        box = _clip_bbox_with_padding(bbox_xyxy, w, h, padding_ratio)
        x1, y1, x2, y2 = box
        crop = bgr_frame[y1:y2, x1:x2]
        crop_lms = self.process_crop(crop, timestamp_ms)
        if crop_lms is None:
            return None
        return map_crop_landmarks_to_full_frame(crop_lms, box, w, h)


def raw_row_from_landmarks(landmarks: Dict[str, dict]) -> List[float]:
    row: List[float] = []
    for name in LANDMARK_NAMES:
        lm = landmarks[name]
        row.extend([lm["x"], lm["y"], lm["z"], lm["visibility"]])
    return row


def nan_row() -> List[float]:
    return [np.nan] * (len(LANDMARK_NAMES) * 4)


def track_frame_to_bbox(track: TrackFrame) -> Tuple[int, int, int, int]:
    if CROP_PADDING_RATIO > 0:
        return _clip_bbox_with_padding(
            track.bbox_xyxy,
            track.frame_width,
            track.frame_height,
            CROP_PADDING_RATIO,
        )
    return track.bbox_xyxy
