# /compare 엔드포인트 — 문제 분석 & 해결 방안

> **작성일:** 2026-05-20  
> **대상 파일:** `backend/routers/video.py` → `compare_videos()`  
> **핵심 참조:** `comparison_service.py`, `alignment.py`, `accuracy_scorer.py`

---

## 1. 현재 파이프라인 요약

```
POST /video/compare
  body: { user_json, reference_json, alignment_method="time" }
       ↓
  load_extraction_json(user_json)       ← video_json/{}.json 전체 로드
  load_extraction_json(reference_json)  ← 마찬가지
       ↓
  align_by_time(user_frames, ref_frames)
    → 각 user 프레임마다 min(ref_frames, key=|t_user - t_ref|)  [O(n×m)]
       ↓
  score_accuracy(aligned_pairs)
    → 프레임별: 0.6 × angle_similarity + 0.4 × bone_cosine
    → 전체 평균 → grade
       ↓
  JSONResponse { alignment, scores, meta }
    frame_diffs: [전 프레임 × 관절별 상세] ← 수 MB 가능
```

---

## 2. 식별된 문제

### 2-A. [성능] align_by_time O(n×m) — **즉시 수정 필요**

**위치:** `alignment.py` L17–28

```python
# 현재 코드: n_user × n_ref 전부 순회
for uf in user_frames:
    best_rf = min(ref_frames, key=lambda rf: abs(rf["time_sec"] - uf["time_sec"]))
```

**문제:**  
- 523 프레임(실 측정치) → 523 × 523 ≈ 27만 비교  
- 1분 30fps(1800 프레임) → 1800 × 1800 = 324만 비교  
- ref_frames는 **time_sec 순 정렬**이 보장되므로 이분 탐색으로 대체 가능

**해결:** `bisect` 사용 → O(n log m)

```python
# alignment.py 수정안
import bisect

def align_by_time(user_frames, ref_frames):
    if not user_frames or not ref_frames:
        return []

    # ref_frames는 frame_index 순 = time_sec 순 보장
    ref_times = [float(rf.get("time_sec", 0.0)) for rf in ref_frames]
    pairs = []

    for uf in user_frames:
        u_t = float(uf.get("time_sec", 0.0))
        # 삽입 위치
        idx = bisect.bisect_left(ref_times, u_t)
        # 양쪽 후보 중 더 가까운 것 선택
        if idx == 0:
            best_idx = 0
        elif idx >= len(ref_times):
            best_idx = len(ref_times) - 1
        else:
            left_diff = u_t - ref_times[idx - 1]
            right_diff = ref_times[idx] - u_t
            best_idx = idx - 1 if left_diff <= right_diff else idx

        pairs.append({
            "user_frame": int(uf["frame_index"]),
            "ref_frame": int(ref_frames[best_idx]["frame_index"]),
            "user": uf,
            "ref": ref_frames[best_idx],
        })
    return pairs
```

---

### 2-B. [정확도] time_sec=0 기준 가정 — **핵심 품질 문제**

**위치:** `alignment.py` — 암묵적 가정

**문제:**
```
user video:  [무대 준비 3초] → [춤 시작] ...
ref video:   [춤 시작 즉시] ...

현재:  user.time_sec=0  ↔  ref.time_sec=0  → 사용자의 정지 동작이 레퍼런스 춤 동작과 매칭
```

- 전문가 영상은 편집본(춤만) / 사용자 영상은 촬영 시작부터 → **오프셋 차이 필연적**
- 결과: 전체 점수가 실제 유사도와 무관하게 낮게 나옴

**해결 방안 (2단계):**

#### 단기: 수동 offset 파라미터 추가

`CompareRequest`에 `user_offset_sec` / `ref_offset_sec` 추가:

```python
# models/transfer/compare_request.py
class CompareRequest(BaseModel):
    user_json: str
    reference_json: str
    alignment_method: str = Field(default="time")
    user_offset_sec: float = Field(default=0.0, ge=0.0,
        description="사용자 영상에서 춤이 시작되는 시각(초)")
    ref_offset_sec: float = Field(default=0.0, ge=0.0,
        description="레퍼런스 영상에서 춤이 시작되는 시각(초)")
```

`align_by_time`에서 오프셋 적용:

