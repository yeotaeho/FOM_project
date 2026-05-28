# FOM 통합 API 레퍼런스

> 작성일: 2026-05-21  
> 구현 기준: `backend1/routers/video.py`, `backend1/services/orchestrator.py`, `backend1/services/extract_coordinator.py`  
> 규범: [ARCHITECTURE.md](./ARCHITECTURE.md) · 흐름: [ORCHESTRATOR.md](./ORCHESTRATOR.md)

---

## 1. 진입점

```bash
cd backend1
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

| 항목 | 값 |
|------|-----|
| OpenAPI | `GET /docs` |
| 헬스 | `GET /health` |
| ROM `sys.path` | `backend1/main.py` 에서 `metrics/rom` 만 설정 |

---

## 2. 통합 `/video` (권장)

### 2.1 `POST /video/extract`

레퍼런스·유저 영상을 **ROM domain1** 한 번만 추출해 `video_json/` 에 저장.

| 필드 | 타입 | 기본 | 설명 |
|------|------|------|------|
| `file` | UploadFile | — | 업로드 영상 (`video_url` 과 택1) |
| `video_url` | Form string | — | HTTP(S) 직링크 |
| `extraction_mode` | `rom` \| `full` | **`full`** | `full` = 6 metric용(full_v1), `rom` = 경량 |
| `target_fps` | float | `15` | `0` 이하이면 전체 프레임 |
| `frame_stride` | int | — | 지정 시 `target_fps` 보다 우선 |
| `include_annotated_video` | bool | — | `None` = rom이면 생략, full이면 생성 |

**응답 (요약):** `json_filename`, `extraction_id`, `fps`, `total_frames`, `schema`, (선택) `annotated_video`

---

### 2.2 `POST /video/analyze/by-name` (개발)

서버 `video_data/` MP4 + `reference_json`. 기본: `gBR_sBM_c01_d04_mBR3_ch03.mp4` + `20260521_134352_bed9b6d2.json`.  
→ [DEV_VIDEO_DATASET.md](./DEV_VIDEO_DATASET.md)

---

### 2.3 `POST /video/analyze` (영상 + 레퍼런스 JSON)

**2단계:** Phase A `extract_coordinator` → Phase B `orchestrator`.

| 필드 | 타입 | 기본 | 설명 |
|------|------|------|------|
| `user_video` | UploadFile | — | 유저 영상 (`video_url` 과 택1) |
| `video_url` | Form string | — | 유저 영상 URL |
| `reference_json` | Form string | 업로드 시 파일명 | `video_json/` 저장명 (asset과 동일 권장) |
| `reference_json_file` | multipart file | 선택 | dance_app `video_data/cardN/*.json` — 있으면 서버에 저장 후 채점 |
| `alignment_method` | `time` \| `dtw` | `time` | 프레임 정렬 |
| `user_offset_sec` / `ref_offset_sec` | float | `0` | 시작 오프셋(초) |
| `auto_detect_start` | bool | `false` | 댄스 시작 자동 감지 |
| `detail_level` | `summary` \| `full` | `summary` | accuracy 상세 |
| `scoring_mode` | `linear` \| `dance` | `dance` | accuracy 모드 |
| `extraction_mode` | `rom` \| `full` | **`full`** | 유저 ROM 추출 모드 |
| `target_fps` | float | `15` | ROM 샘플링 |
| `frame_stride` | int | — | ROM stride |
| `metrics` | Form string | — | 쉼표 구분. 비우면 **6개 전체** |
| `fail_fast` | bool | `false` | 추출·채점 공통 |
| `enable_accuracy` / `enable_rom` | bool | — | **`metrics` 지정 시 무시** (레거시) |

**ROM `full` 자동 승격:** 채점 목록에 `accuracy`, `creativity`, `isolation`, `power`, `rhythm` 중 하나라도 있으면 유저 ROM 추출을 `full` 로 실행 (`extract_coordinator._needs_full_rom_extraction`).

**Phase A — 병렬 추출 (기본 4파이프라인):**

| 파이프라인 | sidecar 파일 | canonical |
|------------|--------------|-----------|
| `rom` | `{base}.json` | **예** (채점 입력) |
| `rhythm` | `{base}_rhythm.json` | 아니오 |
| `power` | `{base}_power.json` | 아니오 |
| `creativity` | `{base}_creativity.json` | 아니오 |

ROM 추출 실패 시 **전체 422** (canonical 없음).

**응답 (요약):**

```json
{
  "user": { "extraction_id", "extraction_json", "annotated_video", "fps", "total_frames" },
  "reference": { "...": "build_reference_meta" },
  "extractions": { "rom": { "ok", "json_filename", ... }, "rhythm": {}, ... },
  "alignment": { "method", "pair_count", "user_offset_sec", "ref_offset_sec", "warning" },
  "scores": {
    "accuracy": { "score", "breakdown", "frame_diffs" },
    "...": {},
    "total_score": 73.33,
    "grade": "B"
  },
  "meta": {
    "metrics_run": ["accuracy", "..."],
    "user_json": "<canonical 파일명>",
    "reference_json": "...",
    "rom_extraction_mode": "full",
    "pipelines_run": ["rom", "rhythm", "power", "creativity"]
  }
}
```

---

### 2.4 `POST /video/analyze/json`

영상·추출 없이 **저장 JSON 2개**만 채점 (`run_analyze_from_json`).

**Body (JSON):**

| 필드 | 타입 | 기본 | 설명 |
|------|------|------|------|
| `user_json` | string | 필수 | `video_json/` 사용자 파일명 |
| `reference_json` | string | 필수 | 레퍼런스 파일명 |
| `alignment_method` | `time` \| `dtw` | `time` | |
| `user_offset_sec` / `ref_offset_sec` | float | `0` | |
| `auto_detect_start` | bool | `false` | |
| `detail_level` | `summary` \| `full` | `summary` | |
| `scoring_mode` | `linear` \| `dance` | `dance` | |
| `metrics` | string[] | `null` → **6개 전체** | 예: `["rom"]` |
| `fail_fast` | bool | `false` | |
| `enable_accuracy` / `enable_rom` | bool | — | `metrics` 지정 시 무시 |

**응답:** `user_json`, `reference_json`, `alignment`, `scores`, `meta` (multipart analyze 와 `scores`/`alignment` 형태 동일, `user`/`extractions` 없음).

---

### 2.4 `POST /video/compare`

ROM `compute_comparison` — **개발·디버그** (6-metric 오케스트레이터와 별도).  
Body: `CompareRequest` (`user_json`, `reference_json`, alignment·accuracy·rom 플래그).

---

### 2.5 정적 파일

| 메서드 | URL | 설명 |
|--------|-----|------|
| `GET` | `/video/json/{filename}` | 추출 JSON |
| `GET` | `/video/data/{filename}` | annotated MP4 |

저장 루트: `metrics/rom/domain/domain1/video_data/video_json/` (및 `video_data/` 영상).

---

## 3. metric 전용 prefix (개발·레거시)

`main.py` 등록 순서: `video` → `rhythm` → `isolation` → `power`.

| prefix | 라우터 | 용도 |
|--------|--------|------|
| `/rhythm` | `metrics/rhythm/routers/video.py` | beat·시각화 등 rhythm 전용 |
| `/isolation` | `metrics/isolation/router.py` | YOLO 등 isolation 전용 |
| `/power` | `metrics/power/routers/video.py` | power extract/score one-shot |

**creativity / accuracy:** HTTP 라우터 없음. 통합 채점은 `score_creativity` / ROM `score_accuracy`.

---

## 4. 채점 동작 (`orchestrator.py`)

| metric | 함수 | 입력 |
|--------|------|------|
| accuracy | `score_accuracy` | `aligned_pairs`, `detail_level`, `scoring_mode` |
| creativity | `score_creativity` | `aligned_pairs` |
| isolation | `score_isolation` | `aligned_pairs` |
| rom | `score_rom` | offset 이후 `user_frames`, `ref_frames` (**쌍 아님**) |
| power | `score_power` | `user_extraction` (ROM JSON 전체) |
| rhythm | `score_rhythm_vs_reference` 또는 `score_rhythm_from_extraction` | user/ref extraction |

- **정렬:** `build_aligned_pairs` → ROM `align_by_time` / `align_by_dtw`
- **병렬:** `ThreadPoolExecutor(6)` + `asyncio.create_task` / `gather`
- **`total_score`:** 오류 없는 metric `score` 의 **단순 평균** → `score_to_grade` (ROM)
- **`fail_fast=false` (기본):** 실패 metric → `scores.<name>.breakdown.error`, 나머지 계속
- **`fail_fast=true`:** 첫 예외 시 HTTP 500

---

## 5. 클라이언트 권장 시퀀스

1. 레퍼런스: `POST /video/extract` → `reference_json` 파일명 확보  
2. 유저: `POST /video/analyze` — 영상 + `reference_json` + (선택) `metrics`  
3. 재채점: `POST /video/analyze/json` — 동일·다른 `user_json` 으로 파라미터만 변경  

**ROM만 빠르게:** `metrics=rom` (Form) 또는 body `metrics: ["rom"]`.  
추출은 기본적으로 rhythm/power/creativity sidecar 까지 실행 (향후 `pipelines` 로 최적화 예정).

---

## 6. 알려진 제한

| 항목 | 설명 |
|------|------|
| 채점 입력 | 대부분 **ROM canonical JSON** (`full_v1` 권장). `rom_v1` 만이면 일부 metric `breakdown.error` |
| sidecar | rhythm/power/creativity JSON 저장·채점 입력 미연동 |
| isolation 추출 | `extract_coordinator` 파이프라인 없음. 채점은 ROM 포즈로 `score_isolation` 시도 |
| creativity 정렬 | 통합 경로는 ROM `time`/`dtw` 만. CLI `index` 정렬은 미연동 |

---

## 7. 변경 이력

| 날짜 | 내용 |
|------|------|
| 2026-05-21 | Phase 1~3 반영, 본 레퍼런스 최초 작성 |
