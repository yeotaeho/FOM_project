# ROM (Range of Motion) 채점 설계

> **목적:** 스트릿 댄스 동작의 관절 가동 범위 평가  
> **작성일:** 2026-05-20  
> **대상:** 개발팀, 채점 로직 구현 담당자

---

## 1. ROM 정의 및 댄스 맥락

### 1.1 일반 정의

**ROM (Range of Motion, 관절 가동 범위):**  
하나의 관절이 **움직일 수 있는 각도의 범위**. 예를 들어 팔꿈치를 완전히 펴면 180°, 완전히 굽히면 30° → ROM = 150°.

### 1.2 댄스 맥락에서의 의미

스트릿 댄스(특히 팝핑·락킹·크럼프 등)에서 ROM은:
- **표현력의 핵심:** 큰 동작, 과장된 제스처, 관절의 최대 가동
- **유연성 지표:** 낮은 자세, 높은 킥, 팔 뻗기 등 극단 동작
- **차별화 요소:** 같은 안무라도 ROM이 큰 댄서가 더 "시원하고 다이나믹"하게 보임

**평가 의도:**  
전문가가 팔꿈치를 30°~180°까지 사용했는데, 사용자가 60°~120°만 썼다면 → **가동 범위가 좁음** → 동작이 작고 소극적으로 보일 수 있음.

---

## 2. 채점 방식 선택

### 2.1 절대 평가 vs 상대 평가

| 방식 | 기준 | 장점 | 단점 |
|------|------|------|------|
| **절대 평가** | "팔꿈치 ROM ≥ 120°면 80점" | 구현 간단, 레퍼런스 불필요 | 안무별 특성 무시 (느린 춤은 ROM 작을 수 있음) |
| **상대 평가** | "전문가 ROM 대비 사용자 커버리지" | 안무 맞춤, Accuracy와 일관 | 레퍼런스 필수 |

**MVP 선택: 상대 평가 (레퍼런스 기반)**  
- 이유 1: `/video/compare` API 구조와 일관 (Accuracy도 상대)
- 이유 2: "같은 안무를 얼마나 크게 춤?" 질문에 맞음
- 향후: 절대 평가를 보조 지표로 추가 가능 (예: "최소 ROM 미달 경고")

---

## 3. 입력 데이터 및 전제

### 3.1 사용 필드

추출 JSON의 **`joint_angles`** 필드:
```json
{
  "frame_index": 0,
  "time_sec": 0.0,
  "joint_angles": {
    "left_elbow": 142.5,
    "right_elbow": 135.8,
    "left_knee": 165.2,
    "right_knee": 168.3,
    "left_shoulder": 85.4,
    "right_shoulder": 88.1,
    "left_hip": 92.7,
    "right_hip": 91.3,
    "left_ankle": 105.2,
    "right_ankle": 103.8
  }
}
```

**10개 관절 각도 (도):**  
- 팔꿈치 (왼쪽·오른쪽)
- 무릎 (왼쪽·오른쪽)
- 어깨 (elbow→shoulder→hip 각)
- 골반 (shoulder→hip→knee 각)
- 발목 (knee→ankle→foot_index 각)

### 3.2 전제 조건

1. **추출 완료:** 사용자·전문가 영상이 이미 `extract_dance_data` 완료 (`joint_angles` 저장)
2. **정규화 좌표 기반:** `joint_angles`는 `normalized_landmarks`에서 계산됨 → **시점·체형 보정됨**
3. **MediaPipe 신뢰도:** 관절 검출 실패 프레임은 이미 보간 처리됨 (`extraction_service`)

---

## 4. 알고리즘 설계

### 4.1 개념 흐름

```
[전문가 영상]
  → 각 관절별 max/min 각도 추출
  → ROM_ref[joint] = max - min

[사용자 영상]
  → 각 관절별 max/min 각도 추출
  → ROM_user[joint] = max - min

[비교]
  → coverage[joint] = ROM_user / ROM_ref
  → 전체 평균 또는 가중 평균 → ROM_score
```

### 4.2 관절별 ROM 계산

