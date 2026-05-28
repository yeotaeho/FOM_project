# 시스템 아키텍처 (Architecture)

> **폼미쳤다 (FOM)** - AI 스트릿 댄스 분석 플랫폼  
> **작성일:** 2026-05-20

---

## 1. 전체 시스템 구조

### 1.1 High-Level Overview

```
┌─────────────┐
│   Client    │  (Web Browser / Mobile App)
│  (React)    │
└──────┬──────┘
       │ HTTPS
       ↓
┌──────────────────────────────────────────────┐
│            FastAPI Backend                    │
│  ┌────────────────────────────────────────┐  │
│  │  main.py (Entry Point)                 │  │
│  │  - CORS Middleware                     │  │
│  │  - Router Registration                 │  │
│  └────────────┬───────────────────────────┘  │
│               ↓                               │
│  ┌────────────────────────────────────────┐  │
│  │  routers/video.py                      │  │
│  │  - POST /video/extract                 │  │
│  │  - File Validation (size, extension)  │  │
│  │  - Temp File Management                │  │
│  └────────────┬───────────────────────────┘  │
│               ↓                               │
│  ┌────────────────────────────────────────┐  │
│  │  domain/domain1/ (Hub-Spoke)          │  │
│  │  ┌──────────────────────────────────┐ │  │
│  │  │  hub/services/                   │ │  │
│  │  │  - extraction_service.py         │ │  │
│  │  │    → extract_dance_data()        │ │  │
│  │  │  - scoring_service.py (예정)     │ │  │
│  │  └──────────┬───────────────────────┘ │  │
│  │             ↓                          │  │
│  │  ┌──────────────────────────────────┐ │  │
│  │  │  MediaPipe Pose                  │ │  │
│  │  │  - 3D Landmark Extraction        │ │  │
│  │  │  - 33 Keypoints (x,y,z,vis)      │ │  │
│  │  └──────────┬───────────────────────┘ │  │
│  │             ↓                          │  │
│  │  ┌──────────────────────────────────┐ │  │
│  │  │  Data Processing Pipeline        │ │  │
│  │  │  - Interpolation (pandas)        │ │  │
│  │  │  - Smoothing (rolling mean)      │ │  │
│  │  │  - Normalization (Mid-Hip, Torso)│ │  │
│  │  └──────────┬───────────────────────┘ │  │
│  │             ↓                          │  │
│  │  [Standard JSON Output]               │  │
│  │             ↓                          │  │
│  │  ┌──────────────────────────────────┐ │  │
│  │  │  Scoring Functions (Phase 2)     │ │  │
│  │  │  - score_rom()                   │ │  │
│  │  │  - score_power()                 │ │  │
│  │  │  - score_isolation()             │ │  │
│  │  │  - score_rhythm()                │ │  │
│  │  │  - score_creativity()            │ │  │
│  │  │  - score_accuracy()              │ │  │
│  │  └──────────┬───────────────────────┘ │  │
│  │             ↓                          │  │
│  │  ┌──────────────────────────────────┐ │  │
│  │  │  spokes/agents/                  │ │  │
│  │  │  - feedback_agent.py (Phase 3)   │ │  │
│  │  │    → generate_feedback()         │ │  │
│  │  │    → call_llm(scores)            │ │  │
│  │  └──────────────────────────────────┘ │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
       │
       ↓ (JSON Response)
┌─────────────┐
│   Client    │
│  Visualize  │
│  - Scores   │
│  - Feedback │
│  - Charts   │
└─────────────┘
```

---

## 2. 데이터 플로우

### 2.1 영상 처리 파이프라인

