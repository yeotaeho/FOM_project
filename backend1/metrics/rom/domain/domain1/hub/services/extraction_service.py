import math
import os
import shutil
import socket
import urllib.request
import cv2
import mediapipe as mp
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from .pose_geometry import (
    LANDMARKS_FOR_ROM,
    compute_bone_vectors,
    compute_joint_angles,
)

# MediaPipe Tasks API 모델 (power metric과 동일 full task)
_MODEL_DIR = Path(__file__).parent.parent.parent.parent.parent / "models"
_MODEL_PATH = _MODEL_DIR / "pose_landmarker_full.task"
_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task"
)
_MIN_MODEL_BYTES = 5_000_000
_MODEL_DOWNLOAD_TIMEOUT_SEC = 120


def _runtime_model_file() -> Path:
    """
    MediaPipe 네이티브는 Windows에서 non-ASCII 경로(한글 사용자명·OneDrive)에서
    .task 를 열지 못하는 경우가 많음 → ASCII 전용 디렉터리만 사용.
    """
    candidates = (
        Path("C:/fom_mediapipe_cache"),
        Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "FOM" / "mediapipe",
    )
    for base in candidates:
        try:
            base.mkdir(parents=True, exist_ok=True)
            target = (base / "pose_landmarker_full.task").resolve()
            if str(target).isascii():
                return target
        except OSError:
            continue
    raise RuntimeError(
        "MediaPipe 모델용 ASCII 경로를 만들 수 없습니다. "
        "C:/fom_mediapipe_cache 쓰기 권한을 확인하세요."
    )


def _ensure_model() -> str:
    """모델을 ASCII 경로에 다운로드·캐시 후 MediaPipe에 전달."""
    target = _runtime_model_file()
    if not target.is_file() or target.stat().st_size < _MIN_MODEL_BYTES:
        prev = socket.getdefaulttimeout()
        socket.setdefaulttimeout(_MODEL_DOWNLOAD_TIMEOUT_SEC)
        try:
            urllib.request.urlretrieve(_MODEL_URL, target)
        finally:
            socket.setdefaulttimeout(prev)

    if not target.is_file() or target.stat().st_size < _MIN_MODEL_BYTES:
        size = target.stat().st_size if target.is_file() else 0
        raise RuntimeError(
            f"pose 모델 다운로드 실패 또는 불완전: {target} (size={size} bytes). "
            f"URL 수동 다운로드 후 해당 경로에 저장: {_MODEL_URL}"
        )

    try:
        _MODEL_DIR.mkdir(parents=True, exist_ok=True)
        if not _MODEL_PATH.is_file() or _MODEL_PATH.stat().st_size < _MIN_MODEL_BYTES:
            shutil.copy2(target, _MODEL_PATH)
    except OSError:
        pass

    return str(target)

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

EXTRACTION_SCHEMA_ROM = "rom_v1"
EXTRACTION_SCHEMA_FULL = "full_v1"
DEFAULT_TARGET_FPS_ROM = 15.0

ExtractionMode = Literal["rom", "full"]


def _safe_fps(raw: object, default: float = 30.0) -> float:
    """OpenCV CAP_PROP_FPS 가 0·NaN 인 경우(에뮬레이터·일부 mp4) 기본값 사용."""
    try:
        v = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v) or v <= 0:
        return default
    return v


def _safe_frame_count(raw: object) -> int:
    try:
        v = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(v) or v < 0:
        return 0
    return int(v)


def resolve_sample_stride(
    source_fps: float,
    target_fps: Optional[float] = DEFAULT_TARGET_FPS_ROM,
    frame_stride: Optional[int] = None,
) -> int:
    """MediaPipe 처리 간격. frame_stride 우선, target_fps<=0 이면 전체 프레임."""
    if frame_stride is not None:
        return max(1, int(frame_stride))
    if target_fps is None or target_fps <= 0:
        return 1
    if source_fps <= 0:
        source_fps = 30.0
    if target_fps >= source_fps:
        return 1
    return max(1, int(round(source_fps / target_fps)))


def _mediapipe_landmark_df(
    video_path: str,
    *,
    target_fps: Optional[float] = DEFAULT_TARGET_FPS_ROM,
    frame_stride: Optional[int] = None,
) -> Tuple[pd.DataFrame, float, int, int, int]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"영상을 열 수 없습니다: {video_path}")

    try:
        source_fps: float = _safe_fps(cap.get(cv2.CAP_PROP_FPS))
        source_total_frames: int = _safe_frame_count(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        stride = resolve_sample_stride(source_fps, target_fps, frame_stride)

        cols = [
            f"{name}_{coord}"
            for name in LANDMARK_NAMES
            for coord in ("x", "y", "z", "vis")
        ]
        raw_rows: List[List[float]] = []
        source_frame_indices: List[int] = []

        # MediaPipe Tasks API (VIDEO 모드)
        BaseOptions = mp.tasks.BaseOptions
        PoseLandmarker = mp.tasks.vision.PoseLandmarker
        PoseLandmarkerOptions = mp.tasks.vision.PoseLandmarkerOptions
        VisionRunningMode = mp.tasks.vision.RunningMode

        model_path = _ensure_model()
        options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=VisionRunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )

        frame_idx = 0
        with PoseLandmarker.create_from_options(options) as landmarker:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                if frame_idx % stride != 0:
                    frame_idx += 1
                    continue

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                timestamp_ms = int(frame_idx * 1000 / source_fps)

                result = landmarker.detect_for_video(mp_image, timestamp_ms)

                if result.pose_landmarks and len(result.pose_landmarks) > 0:
                    row: List[float] = []
                    for lm in result.pose_landmarks[0]:
                        row.extend([lm.x, lm.y, lm.z, lm.visibility])
                    raw_rows.append(row)
                else:
                    raw_rows.append([np.nan] * len(cols))
                source_frame_indices.append(frame_idx)
                frame_idx += 1
    finally:
        cap.release()

    if not raw_rows:
        raise ValueError("영상에서 처리할 프레임이 없습니다.")

    df = pd.DataFrame(raw_rows, columns=cols)
    df["source_frame_index"] = source_frame_indices

    df = df.interpolate(method="linear", limit_direction="both")
    df = df.ffill().bfill()

    smooth_window = 3 if stride <= 2 else 1
    numeric_cols = cols
    df[numeric_cols] = (
        df[numeric_cols]
        .rolling(window=smooth_window, min_periods=1, center=True)
        .mean()
    )

    return df, source_fps, source_total_frames, stride, len(raw_rows)