```python
def compute_joint_rom(frames: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    각 관절의 최대·최소 각도를 찾아 ROM(범위) 반환.
    입력: frames[{"joint_angles": {...}}]
    출력: {"left_elbow": 135.2, "right_knee": 142.8, ...}
    """
    angle_sequences = {}  # joint_name → [각도 리스트]
    
    for frame in frames:
        angles = frame.get("joint_angles") or {}
        for joint, value in angles.items():
            if joint not in angle_sequences:
                angle_sequences[joint] = []
            angle_sequences[joint].append(float(value))
    
    rom = {}
    for joint, values in angle_sequences.items():
        if not values:
            rom[joint] = 0.0
            continue
        rom[joint] = round(max(values) - min(values), 2)
    
    return rom
```

**예시:**
- 전문가 left_elbow: 최소 35°, 최대 175° → ROM = 140°
- 사용자 left_elbow: 최소 60°, 최대 150° → ROM = 90°
- Coverage = 90 / 140 ≈ 64.3%

### 4.3 커버리지 점수 계산

```python
def score_rom_coverage(user_rom: Dict[str, float], 
                       ref_rom: Dict[str, float]) -> Dict[str, Any]:
    """
    사용자 ROM / 레퍼런스 ROM 비율로 점수 산출.
    반환: {"score": 75.2, "joint_details": {...}}
    """
    coverages = []
    joint_details = {}
    
    for joint in user_rom:
        if joint not in ref_rom:
            continue
        
        r_rom = ref_rom[joint]
        u_rom = user_rom[joint]
        
        # 레퍼런스 ROM이 너무 작으면 (< 10°) 해당 관절은 "정적"으로 판단 → 제외
        if r_rom < 10.0:
            joint_details[joint] = {
                "user_rom": u_rom,
                "ref_rom": r_rom,
                "coverage": 100.0,  # 정적 관절은 만점
                "note": "static_joint"
            }
            continue
        
        # 커버리지 = min(user/ref, 1.0) × 100
        # 사용자가 더 크게 움직여도 100점 상한
        coverage_ratio = min(u_rom / r_rom, 1.0)
        coverage_pct = coverage_ratio * 100.0
        coverages.append(coverage_pct)
        
        joint_details[joint] = {
            "user_rom": round(u_rom, 2),
            "ref_rom": round(r_rom, 2),
            "coverage": round(coverage_pct, 2),
            "min_angle_user": "...",  # 옵션: 최대/최소 각도 기록
            "max_angle_user": "...",
        }
    
    # 전체 평균 (가동 관절만)
    final_score = round(sum(coverages) / len(coverages), 2) if coverages else 0.0
    
    return {
        "score": final_score,
        "joint_details": joint_details,
    }
```

### 4.4 경계 케이스

| 상황 | 처리 |
|------|------|
| 레퍼런스 ROM < 10° | "정적 관절" → 커버리지 100% (또는 제외) |
| 사용자 ROM > 레퍼런스 ROM | 상한 100% (과도한 동작은 보너스 없음) |
| 사용자 ROM = 0 (정지) | 0% → 점수 하락 |
| 관절 누락 | 해당 관절 제외, 나머지로 평균 |

---

## 5. ROM 점수 가중치 및 등급

### 5.1 총점 통합 (6개 함수)

`ARCHITECTURE.md` 및 `COMPARISON_STRATEGY.md` 기준:

| 채점 | 가중치 (예시) |
|------|--------------|
| Accuracy | 30% |
| ROM | 15% |
| Power | 20% |
| Rhythm | 15% |
| Isolation | 10% |
| Creativity | 10% |

**총점 계산:**
```python
total_score = (
    accuracy * 0.30 +
    rom * 0.15 +
    power * 0.20 +
    rhythm * 0.15 +
    isolation * 0.10 +
    creativity * 0.10
)
```

### 5.2 ROM 단독 등급

| 점수 | 등급 | 의미 |
|------|------|------|
| 90~100 | A+ | 전문가 ROM의 90% 이상 커버 |
| 80~89 | A | 대부분 관절을 충분히 사용 |
| 70~79 | B | 보통, 일부 관절 가동 범위 부족 |
| 60~69 | C | 동작이 작거나 소극적 |
| <60 | D | 관절 가동이 매우 제한적 |

---

## 6. 구현 계획

### 6.1 파일 구조

```
backend/domain/domain1/
├── hub/services/scoring/
│   ├── accuracy_scorer.py     ← 기존
│   ├── alignment.py            ← 기존
│   ├── rom_scorer.py           ← 신규 (ROM 로직)
│   └── __init__.py             ← import 추가
├── comparison_service.py       ← score_rom() 호출 추가
└── models/transfer/
    └── compare_request.py      ← enable_rom 플래그 (옵션)
```

