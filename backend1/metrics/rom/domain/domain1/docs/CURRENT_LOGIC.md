# 현재 비교 로직 구현 상태 (Current Implementation Status)

> **목적:** 추출·정규화·비교 파이프라인의 실제 동작과 한계 명세  
> **대상:** 개발팀, QA, 채점 로직 확장 담당자  
> **작성일:** 2026-05-20  
> **최종 갱신:** 2026-05-21 — ROM 경량 추출(`rom_v1`)·`enable_accuracy` 기본값 반영  
> **성능:** [ROM_EXTRACTION_PERFORMANCE.md](./ROM_EXTRACTION_PERFORMANCE.md)  
> **기술·라이브러리 총정리:** [ROM_IMPLEMENTATION_TECH.md](./ROM_IMPLEMENTATION_TECH.md)

---

## 1. 전체 흐름 요약

```
[추출 단계] POST /video/extract
  ① MediaPipe → landmarks (원본 화면 좌표)
  ② 보간·스무딩 (pandas interpolate + rolling mean)
  ③ 정규화
     - Step A: Mid-Hip → 원점 (0,0,0)
     - Step B: Torso Length로 스케일
  ④ normalized_landmarks 기반
     - joint_angles 계산 (10개 관절 각도)
     - bone_vectors 계산 (11개 뼈 방향 벡터)
  → video_json/{id}.json 저장

[비교 단계] POST /video/compare
  ① load_comparison_fields (joint_angles·bone_vectors·time_sec 등만 로드)
  ② 오프셋 적용 (user_offset_sec / ref_offset_sec 또는 auto_detect_start)
  ③ align_by_time (bisect) 또는 align_by_dtw (fastdtw)
  ④ score_accuracy (scoring_mode=dance 기본, detail_level=summary 기본)
     - joint_angles → 60%, bone_vectors 코사인 → 40%
  → Accuracy 점수 + worst_frames (summary) 또는 frame_diffs (full)
```

---

## 2. 문제 요인별 대응 현황

### 2.1 화면 위치·시작점 (Translation) ✅

**문제:** 전문가는 화면 중앙, 사용자는 왼쪽에서 춤 → 같은 동작이라도 `landmarks.x/y`가 다름.

**구현 (`extraction_service.py` Line 97–100):**
```python
# Step A: Mid-Hip을 원점(0,0,0)으로 이동
mid_hip_x = (left_hip.x + right_hip.x) / 2
# 모든 관절 좌표에서 mid_hip을 뺌
normalized_landmarks[name].x = (landmarks[name].x - mid_hip_x) / torso_length
```

**효과:**
- 화면 **좌우·상하** 위치 차이는 정규화 좌표에서 제거됨
- `joint_angles` / `bone_vectors`는 **normalized_landmarks** 기준이므로 화면 위치 무관

**한계:**
- 골반 검출이 불안정하면 기준점이 흔들림
- 프레임마다 독립 정규화 → 골반이 크게 움직이는 동작은 상대 위치가 덜 안정적

**비교 단계 보강:** `accuracy_scorer`는 `landmarks`를 **직접 쓰지 않음** → 화면 좌표 차이가 점수에 직접 영향 ❌

---

### 2.2 체형·키 차이 (Scaling) ✅

**문제:** 키 180cm vs 150cm → 손목 절대 위치가 다름, 팔다리 길이 비율 차이.

**구현 (Step B, Line 102–116):**
```python
# Torso Length = Mid-Shoulder ↔ Mid-Hip 거리
torso_length = sqrt((mid_shoulder - mid_hip)^2)
# 모든 좌표를 torso_length로 나눔
normalized_landmarks[name] = (원본 - mid_hip) / torso_length
```

**효과:**
- "손목이 몸통 길이의 몇 배 떨어져 있는가"로 변환 → **상대 비율** 기준
- `joint_angles`는 **각도(스칼라)** → 체형 스케일과 무관
- `bone_vectors`는 **단위 방향 벡터** → 길이 아닌 **방향** 비교

**한계:**
- 팔다리 **비율**(팔 대 다리 길이 비)이 극단적으로 다르면 미세 오차
- 몸통이 너무 짧거나 검출 실패 시 `torso_length < 1e-6` → 1.0 고정 (fallback)

**비교 단계 보강:**
- `joint_angles` 60% 가중 → 체형 변화에 **가장 강건**
- `bone_vectors` 코사인은 방향만 → 길이 차이 무시

---

### 2.3 카메라 시점·앵글 (Viewpoint) △

**문제:** 정면 vs 측면 촬영 → 2D 화면 투영 왜곡 (시점 불변성).