```
[1] 사용자 업로드 (MP4/MOV)
     ↓
[2] FastAPI Router: 검증 + 임시 저장
     - 확장자 체크 (.mp4, .mov, .avi, .mkv, .webm)
     - 크기 제한 (500MB)
     - tempfile.NamedTemporaryFile(suffix=ext)
     ↓
[3] extraction_service.extract_dance_data(tmp_path)
     ├─ Step 1: OpenCV로 fps, total_frames 추출
     ├─ Step 2: MediaPipe Pose 루프
     │   ├─ 각 프레임 → RGB 변환
     │   ├─ pose.process(rgb) → 33 landmarks
     │   └─ 미검출 → NaN 행 삽입
     ├─ Step 3: 데이터 정제
     │   ├─ pandas DataFrame 생성
     │   ├─ interpolate(method='linear')
     │   ├─ ffill() + bfill()
     │   └─ rolling(window=3).mean()
     └─ Step 4: 정규화 (프레임별)
         ├─ Mid-Hip 계산 → Translation
         ├─ Torso Length 계산 → Scaling
         └─ normalized_landmarks 생성
     ↓
[4] 표준 JSON 반환
     {
       "fps": 30.0,
       "total_frames": N,
       "frames": [
         {
           "frame_index": i,
           "time_sec": i/fps,
           "landmarks": {...},         ← 원본 (x,y,z,vis)
           "normalized_landmarks": {...} ← 정규화 (x,y,z)
         }
       ]
     }
     ↓
[5] scoring_service.score_all(json_data) (Phase 2)
     ├─ score_rom() → 85.0
     ├─ score_power() → 70.5
     ├─ score_isolation() → 90.2
     ├─ score_rhythm() → 68.3
     ├─ score_creativity() → 75.0
     └─ score_accuracy() → 80.1
     ↓
[6] feedback_agent.generate_feedback(scores) (Phase 3)
     ├─ 프롬프트 빌드
     ├─ LLM API 호출 (GPT-4/Claude)
     └─ JSON 파싱
         {
           "summary": "...",
           "improvements": {...},
           "career_guide": "...",
           "motivation": "..."
         }
     ↓
[7] 최종 응답
     {
       "extraction": {...},  ← Step 4
       "scores": {...},      ← Step 5
       "feedback": {...}     ← Step 6
     }
     ↓
[8] Frontend 시각화
     - 레이더 차트 (6개 점수)
     - 피드백 텍스트
     - 스켈레톤 오버레이 (선택)
```

---

## 3. 백엔드 아키텍처

### 3.1 디렉터리 구조

```
backend/
├── main.py                    ← FastAPI 앱 진입점
├── requirements.txt           ← Python 의존성
├── routers/
│   └── video.py              ← /video/extract 엔드포인트
├── domain/
│   └── domain1/              ← 스트릿 댄스 도메인 (Hub-Spoke)
│       ├── __init__.py
│       ├── hub/              ← 공통 코어 로직
│       │   ├── services/
│       │   │   ├── extraction_service.py  ← 비디오 → JSON 파이프라인
│       │   │   └── scoring_service.py     ← 6개 채점 함수 통합 (예정)
│       │   ├── repositories/
│       │   │   └── video_repository.py    ← DB 접근 (예정)
│       │   └── mcp/
│       │       └── __init__.py
│       ├── spokes/           ← 확장 기능
│       │   ├── agents/
│       │   │   └── feedback_agent.py      ← LLM 피드백 (예정)
│       │   └── infra/
│       │       └── s3_uploader.py         ← 파일 저장소 (예정)
│       ├── models/           ← Pydantic 스키마
│       │   ├── bases/
│       │   │   └── landmark.py            ← Landmark, NormalizedLandmark
│       │   └── transfer/
│       │       └── video_data.py          ← FrameData, VideoExtractionResult
│       └── docs/
│           ├── PROJECT_CONTEXT.md         ← 프로젝트 기획
│           ├── IMPLEMENTATION_STATUS.md   ← 구현 현황
│           └── ARCHITECTURE.md            ← 이 문서
└── tests/                    ← 테스트 코드 (예정)
    ├── test_extraction.py
    └── test_scoring.py
```

### 3.2 Hub-Spoke 패턴

**Hub (중앙 집중):**
- 공통 비즈니스 로직
- 비디오 처리, 채점 엔진
- 도메인 모델

**Spokes (확장 포인트):**
- 외부 연동 (LLM, S3, DB)
- 에이전트 (피드백, 추천)
- 인프라 레이어

**장점:**
- 팀원 간 병렬 개발 가능
- 새 기능 추가 시 Hub 수정 불필요
- 테스트 격리 용이

---

## 4. API 명세

