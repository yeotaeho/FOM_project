"""추출·정렬 JSON 로드/저장."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def load_extraction_json(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"추출 JSON 없음: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    validate_extraction(data, p.name)
    return data


def validate_extraction(data: Dict[str, Any], label: str = "json") -> None:
    if "frames" not in data or not isinstance(data["frames"], list):
        raise ValueError(f"{label}: frames 필드가 없습니다.")
    if not data["frames"]:
        raise ValueError(f"{label}: frames 가 비어 있습니다.")
    sample = data["frames"][0]
    if "bone_vectors" not in sample:
        raise ValueError(f"{label}: bone_vectors 가 없습니다 (extract 먼저 실행).")


def save_json(data: Dict[str, Any], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def get_frames(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(data["frames"])
