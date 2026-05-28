# 구현 현황 (Implementation Status)

> **마지막 업데이트:** 2026-05-20  
> **현재 단계:** Phase 1 완료 / Phase 2 진행 중

---

## 1. 전체 진행 상황

### 1.1 Phase별 체크리스트

| Phase | 기능 | 상태 | 완성도 | 비고 |
|-------|------|------|--------|------|
| **Phase 1** | 비디오 데이터 추출 모듈 | ✅ 완료 | 100% | 프로덕션 준비 완료 |
| **Phase 2** | 6개 채점 함수 구현 | 🔄 진행 중 | ~50% | Accuracy + ROM + `/compare` (DTW·offset) 완료 |
| **Phase 3** | LLM 피드백 생성 | ⏳ 대기 | 0% | Phase 2 이후 시작 |
| **Phase 4** | 프론트엔드 시각화 | ⏳ 대기 | 0% | 별도 팀 담당 |

---

## 2. Phase 1: 비디오 데이터 추출 모듈 ✅

### 2.1 구현 완료 항목

#### 2.1.1 FastAPI 서버 구조
- ✅ `main.py`: FastAPI 앱 초기화, CORS 설정, 라우터 등록
- ✅ `routers/video.py`: `/video/extract` 엔드포인트
  - 파일 업로드 검증 (확장자, 크기)
  - 임시 파일 관리 (자동 삭제)
  - HTTP 에러 핸들링 (415, 413, 422, 500)

#### 2.1.2 도메인 레이어 (`domain/domain1/`)
- ✅ **Hub-Spoke 디렉터리 구조 확립**
  ```
  domain1/
  ├── hub/services/extraction_service.py  ← 핵심 파이프라인
  ├── models/bases/landmark.py            ← 기본 스키마
  ├── models/transfer/video_data.py       ← 응답 DTO
  └── docs/                                ← 프로젝트 문서
  ```

#### 2.1.3 핵심 파이프라인 (`extraction_service.py`)
**4단계 처리 로직 완성:**

1. ✅ **메타데이터 추출**
   - OpenCV로 `fps`, `total_frames` 획득
   - 기본값 처리 (fps 없으면 30.0)

2. ✅ **원시 랜드마크 추출**
   - MediaPipe Pose (model_complexity=1)
   - 33개 랜드마크 × (x, y, z, visibility)
   - 미검출 프레임은 NaN 처리 (보간 대상)

3. ✅ **데이터 스무딩 & 보간**
   - `pandas.interpolate(method='linear')`: NaN 선형 보간
   - `ffill()` + `bfill()`: 양 끝 프레임 처리
   - `rolling(window=3, center=True).mean()`: 이동평균 필터
   - **중요:** Power(가속도) 채점을 위해 필수

4. ✅ **정규화 (Normalization)**
   - **Step A (Translation):** Mid-Hip을 원점 (0, 0, 0)으로 이동
   - **Step B (Scaling):** Torso Length (Mid-Shoulder ↔ Mid-Hip 거리)로 나눔
   - **목적:** 체형(키, 팔다리 길이) 차이 제거 → Accuracy 채점에 필수

#### 2.1.4 표준 JSON 출력
**스키마 (실제 반환값):**
```json
{
  "fps": 30.0,
  "total_frames": 120,
  "frames": [
    {
      "frame_index": 0,
      "time_sec": 0.0,
      "landmarks": {
        "left_shoulder": {"x": 0.52, "y": 0.31, "z": -0.15, "visibility": 0.99},
        "right_shoulder": {...},
        // ... 33개 랜드마크
      },
      "normalized_landmarks": {
        "left_shoulder": {"x": -0.2, "y": 0.8, "z": -0.1},
        "right_shoulder": {...},
        // ... 33개 (visibility 제외)
      }
    }
  ]
}
```

**특징:**
- `total_frames`는 OpenCV 메타가 아닌, **실제 처리된 프레임 수** (`len(df)`)
- `time_sec = frame_index / fps`로 타임스탬프 계산
- Rhythm, Accuracy 모듈이 이 데이터를 직접 사용

