# 6-Metric 통합 전략 및 구현 현황

> 작성일: 2026-05-21 (최종 갱신)  
> 기준 문서: [ARCHITECTURE.md](./ARCHITECTURE.md)  
> API 상세: [API_REFERENCE.md](./API_REFERENCE.md)  
> 구현: `backend1/main.py`, `backend1/routers/video.py`, `backend1/services/orchestrator.py`, `backend1/services/extract_coordinator.py`

---

## 1. 구현 완료 현황 (2026-05-21)

### 1.1 Phase 요약

| Phase | 내용 | 상태 |
|-------|------|------|
| **1** | rhythm `prefix=/rhythm`, `main.py` 에 isolation·power·rhythm 등록, `/video` 통합 우선 | ✅ 완료 |
| **2** | `services/orchestrator.py`, `POST /video/analyze/json` | ✅ 완료 |
| **3** | `services/extract_coordinator.py`, `POST /video/analyze` 2단계(추출→채점) | ✅ 완료 |
| **4** | OpenAPI·통합 E2E 검증 | 🔲 수동 테스트 권장 |

### 1.2 metric별 `score_*` (오케스트레이터 연결)

| metric | `score_*` 위치 | 오케스트레이터 입력 | 상태 |
|--------|----------------|---------------------|------|
| **accuracy** | `rom/.../accuracy_scorer.py` | `aligned_pairs` | ✅ |
| **creativity** | `metrics/creativity/creativity.py` | `aligned_pairs` | ✅ |
| **isolation** | `metrics/isolation/score.py` | `aligned_pairs` | ✅ |
| **rom** | `rom/.../rom_scorer.py` | offset 이후 활성 프레임 리스트 | ✅ |
| **power** | `metrics/power/__init__.py` | `user_extraction` (ROM JSON) | ✅ |
| **rhythm** | `metrics/rhythm/.../rhythm_scorer.py` | user/ref extraction (프레임 수에 따라 vs_reference 분기) | ✅ |

### 1.3 라우터·prefix (현재 `main.py`)

| metric | 라우터 | prefix | `main.py` |
|--------|--------|--------|-----------|
| **통합** | `routers/video.py` | `/video` | ✅ (먼저 등록) |
| **rhythm** | `metrics/rhythm/routers/video.py` | `/rhythm` | ✅ |
| **isolation** | `metrics/isolation/router.py` | `/isolation` | ✅ |
| **power** | `metrics/power/routers/video.py` | `/power` | ✅ |
| **accuracy** | — (ROM scorer) | — | 통합 `/video` 만 |
| **creativity** | CLI (`python -m metrics.creativity`) | — | 통합 `/video` 만 |
| **rom** | domain1 + 통합 `/video` | `/video` | ✅ |

```python
# backend1/main.py (현재)
app.include_router(video_router)       # /video/*
app.include_router(rhythm_router)      # /rhythm/*
app.include_router(isolation_router)   # /isolation/*
app.include_router(power_router)       # /power/*
```

**해결된 이슈:** rhythm 이 `/video` prefix 일 때 `POST /video/analyze` 가 rhythm 핸들러에 가려지던 충돌 → `/rhythm` 분리로 해소.

---

## 2. 목표 아키텍처 (달성 형태)

```
# 통합 (routers/video.py)
POST /video/extract          → ROM domain1 추출 (레퍼런스 1회)
POST /video/analyze          → extract_coordinator(병렬) → orchestrator(채점)
POST /video/analyze/json     → orchestrator 만
POST /video/compare          → ROM compute_comparison (디버그)
GET  /video/json/{filename}
GET  /video/data/{filename}

# metric 전용 (개발·레거시)
POST /rhythm/*
POST /isolation/*
POST /power/*

GET  /health
```

---

## 3. 레이어 분리

| 레이어 | 파일 | 역할 |
|--------|------|------|
| HTTP | `routers/video.py` | multipart/JSON, 임시 영상 |
| 추출 조율 | `extract_coordinator.py` | rom/rhythm/power/creativity 병렬, canonical = ROM JSON |
| 채점 | `orchestrator.py` | JSON 로드·정렬·`score_*` 병렬·`total_score`/`grade` |
| ROM 도메인 | `metrics/rom/domain/domain1/` | 추출 파이프라인, alignment, accuracy/rom scorer |

**ARCHITECTURE §1.1 보완:** analyze **오케스트레이터** 는 채점 시 추출하지 않는다.  
다만 **`POST /video/analyze`** 는 라우터가 **먼저** `extract_coordinator`, **이어서** `run_analyze_from_json` 을 호출한다.

---

## 4. 오케스트레이터 설계 (구현됨)

### 4.1 `POST /video/analyze/json` Body

