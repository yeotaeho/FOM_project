# 두 영상 비교·채점 구현 전략 (Comparison Strategy)

> **목적:** 전문가·사용자 영상 비교 → 6개 항목 채점 → 일치도·차이점 수치화  
> **대상:** Phase 2 (채점 모듈) 구현 가이드  
> **작성일:** 2026-05-20

---

## 1. 목표와 범위

### 1.1 MVP 목표

사용자가 업로드한 댄스 영상과 **전문가 레퍼런스 영상**을 비교하여:

1. **6개 항목 점수** 산출 (0~100)  
   - Accuracy, ROM, Power, Isolation, Rhythm, Creativity
2. **세부 분석 데이터** 제공  
   - 프레임별 각도 차이, 벡터 유사도, 동기화율 등
3. **비교 시각화 영상** (선택)  
   - 전문가·사용자 스켈레톤 나란히 오버레이

### 1.2 현재 상태

| 완료 | 미완료 |
|------|--------|
| ✅ 단일 영상 추출 (`/video/extract`) | ⏳ 두 영상 비교 API |
| ✅ `joint_angles`, `bone_vectors` 추출 | ⏳ 6개 채점 함수 |
| ✅ `normalized_landmarks` | ⏳ 전문가 영상 DB |
| ✅ 시각화 영상 생성 | ⏳ 프레임 정렬 (DTW 등) |

---

## 2. API 엔드포인트 설계

### 2.1 추천 방식 — `POST /video/compare` (두 파일 업로드)

**요청:**
```http
POST /video/compare
Content-Type: multipart/form-data

user_video: <file>          # 사용자 영상
reference_video: <file>      # 전문가 영상 (또는 reference_id)
options: {
  "enable_accuracy": true,   # Accuracy 채점 (기본 true)
  "enable_rom": true,        # ROM 채점
  "enable_power": false,     # Power는 단일 영상만 필요하므로 선택
  "alignment_method": "dtw"  # 프레임 정렬: "dtw" | "time" | "none"
}
```

**응답 스키마:**
```json
{
  "user_extraction": { "fps": 30.0, "frames": [...] },
  "reference_extraction": { "fps": 30.0, "frames": [...] },
  "comparison": {
    "alignment": {
      "method": "dtw",
      "aligned_pairs": [
        {"user_frame": 0, "ref_frame": 0},
        {"user_frame": 1, "ref_frame": 2},
        ...
      ]
    },
    "scores": {
      "accuracy": {
        "score": 85.0,
        "percentile": 20,
        "breakdown": {
          "joint_angles_similarity": 88.0,
          "bone_vectors_cosine": 82.0
        }
      },
      "rom": { "score": 75.0, "details": {...} },
      "total_score": 80.0,
      "grade": "B+"
    },
    "frame_diffs": [
      {
        "user_frame": 0,
        "ref_frame": 0,
        "joint_angle_diffs": {
          "left_elbow": 5.2,
          "right_knee": 12.8
        },
        "bone_vector_cosines": {
          "left_upper_arm": 0.95,
          "right_thigh": 0.88
        }
      }
    ]
  },
  "comparison_video": {
    "filename": "..._comparison.mp4",
    "url": "/video/data/..."
  }
}
```

### 2.2 구현 완료 — 저장 JSON 2개로 비교 (추출·비교 분리) ✅

**흐름:**
```
POST /video/extract (전문가) → video_json/{base}.json + video_data/{base}_annotated.mp4
POST /video/extract (사용자) → video_json/{base}.json + ...

POST /video/compare
  Body: { "user_json": "....json", "reference_json": "....json", "alignment_method": "time" }
  → comparison_service → Accuracy 점수 + frame_diffs
```

**저장 경로:**
| 종류 | 경로 |
|------|------|
| 추출 JSON | `domain1/video_data/video_json/{timestamp}_{uuid}.json` |
| 오버레이 MP4 | `domain1/video_data/{timestamp}_{uuid}_annotated.mp4` |

**응답 (`/extract`):**
- `extraction_id`: MP4·JSON 공통 접두사
- `extraction_json.filename`, `extraction_json.url` → `/video/json/{filename}`
- `annotated_video.url` → `/video/data/{filename}`

