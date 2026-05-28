# Isolation metric (로컬 + API)

## 팀 MediaPipe (병합 기준)

- **Tasks API** + `mediapipe>=0.10.31` (`mediapipe_pose_tasks.py`)
- **0.10.30은 Windows/Python 3.12에서 사용 불가** (`function 'free' not found`) → **0.10.31 이상**

## Git에 올리지 않는 것

| 항목 | 위치 | 준비 방법 |
|------|------|-----------|
| YOLO 가중치 | `data/models/yolo11n.pt` | `track` / `extract` 첫 실행 시 자동 다운로드 |
| MediaPipe Heavy | `data/models/pose_landmarker_heavy.task` | `extract` 첫 실행 시 자동 다운로드 (Tasks API) |
| 기준 영상 | `data/raw/ref.mp4` | `cli download` |
| 추출·트랙 JSON | `data/artifacts/*.json` | `cli track` → `cli extract` |

저장소에는 `.gitkeep`과 `metrics/isolation/.gitignore`(단일)만 포함됩니다. 클론 후 아래 **첫 설정**을 한 번 실행하세요.

## 첫 설정 (1회)

```powershell
cd backend1
pip install -r requirements.txt
python -m metrics.isolation.cli download   # ref + user(기본 Shorts 9kLf88IksZU)
python -m metrics.isolation.cli extract   # → data/artifacts/ref.json (API 필수)
```

**solutions API로 만든 `ref.json`은 Tasks 전환 후 반드시 `extract`로 다시 생성하세요.**

기존에 `backend1/yolo11n.pt`만 있다면 `data/models/`로 옮기거나 삭제 후 재실행해도 됩니다.

## 영상 URL (기본)

| 역할 | URL |
|------|-----|
| 기준(ref) | [Shorts YzTywjy0VXU](https://www.youtube.com/shorts/YzTywjy0VXU) |
| 사용자(user) | [Shorts 9kLf88IksZU](https://www.youtube.com/shorts/9kLf88IksZU) |

**비교 구간**: 음악이 **시작된 시점**부터 ref **15초** (`REF_COMPARE_DURATION_SEC=15`). 영상 0초(무음·인트로)는 제외. CLI: `--ref-compare-sec 0` 이면 음악 시작~끝.

## 음악(박자) 정렬

기본 정렬은 **`beat`** 입니다. ref/user mp4 오디오에서 **음악 시작(`music_start_sec`)** 과 비트를 뽑고, 같은 박 인덱스끼리 포즈 프레임을 맞춥니다.

- `ref_beats.json` 을 예전에 만들었다면 `cli beats` 를 다시 실행하세요 (`music_start_sec` 필드 필요).

- **같은 곡**이어야 BPM·beat_lag가 의미 있습니다.
- **ffmpeg** 가 PATH에 있어야 mp4 오디오를 읽을 수 있습니다.
- 기준 비트 캐시: `data/artifacts/ref_beats.json` (`cli beats` 또는 첫 beat align 시 생성)

시각만 맞출 때: `--alignment-method time`

## CLI

```powershell
cd backend1

# 통합 검증 (추천): 음악 싱크 + 박자 정렬 + isolation 점수 + 채점 기준
python -m metrics.isolation.cli verify
python -m metrics.isolation.cli verify --json --out metrics/isolation/data/artifacts/verify_report.json

# user.json 없을 때: 비트·싱크만 (가벼움)
python -m metrics.isolation.cli verify --beats-only

# 포즈 추출까지 한 번에 (느림)
python -m metrics.isolation.cli verify --with-extract

python -m metrics.isolation.cli extract   # ref.json
python -m metrics.isolation.cli run --user-video metrics/isolation/data/raw/user.mp4 --json

# ref/user JSON 만 있을 때 (extract 생략)
python -m metrics.isolation.cli score --user metrics/isolation/data/artifacts/user.json --json
```

## HTTP (프론트 연동)

```powershell
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- `GET /isolation/ready` — `ref.json` 준비 여부
- `POST /isolation/analyze` — `user_video` multipart 업로드 → isolation 점수

통합 `POST /video/analyze` 의 **`scores.isolation` 과 동일** (`score_isolation_for_fom`).

서버 1회: `python -m metrics.isolation.cli extract` 후 `ref_isolation.json` 이 `video_json/` 에 있어야 통합 채점 가능 (없으면 `ref.json` 자동 복사).

## Flutter

`dance_app` Studio → 촬영 → 분석 시 `POST /isolation/analyze` 호출.

- Windows: `http://127.0.0.1:8000`
- Android 에뮬레이터: `http://10.0.2.2:8000`
- 실기기: `flutter run --dart-define=API_BASE_URL=http://<PC_IP>:8000`