#### 2.1.5 Pydantic 스키마
- ✅ `Landmark`: x, y, z, visibility
- ✅ `NormalizedLandmark`: x, y, z (visibility 제외)
- ✅ `FrameData`, `VideoExtractionResult`: 응답 구조 정의
- ⚠️ **현재 미사용:** `extract_dance_data()`는 plain `dict` 반환
- 🔜 **TODO:** FastAPI `response_model`로 타입 검증 추가

---

## 3. Phase 2: 6개 채점 함수 구현 ⏳

### 3.1 채점 함수 사양 (설계)

각 함수는 **Phase 1의 표준 JSON**을 입력받아 **0~100점 사이 점수**를 반환합니다.

#### 3.1.1 함수 시그니처 (예시)
```python
def score_rom(extraction_result: dict) -> dict:
    """
    ROM (Range of Motion) 채점
    Args:
        extraction_result: extract_dance_data()의 반환값
    Returns:
        {"score": 85.0, "details": {...}}
    """
    pass
```

#### 3.1.2 채점 기준 설계

| 함수 | 평가 항목 | 알고리즘 방향 | 담당자 |
|------|-----------|---------------|--------|
| **ROM** | 관절 가동 범위 | 각 관절의 최대/최소 각도 계산 → 전문가 대비 커버리지 | 미정 |
| **Power** | 순간 가속도 | 속도 벡터 미분 → 피크 가속도의 크기와 빈도 | 미정 |
| **Isolation** | 부위별 독립성 | 특정 관절 움직일 때 다른 관절의 정적도 측정 | 미정 |
| **Rhythm** | 박자 정확도 | BPM 추출 → 동작 피크와 비트 동기화율 | 미정 |
| **Creativity** | 독창성 | 전문가 영상과의 궤적 차이 → 독창적 변형 비율 | 미정 |
| **Accuracy** | 전문가 유사도 | `normalized_landmarks` 기반 DTW 거리 | 미정 |

#### 3.1.3 공통 인터페이스 설계 (제안)
```python
# domain1/hub/services/scoring_service.py (예정)

from typing import Dict, List

def score_all(extraction_result: dict) -> dict:
    """
    6개 채점 함수를 병렬/순차 호출하여 종합 결과 반환
    """
    return {
        "rom": score_rom(extraction_result),
        "power": score_power(extraction_result),
        "isolation": score_isolation(extraction_result),
        "rhythm": score_rhythm(extraction_result),
        "creativity": score_creativity(extraction_result),
        "accuracy": score_accuracy(extraction_result),
        "total_score": calculate_weighted_total(...),
        "grade": get_grade(...)  # S/A/B/C/D 등급
    }
```

### 3.2 구현 진행 상황
- [x] **Accuracy** — `accuracy_scorer.py` (joint_angles 60% + bone_vectors 40%)
- [x] **비교 API** — `POST /video/compare` (video_json 파일명 2개)
- [x] **JSON 저장** — `POST /video/extract` → `video_data/video_json/`
- [x] **프레임 정렬** — `align_by_time` (bisect + offset), `align_by_dtw` (fastdtw)
- ⏳ ROM, Power, Isolation, Rhythm, Creativity
- [x] DTW 정렬 (`alignment_method=dtw`)
- [x] 오프셋·자동 시작점 (`user_offset_sec`, `auto_detect_start`)
- [x] 응답 축소 (`detail_level=summary`, `worst_frames`)
- [x] 비선형 각도 (`scoring_mode=dance`)
- [x] ROM 채점 설계 (`ROM_SCORING.md`)
- [x] ROM 구현 (`rom_scorer.py`, `enable_rom`, 가중 total_score)
- ⏳ Power, Isolation, Rhythm, Creativity
- ⏳ 실영상 통합 테스트 (동일 영상 95점+)

---

## 4. Phase 3: LLM 피드백 생성 ⏳

### 4.1 목표
Phase 2의 채점 결과(`score_all()`)를 입력으로, **10대 친화적이고 구체적인 피드백**을 생성합니다.

### 4.2 설계 아이디어