**구현 파일:**
- `hub/services/storage_paths.py` — 저장·로드·파일명 검증
- `hub/services/comparison_service.py` — 비교 오케스트레이션
- `hub/services/scoring/alignment.py` — `align_by_time`
- `hub/services/scoring/accuracy_scorer.py` — 각도·벡터 채점
- `routers/video.py` — `POST /compare`, `GET /json/{filename}`

### 2.3 대안 — 전문가 영상 DB 참조 (확장)

**요청:**
```http
POST /video/analyze
Content-Type: multipart/form-data

user_video: <file>
reference_id: "expert_hiphop_basic_001"  # DB에 저장된 전문가 영상 ID
```

**장점:**
- 사용자가 전문가 영상을 직접 올릴 필요 없음
- 사전 추출된 JSON 재사용 → 속도 빠름

**단점:**
- 전문가 영상 DB 구축 필요 (Phase 1.5)
- MVP는 **2.1 방식(두 파일 업로드)** 이 단순함

---

## 3. 프레임 정렬 (Alignment) 전략

### 3.1 문제

전문가와 사용자의 영상 길이·FPS·템포가 다를 수 있습니다.

| 케이스 | 예시 |
|--------|------|
| **길이** | 전문가 60초, 사용자 58초 |
| **FPS** | 전문가 30fps, 사용자 24fps |
| **템포** | 사용자가 중간에 멈칫하거나 빠르게 움직임 |

프레임을 단순히 `frame_index`로 1:1 매칭하면 오차가 큽니다.

### 3.2 정렬 알고리즘 옵션

#### 옵션 1: 시간 기반 정렬 (`time`)

**개념:** 각 프레임의 `time_sec`를 기준으로 가장 가까운 프레임 매칭.

**구현:**
```python
def align_by_time(user_frames, ref_frames):
    pairs = []
    for uf in user_frames:
        closest_rf = min(ref_frames, key=lambda rf: abs(rf['time_sec'] - uf['time_sec']))
        pairs.append({'user': uf['frame_index'], 'ref': closest_rf['frame_index']})
    return pairs
```

**장점:** 빠름 (O(n*m), m≈n)  
**단점:** 템포 차이(중간에 멈춤·빠른 구간)를 무시 → Rhythm·Accuracy 오차

#### 옵션 2: DTW (Dynamic Time Warping) 정렬 (`dtw`)

**개념:** 두 시퀀스의 **특징(feature) 거리**를 최소화하는 경로를 동적 계획법으로 찾음.

**특징 벡터 예:**
- `normalized_landmarks` 33개 × 3 = 99차원
- `joint_angles` 10개 (권장 — 차원 낮음)
- `bone_vectors` 11개 × 3 = 33차원

**구현 (의존성: `dtaidistance` 또는 `fastdtw`):**
```python
from dtaidistance import dtw

def align_by_dtw(user_frames, ref_frames):
    # 특징: joint_angles 10개 → 시퀀스 [frame × 10]
    user_seq = [list(f['joint_angles'].values()) for f in user_frames]
    ref_seq = [list(f['joint_angles'].values()) for f in ref_frames]
    
    path = dtw.warping_path(user_seq, ref_seq)  # [(u_idx, r_idx), ...]
    return [{'user': u, 'ref': r} for u, r in path]
```

**장점:** 템포 차이·멈춤 구간 흡수 → **Accuracy·Rhythm 정확도↑**  
**단점:** 느림 (O(n²)), 긴 영상(3분+)은 계산 부담

#### 옵션 3: 정렬 없음 (`none`)

**개념:** 같은 `frame_index`끼리 비교.

**적합:** 전문가·사용자가 **동일 템포·FPS**로 촬영된 경우 (통제 환경)  
**MVP:** 비현실적 → 옵션 1·2 병행 권장

### 3.3 MVP 권장

1. **기본:** `time` (구현 빠름, 웬만한 영상 OK)
2. **고급:** `dtw` (선택 파라미터, Accuracy 정밀도 필요 시)
3. **Phase 2:** `time`만 구현 후 Accuracy 오차 검증 → 필요시 DTW 추가

---

## 4. Accuracy 채점 알고리즘 (핵심)

