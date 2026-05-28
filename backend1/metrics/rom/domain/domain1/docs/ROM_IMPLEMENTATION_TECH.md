# ROM Metric — 구현 기술 정리

> **목적:** FOM 6차원 중 **ROM(Range of Motion)** 만 구현·운영하는 데 사용한 기술·라이브러리·채점 로직을 한 문서로 정리  
> **범위:** `metrics/rom/domain/domain1` + 통합 진입점 `backend1`  
> **작성일:** 2026-05-21  
> **관련 문서:** [ROM_SCORING.md](./ROM_SCORING.md), [ROM_EXTRACTION_PERFORMANCE.md](./ROM_EXTRACTION_PERFORMANCE.md), [CURRENT_LOGIC.md](./CURRENT_LOGIC.md), [metrics/docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md)

---

## 1. ROM이 하는 일 (한 줄)

전문가(레퍼런스) 영상에서 관절이 쓴 **가동 범위(ROM)** 를 기준으로, 사용자 영상이 그 범위를 **얼마나 커버했는지(%)** 를 관절별·전체 평균으로 점수화한다.

- **평가 방식:** 절대 각도 기준이 아니라 **레퍼런스 대비 상대 커버리지** (같은 안무에서 “동작 크기” 비교)
- **입력:** 동영상 → 포즈 추정 → 프레임별 `joint_angles` → 시퀀스 min/max → ROM 비교

---

## 2. 아키텍처·폴더

### 2.1 Hub–Spoke (domain1)

| 구역 | 경로 | 역할 |
|------|------|------|
| **Hub** | `hub/services/` | 추출·저장·비교·채점 오케스트레이션 |
| **Scoring** | `hub/services/scoring/` | ROM·Accuracy·프레임 정렬 |
| **Models** | `models/transfer/` | API 요청 스키마 (Pydantic) |
| **데이터** | `video_data/`, `video_data/video_json/` | annotated MP4, 추출 JSON |
| **문서** | `docs/` | 설계·현황·성능 |

ROM metric 담당 코드는 **`domain/domain1`만** 수정하는 것을 전제로 한다 (`metrics/docs/ARCHITECTURE.md`).

### 2.2 통합 API (backend1)

| 항목 | 위치 |
|------|------|
| HTTP 진입 | `backend1/main.py`, `backend1/routers/video.py` |
| ROM import | `backend1/main.py` 시작부 → `metrics/rom`을 `sys.path`에 append → `from domain.domain1...` |
| 의존성 | `backend1/requirements.txt` |

`metrics/rom/main.py`, `metrics/rom/routers/video.py` 는 **사용하지 않음** (통합 서버만 기동).

---

## 3. 기술 스택·라이브러리

### 3.1 런타임·API

| 기술 | 버전(요구) | 용도 |
|------|------------|------|
| **Python** | 3.10+ 권장 | 서비스 전반 |
| **FastAPI** | ≥0.110 | REST API, multipart 업로드, JSON body |
| **Uvicorn** | ≥0.27 | ASGI 서버 |
| **httpx** | ≥0.27 | `video_url` HTTP(S) 스트리밍 다운로드 |
| **Pydantic** | ≥2.6 | 요청/응답 검증 (`CompareRequest`, `AnalyzeJsonRequest` 등) |

### 3.2 영상·포즈·수치

| 라이브러리 | 버전(요구) | ROM에서의 역할 |
|------------|------------|----------------|
| **MediaPipe Tasks** | `mediapipe>=0.10.31,<0.11` | Pose Landmarker로 33 body landmarks 추정 (`mp.tasks.vision.PoseLandmarker`) |
| **OpenCV** | `opencv-python>=4.9` | `VideoCapture` 프레임 읽기, (선택) annotated MP4 작성 |
| **NumPy** | ≥1.26 | 벡터·각도·정규화 연산 |
| **pandas** | ≥2.2 | 랜드마크 시계열 보간·rolling 스무딩 |
| **SciPy** | ≥1.12 | DTW 거리 (`euclidean`) — Accuracy 정렬 시 |
| **fastdtw** | ≥0.3.4 | `joint_angles` 시퀀스 DTW 정렬 — Accuracy 정렬 시 |

> **MediaPipe 버전:** 0.10.31+부터 Legacy Solutions API(`mp.solutions.pose`)가 제거되어 **Tasks API(`mp.tasks.vision.PoseLandmarker`)** 를 사용합니다. 모델 파일(`pose_landmarker_full.task`)은 별도 다운로드 필요.

