"""Rhythm metric — 오케스트레이터 진입점."""

from .services.extraction_service import extract_rhythm_data
from .services.scoring.rhythm_scorer import score_rhythm_from_extraction


def score_rhythm(user_video_path: str) -> dict:
    """
    user_video_path: 사용자 영상 파일 경로
    returns: {"score": float, "breakdown": dict, "frame_diffs": list}
    """
    extraction = extract_rhythm_data(user_video_path)
    return score_rhythm_from_extraction(extraction)