**구현 원칙 (`VIEWPOINT_INVARIANCE.md` §1.2):**
| 데이터 | 비교 사용 여부 | 이유 |
|--------|---------------|------|
| `landmarks` | ❌ 금지 | 화면 좌표 그대로 → 시점 민감 |
| `normalized_landmarks` | △ 보조만 | 위치·스케일만 보정, 앵글 여전히 영향 |
| `joint_angles` | ✅ 60% | **시점에 가장 강건** (내부 각도) |
| `bone_vectors` | ✅ 40% | 방향 비교 (정규화 좌표 기반) |

**구현 (`accuracy_scorer.py` Line 7–9, 28–69):**
```python
ANGLE_WEIGHT = 0.6  # joint_angles 우선
BONE_WEIGHT = 0.4

# 프레임 쌍 점수 = 0.6 * 각도 유사도 + 0.4 * 벡터 코사인
```

**효과:**
- 정면·측면에서도 "팔꿈치 각도"는 (이상적으로) 동일 → 점수 안정
- 뼈 방향 코사인도 정규화 좌표 기준 → `landmarks` 직접 비교보다 훨씬 나음

**한계:**
- MediaPipe **Z축은 추정값** → 측면·대각 촬영 시 각도·벡터도 오차 발생
- **3D 몸통 평면 회전 보정** 미구현 (`VIEWPOINT_INVARIANCE.md` §3 대안 2) — MVP 범위 외
- 극단적 앵글(위/아래 촬영)은 여전히 취약

**권장 (문서 §4.3):** 프론트엔드 **촬영 가이드 UI**로 앵글 차이 최소화 (대안 3) — 백엔드 현재 미적용.

---

### 2.4 시간·템포 차이 (Temporal Alignment) △

**문제:** 사용자가 늦게 시작, 중간에 빠르게/느리게 → 프레임 어긋남.

**구현 (`alignment.py`, `compare_request.py`):**
- `align_by_time`: 오프셋 이후 **상대 time_sec** + `bisect` → O(n log m)
- `user_offset_sec` / `ref_offset_sec`: 춤 시작 시점 수동 지정
- `auto_detect_start=True`: `detect_dance_start()` — 골반·어깨 4관절 움직임 threshold
- `alignment_method=dtw`: `fastdtw` + `joint_angles` 10차원 벡터 시퀀스 정렬
- `duplicate_ratio` + `meta.warnings`: ref 프레임 중복 매칭 30% 초과 시 경고

**효과:**
- 준비 동작·편집본 오프셋 → **수동/자동 offset으로 상당히 개선**
- 템포 차이 → **DTW**로 완화 (느린 구간·빠른 구간 warp)
- FPS 차이 → time 정렬에서 bisect로 nearest 매칭

**남은 한계:**
- `auto_detect_start`는 카메라 흔들림·입장 동작에 오탐 가능
- DTW는 근사(fastdtw) + user 프레임 1회 매칭 제한 → 극단 템포는 여전히 어려움
- 영상 **길이**가 크게 다르면 10배 검증에서 422

**API 예:**
```json
{
  "user_json": "user.json",
  "reference_json": "ref.json",
  "alignment_method": "dtw",
  "user_offset_sec": 2.0,
  "auto_detect_start": false,
  "detail_level": "summary",
  "scoring_mode": "dance"
}
```

---

### 2.5 3D 회전·깊이 보정 ❌

**문제:** 카메라 위치에 따라 Z축(깊이)이 다르게 추정됨 → `normalized_landmarks`·각도도 영향.

**구현:** 없음.

**설계 (문서만):** `VIEWPOINT_INVARIANCE.md` §3 대안 2 — 양쪽 어깨·골반 4점으로 몸통 평면 정의 → 법선 방향을 Z축 정렬 → 회전 행렬 적용.

**미구현 이유:**
- MediaPipe **Z는 단일 카메라 추정** → 신뢰도 낮음
- 과도한 회전 시 좌표 **붕괴** 위험
- MVP **1주일 범위 외**

**영향:** 측면·대각 촬영은 `joint_angles`·`bone_vectors`로 어느 정도 버티지만, Z 노이즈가 큰 각도(어깨 등)는 오차 가능.

---

## 3. 추출 데이터 필드별 역할

| 필드 | 좌표계 | 비교 사용 | 용도 |
|------|--------|-----------|------|
| **`landmarks`** | 화면 0~1 | ❌ | 시각화, Power(가속도), Rhythm |
| **`normalized_landmarks`** | Mid-Hip 원점, Torso=1 | △ (내부 계산만) | `joint_angles`·`bone_vectors` 입력 |
| **`joint_angles`** | 각도(도) | ✅ 60% | Accuracy 1순위, ROM |
| **`bone_vectors`** | 단위 방향 + 길이 | ✅ 40% | Accuracy 2순위, Isolation |

