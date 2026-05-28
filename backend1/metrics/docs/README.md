# Metrics 문서

6개 채점 서비스를 **담당 폴더 단위로 분리**하고, **`backend1`** 통합 API에서 추출·채점을 조율한다.

## 문서 목록

| 문서 | 대상 독자 | 내용 |
|------|-----------|------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | metric 담당자·통합 담당 | 6 metric 규범, 추출/채점 경계, API 개요 |
| [INTEGRATION_STRATEGY.md](./INTEGRATION_STRATEGY.md) | 통합·인프라 | Phase 1~3 **완료 현황**, 라우터 맵, 백로그 |
| [ORCHESTRATOR.md](./ORCHESTRATOR.md) | 통합·백엔드 | `extract_coordinator` + `orchestrator` 설계·흐름 |
| [API_REFERENCE.md](./API_REFERENCE.md) | 클라이언트·QA | `/video/*` Form/Body·응답 필드 |
| [DEV_VIDEO_DATASET.md](./DEV_VIDEO_DATASET.md) | 개발·E2E | 고정 user MP4 + expert JSON 매핑 |

## 빠른 링크 (코드)

| 역할 | 경로 |
|------|------|
| HTTP | `backend1/routers/video.py` |
| 추출 병렬 | `backend1/services/extract_coordinator.py` |
| 채점 병렬 | `backend1/services/orchestrator.py` |
| 진입 | `backend1/main.py` |
| ROM 도메인 | `metrics/rom/domain/domain1/` |

## 실행

```bash
cd backend1
uvicorn main:app --host 0.0.0.0 --port 8000
```

`GET /docs` · `GET /health`
