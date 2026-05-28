from typing import Literal

from pydantic import BaseModel, Field


class CompareRequest(BaseModel):
    user_json: str = Field(..., description="video_json/ 아래 사용자 추출 JSON 파일명")
    reference_json: str = Field(..., description="video_json/ 아래 전문가 추출 JSON 파일명")
    alignment_method: str = Field(
        default="time",
        description="프레임 정렬: time | dtw",
    )
    user_offset_sec: float = Field(
        default=0.0,
        ge=0.0,
        description="사용자 영상에서 춤이 시작되는 시각(초). auto_detect_start=True면 무시될 수 있음",
    )
    ref_offset_sec: float = Field(
        default=0.0,
        ge=0.0,
        description="레퍼런스 영상에서 춤이 시작되는 시각(초)",
    )
    auto_detect_start: bool = Field(
        default=False,
        description="True면 normalized_landmarks 움직임으로 시작 시점 자동 추정",
    )
    detail_level: Literal["summary", "full"] = Field(
        default="summary",
        description="summary=집계+worst_frames, full=전 프레임 frame_diffs",
    )
    scoring_mode: Literal["linear", "dance"] = Field(
        default="dance",
        description="linear=기존 선형 각도 감점, dance=구간별 비선형(권장)",
    )
    enable_accuracy: bool = Field(
        default=False,
        description="Accuracy 채점 포함 (full_v1 JSON·bone_vectors 필요)",
    )
    enable_rom: bool = Field(
        default=True,
        description="ROM(관절 가동 범위) 채점 포함 여부",
    )