```python
def align_by_time(user_frames, ref_frames,
                  user_offset=0.0, ref_offset=0.0):
    # 유효 시작점 이후 프레임만 사용
    user_active = [f for f in user_frames
                   if float(f.get("time_sec", 0)) >= user_offset]
    ref_active  = [f for f in ref_frames
                   if float(f.get("time_sec", 0)) >= ref_offset]

    # time_sec를 오프셋 기준으로 재계산 (상대 시간으로 변환)
    u_offset_fn = lambda t: t - user_offset
    r_offset_fn = lambda t: t - ref_offset
    ...
```

#### 중기: 자동 시작점 감지 (Motion Threshold)

```python
def detect_dance_start(frames, motion_threshold=0.01):
    """
    연속 2프레임 normalized_landmarks 변화량이 threshold 초과 시점을 반환.
    사용자가 춤을 시작한 프레임 = 움직임이 감지된 첫 프레임.
    """
    prev = None
    for frame in frames:
        lms = frame.get("normalized_landmarks", {})
        if prev is None:
            prev = lms
            continue
        # 어깨·골반 4개 관절의 평균 변화량
        key_joints = ["left_shoulder", "right_shoulder", "left_hip", "right_hip"]
        diffs = []
        for j in key_joints:
            if j in lms and j in prev:
                dx = lms[j]["x"] - prev[j]["x"]
                dy = lms[j]["y"] - prev[j]["y"]
                diffs.append((dx**2 + dy**2) ** 0.5)
        if diffs and sum(diffs) / len(diffs) > motion_threshold:
            return float(frame["time_sec"])
        prev = lms
    return 0.0
```

---

### 2-C. [응답 크기] frame_diffs 무제한 반환 — **API 안정성 문제**

**위치:** `comparison_service.py` L51–54, `accuracy_scorer.py` L98–104

**문제:**
- 523 프레임 → frame_diffs 523개 (관절 10개 × 뼈 11개 per 프레임)
- 1800 프레임 → 응답 수 MB → 프론트 파싱 지연, 모바일 메모리 부족

**해결:** 응답 레벨 분리 (`summary` vs `full`)

```python
# models/transfer/compare_request.py 추가
detail_level: Literal["summary", "full"] = Field(
    default="summary",
    description="summary=집계만, full=프레임별 상세 포함"
)
```

```python
# accuracy_scorer.py 수정
def score_accuracy(aligned_pairs, detail_level="summary"):
    ...
    result = {
        "score": round(final, 2),
        "breakdown": { ... },
    }
    if detail_level == "full":
        result["frame_diffs"] = frame_diffs  # 전 프레임 상세
    else:
        # 최하위 5% 프레임만 반환 (개선 우선순위 제시용)
        worst = sorted(frame_diffs, key=lambda x: x["frame_score"])[:10]
        result["worst_frames"] = worst
    return result
```

---

### 2-D. [점수 왜곡] 동일 ref 프레임 중복 매칭

**문제:**  
사용자 영상이 레퍼런스보다 느리면 여러 user_frame이 같은 ref_frame에 매칭됨.

```
user: [0, 0.03, 0.07, 0.10, 0.13, ...]  (30fps)
ref:  [0, 0.10, 0.20, ...]               (10fps로 느린 레퍼런스)

매칭: u0→r0, u1→r0, u2→r0, u3→r0, u4→r1 ...
```

같은 포즈가 반복 채점되어 특정 동작이 점수를 지배할 수 있음.

**해결:**

```python
# alignment.py에 중복 감지 경고 추가
from collections import Counter

def align_by_time(user_frames, ref_frames, ...):
    ...pairs 생성...
    
    # 중복 ref 프레임 비율 계산
    ref_counts = Counter(p["ref_frame"] for p in pairs)
    duplicate_ratio = sum(1 for c in ref_counts.values() if c > 1) / max(len(ref_counts), 1)
    
    return pairs, {"duplicate_ratio": round(duplicate_ratio, 3)}
```

`comparison_service.py`에서 `alignment.meta.duplicate_ratio > 0.3` 이면 응답에 경고 포함:

```json
"alignment": {
    "method": "time",
    "pair_count": 523,
    "duplicate_ratio": 0.42,
    "warning": "레퍼런스 프레임이 중복 매칭됨 (42%). DTW 정렬을 권장합니다."
}
```

---

