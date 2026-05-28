"""video_data / video_json 경로·파일명 검증·추출 JSON 저장·로드."""

import json
from pathlib import Path
from typing import Any, Dict

# domain1/video_data, domain1/video_data/video_json
VIDEO_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "video_data"
VIDEO_JSON_DIR = VIDEO_DATA_DIR / "video_json"


def ensure_storage_dirs() -> None:
    VIDEO_DATA_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_JSON_DIR.mkdir(parents=True, exist_ok=True)


def validate_filename(filename: str) -> None:
    """경로 탈출 방지 — 파일명만 허용."""
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        raise ValueError("잘못된 파일명입니다.")


def make_extraction_basename() -> str:
    """MP4·JSON 공통 접두사 (타임스탬프_uuid)."""
    from datetime import datetime, timezone
    import uuid

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{uuid.uuid4().hex[:8]}"


def json_path(filename: str) -> Path:
    validate_filename(filename)
    if not filename.endswith(".json"):
        raise ValueError("JSON 파일명은 .json 확장자여야 합니다.")
    return VIDEO_JSON_DIR / filename


def video_path(filename: str) -> Path:
    validate_filename(filename)
    return VIDEO_DATA_DIR / filename


def save_reference_json_bytes(raw: bytes, filename: str) -> str:
    """
    앱 asset 등에서 업로드한 레퍼런스 JSON을 video_json/에 저장.
    반환: 저장된 파일명 (채점 시 reference_json 으로 사용).
    """
    if not raw:
        raise ValueError("reference_json_file이 비어 있습니다.")
    validate_filename(filename)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"reference_json_file UTF-8 디코딩 오류: {e}") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"reference_json_file JSON 파싱 오류: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("reference_json_file은 JSON 객체여야 합니다.")
    if "frames" not in data and data.get("schema") not in (
        EXTRACTION_SCHEMA_ROM,
        "full_v1",
        "rom_v1",
    ):
        raise ValueError(
            "reference_json_file: 'frames' 또는 지원 schema(rom_v1/full_v1)가 필요합니다."
        )
    save_extraction_json(data, filename)
    return filename


def save_extraction_json(data: Dict[str, Any], filename: str) -> Path:
    """추출 결과를 video_json에 저장 (응답 전용 필드 제외)."""
    ensure_storage_dirs()
    path = json_path(filename)
    payload = {
        k: v
        for k, v in data.items()
        if k not in ("annotated_video", "extraction_json", "extraction_id")
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return path


def load_extraction_json(filename: str) -> Dict[str, Any]:
    """video_json에서 추출 JSON 로드."""
    path = json_path(filename)
    if not path.is_file():
        raise FileNotFoundError(f"추출 JSON을 찾을 수 없습니다: {filename}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


EXTRACTION_SCHEMA_ROM = "rom_v1"


def is_rom_schema(data: Dict[str, Any]) -> bool:
    return data.get("schema") == EXTRACTION_SCHEMA_ROM


def load_rom_fields(filename: str) -> Dict[str, Any]:
    """ROM 채점·정렬용 최소 필드."""
    data = load_extraction_json(filename)
    light_frames = [
        {
            "frame_index": f["frame_index"],
            "time_sec": f["time_sec"],
            "joint_angles": f.get("joint_angles"),
        }
        for f in data.get("frames", [])
    ]
    return {
        "schema": data.get("schema"),
        "fps": data.get("fps"),
        "total_frames": data.get("total_frames"),
        "sample_stride": data.get("sample_stride"),
        "frames": light_frames,
    }


def load_comparison_fields(filename: str) -> Dict[str, Any]:
    """비교·정렬에 필요한 필드만 로드 (메모리 절약)."""
    data = load_extraction_json(filename)
    if is_rom_schema(data):
        return load_rom_fields(filename)
    light_frames = [
        {
            "frame_index": f["frame_index"],
            "time_sec": f["time_sec"],
            "joint_angles": f.get("joint_angles"),
            "bone_vectors": f.get("bone_vectors"),
            "normalized_landmarks": f.get("normalized_landmarks"),
        }
        for f in data.get("frames", [])
    ]
    return {
        "schema": data.get("schema"),
        "fps": data.get("fps"),
        "total_frames": data.get("total_frames"),
        "frames": light_frames,
    }


def build_json_meta(filename: str) -> dict:
    return {
        "filename": filename,
        "relative_path": f"domain/domain1/video_data/video_json/{filename}",
        "url": f"/video/json/{filename}",
    }


def build_annotated_video_meta(filename: str) -> dict:
    return {
        "filename": filename,
        "relative_path": f"domain/domain1/video_data/{filename}",
        "url": f"/video/data/{filename}",
    }
