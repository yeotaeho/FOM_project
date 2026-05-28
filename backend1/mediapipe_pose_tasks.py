"""MediaPipe Tasks API — Pose Landmarker (VIDEO 모드, 33 랜드마크)."""

from __future__ import annotations

import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

LANDMARK_NAMES: Tuple[str, ...] = (
    "nose",
    "left_eye_inner",
    "left_eye",
    "left_eye_outer",
    "right_eye_inner",
    "right_eye",
    "right_eye_outer",
    "left_ear",
    "right_ear",
    "mouth_left",
    "mouth_right",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_pinky",
    "right_pinky",
    "left_index",
    "right_index",
    "left_thumb",
    "right_thumb",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "left_heel",
    "right_heel",
    "left_foot_index",
    "right_foot_index",
)

MIN_MEDIAPIPE_VERSION = (0, 10, 31)


def _parse_version(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in version.split("."):
        if not piece.isdigit():
            break
        parts.append(int(piece))
    return tuple(parts)


def assert_mediapipe_tasks_compatible() -> None:
    """
    Windows + Py3.12: mediapipe==0.10.30 Tasks API → AttributeError: function 'free' not found.
    requirements.txt: mediapipe>=0.10.31
    """
    import mediapipe as mp

    v = _parse_version(getattr(mp, "__version__", "0"))
    if v < MIN_MEDIAPIPE_VERSION:
        raise RuntimeError(
            f"mediapipe {mp.__version__} 은 PoseLandmarker(Tasks)에 사용할 수 없습니다. "
            f"필요: >=0.10.31. conda activate aiproject 후 "
            "pip install -r requirements.txt 를 실행하세요."
        )


POSE_LANDMARKER_HEAVY_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task"
)
POSE_LANDMARKER_FULL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_full/float16/latest/pose_landmarker_full.task"
)
MODEL_DOWNLOAD_TIMEOUT_SEC = 120

BACKEND1_ROOT = Path(__file__).resolve().parent
ROM_POSE_MODEL_PATH = (
    BACKEND1_ROOT / "metrics" / "rom" / "data" / "models" / "pose_landmarker_full.task"
)


def ensure_pose_model(model_path: str | Path, download_url: str) -> Path:
    path = Path(model_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        return path
    print(f"Downloading pose model → {path} (timeout={MODEL_DOWNLOAD_TIMEOUT_SEC}s)")
    try:
        prev = socket.getdefaulttimeout()
        socket.setdefaulttimeout(MODEL_DOWNLOAD_TIMEOUT_SEC)
        try:
            urllib.request.urlretrieve(download_url, path)
        finally:
            socket.setdefaulttimeout(prev)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise FileNotFoundError(
            f"pose 모델 다운로드 실패: {path}\n"
            f"  URL: {download_url}\n"
            f"  수동: 브라우저로 받아 {path} 에 저장\n"
            f"  원인: {e}"
        ) from e
    if not path.is_file() or path.stat().st_size < 1_000_000:
        raise FileNotFoundError(
            f"pose 모델 파일이 비정상입니다: {path} "
            f"(size={path.stat().st_size if path.is_file() else 0})"
        )
    return path


def landmarks_dict_from_list(landmark_list) -> Dict[str, dict]:
    if len(landmark_list) < len(LANDMARK_NAMES):
        raise ValueError(
            f"랜드마크 수 부족: {len(landmark_list)} < {len(LANDMARK_NAMES)}"
        )
    out: Dict[str, dict] = {}
    for name, lm in zip(LANDMARK_NAMES, landmark_list):
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


class VideoPoseLandmarker:
    """PoseLandmarker — RunningMode.VIDEO (연속 프레임 timestamp_ms 필요)."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        download_url: str,
        min_pose_detection_confidence: float = 0.5,
        min_pose_presence_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ) -> None:
        assert_mediapipe_tasks_compatible()
        import mediapipe as mp
        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python.core import base_options as base_options_lib

        resolved = ensure_pose_model(model_path, download_url)
        base_options = base_options_lib.BaseOptions(model_asset_path=str(resolved))
        options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=min_pose_detection_confidence,
            min_pose_presence_confidence=min_pose_presence_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._mp = mp
        self._landmarker = vision.PoseLandmarker.create_from_options(options)

    def close(self) -> None:
        self._landmarker.close()

    def __enter__(self) -> "VideoPoseLandmarker":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def detect_rgb(
        self, rgb: np.ndarray, timestamp_ms: int
    ) -> Optional[Dict[str, dict]]:
        if rgb.size == 0:
            return None
        if not rgb.flags["C_CONTIGUOUS"]:
            rgb = np.ascontiguousarray(rgb)
        mp_image = self._mp.Image(
            image_format=self._mp.ImageFormat.SRGB, data=rgb
        )
        result = self._landmarker.detect_for_video(mp_image, int(timestamp_ms))
        if not result.pose_landmarks:
            return None
        return landmarks_dict_from_list(result.pose_landmarks[0])


def frame_timestamp_ms(frame_index: int, fps: float) -> int:
    step = int(1000.0 / fps) if fps > 1e-6 else 33
    return max(0, int(frame_index) * max(1, step))
