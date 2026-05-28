from pydantic import BaseModel
from typing import Dict, List
from ..bases.landmark import Landmark, NormalizedLandmark
from ..bases.pose_features import BoneVector


class FrameData(BaseModel):
    frame_index: int
    time_sec: float
    landmarks: Dict[str, Landmark]
    normalized_landmarks: Dict[str, NormalizedLandmark]
    bone_vectors: Dict[str, BoneVector]
    joint_angles: Dict[str, float]


class VideoExtractionResult(BaseModel):
    fps: float
    total_frames: int
    frames: List[FrameData]