### 6.2 `rom_scorer.py` 함수 구조

```python
"""ROM (관절 가동 범위) 채점."""

from typing import Any, Dict, List

def compute_joint_rom(frames: List[Dict[str, Any]]) -> Dict[str, float]:
    """각 관절의 max-min 각도 범위."""
    ...

def score_rom(
    user_frames: List[Dict[str, Any]],
    ref_frames: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    사용자·전문가 ROM 비교 → 커버리지 점수.
    반환: {"score": 75.2, "breakdown": {...}}
    """
    user_rom = compute_joint_rom(user_frames)
    ref_rom = compute_joint_rom(ref_frames)
    
    return score_rom_coverage(user_rom, ref_rom)

def score_to_grade_rom(score: float) -> str:
    """ROM 점수 → 등급."""
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 70: return "B"
    if score >= 60: return "C"
    return "D"
```

### 6.3 `comparison_service.py` 통합

```python
from .scoring.rom_scorer import score_rom

def compute_comparison(..., enable_rom: bool = True, ...) -> Dict[str, Any]:
    ...
    accuracy = score_accuracy(aligned_pairs, ...)
    
    rom = None
    if enable_rom:
        rom = score_rom(user_frames, ref_frames)
    
    scores_block = {
        "accuracy": accuracy,
    }
    if rom is not None:
        scores_block["rom"] = rom
    
    # total_score 가중 평균 (Accuracy만 있으면 = accuracy, ROM도 있으면 가중)
    if rom is not None:
        total_score = accuracy["score"] * 0.67 + rom["score"] * 0.33  # 임시 비율
    else:
        total_score = accuracy["score"]
    
    return {
        ...,
        "scores": {
            **scores_block,
            "total_score": total_score,
        },
    }
```

### 6.4 구현 단계

| 단계 | 작업 | 소요 |
|------|------|------|
| 1 | `rom_scorer.py` 작성 (compute, score, grade) | ~1시간 |
| 2 | `comparison_service` 통합 + `enable_rom` 플래그 | ~30분 |
| 3 | 단위 테스트 (동일 영상 → 100점, 절반 ROM → ~50점) | ~1시간 |
| 4 | 실영상 검증 (사용자 vs 전문가) | ~1시간 |
| 5 | 문서 갱신 (`IMPLEMENTATION_STATUS`, `CURRENT_LOGIC`) | ~30분 |

**총 예상:** ~4시간 (순수 개발 기준)

---

## 7. 예상 응답 구조

### 7.1 `/video/compare` 응답 (ROM 포함)

```json
{
  "user_json": "user.json",
  "reference_json": "ref.json",
  "alignment": { ... },
  "scores": {
    "accuracy": {
      "score": 85.2,
      "breakdown": { ... }
    },
    "rom": {
      "score": 72.5,
      "joint_details": {
        "left_elbow": {
          "user_rom": 90.2,
          "ref_rom": 140.5,
          "coverage": 64.2
        },
        "right_knee": {
          "user_rom": 135.8,
          "ref_rom": 145.3,
          "coverage": 93.5
        },
        "left_shoulder": {
          "user_rom": 8.5,
          "ref_rom": 5.2,
          "coverage": 100.0,
          "note": "static_joint"
        }
      },
      "grade": "B"
    },
    "total_score": 81.3,
    "grade": "A"
  },
  "meta": {
    "enable_rom": true,
    ...
  }
}
```

### 7.2 프론트엔드 시각화 권장

- **레이더 차트:** Accuracy, ROM, Power, ... (6축)
- **관절별 막대 그래프:** `joint_details`의 `coverage` 값
- **피드백 문구:**
  - ROM 90% 이상: "동작의 크기가 훌륭합니다!"
  - ROM 60~80%: "팔꿈치·무릎을 더 크게 펼쳐 보세요."
  - ROM < 60%: "동작이 소극적입니다. 관절 가동 범위를 늘려보세요."

---

## 8. 주의 사항 및 한계

### 8.1 ROM만으로는 불완전

- **ROM이 크다 ≠ 춤을 잘 춤:**
  - 타이밍·리듬·정확도가 더 중요할 수 있음
  - ROM은 **표현력·유연성** 지표일 뿐
- **안무 특성:**
  - 느린 감성 춤: ROM 작아도 정상
  - 과격한 브레이킹: ROM 커야 정상
  - → **상대 평가로 안무별 보정**

### 8.2 MediaPipe 오차 영향