### 3.3 ROM 기본 경로에서 쓰지 않는 것

| 항목 | 상태 |
|------|------|
| **YOLO / Ultralytics** | `requirements.txt` 주석만 존재, ROM 파이프라인 미연동 |
| **딥러닝 ROM 전용 모델** | 없음 — 규칙 기반(min/max, 비율) |
| **DB** | 파일 시스템 JSON·MP4만 사용 |

---

## 4. 추출(Extraction) 기술

### 4.1 파이프라인 개요

```
동영상 (mp4/mov/avi/mkv/webm)
  → OpenCV 프레임 읽기 (+ 샘플링 stride)
  → MediaPipe Tasks Pose Landmarker (VIDEO 모드)
  → pandas: NaN 보간 + rolling mean
  → Mid-Hip 원점 + Torso Length 스케일 정규화
  → joint_angles 10관절 (도)
  → JSON 저장 (rom_v1 | full_v1)
```

구현: `hub/services/extraction_service.py`, `extraction_pipeline.py`

### 4.2 MediaPipe Tasks 설정

```python
BaseOptions = mp.tasks.BaseOptions
PoseLandmarker = mp.tasks.vision.PoseLandmarker
PoseLandmarkerOptions = mp.tasks.vision.PoseLandmarkerOptions
VisionRunningMode = mp.tasks.vision.RunningMode

options = PoseLandmarkerOptions(
    base_options=BaseOptions(model_asset_path="models/pose_landmarker_full.task"),
    running_mode=VisionRunningMode.VIDEO,
    num_poses=1,
    min_pose_detection_confidence=0.5,
    min_pose_presence_confidence=0.5,
    min_tracking_confidence=0.5,
)

with PoseLandmarker.create_from_options(options) as landmarker:
    # VIDEO 모드: timestamp_ms 필요
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = landmarker.detect_for_video(mp_image, timestamp_ms)
```

- **모델:** `pose_landmarker_full.task` (float16, ~9.4MB) — `models/` 디렉토리에 배치
- **VIDEO 모드:** tracking 지원으로 프레임 간 일관성 향상
- 검출 실패 프레임은 NaN → **선형 보간 + ffill/bfill**

### 4.3 좌표 정규화 (시점·체형 보정)

ROM 각도는 **정규화 랜드마크**에서 계산한다 (`pose_geometry.py`).

1. **Translation:** Mid-Hip = (left_hip + right_hip) / 2 → 원점
2. **Scaling:** Torso Length = ‖Mid-Shoulder − Mid-Hip‖ 로 나눔 (0 방지 epsilon)

→ 키·화면 위치에 덜 민감한 **각도(feature)** 를 얻기 위함 ([VIEWPOINT_INVARIANCE.md](./VIEWPOINT_INVARIANCE.md)).

### 4.4 관절 각도 (10개)

∠ABC (꼭짓점 B)를 **도(degree)** 로 계산. `numpy` 내적 + `acos` + `math.degrees`.

| 키 | 의미 (대략) |
|----|-------------|
| `left_elbow`, `right_elbow` | 어깨–팔꿈치–손목 |
| `left_knee`, `right_knee` | 골반–무릎–발목 |
| `left_shoulder`, `right_shoulder` | 팔꿈치–어깨–골반 |
| `left_hip`, `right_hip` | 어깨–골반–무릎 |
| `left_ankle`, `right_ankle` | 무릎–발목–발끝 |

가상 관절: `mid_hip`, `mid_shoulder` (양쪽 평균).

### 4.5 추출 스키마

| schema | 모드 | 프레임에 저장 | 기본 용도 |
|--------|------|---------------|-----------|
| **`rom_v1`** | `extraction_mode=rom` | `joint_angles`, `time_sec`, `source_frame_index`, `frame_index` | ROM 전용·경량 |
| **`full_v1`** | `extraction_mode=full` | 위 + `landmarks`, `normalized_landmarks`, `bone_vectors` | Accuracy 등 확장 |

ROM 경량 시 MediaPipe는 33점 추론하지만, JSON에는 **14개 랜드마크 subset**만 정규화·각도 계산에 사용 (`LANDMARKS_FOR_ROM`).

### 4.6 성능 최적화 (ROM 기본)