#### 4.2.1 프롬프트 구조 (초안)
```
당신은 10대 청소년을 위한 친근한 댄스 코치입니다.

[분석 결과]
- ROM: 85점 (상위 20%)
- Power: 65점 (중위 50%)
- Isolation: 90점 (상위 10%)
- Rhythm: 70점 (중위 40%)
- Creativity: 80점 (상위 25%)
- Accuracy: 60점 (중위 60%)

[요청 사항]
1. 각 항목별로 구체적인 개선 방법 제시 (2문장 이내)
2. 강점을 살릴 수 있는 진로 추천 (댄서/안무가/강사 등)
3. 동기부여 메시지 (10대 톤앤매너)

[출력 형식]
JSON으로 반환:
{
  "summary": "전체적으로 ...",
  "improvements": {
    "rom": "...",
    "power": "파워 동작에서 무릎을 더 깊게 구부려 보세요..."
  },
  "career_guide": "...",
  "motivation": "..."
}
```

#### 4.2.2 기술 스택 후보
- **OpenAI GPT-4-turbo** (가장 안정적)
- **Anthropic Claude 3.5 Sonnet** (긴 맥락 처리 우수)
- **Gemini 1.5 Pro** (비용 효율)

#### 4.2.3 구현 위치
```python
# domain1/spokes/agents/feedback_agent.py (예정)

def generate_feedback(scores: dict) -> dict:
    """
    채점 결과를 LLM에 전달하여 피드백 생성
    """
    prompt = build_prompt(scores)
    response = call_llm(prompt)
    return parse_feedback(response)
```

### 4.3 현재 상태
- ⏳ LLM API 키 미설정
- ⏳ 프롬프트 엔지니어링 미완성
- ⏳ 10대 톤앤매너 가이드라인 미확립

---

## 5. Phase 4: 프론트엔드 시각화 ⏳

### 5.1 필수 화면
1. **업로드 페이지:** 영상 드래그앤드롭 / 파일 선택
2. **분석 중 페이지:** 로딩 인디케이터 + 진행률 (선택)
3. **결과 페이지:**
   - 종합 점수 + 등급 (S/A/B/C/D)
   - 6개 항목별 점수 (레이더 차트)
   - LLM 피드백 텍스트
4. **비교 시각화 (선택):**
   - 프레임별 스켈레톤 오버레이
   - 전문가 vs 사용자 동작 비교

### 5.2 기술 스택 제안
- **React + Next.js** (SSR/SSG 가능)
- **Tailwind CSS** (빠른 스타일링)
- **Recharts / Chart.js** (레이더 차트)
- **Three.js (선택)** (3D 스켈레톤 렌더링)

### 5.3 현재 상태
- ⏳ 프론트엔드 팀 미지정
- ⏳ API 연동 명세 미작성
- ⏳ 디자인 시안 없음

---

## 6. 인프라 & 배포

### 6.1 현재 환경
- **로컬 개발:**
  - `uvicorn main:app --reload --host 0.0.0.0 --port 8000`
  - Swagger UI: `http://localhost:8000/docs`
- **버전 관리:** Git (레포지토리: `C:/Users/804/Documents/app`)

### 6.2 배포 계획 (미확정)
- **Backend:** AWS EC2 / Google Cloud Run / Heroku
- **파일 저장소:** AWS S3 (업로드된 영상 임시 저장)
- **DB:** PostgreSQL (사용자 히스토리, 레퍼런스 영상 메타데이터)
- **비동기 작업:** Celery + Redis (영상 처리 큐)

---

## 7. 테스트 현황

### 7.1 완료된 테스트
- ✅ `POST /video/extract` 수동 테스트 (Postman/Thunder Client)
- ✅ MediaPipe 파이프라인 로컬 검증

### 7.2 필요한 테스트
- ⏳ 단위 테스트 (`pytest`)
  - `extraction_service.py` 각 함수
  - 에러 케이스 (영상 열기 실패, 빈 프레임 등)
- ⏳ 통합 테스트
  - `/video/extract` 엔드투엔드
  - 대용량 파일 (500MB 경계)
- ⏳ 성능 테스트
  - 1분 영상 처리 시간 벤치마크
  - 동시 요청 부하 테스트

---

## 8. 알려진 이슈 & 개선 사항

### 8.1 현재 이슈
1. ⚠️ **Pydantic 모델 미활용:**
   - `VideoExtractionResult`, `FrameData` 정의는 있지만 실제 사용 안 함
   - `extract_dance_data()`가 plain `dict` 반환
   - **해결 방법:** FastAPI `response_model` 적용 + 서비스 레이어 리팩터링

