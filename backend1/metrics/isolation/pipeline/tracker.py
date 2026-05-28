"""
YOLO11 person tracking — 프레임마다 주인공 bbox 1개.

Ultralytics 영상 스트림 API 사용 (프레임마다 model.track 호출보다 빠름).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

import cv2
import numpy as np

from metrics.isolation.config import (
    YOLO_CONF,
    YOLO_IOU,
    YOLO_MODEL,
    YOLO_PERSON_CLASS,
)


def _ensure_tracking_deps() -> None:
    """ByteTrack용 lap — 미설치 시 ultralytics 런타임 AutoUpdate 방지."""
    try:
        import lap  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "YOLO track에 lap 패키지가 필요합니다. "
            "backend1 루트에서: pip install \"lap>=0.5.12\""
        ) from e


@dataclass(frozen=True)
class TrackFrame:
    """한 프레임의 주인공 추적 결과."""

    frame_index: int
    time_sec: float
    bbox_xyxy: Tuple[int, int, int, int]  # x1, y1, x2, y2 (픽셀, 원본 프레임)
    track_id: Optional[int]
    confidence: float
    frame_width: int
    frame_height: int

    @property
    def bbox_area(self) -> int:
        x1, y1, x2, y2 = self.bbox_xyxy
        return max(0, x2 - x1) * max(0, y2 - y1)


def _pick_primary_box(
    boxes_xyxy: np.ndarray,
    confidences: np.ndarray,
    track_ids: Optional[np.ndarray],
    frame_w: int,
    frame_h: int,
) -> Tuple[Tuple[int, int, int, int], float, Optional[int]]:
    """여러 person 중 bbox 면적 최대 = 주인공."""
    if boxes_xyxy is None or len(boxes_xyxy) == 0:
        raise ValueError("검출된 person bbox 없음")

    areas = []
    for box in boxes_xyxy:
        x1, y1, x2, y2 = box[:4]
        areas.append(max(0, x2 - x1) * max(0, y2 - y1))

    best_i = int(np.argmax(areas))
    x1, y1, x2, y2 = boxes_xyxy[best_i][:4]
    x1 = int(max(0, min(x1, frame_w - 1)))
    y1 = int(max(0, min(y1, frame_h - 1)))
    x2 = int(max(x1 + 1, min(x2, frame_w)))
    y2 = int(max(y1 + 1, min(y2, frame_h)))

    conf = float(confidences[best_i]) if confidences is not None else 0.0
    tid: Optional[int] = None
    if track_ids is not None and len(track_ids) > best_i:
        try:
            tid = int(track_ids[best_i])
        except (TypeError, ValueError):
            tid = None
    return (x1, y1, x2, y2), conf, tid


def _clip_bbox_with_padding(
    bbox: Tuple[int, int, int, int],
    frame_w: int,
    frame_h: int,
    padding_ratio: float,
) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    pad_x = int(w * padding_ratio)
    pad_y = int(h * padding_ratio)
    return (
        max(0, x1 - pad_x),
        max(0, y1 - pad_y),
        min(frame_w, x2 + pad_x),
        min(frame_h, y2 + pad_y),
    )


def _read_video_meta(path: Path) -> Tuple[float, int, int]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"영상을 열 수 없습니다: {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return fps, frame_w, frame_h


class PersonTracker:
    """영상 파일 단위 YOLO11 track."""

    def __init__(
        self,
        model_name: str = YOLO_MODEL,
        conf: float = YOLO_CONF,
        iou: float = YOLO_IOU,
        padding_ratio: float = 0.0,
        device: str | None = None,
        vid_stride: int = 1,
    ) -> None:
        _ensure_tracking_deps()
        from ultralytics import YOLO

        model_path = Path(model_name)
        if model_path.suffix:
            model_path.parent.mkdir(parents=True, exist_ok=True)

        self.model = YOLO(model_name)
        self.conf = conf
        self.iou = iou
        self.padding_ratio = padding_ratio
        self.device = device
        self.vid_stride = max(1, int(vid_stride))

    def iter_frames(self, video_path: str | Path) -> Iterator[TrackFrame]:
        """
        YOLO가 영상 전체를 stream 처리 — 프레임별 수동 track 보다 빠름.
        검출 실패 프레임은 직전 bbox 최대 5프레임 유지.
        """
        path = Path(video_path)
        if not path.is_file():
            raise FileNotFoundError(f"영상 없음: {path}")

        fps, frame_w, frame_h = _read_video_meta(path)

        track_kwargs = {
            "source": str(path),
            "persist": True,
            "stream": True,
            "classes": [YOLO_PERSON_CLASS],
            "conf": self.conf,
            "iou": self.iou,
            "verbose": False,
            "vid_stride": self.vid_stride,
        }
        if self.device:
            track_kwargs["device"] = self.device

        last_bbox: Optional[Tuple[int, int, int, int]] = None
        last_tid: Optional[int] = None
        last_conf: float = 0.0
        hold_left = 0
        max_hold = 5

        for frame_index, result in enumerate(self.model.track(**track_kwargs)):
            time_sec = frame_index * self.vid_stride / fps
            bbox_out: Optional[Tuple[int, int, int, int]] = None
            tid_out: Optional[int] = None
            conf_out = 0.0

            if result.boxes is not None and len(result.boxes) > 0:
                boxes = result.boxes.xyxy.cpu().numpy()
                confs = result.boxes.conf.cpu().numpy()
                tids = None
                if result.boxes.id is not None:
                    tids = result.boxes.id.cpu().numpy()
                try:
                    bbox_out, conf_out, tid_out = _pick_primary_box(
                        boxes, confs, tids, frame_w, frame_h
                    )
                    if self.padding_ratio > 0:
                        bbox_out = _clip_bbox_with_padding(
                            bbox_out, frame_w, frame_h, self.padding_ratio
                        )
                    last_bbox = bbox_out
                    last_tid = tid_out
                    last_conf = conf_out
                    hold_left = max_hold
                except ValueError:
                    bbox_out = None

            if bbox_out is None and last_bbox is not None and hold_left > 0:
                bbox_out = last_bbox
                tid_out = last_tid
                conf_out = last_conf
                hold_left -= 1

            if bbox_out is not None:
                yield TrackFrame(
                    frame_index=frame_index,
                    time_sec=round(time_sec, 4),
                    bbox_xyxy=bbox_out,
                    track_id=tid_out,
                    confidence=conf_out,
                    frame_width=frame_w,
                    frame_height=frame_h,
                )

    def track_all(self, video_path: str | Path) -> List[TrackFrame]:
        return list(self.iter_frames(video_path))


def track_video_file(
    video_path: str | Path,
    model_name: str = YOLO_MODEL,
    padding_ratio: float = 0.0,
    device: str | None = None,
    vid_stride: int = 1,
) -> List[TrackFrame]:
    """편의 함수: 전체 프레임 TrackFrame 리스트."""
    return PersonTracker(
        model_name=model_name,
        padding_ratio=padding_ratio,
        device=device,
        vid_stride=vid_stride,
    ).track_all(video_path)