### 4.1 원칙 (VIEWPOINT_INVARIANCE.md 기준)

| 사용 | 금지 |
|------|------|
| ✅ `joint_angles` | ❌ `landmarks` 좌표 직접 비교 |
| ✅ `bone_vectors` 코사인 유사도 | (시점 왜곡 큼) |
| △ `normalized_landmarks` DTW 거리 | (보조적) |

### 4.2 세부 알고리즘

#### Step 1: 프레임 정렬

위 3.2 선택 (`time` 또는 `dtw`).

#### Step 2: 관절 각도 유사도 (primary)

**수식:**
```
angle_diff[j] = |user.joint_angles[j] - ref.joint_angles[j]|  # 도(degree)
similarity[j] = max(0, 100 - angle_diff[j] / 180 * 100)       # 0~180° → 0~100
angle_score = mean(similarity over joints j)
```

**예:** 전문가 팔꿈치 120°, 사용자 135° → 차이 15° → 유사도 91.7

#### Step 3: 뼈 벡터 코사인 유사도 (secondary)

**수식:**
```
cosine[b] = dot(user.bone_vectors[b], ref.bone_vectors[b])  # 단위벡터 → -1~1
bone_score = mean((cosine[b] + 1) / 2 * 100 for b in bones)  # 0~100
```

**예:** `left_upper_arm` 코사인 0.95 → (0.95+1)/2*100 = 97.5

#### Step 4: 최종 Accuracy 점수

**가중 평균:**
```
Accuracy = 0.6 * angle_score + 0.4 * bone_score
```

- 각도(60%) 우선 (시점 강건성 최고)
- 벡터(40%) 보조 (방향 미세 차이 감지)

**프레임별 점수 → 영상 전체 평균:**
```
frame_scores = [compute_accuracy(u, r) for u, r in aligned_pairs]
final_accuracy = mean(frame_scores)
```

### 4.3 추가 지표 (응답에 포함)

- **프레임별 각도 차이 히트맵:** 어느 구간에서 차이가 컸는지
- **관절별 평균 차이:** 어떤 관절(팔꿈치·무릎 등)이 가장 달랐는지
- **DTW 비용(cost):** 정렬 난이도 → Rhythm 점수에 반영 가능

---

## 5. 나머지 5개 채점 함수 (간략)

| 함수 | 입력 | 알고리즘 개요 | 우선순위 |
|------|------|---------------|----------|
| **ROM** | 단일 영상 `joint_angles` | max - min 각도 범위 → 전문가 대비 커버리지 | 2순위 |
| **Power** | 단일 영상 `landmarks` + time | 속도 미분 → 가속도 피크 크기·빈도 | 3순위 |
| **Isolation** | 단일 영상 `bone_vectors` | 목표 관절 움직임 vs 비목표 관절 정적도 비율 | 4순위 |
| **Rhythm** | 비교 또는 BPM | DTW 비용 또는 동작 피크–비트 시간차 | 5순위 |
| **Creativity** | 비교 `normalized_landmarks` | DTW 거리 역수 (Accuracy와 반대) + 독창적 패턴 | 6순위 |

**MVP 범위:**
1. **Accuracy** 완전 구현 (4장 알고리즘)
2. **ROM** 단순 버전 (각 관절 max-min만)
3. 나머지는 **더미 점수 (70~80 고정)** 또는 Stub

---

## 6. 구현 단계 (Phased Approach)

### 6.1 Phase 2A — 비교 API 뼈대 (2~3일)

**목표:** `/video/compare` 동작 + Accuracy 점수 산출

**작업:**
1. `routers/video.py` — `POST /compare` 엔드포인트
   - 두 파일 업로드 → `extract_dance_data()` 각각 호출
   - `hub/services/comparison_service.py` 호출
2. `comparison_service.py` 신규
   - `align_frames(user, ref, method='time')` — 시간 기반 정렬
   - `score_accuracy(user, ref, aligned_pairs)` — 4.2 알고리즘
   - `compute_comparison(user, ref)` — 종합 응답 조립
3. 테스트 영상 2개로 Swagger 검증

**산출물:**
- JSON 응답: `scores.accuracy.score`, `frame_diffs[]`
- 에러 핸들링: 영상 길이 차이 10배 초과 시 422