2. ⚠️ **YOLO 통합 미완:**
   - `requirements.txt`에 `ultralytics` 주석 처리
   - MVP는 MediaPipe만으로 진행 (합의됨)

3. ⚠️ **전문가 레퍼런스 영상 없음:**
   - Accuracy, Creativity 채점을 위해 필수
   - 각 장르별로 최소 5~10개 필요

4. ⚠️ **에러 로깅 부족:**
   - 현재 `HTTPException`만 던짐
   - Sentry/CloudWatch 등 모니터링 미연동

### 8.2 개선 로드맵
1. **Phase 1 마무리:**
   - [ ] Pydantic 모델 적용
   - [ ] 단위 테스트 추가
   - [ ] API 명세 문서 작성 (`API_SPEC.md`)

2. **Phase 2 시작 전:**
   - [ ] 6개 채점 함수 담당자 배정
   - [ ] 테스트 데이터셋 수집 (전문가 영상)
   - [ ] 알고리즘 수식 검증 (수학적 타당성)

3. **Phase 3~4 병렬 진행:**
   - [ ] LLM 피드백 프롬프트 설계
   - [ ] 프론트엔드 기본 UI 구현
   - [ ] API 연동 테스트

---

## 9. 다음 액션 아이템 (Next Steps)

### 9.1 즉시 착수 (이번 주)
1. **Phase 2 킥오프:**
   - [ ] 6개 채점 함수 담당자 결정
   - [ ] 각 함수의 수식/알고리즘 설계 문서 작성
   - [ ] 공통 인터페이스 `scoring_service.py` 뼈대 생성

2. **데이터 준비:**
   - [ ] 전문가 스트릿 댄스 영상 5개 수집 (YouTube 등)
   - [ ] `extract_dance_data()` 실행하여 JSON 생성 (테스트용)

3. **문서화:**
   - [ ] `API_SPEC.md` 작성 (Swagger 기반)
   - [ ] `ARCHITECTURE.md` 다이어그램 추가

### 9.2 중기 (2주 내)
- [ ] Phase 2 완료 (6개 채점 함수 통합)
- [ ] Phase 3 LLM 프롬프트 검증
- [ ] Phase 4 프론트엔드 프로토타입

### 9.3 장기 (1개월 내)
- [ ] MVP 전체 통합 테스트
- [ ] 베타 사용자 피드백 수집
- [ ] 배포 환경 구축 (AWS/GCP)

---

## 10. 팀 커뮤니케이션

### 10.1 진행 상황 공유
- **주 단위 스탠드업:** 매주 월요일 오전
- **블로킹 이슈:** Slack/Discord 즉시 공유
- **문서 업데이트:** 이 파일(`IMPLEMENTATION_STATUS.md`)을 매 Phase 완료 시 갱신

### 10.2 연락처 (예시, 실제 정보로 대체)
- **프로젝트 리드:** [이름] - [이메일/Slack]
- **Backend 리드:** [이름]
- **Frontend 리드:** [이름]
- **채점 알고리즘 리드:** [이름]

---

## 11. 참고 자료

- `PROJECT_CONTEXT.md`: 프로젝트 기획과 목표
- `CURRENT_LOGIC.md`: 현재 비교 로직 실제 동작·보정·한계 (시작점·체형·시점)
- `ROM_SCORING.md`: ROM 채점 설계·알고리즘·구현 계획
- `COMPARISON_STRATEGY.md`: 두 영상 비교·채점 구현 전략 (정렬 알고리즘·Accuracy·6개 함수)
- `ARCHITECTURE.md`: 시스템 아키텍처 상세
- `VIEWPOINT_INVARIANCE.md`: `landmarks` 시점 한계 및 Accuracy 대안 (joint_angles / 3D 회전 / 촬영 UI)
- `CLAUDE.md`: AI 개발 가이드
- `requirements.txt`: Python 의존성
- Swagger UI: `http://localhost:8000/docs`

---

**마지막 업데이트:** 2026-05-20  
**다음 업데이트 예정:** Phase 2 완료 시