```json
{
  "user_json": "20260521_120000_abc123.json",
  "reference_json": "ref_idol_A.json",
  "alignment_method": "time",
  "user_offset_sec": 0.0,
  "ref_offset_sec": 0.0,
  "auto_detect_start": false,
  "metrics": null,
  "fail_fast": false
}
```

- `metrics: null` → **6개 전체** (`resolve_metrics_list`)
- `metrics: ["rom"]` → ROM 만

### 4.2 처리 흐름

```
1. load_comparison_fields / load_extraction_json
2. build_aligned_pairs (time | dtw, offset, auto_detect_start)
3. run_all_scores — asyncio + ThreadPoolExecutor(6)
4. compute_total_score — 성공 metric score 단순 평균
5. alignment + scores + meta 응답
```

### 4.3 입력 분기 (실제 코드)

| metric | 인자 |
|--------|------|
| accuracy, creativity, isolation | `aligned_pairs` |
| rom | offset 이후 `user_frames`, `ref_frames` |
| power | `user_extraction` |
| rhythm | `user_extraction`, `ref_extraction` (2프레임 이상이면 `score_rhythm_vs_reference`) |

---

## 5. 추출 조율 (`extract_coordinator.py`)

### 5.1 기본 파이프라인

`DEFAULT_EXTRACT_PIPELINES`: `rom`, `rhythm`, `power`, `creativity` (max_workers=4).

- **canonical:** ROM `{base}.json` — Phase B 채점 입력
- **sidecar:** `{base}_rhythm.json`, `{base}_power.json`, `{base}_creativity.json` — 저장만, 채점 미연동

### 5.2 ROM 모드

| 조건 | `rom_mode` |
|------|------------|
| 채점에 accuracy/creativity/isolation/power/rhythm 포함 | `full` (자동) |
| 그 외 | Form `extraction_mode` (**`full` 기본**) |

### 5.3 미구현·백로그

- `pipelines` HTTP 노출 (코드에 `run_user_extractions_parallel(pipelines=...)` 는 있음)
- isolation YOLO 추출 병렬
- sidecar → 오케스트레이터 입력 연동

---

## 6. 병렬·오류 처리 (구현)

| 항목 | 구현 |
|------|------|
| 채점 executor | `ThreadPoolExecutor(max_workers=6)` |
| 추출 executor | `ThreadPoolExecutor(max_workers=4)` |
| `fail_fast` 기본값 | **`false`** — metric별 `breakdown.error` |
| `fail_fast=true` | 첫 예외 → 요청 실패 |
| `total_score` | 오류 없는 metric 점수 **평균** (`METRIC_WEIGHTS` 는 예약, 미사용) |
| 프레임 길이 검증 | user/ref 프레임 수 비율 10배 초과·1/10 미만 → `ValueError` |

### MediaPipe

- **추출** 단계만 MediaPipe/영상 디코딩 — 파이프라인별 독립 실행 권장
- **채점** 오케스트레이터는 JSON만 처리

---

## 7. 엔드포인트 맵 (현재)

상세 필드는 [API_REFERENCE.md](./API_REFERENCE.md) 참고.

```
POST /video/extract
POST /video/analyze
POST /video/analyze/json
POST /video/compare
GET  /video/json/{filename}
GET  /video/data/{filename}

GET  /isolation/ready
POST /isolation/analyze
POST /power/extract
POST /power/score
POST /rhythm/analyze
POST /rhythm/extract
… (rhythm 라우터 전체 — prefix /rhythm)

GET  /health
```

---

## 8. 경계 규칙

| 규칙 | 이유 |
|------|------|
| metric끼리 **import 금지** | 독립 수정·배포 |
| `score_*` 는 analyze 경로에서 **영상 재추출 없음** | 지연·책임 분리 |
| `aligned_pairs` **읽기 전용** | 병렬 안전 |
| metric 전용 **고유 prefix** | `/video` 통합 경로 보호 |
| 레거시 `enable_accuracy` / `enable_rom` | `metrics` 명시 시 **무시** |

---

## 9. 과거 진단 (참고 — 해결됨)

<details>
<summary>2026-05-21 이전 prefix 충돌</summary>

- rhythm `prefix=/video` 가 먼저 등록되어 통합 `POST /video/analyze` 가 가려짐
- isolation·power 가 `main.py` 에 미등록

**조치 완료:** rhythm → `/rhythm`, 세 metric 라우터 등록, `orchestrator` + `extract_coordinator` 도입.

</details>

---

## 10. 백로그

1. 오케스트레이터 sidecar JSON 경로 입력
2. `POST /video/analyze` 에 `pipelines` Form (ROM-only 시 sidecar 생략)
3. isolation YOLO 추출 파이프라인
4. creativity CLI `index` 정렬을 통합 경로에 반영 여부
5. Flutter `api_config` ↔ 통합 응답 스키마 정렬