### 6.2 Phase 2B — ROM·Power 추가 (1~2일)

**작업:**
1. `hub/services/scoring/rom_scorer.py`
   - 단일 영상 `joint_angles` → 각 관절 max-min
   - 전문가 대비 커버리지 비율
2. `hub/services/scoring/power_scorer.py`
   - `landmarks` 속도 미분 → 가속도 피크
3. `comparison_service.compute_comparison()` 확장
   - `scores.rom`, `scores.power` 추가

### 6.3 Phase 2C — 비교 시각화 영상 (선택, 2일)

**작업:**
1. `video_visualizer.py` 확장
   - `render_comparison_video(user_path, ref_path, aligned_pairs)`
   - 화면 좌우 분할: 왼쪽 전문가, 오른쪽 사용자
   - 중앙에 프레임별 Accuracy 점수·각도 차이 표시
2. `/compare` 응답에 `comparison_video.url` 추가

### 6.4 Phase 2D — DTW 정렬 + 나머지 함수 (Phase 3 전)

**작업:**
1. `requirements.txt`에 `dtaidistance` 또는 `fastdtw` 추가
2. `align_frames(method='dtw')` 구현
3. Isolation, Rhythm, Creativity Stub → 실제 로직 (우선순위 낮음)

---

## 7. 디렉터리 구조 (완성 후)

```
backend/domain/domain1/hub/services/
├── extraction_service.py       ← 기존
├── pose_geometry.py            ← 기존
├── video_visualizer.py         ← 기존 + render_comparison_video()
├── comparison_service.py       ← 신규 (align + score_accuracy)
└── scoring/
    ├── __init__.py
    ├── accuracy_scorer.py      ← 4.2 알고리즘 분리
    ├── rom_scorer.py
    ├── power_scorer.py
    ├── isolation_scorer.py
    ├── rhythm_scorer.py
    └── creativity_scorer.py
```

---

## 8. API 사용 예시

### 8.1 단일 영상 추출

```bash
curl -X POST http://localhost:8000/video/extract \
  -F "file=@user_dance.mp4"
```

**응답:** `landmarks`, `joint_angles`, `bone_vectors` JSON + annotated 영상

### 8.2 두 영상 비교

```bash
curl -X POST http://localhost:8000/video/compare \
  -F "user_video=@user_dance.mp4" \
  -F "reference_video=@expert_hiphop.mp4" \
  -F "options={\"alignment_method\":\"time\"}"
```

**응답:** 위 2.1 스키마 (Accuracy·ROM 점수, frame_diffs, comparison_video)

### 8.3 저장 JSON으로 비교 (구현됨)

```bash
# 1) 전문가·사용자 각각 추출 (JSON 파일명 확인)
curl -X POST http://localhost:8000/video/extract -F "file=@expert.mp4"
curl -X POST http://localhost:8000/video/extract -F "file=@user.mp4"

# 2) 비교
curl -X POST http://localhost:8000/video/compare \
  -H "Content-Type: application/json" \
  -d "{\"user_json\": \"20260520_xxx_user.json\", \"reference_json\": \"20260520_yyy_expert.json\"}"
```

### 8.4 전문가 DB 참조 (확장)

```bash
curl -X POST http://localhost:8000/video/analyze \
  -F "user_video=@user_dance.mp4" \
  -F "reference_id=expert_hiphop_basic_001"
```

---

## 9. 테스트 전략

### 9.1 단위 테스트

| 함수 | 테스트 케이스 |
|------|---------------|
| `align_by_time()` | 같은 FPS → 1:1, 다른 FPS → 보간 |
| `score_accuracy()` | 동일 영상 → 100점, 90° 차이 → 50점 |
| `compute_joint_angle_diff()` | 각도 15° 차이 → 유사도 91.7 |

### 9.2 통합 테스트

1. **동일 영상 비교:** 사용자 = 전문가 → Accuracy **95점 이상** (오차 허용)
2. **반대 방향 영상:** 전문가 정면, 사용자 뒷모습 → Accuracy **30점 이하**
3. **템포 2배 차이:** DTW vs time 정렬 → DTW가 점수 **10점 이상 높음**

