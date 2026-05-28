# feature_isolation — develop 병합 체크리스트

## 팀 MediaPipe 합의

- **버전:** `mediapipe==0.10.30` (`backend1/requirements.txt`)
- **API:** Tasks `PoseLandmarker` only (`backend1/mediapipe_pose_tasks.py`)
- **0.10.30:** Windows wheel에 `solutions` 없음 → legacy `<0.10.31` pin 브랜치(power 등)와 **병합 시 requirements 통일 필수**

## 리뷰 항목 대응

| 항목 | 조치 |
|------|------|
| 대용량 artifact Git 커밋 | `metrics/isolation/.gitignore` + `git rm --cached` (yolo/pt, ref.json 등) |
| `main.py` 라우터 충돌 | 병합 시 **모든 metric 라우터를 나열** (아래 예시). isolation만 단독 유지하지 않음 |
| `__init__.py` 비어 있음 | `score_isolation` export 완료 |
| `service.py` temp 누수 | `keep_user_json` 시 artifact로 복사 후 **항상** `rmtree` |
| 기준 YouTube URL | `config.REF_VIDEO_URL` — 팀 고정 ref, 삭제 시 `cli download` 재실행 |
| Tasks + creativity 충돌 | 동일 `mediapipe==0.10.30` + 공용 `mediapipe_pose_tasks.py` 패턴 권장 |

## `main.py` 병합 예시 (통합 담당·머지 시)

```python
from routers.video import router as video_router
from metrics.isolation.router import router as isolation_router
# from metrics.power.router import router as power_router  # feature_power

app.include_router(video_router)
app.include_router(isolation_router)
# app.include_router(power_router)
```

## 병합 후 1회 (isolation 담당)

```powershell
cd backend1
pip install -r requirements.txt
python -m metrics.isolation.cli extract
```

## 하지 말 것

- `metrics/rom/requirements.txt` 수정 (power 브랜치 리뷰와 동일 — 타 metric 소유)
- `dance_app` home_repository 등 **isolation 범위 밖** 파일 변경