### 2-E. [확장성] DTW 미구현 — alignment_method="dtw" 지원 불가

**현재 상태:**  
`SUPPORTED_ALIGNMENT = frozenset({"time"})` — "dtw" 입력 시 422 오류

**MVP 범위 내 구현 방안:**

`fastdtw` 라이브러리 사용 (O(n) 근사 DTW):

```python
# alignment.py 추가
from fastdtw import fastdtw
from scipy.spatial.distance import euclidean
import numpy as np

def align_by_dtw(user_frames, ref_frames):
    """
    joint_angles 벡터 시퀀스를 DTW로 정렬.
    템포 차이, 시작 오프셋에 강건.
    """
    ANGLE_KEYS = ["left_elbow", "right_elbow", "left_knee", "right_knee",
                  "left_shoulder", "right_shoulder", "left_hip", "right_hip",
                  "left_ankle", "right_ankle"]

    def frame_to_vec(frame):
        angles = frame.get("joint_angles") or {}
        return np.array([float(angles.get(k, 0.0)) for k in ANGLE_KEYS])

    user_seq = [frame_to_vec(f) for f in user_frames]
    ref_seq  = [frame_to_vec(f) for f in ref_frames]

    _, path = fastdtw(user_seq, ref_seq, dist=euclidean)

    pairs = []
    seen_user = set()
    for u_idx, r_idx in path:
        if u_idx in seen_user:
            continue  # 각 user 프레임 1회만
        seen_user.add(u_idx)
        pairs.append({
            "user_frame": int(user_frames[u_idx]["frame_index"]),
            "ref_frame":  int(ref_frames[r_idx]["frame_index"]),
            "user": user_frames[u_idx],
            "ref":  ref_frames[r_idx],
        })
    return pairs
```

`comparison_service.py`에서 분기:

```python
SUPPORTED_ALIGNMENT = frozenset({"time", "dtw"})

if alignment_method == "dtw":
    aligned_pairs = align_by_dtw(user_frames, ref_frames)
else:
    aligned_pairs = align_by_time(user_frames, ref_frames, ...)
```

**성능 고려:**
| 방법 | 1800 프레임 기준 | 비고 |
|------|-----------------|------|
| `time` (bisect) | ~0.01초 | 수정 후 |
| `fastdtw` | ~0.5~2초 | O(n) 근사 |
| 순수 DTW | ~60~180초 | O(n²) — 사용 금지 |

`fastdtw`는 `pip install fastdtw`로 설치.

---

### 2-F. [점수 품질] 각도 유사도 선형 함수

**현재:**
```python
similarity = 100 - (diff / 180 * 100)  # 선형
```

**문제:**  
- 댄스에서 5도 오차 → 97.2점 (너무 관대)  
- 사용자가 완전히 다른 동작을 해도 90도 오차 기준 50점

**개선 방안 (비선형 감점):**

```python
def _angle_similarity(user_deg: float, ref_deg: float) -> float:
    diff = abs(float(user_deg) - float(ref_deg))
    # 구간별 감점: 댄스 맥락에서 10도 이상 오차는 명확한 실수
    if diff <= 10:
        return 100.0 - diff * 0.5        # 10도 → 95점 (관대)
    elif diff <= 30:
        return 95.0 - (diff - 10) * 1.5  # 30도 → 65점 (중간)
    elif diff <= 60:
        return 65.0 - (diff - 30) * 1.5  # 60도 → 20점 (엄격)
    else:
        return max(0.0, 20.0 - (diff - 60) * 0.33)  # 60도 이상 → 0점 수렴
```

**전환 방식:** `scoring_mode` 파라미터로 `"linear"` / `"dance"` 선택 가능하게 하거나, MVP에서는 단순히 상수 교체.

---

### 2-G. [메모리] 대용량 JSON 전체 로드

**현재:**
```python
user_data = load_extraction_json(user_json_filename)  # 수십 MB 메모리 점유
```

**실 측정:** `20260520_021629_59bd1ba6.json` — 523 프레임, 처리 시 수십 MB 메모리 사용.  
1800 프레임이면 ~100 MB 이상 예상.

**단기 해결:**  
비교에 필요한 필드만 추출 (landmarks 제외, joint_angles + bone_vectors + time_sec만):