### 4.1 현재 구현된 엔드포인트

#### `POST /video/extract`
**요청:**
```http
POST /video/extract
Content-Type: multipart/form-data

file: <binary video file>
```

**응답 (성공 200):**
```json
{
  "fps": 30.0,
  "total_frames": 120,
  "frames": [
    {
      "frame_index": 0,
      "time_sec": 0.0,
      "landmarks": {
        "nose": {"x": 0.5, "y": 0.3, "z": -0.1, "visibility": 0.99},
        "left_shoulder": {...},
        ...
      },
      "normalized_landmarks": {
        "nose": {"x": 0.2, "y": 0.8, "z": -0.05},
        "left_shoulder": {...},
        ...
      }
    },
    ...
  ]
}
```

**에러 응답:**
| 코드 | 상황 | 메시지 예시 |
|------|------|-------------|
| 415 | 지원하지 않는 확장자 | `"지원하지 않는 형식입니다. 허용: {'.mp4', '.mov', ...}"` |
| 413 | 파일 크기 초과 | `"파일 크기가 500MB를 초과합니다."` |
| 422 | 영상 열기 실패 | `"영상을 열 수 없습니다: /tmp/xyz.mp4"` |
| 500 | 내부 오류 | `"처리 중 오류: ..."` |

#### `GET /health`
**응답:**
```json
{"status": "ok"}
```

### 4.2 예정된 엔드포인트 (Phase 2~3)

#### `POST /video/analyze` (통합 분석)
**요청:**
```http
POST /video/analyze
Content-Type: multipart/form-data

file: <video>
reference_id: <전문가 영상 ID>  (선택)
```

**응답:**
```json
{
  "extraction": {
    "fps": 30.0,
    "total_frames": 120,
    "frames": [...]
  },
  "scores": {
    "rom": {"score": 85.0, "percentile": 20, "details": {...}},
    "power": {...},
    "isolation": {...},
    "rhythm": {...},
    "creativity": {...},
    "accuracy": {...},
    "total_score": 78.5,
    "grade": "B+"
  },
  "feedback": {
    "summary": "전체적으로 파워와 리듬이 돋보이지만...",
    "improvements": {
      "rom": "무릎을 더 낮춰 보세요.",
      "power": "순간 가속을 더 강하게!"
    },
    "career_guide": "프리스타일 댄서로 발전 가능성 높음.",
    "motivation": "계속 이렇게만 하면 프로도 가능해!"
  }
}
```

---

## 5. 데이터 모델

### 5.1 MediaPipe Landmark 스키마

**33개 랜드마크 (MediaPipe Pose 기준):**
```
0: nose
1-7: 눈/귀 (left_eye_inner, left_eye, ..., right_ear)
8-10: 입 (mouth_left, mouth_right)
11-23: 상체 (left_shoulder, right_shoulder, ..., left_thumb, right_thumb)
23-32: 하체 (left_hip, right_hip, ..., left_foot_index, right_foot_index)
```

**원본 좌표 (landmarks):**
- `x`: 프레임 너비 대비 0~1 정규화
- `y`: 프레임 높이 대비 0~1 정규화
- `z`: 깊이 (hip 중심점 대비 상대 거리, 단위 임의)
- `visibility`: 0~1 (1에 가까울수록 확실)

**정규화 좌표 (normalized_landmarks):**
- `x, y, z`: Mid-Hip을 (0,0,0)으로 이동 후, Torso Length로 나눈 값
- `visibility` 없음 (채점용으로는 불필요)

### 5.2 Pydantic 모델

```python
# models/bases/landmark.py
class Landmark(BaseModel):
    x: float
    y: float
    z: float
    visibility: float

class NormalizedLandmark(BaseModel):
    x: float
    y: float
    z: float

# models/transfer/video_data.py
class FrameData(BaseModel):
    frame_index: int
    time_sec: float
    landmarks: Dict[str, Landmark]
    normalized_landmarks: Dict[str, NormalizedLandmark]

class VideoExtractionResult(BaseModel):
    fps: float
    total_frames: int
    frames: List[FrameData]
```

---

## 6. 채점 알고리즘 설계 (Phase 2)

