"""POST /video/analyze — multipart form 필드 (영상은 File로 별도)."""

from typing import Literal

from pydantic import BaseModel, Field


class AnalyzeFormParams(BaseModel):
    """Swagger 문서용; 실제 엔드포인트는 Form() 파라미터."""

    reference_json: str = Field(
        ...,
        description="video_json/에 이미 저장된 전문가(레퍼런스) 추출 JSON 파일명",
    )
    alignment_method: str = Field(default="time", description="time | dtw")
    user_offset_sec: float = Field(default=0.0, ge=0.0)
    ref_offset_sec: float = Field(default=0.0, ge=0.0)
    auto_detect_start: bool = Field(default=False)
    detail_level: Literal["summary", "full"] = Field(default="summary")
    scoring_mode: Literal["linear", "dance"] = Field(default="dance")
    enable_accuracy: bool = Field(
        default=False,
        description="Accuracy 채점 (full 추출·full_v1 JSON 필요)",
    )
    enable_rom: bool = Field(default=True)
    extraction_mode: Literal["rom", "full"] = Field(
        default="rom",
        description="사용자 영상 추출 모드",
    )
    target_fps: float | None = Field(
        default=15.0,
        description="ROM 샘플링 목표 fps. 0 이하면 전체 프레임",
    )
    frame_stride: int | None = Field(
        default=None,
        description="지정 시 target_fps보다 우선",
    )
