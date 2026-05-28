# Creativity metric

영상 또는 이미지 **쌍**을 비교해 창의성 점수(0~100)를 산출합니다.  
미디어 없이 JSON·샘플만으로 점수를 내는 기능은 **없습니다.**

## 보정 체크리스트 (두 영상 댄스 비교)

### 반드시 맞출 것

- [x] **동일 BGM 구간**: `--music-align`(기본 on) — 크로마로 `[시작, 끝]` 검출
- [x] **동작 단위 비교**: 연속 **3프레임** 이상 정지=경계 → 상위 **n=3** 동작 구간, 구간 내 **전 프레임** 비교
- [x] **메인 댄서**: 화면 중앙 72% crop 후 MediaPipe
- [x] **신체 스케일**: Mid-Hip 원점 + torso 길이 정규화
- [x] **비교 특징**: `normalized_landmarks`, `joint_angles`, `bone_vectors`

### 가능하면 맞출 것

- [x] **미러 보정**: `--apply-mirror` (기본 on)
- [x] **정렬**: `--alignment index|time|dtw` (기본 `dtw`, `dtw_mean_cost` 패널티)
- [x] **기준선**: `--baseline` (기본 on) — ref vs ref 보정
- [ ] **수동 offset**: `--user-offset` / `--ref-offset` 지정 시 음악 정렬 스킵
- [ ] **포즈 시작 추정**: `--auto-detect-start` (음악 정렬과 동시 사용 안 함)

## 3단계 창의성 점수 (P0)

1. **이탈 band** — mean_divergence 양쪽 감쇠 (0.08~0.22 상승, 0.22~0.55=1, 0.55~0.85→0.15)
2. **DTW 패널티** — cost ≤28→1, ≥42→0.25
3. **ref vs ref 기준선** — `score = 100×(raw−baseline)/(1−baseline)`

## CLI

```powershell
cd C:\ai-x\FOM\backend1
pip install -r requirements.txt
$env:PYTHONPATH = (Get-Location).Path
```

**MediaPipe 0.10.31+:** Tasks API 사용. 첫 실행 시 `models/pose_landmarker_lite.task` 자동 다운로드.

**오디오:** 음악 정렬에 `librosa` + `ffmpeg`(또는 `imageio-ffmpeg`) 필요.

### 영상 vs 영상 (권장)

```cmd
cd /d C:\ai-x\FOM\backend1
set PYTHONPATH=C:\ai-x\FOM\backend1
python -m metrics.creativity.cli --user user.mp4 --reference ref.mp4 --num-motion-units 3 --alignment dtw
```

### 옵션 요약

| 옵션 | 기본 | 설명 |
|------|------|------|
| `--num-motion-units` | 3 | 비교할 동작 단위 수 |
| `--idle-min-frames` | 3 | 연속 정지 프레임(동작 경계) |
| `--music-align` / `--no-music-align` | on | 동일 BGM 크로마 구간 정렬 |
| `--baseline` / `--no-baseline` | on | ref vs ref 기준선 |
| `--with-accuracy` | off | 동일 파이프라인 정확도(참고) |
| `--with-llm` | off | 수식 점수 × LLM 보정(0.8~1.2, Ollama) |
| `--alignment` | dtw | index / time / dtw |

## 파이프라인

```text
미디어 쌍 → 전체 프레임 추출(중앙 crop)
  → music_align: [user_start, user_end], [ref_start, ref_end] (동일 곡 전제)
  → preprocess: 구간 내 균등 N프레임(기본 50), 미러, visibility
  → align (index|time|dtw) + dtw_mean_cost
  → align(ref, ref) 기준선
  → score_creativity(3단계) → (선택) LLM 하이브리드 보정
  → (선택) score_accuracy
```

### LLM 하이브리드 (방안 1)

- `최종 점수 = 수식 점수 × creativity_adjustment` (0.80~1.20, 기본 1.0)
- Ollama `qwen2.5:7b-instruct-q4_K_M` @ `http://localhost:11434`
- CLI: `--with-llm` / API: `with_llm_adjustment=true`
- 실패 시 계수 1.0, `breakdown.llm_error` 기록

## 출력 JSON

`inputs`, `music_align`, `preprocess`, `alignment`, `creativity` (score, breakdown, frame_diffs, `llm_hybrid`), (선택) `accuracy`

### breakdown 주요 필드 (P4)

- `mean_divergence`, `divergence_band_factor`, `dtw_penalty_factor`, `effective_band_factor`
- `combined_raw`, `baseline_combined_raw`, `combined_after_baseline`, `baseline_subtracted`
- `dtw_mean_cost`, `divergence_thresholds`, `dtw_thresholds`
- `formula_score`, `llm_adjustment`, `llm_rationale`, `llm_flags`, `score_after_llm`

## HTTP API (Swagger 테스트)

서버 실행 후 `http://localhost:8000/docs` → 태그 **creativity**

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/creativity/ready` | API 준비 상태 |
| `POST` | `/creativity/analyze` | user + reference 영상/이미지 업로드 → 전체 파이프라인 |

```bash
cd C:\ai-x\FOM\backend1
uvicorn main:app --host 0.0.0.0 --port 8000
```

Form 기본값(영상): `num_motion_units=3`, `idle_min_frames=3`, `music_align=true`, `baseline=true`, `alignment=dtw`

## 통합 API (별도)

`POST /video/analyze` 에서 creativity 채점은 오케스트레이터(ROM 정렬) 경로입니다.  
**음악 구간·동작 단위(n=3)·3단계 전체** 는 `POST /creativity/analyze` 또는 CLI를 사용하세요.