### 6.1 ROM (Range of Motion)

**목적:** 관절 가동 범위의 넓이 평가

**알고리즘:**
1. 각 관절 각도 계산 (예: 팔꿈치 = shoulder-elbow-wrist 각도)
2. 전체 프레임에서 최대/최소 각도 추출 → 가동 범위
3. 전문가 영상의 가동 범위와 비교 → 커버리지 비율

**수식 (예시):**
```
ROM_score = (user_range / expert_range) * 100
```

### 6.2 Power

**목적:** 순간적인 폭발력(가속도) 평가

**알고리즘:**
1. 각 랜드마크의 속도 벡터 계산 (연속 프레임 간 좌표 차이 / 시간)
2. 속도를 미분하여 가속도 계산
3. 피크 가속도의 크기와 빈도를 측정

**수식 (예시):**
```
velocity[t] = (position[t] - position[t-1]) / dt
acceleration[t] = (velocity[t] - velocity[t-1]) / dt
Power_score = f(max(acceleration), count(peaks))
```

**주의:** 스무딩이 없으면 노이즈로 인해 과대 평가됨 (Phase 1에서 해결)

### 6.3 Isolation

**목적:** 특정 부위만 움직이는 독립성 평가

**알고리즘:**
1. 동작 구간을 세그먼트로 나눔 (예: 어깨 움직임 구간)
2. 해당 구간에서 목표 관절(어깨)의 변위 vs 비목표 관절(허리)의 변위 비교
3. 비목표 관절이 정적일수록 높은 점수

**수식 (예시):**
```
Isolation_score = 100 * (1 - non_target_motion / target_motion)
```

### 6.4 Rhythm

**목적:** 음악 BPM과 동작 타이밍의 동기화 평가

**알고리즘:**
1. 음악 BPM 추출 (Librosa 등)
2. 동작의 피크(가속도/각속도) 발생 시점 추출
3. 피크 시점과 비트 시점의 시간차 계산 → 평균 편차

**수식 (예시):**
```
Rhythm_score = 100 * exp(-avg_time_deviation / threshold)
```

**제약:** MVP는 음악 없이 전문가 영상과의 시간 동기화로 단순화 가능

### 6.5 Creativity

**목적:** 전문가 영상과 다른 독창적 요소 평가

**알고리즘:**
1. 사용자 궤적과 전문가 궤적의 DTW 거리 계산
2. 특정 구간에서 거리가 크지만 자연스러운 경우 → 창의적 변형으로 간주
3. 급격한 각도 변화나 예상 밖 동작 패턴 탐지

**수식 (예시):**
```
Creativity_score = f(DTW_distance, novelty_metric)
```

**주의:** Accuracy와 트레이드오프 관계

### 6.6 Accuracy

**목적:** 전문가 영상과의 전체적인 유사도 평가

**알고리즘:**
1. `normalized_landmarks` 기반으로 전문가와 사용자의 궤적 비교
2. DTW (Dynamic Time Warping) 거리 계산 (시간 축 정렬)
3. 거리 역수를 0~100 스케일로 변환

**수식 (예시):**
```
DTW_distance = dtw(user_trajectory, expert_trajectory)
Accuracy_score = 100 * exp(-DTW_distance / normalization_factor)
```

---

## 7. LLM 피드백 아키텍처 (Phase 3)

### 7.1 프롬프트 구조

```python
SYSTEM_PROMPT = """
당신은 10대 청소년을 위한 친근하고 전문적인 스트릿 댄스 코치입니다.
분석 결과를 바탕으로 구체적이고 동기부여적인 피드백을 제공하세요.

[제약 사항]
- 10대가 이해하기 쉬운 언어 사용
- 부정적 표현보다 개선 방향 제시
- 진로 가이드는 현실적이고 구체적으로
"""

USER_PROMPT = """
[분석 결과]
- ROM: {rom_score}점 (상위 {rom_percentile}%)
- Power: {power_score}점 (상위 {power_percentile}%)
- Isolation: {isolation_score}점 (상위 {isolation_percentile}%)
- Rhythm: {rhythm_score}점 (상위 {rhythm_percentile}%)
- Creativity: {creativity_score}점 (상위 {creativity_percentile}%)
- Accuracy: {accuracy_score}점 (상위 {accuracy_percentile}%)

[강점 항목]
{top_strengths}

[약점 항목]
{bottom_weaknesses}

[요청]
1. 전체 요약 (2문장)
2. 각 항목별 개선 방법 (약점 중심, 각 1~2문장)
3. 강점을 살린 진로 추천 (댄서/안무가/강사/유튜버 등)
4. 동기부여 메시지 (1문장)

JSON 형식으로 출력:
{{
  "summary": "...",
  "improvements": {{"rom": "...", "power": "..."}},
  "career_guide": "...",
  "motivation": "..."
}}
"""
```

