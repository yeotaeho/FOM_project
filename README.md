# FOM (폼미쳤다) — AI 댄스 분석 플랫폼

<div align="center">

**"방구석이 나만의 무대로, AI가 찾아주는 나의 댄스 DNA"**

AI 비전과 LLM 기술을 활용해 10대 청소년의 스트릿 댄스 동작을 분석·평가하고,  
맞춤형 피드백과 진로 가이드를 제공하는 앱 기반 MVP 플랫폼

</div>
ㅁㅁㅁ
---

## 📋 목차

- [프로젝트 개요](#-프로젝트-개요)
- [주요 기능](#-주요-기능)
- [시스템 아키텍처](#-시스템-아키텍처)
- [기술 스택](#-기술-스택)
- [시작하기](#-시작하기)
- [프로젝트 구조](#-프로젝트-구조)
- [API 문서](#-api-문서)
- [성능 최적화](#-성능-최적화)

---

## 🎯 프로젝트 개요

### 핵심 가치

**FOM (Freedom Of Movement / "폼미쳤다")**은 10대 청소년이 혼자서도 전문가급 댄스 피드백을 받을 수 있는 AI 기반 플랫폼입니다.

- **교육 격차 해소**: 비싼 학원 없이도 어디서나 전문가급 피드백 제공
- **심리적 장벽 완화**: 비대면 AI 코칭으로 부담 없이 자신감 형성
- **구체적 진로 설계**: 데이터 기반 실질적 진로 가이드 제공

### 팀 정보

- **팀명**: Hi-Six ("인사는 가볍게, 퀄리티는 높게!")
- **개발 기간**: 1주일 MVP
- **타겟 사용자**: 10대 청소년

---

## ✨ 주요 기능

### 1. 정밀한 동작 분석 (6차원 평가)

AI 비전 기술을 활용해 전문가 영상과 사용자 동작을 다차원으로 비교·평가합니다.

| 지표 | 설명 |
|------|------|
| **ROM** (Range of Motion) | 관절 가동 범위 — 움직임의 크기와 유연성 |
| **Power** | 순간 가속도 및 에너지 방출 — 폭발적인 힘 |
| **Isolation** | 부위별 독립성 — 특정 신체 부위만 움직이는 능력 |
| **Rhythm** | 박자 정확도 — 음악과의 타이밍 일치 |
| **Creativity** | 독창성 — 전문가와의 차별화된 요소 |
| **Accuracy** | 정확도 — 전문가 동작과의 유사도 |

### 2. LLM 기반 맞춤형 피드백

- 10대 눈높이에 맞는 친화적 톤앤매너
- 구체적인 개선 방안 제시
- 강점 기반 진로 추천 (예: Rhythm 높음 → 프리스타일 특화)

### 3. 시각화 및 교정 포인트

- 프레임별 스켈레톤 오버레이
- 전문가 vs 사용자 비교
- 타임라인 기반 미스 타이밍 표시
- 레이더 차트 재능 분석

---

## 🏗 시스템 아키텍처

### 전체 구조

```
┌─────────────────┐
│   Flutter App   │  ← 사용자 인터페이스
│   (dance_app)   │
└────────┬────────┘
         │ HTTP/REST
         ▼
┌─────────────────┐
│   FastAPI       │  ← 통합 API 서버
│   (backend1)    │
└────────┬────────┘
         │
    ┌────┴──────────────┬─────────────────┐
    ▼                   ▼                 ▼
┌─────────┐     ┌──────────┐    ┌──────────────┐
│MediaPipe│     │  YOLO11  │    │ LLM (Ollama) │
│ Pose    │     │ Isolation│    │ Qwen 2.5     │
│ ROM 등  │     │   추적   │    │ 피드백 생성  │
└─────────┘     └──────────┘    └──────────────┘
```

### Hub-Spoke 패턴

```
backend1/
├── routers/           ← HTTP 엔드포인트
├── services/          ← 오케스트레이션 로직
│   ├── extract_coordinator.py   ← 추출 병렬 조율
│   ├── orchestrator.py           ← 채점 병렬 조율
│   └── llm_feedback.py           ← LLM 피드백 생성
└── metrics/           ← 6개 독립 평가 모듈
    ├── accuracy/      ← Hub: ROM 도메인 내 구현
    ├── creativity/
    ├── isolation/
    ├── power/
    ├── rhythm/
    └── rom/           ← 코어: 포즈 추출 및 정규화
        └── domain/
            └── domain1/
                ├── hub/        ← 공통 코어 서비스
                ├── spokes/     ← 확장 기능
                └── models/     ← 데이터 스키마
```

### Isolation · Accuracy 도메인

| 도메인 | 경로 | 역할 |
|--------|------|------|
| **Isolation** (아이솔) | `metrics/isolation/` | YOLO11 트래킹·부위별 독립성. 통합 analyze 기본은 ROM `aligned_pairs`로 `score_isolation` 채점. `pipelines`에 `isolation` 명시 시 YOLO sidecar(`{base}_isolation.json`) 추출 |
| **Accuracy** (정확성) | `metrics/rom/domain/domain1/hub/services/scoring/accuracy_scorer.py` | 전문가 대비 포즈 유사도. 오케스트레이터가 ROM 정렬 쌍(`aligned_pairs`)을 넘겨 `score_accuracy` 호출 |

두 metric 모두 **별도 HTTP 라우터 없이** 통합 `/video/analyze` 오케스트레이터 경로로 채점됩니다. Isolation 전용 API는 `POST /isolation/*` (`metrics/isolation/router.py`).

## 🛠 기술 스택

### Backend (backend1/)

| 영역 | 기술 |
|------|------|
| **프레임워크** | FastAPI 0.110+ |
| **포즈 추정** | MediaPipe 0.10.31+ |
| **비디오 처리** | OpenCV 4.9+ |
| **수치 분석** | NumPy, Pandas, SciPy |
| **음악 분석** | librosa 0.10+ |
| **객체 추적** | YOLO11 (Ultralytics) |
| **LLM** | Ollama (Qwen 2.5) |

### Frontend (dance_app/)

| 영역 | 기술 |
|------|------|
| **프레임워크** | Flutter 3.11+ |
| **상태 관리** | flutter_riverpod |
| **라우팅** | go_router |
| **미디어** | image_picker, video_player |
| **차트** | fl_chart (레이더 차트) |

---

## 🚀 시작하기

### 사전 요구사항

- **Python**: 3.9 이상
- **Flutter**: 3.11 이상
- **FFmpeg**: 시스템에 설치 필요 (rhythm 모듈용)
- **Ollama**: LLM 피드백용 (선택)

### Backend 실행

```bash
# 1. 의존성 설치
cd backend1
pip install -r requirements.txt

# 2. 서버 실행
uvicorn main:app --host 0.0.0.0 --port 8000

# 3. API 문서 확인
# 브라우저에서 http://localhost:8000/docs 접속
```

### Frontend 실행

```bash
# 1. 의존성 설치
cd dance_app
flutter pub get

# 2. 앱 실행
flutter run

# 또는 특정 디바이스
flutter run -d <device-id>
```

### LLM 설정 (선택)

```bash
# Ollama 설치 후
ollama pull qwen2.5:3b

# 더 빠른 추론을 위한 경량 모델 권장
# backend1/services/llm_feedback.py 에서 모델명 설정
```

---

## 📁 프로젝트 구조

```
FOM/
├── backend1/                      # FastAPI 통합 API 서버
│   ├── main.py                    # 앱 진입점
│   ├── routers/                   # HTTP 엔드포인트
│   │   └── video.py              # /video/* 통합 API
│   ├── services/                  # 비즈니스 로직
│   │   ├── extract_coordinator.py # 추출 병렬 조율
│   │   ├── orchestrator.py        # 채점 병렬 조율
│   │   └── llm_feedback.py        # LLM 피드백 생성
│   ├── metrics/                   # 6개 평가 모듈
│   │   ├── accuracy/             # ROM 도메인 내 구현
│   │   ├── creativity/           # 독창성 평가
│   │   ├── isolation/            # 부위별 독립성
│   │   ├── power/                # 파워 평가
│   │   ├── rhythm/               # 리듬 정확도
│   │   └── rom/                  # 관절 가동 범위 (코어)
│   │       └── domain/domain1/   # Hub-Spoke 구조
│   ├── mediapipe_pose_tasks.py   # MediaPipe 래퍼
│   └── requirements.txt
│
├── dance_app/                     # Flutter 모바일 앱
│   ├── lib/
│   │   ├── main.dart             # 앱 진입점
│   │   ├── core/                 # 코어 설정
│   │   │   ├── router/           # go_router 설정
│   │   │   ├── theme/            # 다크 테마 + 네온 컬러
│   │   │   └── config/           # API 설정
│   │   ├── features/             # Feature-first 구조
│   │   │   ├── home/             # 챌린지 목록
│   │   │   ├── studio/           # 촬영/업로드
│   │   │   ├── loading/          # AI 분석 대기
│   │   │   ├── feedback/         # 동작 피드백
│   │   │   └── report/           # 재능·커리어 리포트
│   │   └── shared/               # 공통 위젯
│   └── pubspec.yaml
│
├── .gitignore
└── README.md                      # 본 문서
```

---

## 📚 API 문서

### 주요 엔드포인트

#### 1. 영상 추출

**레퍼런스 또는 유저 영상을 1회 추출하여 JSON으로 저장**

```http
POST /video/extract
Content-Type: multipart/form-data

Parameters:
- file: UploadFile (또는 video_url)
- extraction_mode: "rom" | "full" (기본: "full")
- target_fps: float (기본: 15)

Response:
{
  "json_filename": "20260526_123456_abc123.json",
  "extraction_id": "abc123",
  "fps": 15.0,
  "total_frames": 450,
  "schema": "full_v1"
}
```

#### 2. 종합 분석 (영상 업로드)

**유저 영상을 추출하고 레퍼런스와 비교하여 6차원 채점**

```http
POST /video/analyze
Content-Type: multipart/form-data

Parameters:
- user_video: UploadFile (또는 video_url)
- reference_json: string (레퍼런스 JSON 파일명)
- alignment_method: "time" | "dtw" (기본: "time")
- metrics: string (쉼표 구분, 미지정 시 6개 전체)
- extraction_mode: "rom" | "full" (기본: "full")

Response:
{
  "user": { ... },
  "reference": { ... },
  "extractions": {
    "rom": { "ok": true, "json_filename": "..." },
    "rhythm": { ... },
    "power": { ... },
    "creativity": { ... }
  },
  "alignment": {
    "method": "time",
    "pair_count": 120
  },
  "scores": {
    "accuracy": { "score": 85.0, "breakdown": {} },
    "creativity": { "score": 80.0, "breakdown": {} },
    "isolation": { "score": 70.0, "breakdown": {} },
    "power": { "score": 68.0, "breakdown": {} },
    "rhythm": { "score": 65.0, "breakdown": {} },
    "rom": { "score": 72.0, "breakdown": {} },
    "total_score": 73.33,
    "grade": "B"
  }
}
```

#### 3. 재채점 (JSON만)

**이미 추출된 JSON 파일로 빠르게 재채점**

```http
POST /video/analyze/json
Content-Type: application/json

Body:
{
  "user_json": "user_20260526.json",
  "reference_json": "ref_20260526.json",
  "alignment_method": "time",
  "metrics": ["rom", "accuracy"]  // 선택적 부분 채점
}
```

#### 4. LLM 피드백 생성

```http
POST /video/analyze/feedback
Content-Type: application/json

Body:
{
  "user_json": "user_20260526.json",
  "reference_json": "ref_20260526.json"
}

Response:
{
  "feedback": "당신의 팝핑 동작에서 isolation 점수가 95점으로 매우 뛰어납니다! ...",
  "generation_time": 25.3
}
```

### 기타 엔드포인트

- `GET /health` — 서버 상태 및 등록된 라우트 확인
- `GET /video/json/{filename}` — 추출 JSON 다운로드
- `GET /video/data/{filename}` — 스켈레톤 오버레이 영상 다운로드
- `POST /video/compare` — ROM 비교 (개발/디버그용)

### 상세 문서

- [ARCHITECTURE.md](backend1/metrics/docs/ARCHITECTURE.md) — 6 metric 규범 및 경계
- [ORCHESTRATOR.md](backend1/metrics/docs/ORCHESTRATOR.md) — 추출·채점 조율 설계
- [API_REFERENCE.md](backend1/metrics/docs/API_REFERENCE.md) — 전체 필드 명세
- [DEV_VIDEO_DATASET.md](backend1/metrics/docs/DEV_VIDEO_DATASET.md) — 개발용 테스트 데이터

---

## ⚡️ 성능 최적화

### LLM 피드백 병목 해결

현재 LLM 피드백 생성이 전체 파이프라인의 **60~70%**를 차지합니다.

#### 측정 결과 (RTX 3050 6GB)

| 단계 | 시간 | 비율 |
|------|------|------|
| 데이터 추출·채점 | ~20초 | 30% |
| **LLM 피드백 생성** | **40~70초** | **60~70%** |
| **전체** | **60~90초** | 100% |

#### 개선 방안

##### 즉시 적용 가능

1. **경량 모델 사용** (권장)
   ```python
   # backend1/services/llm_feedback.py
   model_name: str = "qwen2.5:3b"  # 7b → 3b
   ```
   - 예상 효과: 70초 → **20~30초**

2. **생성 토큰 수 제한**
   ```python
   "num_predict": 400  # 기존 800 → 400
   ```
   - 예상 효과: **10~20초 단축**

##### 아키텍처 개선

3. **비동기 백그라운드 생성**
   - 사용자는 채점 결과를 즉시 확인
   - 피드백은 별도 엔드포인트에서 폴링

4. **Streaming 응답**
   - 첫 토큰부터 실시간 전송
   - 타이핑 효과로 체감 대기 시간 감소

자세한 내용: [LLM_TIMING_ANALYSIS.md](backend1/LLM_TIMING_ANALYSIS.md)

---

## 📱 앱 화면 구성

### 사용자 여정

```
Home (챌린지)
   ↓ 레퍼런스 선택
Studio (촬영/업로드)
   ↓ 영상 선택
Loading (AI 분석)
   ↓ 자동 (~7초)
Feedback (동작 피드백)
   ↓ 리포트 보기
Report (재능·커리어)
```

### 주요 화면

#### 1. Home — 챌린지 탐색
- 레퍼런스 댄스 영상 목록
- 장르별 필터 (팝핑, 브레이킹, 롹킹, 왜킹, 하우스)
- 난이도 표시 (초급, 중급, 고급)

#### 2. Studio — 촬영/업로드
- 상단: 레퍼런스 영상 루프 재생
- 하단: 갤러리 업로드 / 카메라 촬영

#### 3. Loading — AI 분석
- 스켈레톤 애니메이션
- 동적 안내 문구 (2초마다 순환)
- 진행률 표시

#### 4. Feedback — 동작 피드백
- 영상 + 스켈레톤 오버레이
- 타임라인 기반 미스 타이밍 표시
- 3개 주요 점수 (리듬 정확도, 포즈 일치도, 종합)
- 교정 포인트 목록

#### 5. Report — 재능·커리어 리포트
- 6차원 레이더 차트
- LLM 기반 커리어 가이드
- 추천 진로 (백업 댄서, 안무가, 강사 등)

자세한 내용: [APP_SCREEN_GUIDE.md](dance_app/docs/APP_SCREEN_GUIDE.md)

---

## 🎨 디자인 시스템

### 컬러 팔레트 (다크 모드)

| 용도 | 색상 | HEX |
|------|------|-----|
| 배경 | Background | `#0A0A0A` |
| 서피스 | Surface | `#141414` |
| 카드 | Card | `#1E1E1E` |
| 주 액센트 | Neon Green | `#39FF14` |
| 보조 액센트 | Neon Purple | `#BF5AF2` |
| 점수·태그 | Neon Blue | `#00D4FF` |
| 에러 | Error | `#FF3B30` |

### UI 방향

- **TikTok/Reels 스타일**: 빠르고 직관적
- **10대 친화적**: 네온 악센트 + 동적 애니메이션
- **세로 고정**: portraitUp only

---

## 🔧 개발 가이드

### Backend 개발

#### 새 Metric 추가

```python
# backend1/metrics/new_metric/__init__.py
def score_new_metric(aligned_pairs: list, **kwargs) -> dict:
    """
    새 지표 채점 함수
    
    Returns:
        {
            "score": 0~100,
            "breakdown": {},
            "frame_diffs": []  # 선택
        }
    """
    pass
```

```python
# backend1/services/orchestrator.py
# AVAILABLE_METRICS에 추가
AVAILABLE_METRICS = [
    "accuracy", "creativity", "isolation", 
    "power", "rhythm", "rom", "new_metric"
]
```

#### 채점 로직 수정 시 주의사항

- **절대 추출 단계를 수정하지 마세요** — 이미 저장된 JSON만 사용
- **다른 metric을 import하지 마세요** — 독립성 유지
- **입력은 읽기 전용** — aligned_pairs 등을 변경하지 마세요

### Frontend 개발

#### 새 화면 추가

```dart
// lib/core/router/app_router.dart
GoRoute(
  path: '/new-screen',
  builder: (context, state) => NewScreen(),
)
```

#### API 호출

```dart
// lib/features/studio/data/video_analyze_api.dart
import 'package:http/http.dart' as http;

final response = await http.post(
  Uri.parse('$baseUrl/video/analyze'),
  body: formData,
);
```

---

## 📊 테스트 데이터

### 개발용 영상

`backend1/video_data/`에 고정 테스트 영상이 포함되어 있습니다.

| 파일 | 장르 | 용도 |
|------|------|------|
| `gBR_sBM_c01_d04_mBR3_ch03.mp4` | 브레이킹 | 레퍼런스 |
| `20260521_134352_bed9b6d2.json` | 브레이킹 | 추출 결과 |

### Mock 데이터 (Flutter)

- `home_repository.dart`: 5개 챌린지 영상 메타
- `report_repository.dart`: 샘플 분석 결과

---

## 🤝 기여 가이드

### 브랜치 전략

- `main`: 안정 버전
- `develop`: 개발 통합
- `feature/*`: 기능 개발
- `fix/*`: 버그 수정

### 커밋 컨벤션

```
feat: 새 기능 추가
fix: 버그 수정
docs: 문서 변경
style: 코드 포맷팅
refactor: 리팩토링
test: 테스트 추가
chore: 빌드/설정 변경
```

---

## 🗺 로드맵

### ✅ Phase 1 (완료)
- [x] MediaPipe 포즈 추출 파이프라인
- [x] 6개 metric 채점 엔진
- [x] LLM 피드백 생성
- [x] Flutter 앱 UI/UX

### 🚧 Phase 2 (진행 중)
- [ ] 실시간 비교 기능
- [ ] 사용자 히스토리 저장
- [ ] 진로 가이드 고도화
- [ ] LLM 성능 최적화

### 📝 Phase 3 (계획)
- [ ] 전문가 레퍼런스 DB 확장
- [ ] B2B 오디션 시스템
- [ ] 다중 사용자 지원
- [ ] 실시간 스트리밍 분석

### 🌏 Long-term
- [ ] 장르 확장 (K-POP, 발레 등)
- [ ] 글로벌 댄서 커뮤니티
- [ ] 기획사 비대면 오디션 납품
- [ ] 홈트레이닝 등 타 도메인 확장

---

## 📄 라이선스

본 프로젝트는 교육 목적의 MVP입니다.

---

## 👥 팀 Hi-Six

**"인사는 가볍게, 퀄리티는 높게! 완벽한 호흡으로 뭉친 6명의 인재들"**

- 백엔드 팀: 추출·채점 파이프라인 구축
- 프론트엔드 팀: Flutter 앱 개발
- AI/ML 팀: LLM 통합 및 최적화

---

## 📞 문의

프로젝트 관련 문의사항은 Issues를 통해 남겨주세요.

---

<div align="center">

**FOM (폼미쳤다)** — Made with ❤️ by Hi-Six Team

</div>
