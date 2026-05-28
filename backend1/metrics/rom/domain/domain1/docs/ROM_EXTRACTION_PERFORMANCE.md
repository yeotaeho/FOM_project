# ROM 경량 추출 · 성능

> **대상:** ROM metric만 사용할 때 MediaPipe·저장·채점 지연을 줄이는 설정  
> **진입점:** `POST /video/extract` (`backend1/routers/video.py` → `domain1`)

---

## 1. 문제

전체 프레임 × 33 랜드마크 × `bone_vectors` + annotated MP4는 9초·60fps 영상에서도 **15~27초** 수준으로 느릴 수 있다. ROM 채점은 **`joint_angles` 시퀀스**만 필요하다.

---

## 2. 해결 요약

| 항목 | `extraction_mode=rom` (기본) | `extraction_mode=full` |
|------|------------------------------|-------------------------|
| JSON schema | `rom_v1` | `full_v1` |
| 프레임 필드 | `joint_angles`, `time_sec`, `source_frame_index` | landmarks, normalized, bone_vectors, … |
| MediaPipe 관절 | ROM 최소 14개 | 33개 |
| 기본 샘플링 | `target_fps=15` | 전체 프레임 (`target_fps` 미지정 또는 0) |
| annotated MP4 | 생략 (기본) | 생성 (기본) |

---

## 3. API (`POST /video/extract`)

| Form 필드 | 기본 | 설명 |
|-----------|------|------|
| `extraction_mode` | `rom` | `rom` \| `full` |
| `target_fps` | `15` | `round(source_fps / target_fps)` 간격으로 MediaPipe. `0` 이하 = 전 프레임 |
| `frame_stride` | (없음) | 지정 시 `target_fps`보다 **우선** (예: `4` = 4프레임마다 1회) |
| `include_annotated_video` | (모드별) | `rom` → 기본 false, `full` → 기본 true |

**권장 흐름 (ARCHITECTURE):**

1. 사용자·레퍼런스 각각 `POST /video/extract` (`extraction_mode=rom`, 동일 `target_fps`)
2. `POST /video/analyze` JSON — `enable_accuracy: false`, `enable_rom: true`

---

## 4. 채점 기본값

- `POST /video/analyze`, `POST /video/compare`: **`enable_accuracy=false`**, **`enable_rom=true`**
- `total_score` = ROM만 켠 경우 **ROM 점수 단독**
- Accuracy 필요 시: `full`로 추출 후 `enable_accuracy=true`

`auto_detect_start=true` 시 `rom_v1`은 `joint_angles` 변화량으로 시작 시점 추정 (`alignment.detect_dance_start_from_joint_angles`).

---

## 5. 주의

- **레퍼런스·사용자 JSON은 같은 schema·같은 `target_fps`** 로 맞출 것. `full_v1`과 `rom_v1` 혼용 compare는 왜곡됨.
- 기존 full JSON은 재추출 없이 ROM만 보려면 `joint_angles`가 있으면 동작할 수 있으나, 샘플링 밀도가 다르면 ROM 비교가 부정확해짐.

---

## 6. 구현 위치

- `hub/services/extraction_service.py` — `extract_rom_data`, `resolve_sample_stride`
- `hub/services/extraction_pipeline.py` — `run_extraction_and_save(mode=...)`
- `hub/services/storage_paths.py` — `is_rom_schema`, `load_rom_fields`
- `hub/services/comparison_service.py` — `enable_accuracy`