### 7.2 LLM API 선택

| 모델 | 장점 | 단점 | 비용 (1M 토큰) |
|------|------|------|----------------|
| GPT-4-turbo | 안정적, 한국어 우수 | 느림 | $10 |
| GPT-3.5-turbo | 빠름, 저렴 | 품질 낮음 | $0.5 |
| Claude 3.5 Sonnet | 긴 맥락, 창의적 | 한국어 약간 부족 | $3 |
| Gemini 1.5 Pro | 최장 맥락, 무료 티어 | 응답 품질 변동 | $1.25 |

**추천:** GPT-4-turbo (MVP) → Claude 3.5 (프로덕션)

### 7.3 구현 예시

```python
# domain1/spokes/agents/feedback_agent.py

import openai

def generate_feedback(scores: dict) -> dict:
    prompt = build_prompt(scores)
    response = openai.ChatCompletion.create(
        model="gpt-4-turbo",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)
```

---

## 8. 프론트엔드 아키텍처 (Phase 4)

### 8.1 기술 스택

- **React 18 + Next.js 14** (SSR/SSG)
- **Tailwind CSS** (스타일링)
- **Recharts** (레이더 차트)
- **Framer Motion** (애니메이션)
- **Axios** (API 호출)

### 8.2 페이지 구조

```
pages/
├── index.tsx            ← 랜딩 페이지 (업로드 UI)
├── analysis.tsx         ← 분석 중 로딩 페이지
└── result/[id].tsx      ← 결과 페이지 (점수 + 피드백)

components/
├── Upload.tsx           ← 드래그앤드롭 업로더
├── ScoreRadarChart.tsx  ← 6개 항목 레이더 차트
├── FeedbackCard.tsx     ← LLM 피드백 카드
└── SkeletonOverlay.tsx  ← 스켈레톤 시각화 (선택)
```

### 8.3 API 연동

```typescript
// api/client.ts
import axios from 'axios';

const API_BASE = 'http://localhost:8000';

export const analyzeVideo = async (file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await axios.post(`${API_BASE}/video/analyze`, formData, {
    headers: {'Content-Type': 'multipart/form-data'}
  });
  
  return response.data;
};
```

---

## 9. 인프라 & 배포

### 9.1 개발 환경

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Frontend (예정)
cd frontend
npm install
npm run dev  # http://localhost:3000
```

### 9.2 프로덕션 아키텍처 (제안)

```
[Cloudflare]  ← CDN + DDoS 방어
     ↓
[Load Balancer]
     ↓
┌─────────────────┬─────────────────┐
│  Frontend       │  Backend        │
│  (Vercel)       │  (AWS ECS)      │
│  Next.js SSR    │  FastAPI + GPU  │
└─────────────────┴─────────────────┘
          ↓                ↓
     [S3 Bucket]      [RDS PostgreSQL]
     (비디오 저장)    (사용자 히스토리)
                           ↓
                      [ElastiCache Redis]
                      (비동기 작업 큐)
```

**비용 추정 (월):**
- AWS ECS (t3.medium × 2): $60
- RDS (db.t3.small): $30
- S3 (500GB): $12
- ElastiCache: $15
- Vercel (Pro): $20
- **합계: ~$137/월**

### 9.3 CI/CD (제안)

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run tests
        run: |
          cd backend
          pip install -r requirements.txt
          pytest
  
  deploy-backend:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to ECS
        run: |
          aws ecs update-service --cluster fom --service backend --force-new-deployment
  
  deploy-frontend:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to Vercel
        run: vercel deploy --prod
```

