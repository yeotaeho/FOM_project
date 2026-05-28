# backend1 — FOM 통합 API

[metrics/docs/ARCHITECTURE.md](metrics/docs/ARCHITECTURE.md) 기준 **유일한 HTTP 진입점** (`uvicorn main:app`).

| 문서 | 내용 |
|------|------|
| [ORCHESTRATOR.md](metrics/docs/ORCHESTRATOR.md) | 추출 조율 + 채점 오케스트레이터 |
| [API_REFERENCE.md](metrics/docs/API_REFERENCE.md) | `/video/*` 요청·응답 필드 |
| [DEV_VIDEO_DATASET.md](metrics/docs/DEV_VIDEO_DATASET.md) | 개발용 user MP4 + expert JSON |
| [INTEGRATION_STRATEGY.md](metrics/docs/INTEGRATION_STRATEGY.md) | 통합 Phase 완료·백로그 |

## 실행

```bash
cd backend1
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 엔드포인트 (요약)

| 메서드 | URL | 설명 |
|--------|-----|------|
| `POST` | `/video/extract` | 영상 **파일** 또는 **video_url** → ROM 추출 JSON 저장 |
| `POST` | `/video/analyze` | 유저 영상 → **추출 병렬**(rom/rhythm/power/creativity) → **6 metric 채점** |
| `POST` | `/video/analyze/json` | 저장 JSON 2개 → 채점만 (`metrics` 로 subset 가능) |
| `POST` | `/video/compare` | ROM JSON 2개 비교 (개발·디버그) |
| `GET` | `/video/json/{filename}` | 추출 JSON |
| `GET` | `/video/data/{filename}` | annotated MP4 |
| `POST` | `/rhythm/*` | rhythm 전용 |
| `POST` | `/isolation/*` | isolation 전용 |
| `POST` | `/power/*` | power 전용 |
| `GET` | `/health` | 헬스·route 메타 |

상세 Form 필드: [API_REFERENCE.md](metrics/docs/API_REFERENCE.md).

## 구현 위치

- HTTP: `routers/video.py`
- 추출 병렬: `services/extract_coordinator.py`
- 채점 병렬: `services/orchestrator.py`
- ROM: `metrics/rom/domain/domain1/` (`main.py` → `metrics/rom` on `sys.path`)

`metrics/rom/main.py`, `metrics/rom/routers/` 는 사용하지 않습니다.

## 클라이언트 흐름 (권장)

1. 레퍼런스: `POST /video/extract` → `reference_json` 파일명
2. 유저: `POST /video/analyze` — `user_video` 또는 `video_url` + `reference_json` + (선택) `metrics`
3. 재채점: `POST /video/analyze/json` — 동일 user JSON, 파라미터만 변경

**ROM만:** `metrics=rom` (Form 쉼표 구분) 또는 JSON `"metrics": ["rom"]`.
