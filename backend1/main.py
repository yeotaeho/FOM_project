"""FOM 통합 API — uvicorn main:app (ROM path는 이 파일에서만 설정)."""

import sys
from pathlib import Path

# routers/video → domain.domain1 import 전에 metrics/rom 을 sys.path에 추가
_ROM_ROOT = Path(__file__).resolve().parent / "metrics" / "rom"
_rom_root_str = str(_ROM_ROOT)
if _rom_root_str not in sys.path:
    sys.path.append(_rom_root_str)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.video import router as video_router
from metrics.creativity.router import router as creativity_router
from metrics.isolation.router import router as isolation_router
from metrics.power.routers.video import router as power_router
# rhythm 채점은 POST /video/analyze (orchestrator) — /rhythm/* 레거시 라우터 비활성
# from metrics.rhythm.routers.video import router as rhythm_router

app = FastAPI(
    title="FOM — Dance Analysis API",
    description=(
        "통합 API (backend1). "
        "POST /video/analyze — 유저 영상 업로드 + 레퍼런스 JSON 채점. "
        "POST /video/analyze/json — 저장 JSON 2개, 6 metric 병렬 채점. "
        "POST /creativity/analyze — 창의성 전체 파이프라인(음악 구간·50프레임·DTW). "
        "POST /video/extract — ROM domain1 추출. "
        "rhythm 채점 — POST /video/analyze (metrics/rhythm scorer, /rhythm/* 비활성)."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# prefix 충돌 방지: /video = 통합, /creativity /rhythm /isolation /power = metric 전용
app.include_router(video_router)
app.include_router(creativity_router)
# app.include_router(rhythm_router)
app.include_router(isolation_router)
app.include_router(power_router)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "entry": "backend1/main.py",
        "rom_domain": "metrics/rom/domain/domain1",
        "routes": {
            "video": "/video/*",
            "creativity": "/creativity/*",
            "rhythm": "POST /video/analyze (orchestrator)",
            "isolation": "/isolation/*",
            "power": "/power/*",
        },
    }