```python
def load_comparison_fields(filename: str) -> dict:
    """비교에 필요한 필드만 추출해 메모리 절약."""
    data = load_extraction_json(filename)
    light_frames = [
        {
            "frame_index": f["frame_index"],
            "time_sec": f["time_sec"],
            "joint_angles": f.get("joint_angles"),
            "bone_vectors": f.get("bone_vectors"),
        }
        for f in data.get("frames", [])
    ]
    return {
        "fps": data.get("fps"),
        "total_frames": data.get("total_frames"),
        "frames": light_frames,
    }
```

비교 단계에서 `landmarks`와 `normalized_landmarks` (각각 33관절 × 4값)를 제외하면 메모리 사용량 약 **70% 절감**.

---

## 3. 통합 수정 계획

### Phase 1 — 즉시 (당일) ✅

| 항목 | 파일 | 변경 내용 |
|------|------|----------|
| bisect 정렬 | `alignment.py` | O(n×m) → O(n log m) |
| 경량 JSON 로드 | `storage_paths.py`, `comparison_service.py` | `load_comparison_fields()` |
| frame_diffs 제한 | `accuracy_scorer.py` | `detail_level` 기본 summary, `worst_frames` |
| 중복 매칭 경고 | `alignment.py` + `comparison_service.py` | `duplicate_ratio` + `meta.warnings` |

### Phase 2 — 단기 (2~3일) ✅

| 항목 | 파일 | 변경 내용 |
|------|------|----------|
| offset 파라미터 | `compare_request.py`, `alignment.py` | `user_offset_sec`, `ref_offset_sec` |
| DTW 정렬 | `alignment.py`, `comparison_service.py` | `fastdtw` + `alignment_method=dtw` |
| 비선형 각도 유사도 | `accuracy_scorer.py` | `scoring_mode=dance` (기본) |
| detail_level 파라미터 | `compare_request.py` | `summary`/`full` |
| 자동 시작점 | `alignment.py` | `auto_detect_start` → `detect_dance_start()` |

### Phase 3 — 중기 (1주일)

| 항목 | 변경 내용 |
|------|----------|
| 자동 시작점 감지 | `detect_dance_start()` — motion threshold 기반 |
| 6개 채점 함수 통합 | `comparison_service.py`의 `total_score` 가중 평균 확장 |
| 스트리밍 JSON | `ijson` 라이브러리로 대용량 파일 스트리밍 파싱 |

---

## 4. 수정 후 예상 응답 구조

```json
{
  "user_json": "20260520_abc.json",
  "reference_json": "20260520_def.json",
  "alignment": {
    "method": "dtw",
    "pair_count": 480,
    "duplicate_ratio": 0.05,
    "user_offset_sec": 2.0,
    "ref_offset_sec": 0.0
  },
  "scores": {
    "accuracy": {
      "score": 82.4,
      "breakdown": {
        "joint_angles_similarity": 85.1,
        "bone_vectors_cosine": 78.2
      },
      "worst_frames": [
        {
          "user_frame": 120,
          "ref_frame": 118,
          "frame_score": 54.3,
          "joint_angle_diffs": {"left_knee": 42.1, "right_elbow": 35.8},
          "bone_vector_cosines": {"left_thigh": 0.61}
        }
      ]
    },
    "total_score": 82.4,
    "grade": "A"
  },
  "meta": {
    "user_fps": 59.94,
    "reference_fps": 30.0,
    "warnings": []
  }
}
```

---

## 5. 즉시 적용 가능한 최소 패치

우선순위 기준, **단 3개 파일 수정**으로 가장 큰 효과:

```
1. alignment.py      — bisect 교체 (성능)
2. accuracy_scorer.py — detail_level 기본 summary (응답 크기)
3. compare_request.py — user_offset_sec/ref_offset_sec 추가 (정확도)
```

나머지(DTW, 자동 감지, 비선형 점수)는 Phase 2에서 순차 적용.

---

## 6. 관련 문서

- [CURRENT_LOGIC.md](./CURRENT_LOGIC.md) — 현 구현 상태 전체 명세
- [VIEWPOINT_INVARIANCE.md](./VIEWPOINT_INVARIANCE.md) — 시점 문제 대응 전략
- [COMPARISON_STRATEGY.md](./COMPARISON_STRATEGY.md) — 알고리즘 설계 원칙
- [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) — Phase별 진행 체크리스트
