"""
세로 분할(좌/우) 단일 영상에서 두 명의 포즈 시퀀스 추출.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from .extract import _frame_from_landmarks_row
from .pose_backend import LANDMARK_NAMES, PoseLandmarkerSession

SplitAxis = Literal["vertical"]


def extract_split_screen_video(
    video_path: str,
    *,
    split_axis: SplitAxis = "vertical",
    split_ratio: float = 0.5,
    left_role: Literal["user", "reference"] = "user",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """
    한 영상을 좌/우(또는 역할 스왑)로 잘라 각각 포즈 추출.

    Returns:
        (user_raw, ref_raw, meta)
    """
    import cv2
    import pandas as pd

    if split_axis != "vertical":
        raise ValueError("현재는 split_axis='vertical' 만 지원합니다.")

    path = Path(video_path)
    if not path.is_file():
        raise ValueError(f"영상을 찾을 수 없습니다: {video_path}")

    ratio = float(split_ratio)
    if not 0.35 <= ratio <= 0.65:
        raise ValueError("split_ratio 는 0.35~0.65 사이여야 합니다.")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"영상을 열 수 없습니다: {video_path}")

    fps: float = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    total_in_file = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    if width < 64 or height < 64:
        cap.release()
        raise ValueError("영상 해상도가 너무 작습니다.")

    split_x = int(width * ratio)
    split_x = max(32, min(width - 32, split_x))

    cols = [f"{name}_{c}" for name in LANDMARK_NAMES for c in ("x", "y", "z", "vis")]
    nan_row = [float("nan")] * len(cols)
    left_rows: list[list[float]] = []
    right_rows: list[list[float]] = []
    source_indices: list[int] = []

    session = PoseLandmarkerSession(video_mode=False)
    try:
        fi = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            left_crop = frame[:, :split_x]
            right_crop = frame[:, split_x:]
            ts_ms = int((fi / fps) * 1000) if fps > 0 else fi * 33
            left_row = session.process_bgr(
                left_crop,
                cols,
                timestamp_ms=ts_ms,
                prefer_center_crop=False,
            )
            right_row = session.process_bgr(
                right_crop,
                cols,
                timestamp_ms=ts_ms,
                prefer_center_crop=False,
            )
            left_rows.append(left_row if left_row is not None else list(nan_row))
            right_rows.append(right_row if right_row is not None else list(nan_row))
            source_indices.append(fi)
            fi += 1
    finally:
        session.close()
        cap.release()

    decoded = len(source_indices)
    if decoded == 0:
        raise ValueError(f"영상에 프레임이 없습니다: {video_path}")

    def _build_extraction(
        rows: list[list[float]],
        panel: str,
        panel_width: int,
    ) -> dict[str, Any]:
        df = pd.DataFrame(rows, columns=cols)
        df = df.interpolate(method="linear", limit_direction="both").ffill().bfill()
        df = df.rolling(window=3, min_periods=1, center=True).mean()

        frames_out: list[dict[str, Any]] = []
        for i, src_i in enumerate(source_indices):
            row = df.iloc[i]
            time_sec = float(src_i) / fps if fps > 0 else float(i)
            fr = _frame_from_landmarks_row(row, cols, i, time_sec, src_i)
            fr["panel"] = panel
            fr["panel_width_px"] = panel_width
            fr["panel_height_px"] = height
            frames_out.append(fr)

        return {
            "metric": "creativity",
            "source": str(path),
            "media_type": "video",
            "fps": fps,
            "total_frames_decoded": decoded,
            "total_frames_reported": total_in_file,
            "split_screen": True,
            "panel": panel,
            "frames": frames_out,
        }

    left_ext = _build_extraction(left_rows, "left", split_x)
    right_ext = _build_extraction(right_rows, "right", width - split_x)

    if left_role == "user":
        user_raw, ref_raw = left_ext, right_ext
    else:
        user_raw, ref_raw = right_ext, left_ext

    meta = {
        "split_axis": split_axis,
        "split_ratio": ratio,
        "split_x_px": split_x,
        "frame_width": width,
        "frame_height": height,
        "left_role": left_role,
        "user_panel": user_raw.get("panel"),
        "reference_panel": ref_raw.get("panel"),
        "fps": fps,
        "decoded_frames": decoded,
    }
    return user_raw, ref_raw, meta