def _row_to_landmarks(row: pd.Series, names: Tuple[str, ...]) -> Dict[str, dict]:
    landmarks: Dict[str, dict] = {}
    for name in names:
        landmarks[name] = {
            "x": float(row[f"{name}_x"]),
            "y": float(row[f"{name}_y"]),
            "z": float(row[f"{name}_z"]),
            "visibility": float(row[f"{name}_vis"]),
        }
    return landmarks


def _normalize_landmarks(landmarks: Dict[str, dict]) -> Dict[str, dict]:
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

    normalized: Dict[str, dict] = {}
    for name, lm in landmarks.items():
        normalized[name] = {
            "x": float((lm["x"] - mid_hip_x) / torso_length),
            "y": float((lm["y"] - mid_hip_y) / torso_length),
            "z": float((lm["z"] - mid_hip_z) / torso_length),
        }
    return normalized


def _build_frames_from_df(
    df: pd.DataFrame,
    source_fps: float,
    mode: ExtractionMode,
) -> List[dict]:
    rom_names = tuple(sorted(LANDMARKS_FOR_ROM))
    all_names = tuple(LANDMARK_NAMES)
    landmark_names = rom_names if mode == "rom" else all_names

    frames_output: List[dict] = []
    for seq_i, (_, row) in enumerate(df.iterrows()):
        landmarks = _row_to_landmarks(row, landmark_names)
        normalized_landmarks = _normalize_landmarks(landmarks)
        joint_angles = compute_joint_angles(normalized_landmarks)

        raw_idx = row["source_frame_index"]
        if not math.isfinite(float(raw_idx)):
            continue
        source_idx = int(raw_idx)
        frame: Dict[str, object] = {
            "frame_index": seq_i,
            "source_frame_index": source_idx,
            "time_sec": round(source_idx / source_fps, 4),
            "joint_angles": joint_angles,
        }

        if mode == "full":
            full_landmarks = _row_to_landmarks(row, all_names)
            full_normalized = _normalize_landmarks(full_landmarks)
            frame["landmarks"] = full_landmarks
            frame["normalized_landmarks"] = full_normalized
            frame["bone_vectors"] = compute_bone_vectors(full_normalized)

        frames_output.append(frame)

    return frames_output


def _extraction_sampling_meta(
    source_fps: float,
    source_total_frames: int,
    sample_stride: int,
    processed_frames: int,
    target_fps: Optional[float],
    frame_stride: Optional[int],
) -> Dict[str, object]:
    effective_target = (
        None if sample_stride <= 1 else round(source_fps / sample_stride, 2)
    )
    return {
        "source_fps": source_fps,
        "source_total_frames": source_total_frames,
        "sample_stride": sample_stride,
        "extraction_target_fps": target_fps if frame_stride is None else None,
        "effective_sample_fps": effective_target,
        "total_frames": processed_frames,
    }


def extract_dance_data(
    video_path: str,
    *,
    target_fps: Optional[float] = None,
    frame_stride: Optional[int] = None,
) -> dict:
    """Accuracy용 full 추출. target_fps 미지정·0 이하면 전체 프레임."""
    df, source_fps, source_total, stride, n_proc = _mediapipe_landmark_df(
        video_path,
        target_fps=target_fps,
        frame_stride=frame_stride,
    )
    frames_output = _build_frames_from_df(df, source_fps, mode="full")
    if not frames_output:
        raise ValueError(
            "포즈를 인식한 프레임이 없습니다. 카메라에 전신이 보이도록 다시 촬영해 주세요."
        )
    meta = _extraction_sampling_meta(
        source_fps, source_total, stride, n_proc, target_fps, frame_stride
    )
    return {
        "schema": EXTRACTION_SCHEMA_FULL,
        "fps": source_fps,
        **meta,
        "frames": frames_output,
    }


def extract_rom_data(
    video_path: str,
    *,
    target_fps: Optional[float] = DEFAULT_TARGET_FPS_ROM,
    frame_stride: Optional[int] = None,
) -> dict:
    """ROM 전용: joint_angles + time_sec만 (기본 target_fps=15)."""
    df, source_fps, source_total, stride, n_proc = _mediapipe_landmark_df(
        video_path,
        target_fps=target_fps,
        frame_stride=frame_stride,
    )
    frames_output = _build_frames_from_df(df, source_fps, mode="rom")
    if not frames_output:
        raise ValueError(
            "포즈를 인식한 프레임이 없습니다. 카메라에 전신이 보이도록 다시 촬영해 주세요."
        )
    meta = _extraction_sampling_meta(
        source_fps, source_total, stride, n_proc, target_fps, frame_stride
    )
    return {
        "schema": EXTRACTION_SCHEMA_ROM,
        "fps": source_fps,
        **meta,
        "frames": frames_output,
    }