| 기법 | 기본값 | 효과 |
|------|--------|------|
| **프레임 샘플링** | `target_fps=15` | `stride ≈ round(source_fps/15)` 마다만 `pose.process` |
| **annotated MP4 생략** | `rom` 모드 | 시각화·인코딩 시간 제거 |
| **JSON 축소** | `rom_v1` | 저장·로드·네트워크 감소 |

자세한 수치·API: [ROM_EXTRACTION_PERFORMANCE.md](./ROM_EXTRACTION_PERFORMANCE.md).

---

## 5. 채점(Scoring) 기술 — ROM

구현: `hub/services/scoring/rom_scorer.py`

### 5.1 관절 ROM 정의

활성 구간(오프셋 이후) 프레임에서:

```
ROM[joint] = max(angles[joint]) − min(angles[joint])   # 단위: 도
```

### 5.2 레퍼런스 대비 커버리지

```
coverage[joint] = min(ROM_user / ROM_ref, 1.0) × 100   (%)
```

- **`ROM_ref < 10°` (STATIC_ROM_THRESHOLD_DEG):** 해당 관절은 안무상 거의 정적 → **coverage=100%**, `note: static_joint` (평균에서 제외하지 않고 100 처리 후 active_joint_count에는 미포함 방식 — 구현은 static은 coverages 리스트에 안 넣음)
- **`ROM_ref ≤ 0`:** user도 0이면 100%, 아니면 0%

### 5.3 최종 ROM 점수·등급

```
ROM_score = mean(coverage[joint])   # 활성 관절만
```

등급 (`score_to_grade_rom`): A+ ≥90, A ≥80, B ≥70, C ≥60, else D

### 5.4 ROM이 **프레임 정렬을 쓰지 않는** 이유

- Accuracy는 프레임 쌍 맞춤(`align_by_time` / `align_by_dtw`) 후 각도·뼈 벡터 비교
- ROM은 **시퀀스 전체 min/max** 이므로, `enable_rom`만 켜면 **활성 구간 전체 프레임**으로 ROM 계산 (`comparison_service.py`)
- `enable_accuracy=false` 기본이면 DTW/fastdtw는 ROM 경로에서 **호출되지 않음**

### 5.5 오프셋·시작 시점

| 옵션 | ROM 동작 |
|------|----------|
| `user_offset_sec` / `ref_offset_sec` | `time_sec >= offset` 인 프레임만 ROM에 사용 |
| `auto_detect_start=true` | `rom_v1`: `joint_angles` 변화량 > 3° 첫 시점 (`detect_dance_start_from_joint_angles`) |

---

## 6. 비교·오케스트레이션

| 모듈 | 파일 | 역할 |
|------|------|------|
| **저장·로드** | `storage_paths.py` | `video_json/` JSON, `is_rom_schema`, `load_rom_fields` |
| **비교** | `comparison_service.py` | JSON 2개 로드, 오프셋, `enable_rom` / `enable_accuracy` 분기 |
| **원스텝 분석** | `analyze_service.py` | 유저 영상 추출 → `compute_comparison` |
| **HTTP** | `backend1/routers/video.py` | `/video/analyze`, `/extract`, `/compare` 등 |

### 6.0 영상 입력 (`video_input.py`)

| 방식 | Form 필드 | 처리 |
|------|-----------|------|
| 업로드 | `file` / `user_video` | `save_upload_to_temp` |
| URL | `video_url` | `httpx` 스트리밍 다운로드 → 임시 파일 |

- **택1:** `file`과 `video_url` 동시 지정 불가
- **URL 제한:** `http`/`https`만, localhost·사설 IP·`.local` 차단 (리다이렉트 hop마다 재검증)
- **용량:** 업로드와 동일 최대 500MB
- **미지원:** YouTube 페이지 URL 등 (직링크 mp4/mov 등만)

### 6.1 API 요약 (ROM 관점)

| 메서드 | URL | ROM 관련 동작 |
|--------|-----|----------------|
| `POST` | `/video/analyze` | **유저 영상** file 또는 `video_url` + `reference_json` → `run_analyze` |
| `POST` | `/video/analyze/json` | 저장 `user_json` + `reference_json` 채점 |
| `POST` | `/video/extract` | file 또는 `video_url` → `rom_v1` / `full_v1` 저장 |
| `POST` | `/video/compare` | JSON 2개 비교 (개발·디버그) |
| `GET` | `/video/json/{filename}` | 추출 JSON 조회 |

기본 플래그: `enable_accuracy=false`, `enable_rom=true`, `extraction_mode=rom`, `target_fps=15`.

### 6.2 권장 운영 흐름