- Z축 추정이 부정확하면 `joint_angles`도 오차
- 측면 촬영 시 `shoulder`·`hip` 각도 왜곡 가능
- → **촬영 가이드 UI** (정면 촬영 권장)로 완화

### 8.3 프레임 정렬 의존

- `align_by_time` / `align_by_dtw` 품질에 영향받음
- 사용자가 중간에 멈추면 → 정지 구간 ROM = 0 → 점수 하락
- → `user_offset_sec`, `auto_detect_start` 활용 권장

### 8.4 좌우 비대칭

- `left_elbow`와 `right_elbow`를 별도 평가
- 안무가 한쪽 팔만 쓰면 → 반대쪽 ROM 작음 → 정상
- → 관절별 상세 제공, 평균 점수로 흡수

---

## 9. 테스트 시나리오

### 9.1 단위 테스트

```python
def test_compute_joint_rom():
    frames = [
        {"joint_angles": {"left_elbow": 30}},
        {"joint_angles": {"left_elbow": 180}},
        {"joint_angles": {"left_elbow": 90}},
    ]
    rom = compute_joint_rom(frames)
    assert rom["left_elbow"] == 150.0  # max-min

def test_score_rom_same_video():
    # 동일 영상 → 100점
    user = ref = [{"joint_angles": {"left_elbow": i*10}} for i in range(18)]
    result = score_rom(user, ref)
    assert result["score"] == 100.0

def test_score_rom_half_range():
    ref = [{"joint_angles": {"left_elbow": i*10}} for i in range(18)]  # 0~170
    user = [{"joint_angles": {"left_elbow": 50 + i*5}} for i in range(18)]  # 50~135
    result = score_rom(user, ref)
    # ROM_user = 85, ROM_ref = 170 → 50%
    assert 45 <= result["score"] <= 55
```

### 9.2 통합 테스트

1. 실영상 A(전문가) vs A(동일) → ROM ~100점
2. 실영상 A vs B(초급자, 동작 작음) → ROM ~60점
3. 실영상 A vs C(정면) vs C(측면) → ROM 오차 ±10점 이내

---

## 10. 향후 확장

### 10.1 절대 ROM 기준 추가

```python
ABSOLUTE_ROM_THRESHOLDS = {
    "left_elbow": 120.0,   # 팔꿈치 최소 120° 권장
    "right_knee": 100.0,
}

def check_absolute_rom(user_rom):
    warnings = []
    for joint, threshold in ABSOLUTE_ROM_THRESHOLDS.items():
        if user_rom.get(joint, 0) < threshold:
            warnings.append(f"{joint} 가동 범위 부족 ({user_rom[joint]:.1f}° < {threshold}°)")
    return warnings
```

### 10.2 프레임별 ROM 변화 추적

- 특정 구간(예: 킥 동작)에서만 ROM 계산
- 동작별 ROM 세그먼트 분석 (Phase 3+)

### 10.3 좌우 대칭성 점수

- `abs(ROM_left - ROM_right)` → 비대칭 페널티 (선택 지표)

---

## 11. 관련 문서

- [ARCHITECTURE.md](./ARCHITECTURE.md) — 6개 채점 함수 개요
- [CURRENT_LOGIC.md](./CURRENT_LOGIC.md) — 현재 구현 상태
- [COMPARISON_STRATEGY.md](./COMPARISON_STRATEGY.md) — 비교 API 전략
- [COMPARE_SOLUTION.md](./COMPARE_SOLUTION.md) — Phase 1·2 개선 완료
- [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) — 진행 체크리스트

---

## 12. 구현 체크리스트

- [x] `rom_scorer.py` 작성 (`compute_joint_rom`, `score_rom`, `score_to_grade_rom`)
- [x] `comparison_service.py`에 `score_rom()` 통합 (`enable_rom`, 가중 total_score)
- [x] `CompareRequest`에 `enable_rom` 플래그 (기본 `true`)
- [x] 단위 테스트 (동일 영상 100점, 절반 ROM ~50점)
- [ ] 실영상 검증
- [x] `IMPLEMENTATION_STATUS.md` Phase 2 업데이트
- [x] `/video/compare` 라우터 연동

---

**한 줄 요약:** ROM은 각 관절의 **최대-최소 각도 범위**를 계산하고 **전문가 대비 커버리지**로 점수화하며, `joint_angles` 시계열에서 추출하고 정적 관절 제외·상한 100% 처리로 안무 특성을 반영합니다.
