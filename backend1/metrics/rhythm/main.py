# rhythm 단독 서버 — 레거시. 통합 API는 backend1/main.py (POST /video/analyze).
#
# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware
# from metrics.rhythm.routers.video import router as video_router
#
# app = FastAPI(title="FOM — Rhythm Scoring API", version="0.1.0")
# app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
# app.include_router(video_router)
#
# @app.get("/health")
# def health():
#     return {"status": "ok"}