1. **레퍼런스:** 한 번 `POST /video/extract` → `reference.json` 보관  
2. **유저:** `POST /video/analyze` — 영상 + `reference_json` 파일명  
3. 레퍼런스·유저 추출은 **동일 `extraction_mode`·`target_fps`** 권장

---

## 7. Accuracy와의 관계 (같은 domain1, ROM과 분리)

같은 추출 파이프라인·`comparison_service`를 공유하지만 **ROM MVP 기본값에서는 꺼져 있음**.

| 항목 | Accuracy (`enable_accuracy=true`) | ROM (기본) |
|------|-----------------------------------|------------|
| 추출 | `full_v1` 권장 | `rom_v1` |
| 특징 | `joint_angles` 60% + `bone_vectors` 코사인 40% | ROM 커버리지만 |
| 정렬 | `time` 또는 **fastdtw** + SciPy euclidean | 불필요 |
| 구현 | `accuracy_scorer.py`, `alignment.py` | `rom_scorer.py` |

6차원 통합 시 가중치 예시(문서): Accuracy 0.30, ROM 0.15 — ROM만이면 `total_score = rom.score`.

---

## 8. 시각화 (선택)

| 항목 | 기술 |
|------|------|
| 파일 | `video_visualizer.py` |
| 출력 | 원본 + 사이드 패널(랜드마크·각도·bone_vectors 텍스트) → **mp4v** 코덱 MP4 |
| ROM 기본 | `rom_v1`은 annotated 생성 **안 함** (요청 시 `full` + `include_annotated_video=true`) |

---

## 9. 구현 상태·한계

### 9.1 구현됨 (ROM MVP)

- [x] MediaPipe 기반 추출 + 정규화 + 10관절 각도  
- [x] `rom_v1` 경량 추출 + 15fps 샘플링  
- [x] 레퍼런스 대비 ROM 커버리지 점수·관절별 breakdown  
- [x] 통합 API: 유저 영상 업로드 analyze  
- [x] 파일 기반 JSON 저장·재채점 (`/analyze/json`, `/compare`)

### 9.2 한계·주의

| 한계 | 설명 |
|------|------|
| **샘플링** | 15fps 이하면 짧은 피크 동작 ROM이 **과소 추정**될 수 있음 |
| **2D 포즈** | 카메라 시점·가림에 민감 (정규화·각도로 완화만) |
| **정적 관절** | ref ROM < 10° 관절은 채점에서 “움직임 없음” 처리 |
| **시간 동기** | ROM은 프레임별 정렬 없음 — 길이·오프셋만 맞으면 됨, 템포 차이는 min/max에 흡수 |
| **단일 레퍼런스** | 안무별 전문가 JSON 1개 전제 |

### 9.3 향후 확장 (미구현)

- 관절별 가중치(하체·상체)  
- 절대 ROM 하한 경고  
- YOLO 보조 검출  
- GPU·배치 추론  
- DB·캐시 레이어  

---

## 10. 소스 파일 인덱스

| 기능 | 파일 |
|------|------|
| ROM 추출 | `hub/services/extraction_service.py` |
| 영상 입력(업로드·URL) | `hub/services/video_input.py` |
| 저장·파이프라인 | `hub/services/extraction_pipeline.py`, `storage_paths.py` |
| 각도·정규화 | `hub/services/pose_geometry.py` |
| ROM 채점 | `hub/services/scoring/rom_scorer.py` |
| 비교·플래그 | `hub/services/comparison_service.py` |
| 정렬·시작 감지 | `hub/services/scoring/alignment.py` |
| 유저 영상 analyze | `hub/services/analyze_service.py` |
| HTTP | `backend1/routers/video.py` |
| path 설정 | `backend1/main.py` (통합 진입점만) |

---

## 11. 실행

```bash
cd backend1
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Swagger: `http://localhost:8000/docs` → `POST /video/analyze` (multipart).

---

**요약:** ROM metric은 **MediaPipe Tasks Pose Landmarker + OpenCV + NumPy/pandas** 로 포즈를 뽑고, **정규화 관절 각도 시퀀스의 min/max** 로 가동 범위를 정의한 뒤, **레퍼런스 대비 커버리지 평균**으로 점수를 낸다. **FastAPI**로 노출하며, 기본 운영은 **`rom_v1`·15fps·ROM-only 채점** 이다. MediaPipe 0.10.31+ Tasks API를 사용하며 `pose_landmarker_full.task` 모델 파일이 필요하다.