**설계 원칙:** 비교는 **시점·체형에 강한 지표만** 사용 (`VIEWPOINT_INVARIANCE.md` §1.2).

---

## 4. 현재 Accuracy 채점 알고리즘

### 4.1 프레임 쌍 점수 (`accuracy_scorer.py` Line 28–69)

```python
def score_frame_pair(user_frame, ref_frame):
    # 1. 관절 각도 유사도 (60%)
    for joint in user_angles:
        diff = abs(user_angles[joint] - ref_angles[joint])
        similarity = 100 - (diff / 180 * 100)  # 0° 차이 → 100, 180° → 0
    angle_score = mean(similarities)
    
    # 2. 뼈 벡터 코사인 유사도 (40%)
    for bone in user_bones:
        cosine = dot(user_bones[bone], ref_bones[bone])  # 단위벡터 → [-1, 1]
        score = (cosine + 1) / 2 * 100  # 같은 방향 → 100, 반대 → 0
    bone_score = mean(scores)
    
    # 3. 가중 평균
    total = 0.6 * angle_score + 0.4 * bone_score
```

### 4.2 영상 전체 점수 (`accuracy_scorer.py` Line 91–125)

```python
frame_scores = [score_frame_pair(u, r) for u, r in aligned_pairs]
final_accuracy = mean(frame_scores)
grade = score_to_grade(final_accuracy)  # A+/A/B/C/D
```

**반환:**
- `scores.accuracy.score` (0~100)
- `scores.accuracy.breakdown` (각도·벡터 요약)
- `scores.accuracy.frame_diffs[]` (프레임·관절별 상세)

---

## 5. 비교 API 응답 구조

```json
{
  "user_json": "20260520_abc.json",
  "reference_json": "20260520_def.json",
  "alignment": {
    "method": "time",
    "pair_count": 120,
    "aligned_pairs": [
      {"user_frame": 0, "ref_frame": 0},
      {"user_frame": 1, "ref_frame": 2}
    ]
  },
  "scores": {
    "accuracy": {
      "score": 85.2,
      "breakdown": {
        "joint_angles_similarity": 88.0,
        "bone_vectors_cosine": 81.5
      },
      "frame_diffs": [
        {
          "user_frame": 0,
          "ref_frame": 0,
          "frame_score": 92.3,
          "joint_angle_diffs": {
            "left_elbow": 5.2,
            "right_knee": 12.8
          },
          "bone_vector_cosines": {
            "left_upper_arm": 0.95,
            "torso": 0.88
          }
        }
      ]
    },
    "total_score": 85.2,
    "grade": "B+"
  },
  "meta": {
    "user_fps": 30.0,
    "reference_fps": 30.0
  }
}
```

**주의:** `enable_rom=true`(기본)일 때 `total_score` = Accuracy 30% + ROM 15% 정규화 가중 평균. `enable_rom=false`면 Accuracy만.

---

## 6. 현재 한계 요약

| 항목 | 상태 | 영향 |
|------|------|------|
| **화면 위치** | ✅ 양호 | Mid-Hip 정규화로 거의 해결 |
| **체형·키** | ✅ 양호 | Torso 스케일 + 각도 우선으로 완화 |
| **시점·앵글** | △ 부분 | `joint_angles` 60%로 완화, 극단 앵글은 여전히 취약 |
| **시간·템포** | △ 개선됨 | offset·auto_detect·DTW 지원, 극단 템포·오탐은 잔존 |
| **3D 회전** | ❌ 없음 | Z축 노이즈 → 각도·벡터 오차 가능 |
| **촬영 통제** | ❌ 없음 | 프론트 가이드 UI 미연동 |
| **6개 채점** | 🔄 Accuracy + ROM | Power, Isolation, Rhythm, Creativity 미구현 |
| **API 응답 크기** | ✅ 개선 | `detail_level=summary` 기본, `worst_frames` 10개만 |

---

## 7. 데이터 검증 & 에러 핸들링

### 7.1 추출 단계 (`extraction_service.py`)

| 검증 | 구현 |
|------|------|
| 영상 열기 실패 | `ValueError` (422) |
| 랜드마크 미검출 프레임 | NaN 삽입 → 보간 (투명하게 처리) |
| Torso Length 0 | `< 1e-6` → 1.0 고정 (fallback) |

### 7.2 비교 단계 (`comparison_service.py` Line 12–46)

| 검증 | 구현 |
|------|------|
| JSON 파일 없음 | `FileNotFoundError` (404) |
| `frames` 필드 없음/비어 있음 | `ValueError` (422) |
| 프레임 수 10배 차이 | `ValueError` (422) — "두 영상 길이 차이가 너무 큼" |
| 지원 안 되는 정렬 | `ValueError` (422) — `alignment_method` 검증 |

