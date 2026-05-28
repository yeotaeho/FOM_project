import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from metrics.power import score_power
from metrics.power.extraction import extract_power_data

router = APIRouter(prefix="/power", tags=["power"])

_JSON_DIR = Path(__file__).resolve().parent.parent / "video_data" / "video_json"
_ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
_MAX_FILE_SIZE_MB = 500


def _ensure_dirs() -> None:
    _JSON_DIR.mkdir(parents=True, exist_ok=True)


def _make_basename() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{uuid.uuid4().hex[:8]}"


def _validate_filename(filename: str) -> None:
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        raise ValueError("잘못된 파일명입니다.")


def _save_json(data: dict, filename: str) -> None:
    _ensure_dirs()
    _validate_filename(filename)
    with (_JSON_DIR / filename).open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _load_json(filename: str) -> dict:
    _validate_filename(filename)
    path = _JSON_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"추출 JSON을 찾을 수 없습니다: {filename}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


class ScoreRequest(BaseModel):
    extraction_json: str


@router.post(
    "/extract",
    summary="영상에서 파워 데이터 추출 + JSON 저장",
    description="동영상 업로드 → 파워 측정용 랜드마크 데이터 추출 후 JSON 저장.",
)
async def extract_video(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[-1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"지원하지 않는 형식입니다. 허용: {_ALLOWED_EXTENSIONS}",
        )

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = tmp.name
        content = await file.read()
        if len(content) > _MAX_FILE_SIZE_MB * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail=f"파일 크기가 {_MAX_FILE_SIZE_MB}MB를 초과합니다.",
            )
        tmp.write(content)

    try:
        result = extract_power_data(tmp_path)
        json_name = f"{_make_basename()}_power.json"
        _save_json(result, json_name)
        return JSONResponse(content={
            "extraction_json": json_name,
            "fps": result["fps"],
            "total_frames": result["total_frames"],
        })
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"처리 중 오류: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@router.post(
    "/score",
    summary="추출 JSON으로 파워 점수 계산",
    description="/power/extract에서 반환된 extraction_json 파일명을 전달하면 파워 점수를 반환합니다.",
)
async def score_video(body: ScoreRequest):
    try:
        data = _load_json(body.extraction_json)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        result = score_power(data)
        score_json_name = body.extraction_json.replace(".json", "_score.json")
        _save_json(result, score_json_name)
        result["score_json"] = score_json_name
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"채점 중 오류: {e}")

    return JSONResponse(content=result)
