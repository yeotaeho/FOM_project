# ROM metric

HTTP API는 **통합 서버**에서 제공합니다.

```bash
cd backend1
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 이 폴더에서 수정하는 범위

- `domain/domain1/` — 추출·채점 로직 (ROM 담당)
- `domain/domain1/docs/` — ROM 설계 문서

## 수정하지 않는 범위

- `backend1/routers/video.py` — 통합 라우터 (오케스트레이션 담당)
- 다른 `metrics/<이름>/` 폴더