---

## 8. 성능 특성

| 단계 | 시간 (1분 30fps 기준) | 병목 |
|------|------------------------|------|
| 추출 (MediaPipe) | ~30초 | 프레임 처리 |
| JSON 저장·로드 | ~1초 | 디스크 I/O |
| 정렬 (time, bisect) | ~0.01초 | O(n log m) |
| 정렬 (dtw, fastdtw) | ~0.5~2초 | O(n) 근사 |
| Accuracy 채점 | ~0.5초 | 프레임 순회 |
| **전체 비교** | **~1~3초** | **추출 제외** |

---

## 9. 테스트 현황

### 9.1 단위 테스트 ✅

- `alignment.align_by_time` — 합성 JSON (통과)
- `accuracy_scorer.score_accuracy` — 동일 프레임 → ~99.7점 (통과)

### 9.2 통합 테스트 ⏳

- [ ] 실제 영상 동일 파일 2회 extract → compare → 95점 이상
- [ ] 정면 vs 측면 촬영 → 점수 차이 검증
- [ ] 템포 2배 차이 → time vs DTW 비교 (DTW 미구현)

---

## 10. 추후 개선 로드맵

### Phase 2B–C (단기)
- [ ] ROM, Power 채점 추가 (`comparison_service` 확장)
- [ ] `total_score` 가중 평균 (Accuracy 외 포함)
- [ ] 실영상 통합 테스트

### Phase 2D (중기)
- [ ] DTW 정렬 (`alignment_method=dtw`)
- [ ] Isolation, Rhythm, Creativity

### Phase 3 이후 (장기)
- [ ] 3D 몸통 평면 회전 보정 (Z축 검증 후)
- [ ] 프론트엔드 촬영 가이드 연동
- [ ] 멀티 레퍼런스 (전문가 여러 명 평균)

---

## 11. 의사결정 기록

| 날짜 | 결정 | 근거 |
|------|------|------|
| 2026-05-20 | Accuracy는 `joint_angles` 60% + `bone_vectors` 40% | `VIEWPOINT_INVARIANCE.md` §2.3 |
| 2026-05-20 | `landmarks` 비교 금지 | 시점 민감성 (§1.1) |
| 2026-05-20 | DTW MVP 보류, `time` 정렬만 | 구현 속도 우선, Phase 2D 검토 |
| 2026-05-20 | 3D 회전 보정 보류 | Z축 신뢰도 낮음, MVP 범위 외 (§3.4) |

---

## 12. 관련 문서

- [ROM_SCORING.md](./ROM_SCORING.md) — ROM 채점 알고리즘 설계·구현 가이드
- [COMPARE_SOLUTION.md](./COMPARE_SOLUTION.md) — `/compare` 개선 설계 (Phase 1·2 구현 완료)
- [VIEWPOINT_INVARIANCE.md](./VIEWPOINT_INVARIANCE.md) — 시점 문제 3가지 대안 상세
- [COMPARISON_STRATEGY.md](./COMPARISON_STRATEGY.md) — API 설계·알고리즘 전체
- [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) — Phase별 진행 체크리스트
- [PROJECT_CONTEXT.md](./PROJECT_CONTEXT.md) — 프로젝트 기획·사용자 여정

---

## 13. FAQ

**Q1. 같은 영상 2번 extract → compare → 100점 아닌가요?**  
A. MediaPipe 미세 노이즈, 스무딩 차이 → **95~99점** 정도 예상. 100점은 이론적 최대.

**Q2. 측면 촬영도 괜찮나요?**  
A. `joint_angles`로 어느 정도 버티지만, **정면 대비 5~15점 낮을 수 있음**. 극단 앵글은 피해야.

**Q3. 사용자가 늦게 시작하면?**  
A. `user_offset_sec`(또는 `auto_detect_start=true`)로 춤 시작 시점을 맞춘 뒤 정렬. 템포까지 다르면 `alignment_method=dtw` 권장.

**Q4. 키 차이 2배면?**  
A. Torso Length 정규화 + 각도 우선 → **대부분 흡수**. 팔다리 비율 극단 차이만 주의.

**Q5. `total_score`가 `accuracy.score`와 같은 이유?**  
A. 현재 **Accuracy만 구현**. ROM·Power 추가 시 가중 평균으로 변경 예정.

---

**한 줄 요약:** 화면 위치·체형은 추출 정규화로 양호, 비교는 offset·DTW·비선형 각도로 시간·템포를 개선했으나 시점·3D 회전·6채점은 미해결이며 Accuracy(일치도)만 동작합니다.
