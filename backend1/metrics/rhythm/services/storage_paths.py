"""video_data / video_json 경로·파일명 검증·추출 JSON 저장·로드."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

# services/ 기준 두 단계 위 = metrics/rhythm/
VIDEO_DATA_DIR = Path(__file__).resolve().parent.parent / "video_data"
VIDEO_JSON_DIR = VIDEO_DATA_DIR / "video_json"


def ensure_storage_dirs() -> None:
    VIDEO_DATA_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_JSON_DIR.mkdir(parents=True, exist_ok=True)


def validate_filename(filename: str) -> None:
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        raise ValueError("잘못된 파일명입니다.")


def make_extraction_basename() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{uuid.uuid4().hex[:8]}"


def json_path(filename: str) -> Path:
    validate_filename(filename)
    if not filename.endswith(".json"):
        raise ValueError("JSON 파일명은 .json 확장자여야 합니다.")
    return VIDEO_JSON_DIR / filename


def save_extraction_json(data: Dict[str, Any], filename: str) -> Path:
    ensure_storage_dirs()
    path = json_path(filename)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


def load_extraction_json(filename: str) -> Dict[str, Any]:
    path = json_path(filename)
    if not path.is_file():
        raise FileNotFoundError(f"추출 JSON을 찾을 수 없습니다: {filename}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_json_meta(filename: str) -> dict:
    return {
        "filename": filename,
        "relative_path": f"video_data/video_json/{filename}",
        "url": f"/video/json/{filename}",
    }


def build_annotated_video_meta(filename: str) -> dict:
    return {
        "filename": filename,
        "relative_path": f"video_data/{filename}",
        "url": f"/video/video-data/{filename}",
    }