---

## 10. 보안 & 모니터링

### 10.1 보안

- **파일 업로드:** 확장자 화이트리스트, 크기 제한, 바이러스 스캔 (ClamAV)
- **API 인증:** JWT 토큰 (Phase 2~)
- **Rate Limiting:** 1분당 10 요청 (FastAPI Limiter)
- **HTTPS:** Let's Encrypt SSL 인증서

### 10.2 모니터링

- **로그:** CloudWatch Logs / Datadog
- **에러 추적:** Sentry
- **성능:** OpenTelemetry + Prometheus
- **알림:** Slack Webhook (5xx 에러 발생 시)

---

## 11. 확장성 고려사항

### 11.1 장르 확장 (Long-term)

```
domain/
├── domain1/  ← 스트릿 댄스
├── domain2/  ← K-POP 댄스
│   └── hub/services/
│       ├── extraction_service.py  (동일 로직 재사용)
│       └── scoring_service.py     (장르별 가중치 조정)
└── domain3/  ← 발레
    └── ...
```

### 11.2 비동기 처리 (Phase 5)

**현재:** 동기 처리 (요청 → 즉시 분석 → 응답)  
**문제:** 긴 영상(5분+)은 타임아웃 발생

**해결:**
```
[Client] → POST /video/analyze (비동기)
          ↓
       [Redis Queue] → Celery Worker → MediaPipe 처리
          ↓                                ↓
       [Job ID 반환]                   [S3 저장]
          ↓                                ↓
       [Client Poll] ← GET /result/{job_id}
```

---

## 12. 성능 최적화

### 12.1 병목 지점

1. **MediaPipe 처리:** 1분 영상 = 1800 프레임 × 100ms = 180초
2. **데이터 직렬화:** JSON 크기 (1분 = ~5MB)
3. **LLM API 호출:** 응답 시간 3~10초

### 12.2 최적화 전략

- **프레임 샘플링:** 30fps → 15fps로 다운샘플링 (정확도 유지 가능)
- **JSON 압축:** gzip 압축 전송
- **LLM 캐싱:** 동일 점수 패턴은 캐싱된 피드백 재사용
- **GPU 가속:** CUDA 지원 MediaPipe 빌드

---

## 13. 테스트 전략

### 13.1 테스트 레이어

```
tests/
├── unit/
│   ├── test_extraction_service.py  ← 각 함수 단위 테스트
│   └── test_scoring_functions.py
├── integration/
│   └── test_api_endpoints.py       ← FastAPI 엔드투엔드
└── e2e/
    └── test_user_flow.py            ← Selenium (Frontend 포함)
```

### 13.2 테스트 데이터

- **테스트 영상:** 5초짜리 샘플 영상 (저장소에 포함)
- **Expected JSON:** 사전 생성된 정답 JSON
- **Mock LLM:** LLM API 호출 시 더미 응답 사용

---

## 14. 기술 부채 & 추후 개선

### 14.1 현재 알려진 이슈

1. **Pydantic 미활용:** `extract_dance_data()`가 plain dict 반환
2. **에러 로깅 부족:** Sentry 미연동
3. **테스트 커버리지 0%:** 단위 테스트 없음

### 14.2 리팩터링 계획

- [ ] `extraction_service.py` → 클래스 기반으로 리팩터링
- [ ] `VideoExtractionResult` Pydantic 모델 적용
- [ ] Repository 패턴 도입 (DB 연동 시)
- [ ] 의존성 주입 컨테이너 (Dependency Injector)

---

## 15. 참고 자료

- **MediaPipe:** https://google.github.io/mediapipe/solutions/pose
- **FastAPI:** https://fastapi.tiangolo.com/
- **DTW 알고리즘:** https://en.wikipedia.org/wiki/Dynamic_time_warping
- **프로젝트 문서:**
  - `PROJECT_CONTEXT.md`
  - `IMPLEMENTATION_STATUS.md`
  - `CLAUDE.md`

---

**작성자:** Hi-Six 팀  
**마지막 업데이트:** 2026-05-20  
**문의:** [프로젝트 Slack 채널]