### 9.3 성능 벤치마크

- 1분 영상(30fps) × 2개 비교 → **30초 이내** (DTW 미포함)
- DTW 포함 → **2분 이내** (fastdtw 최적화 전)

---

## 10. 리스크 & 대응

| 리스크 | 확률 | 영향 | 대응 |
|--------|------|------|------|
| DTW 계산 시간 초과 | 높음 | 중 | MVP는 `time` 정렬만, DTW는 옵션 |
| 전문가 영상 부족 | 중 | 높 | 팀원 직접 촬영 or YouTube 크롤링 (저작권 주의) |
| Z축 노이즈 → 각도 오차 | 중 | 중 | 각도 임계값 완화 (5° 이하 차이는 100점) |
| 긴 영상(5분+) 메모리 | 낮 | 중 | 프레임 샘플링 (30fps→15fps) |

---

## 11. 확장 로드맵

### Phase 3 이후

1. **전문가 영상 DB**  
   - PostgreSQL: `reference_videos(id, title, genre, fps, frames_json_path)`
   - S3 저장소 연동
2. **실시간 비교 (WebSocket)**  
   - 사용자 촬영 중 실시간 Accuracy 표시
3. **멀티 레퍼런스**  
   - 여러 전문가 평균과 비교 → "상위 20%" 같은 백분위
4. **LLM 피드백 통합**  
   - Accuracy 80점 + 각도 차이 → "팔꿈치를 15° 더 펴세요"

---

## 12. 의사결정 포인트 (팀 합의 필요)

| 항목 | 옵션 A | 옵션 B | 추천 |
|------|--------|--------|------|
| **정렬 알고리즘** | `time` (빠름) | `dtw` (정확) | A (MVP), B (Phase 2B) |
| **비교 시각화** | 좌우 분할 영상 | JSON만 | A (선택 기능) |
| **전문가 영상** | 매번 업로드 | DB 참조 | A (MVP), B (확장) |
| **6개 함수 범위** | Accuracy만 | Accuracy + ROM + Power | B (Phase 2A+B) |

---

## 13. 구현 체크리스트

### Phase 2A (Accuracy + 비교 API)

- [x] `POST /video/compare` 라우터 (`routers/video.py`)
- [x] `POST /extract` → `video_json/` JSON 저장
- [x] `GET /video/json/{filename}` JSON 조회
- [x] `comparison_service.py` — `align_by_time()`, `score_accuracy()`
- [x] `scoring/accuracy_scorer.py` — 4.2 알고리즘
- [ ] 테스트: 동일 영상 extract 2회 → compare 95점 이상 (실영상)
- [x] Swagger 문서 (`/docs`)

### Phase 2B (ROM + Power)

- [ ] `scoring/rom_scorer.py` — 각도 범위 계산
- [ ] `scoring/power_scorer.py` — 가속도 피크
- [ ] `comparison_service` 통합
- [ ] 테스트: ROM 점수 0~100 범위 검증

### Phase 2C (비교 시각화)

- [ ] `render_comparison_video()` — 좌우 분할 + 점수 오버레이
- [ ] `/compare` 응답 확장
- [ ] 테스트: 출력 MP4 재생 확인

---

## 14. 관련 문서

- [CURRENT_LOGIC.md](./CURRENT_LOGIC.md) — 현재 비교 로직 동작·보정·한계 (시작점·체형·시점·시간)
- [VIEWPOINT_INVARIANCE.md](./VIEWPOINT_INVARIANCE.md) — `landmarks` 한계, `joint_angles` 우선 원칙
- [ARCHITECTURE.md](./ARCHITECTURE.md) — 6개 채점 함수 설계 개요
- [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) — Phase별 진행 상황
- [PROJECT_CONTEXT.md](./PROJECT_CONTEXT.md) — 사용자 여정 (업로드→분석→피드백)

---

**한 줄 요약:** `/video/compare` API로 두 영상(전문가·사용자)을 비교하고, **시간 정렬** 후 `joint_angles` 차이와 `bone_vectors` 코사인으로 **Accuracy 점수**를 계산하며, ROM·Power 등 5개 함수는 단계적 추가, DTW와 비교 시각화는 선택 기능.
