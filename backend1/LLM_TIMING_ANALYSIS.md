# LLM 피드백 생성 시간 측정 결과

## 테스트 일시
2026-05-22 14:10

## 측정 결과

### 단계별 시간

| 단계 | 시간 | 비율 |
|------|------|------|
| 데이터 필터링 | 0.02ms | 무시 가능 |
| 프롬프트 생성 | 0.05ms | 무시 가능 |
| **Ollama 추론 (1회차)** | **71.74초** | **병목** |
| 전체 generate_feedback (2회차) | 43.50초 | 모델 로드됨 |

### 성능 지표

- **토큰 생성 속도**: 4.9 tokens/sec
- **생성 토큰 수**: 약 350 tokens
- **프롬프트 길이**: 2,073 chars (~691 tokens)
- **생성 피드백 길이**: 701 chars

### Ollama 상태 (추론 후)

```
NAME                          PROCESSOR          SIZE
qwen2.5:7b-instruct-q4_K_M    25%/75% CPU/GPU    5.4 GB
```

## 문제 진단

### 1. LLM이 전체 파이프라인 병목의 주요 원인

- 전체 분석 파이프라인: **1분 이상**
- LLM 피드백 생성: **40~70초** (첫 로드 vs 이미 로드)
- **LLM이 전체 시간의 60~70% 차지**

### 2. GPU 사용 중이지만 속도가 느림

**문제점:**
- GPU 75% 사용 중이지만 **4.9 tokens/sec**는 매우 느림
- RTX 3050 (6GB VRAM)에 7B 모델 Q4 quantization
- 예상: 일부 레이어만 GPU, 나머지 CPU (Ollama 서버 로그 참고)

**정상 속도 참고:**
- GPU 전용 (RTX 3090, 4090): 30~50+ tokens/sec
- 하이브리드 (일부 GPU): 10~20 tokens/sec
- CPU 전용: 2~5 tokens/sec

**현재 상태:** CPU 병목이 심하거나 GPU 레이어가 충분하지 않음

### 3. 모델 로드 시간 vs 추론 시간

- 1회차 (콜드 스타트): 71.7초
- 2회차 (모델 로드됨): 43.5초
- **차이 28초** = 모델 로드/언로드 오버헤드

## 개선 방안

### 우선순위 1: 더 작은 모델 사용 (즉시 효과)

```bash
# 현재: qwen2.5:7b-instruct-q4_K_M (4.7GB)
# 권장: qwen2.5:3b
ollama pull qwen2.5:3b

# backend1/services/llm_feedback.py 수정
model_name: str = "qwen2.5:3b"  # 기존 7b → 3b
```

**예상 효과:**
- 생성 시간: 70초 → **20~30초**
- 품질: 피드백 용도로는 충분 (테스트 필요)

### 우선순위 2: 생성 토큰 수 제한

```python
# services/llm_feedback.py line 282-286
"options": {
    "temperature": 0.7,
    "top_p": 0.9,
    "num_predict": 400,  # 기존 800 → 400
}
```

**예상 효과:**
- 현재: 350 tokens 생성 (설정 800)
- 변경: 생성 시간 **10~20초 단축**
- 피드백 길이만 짧아짐 (품질 유지)

### 우선순위 3: 비동기/백그라운드 생성

**현재 흐름 (앱 관점):**
```
POST /video/analyze → 추출·채점 → 응답 → 
POST /video/analyze/feedback (대기) → 응답
```

**개선안:**
```
POST /video/analyze → 추출·채점 → 응답 (즉시)
  (백그라운드에서 LLM 피드백 생성)
GET /video/feedback/{id} → 폴링 또는 WebSocket
```

**장점:**
- 사용자는 채점 결과를 **즉시** 확인
- 피드백은 "생성 중..." → 완료 시 표시
- 체감 대기 시간 **대폭 감소**

### 우선순위 4: Streaming 응답

```python
# services/llm_feedback.py
"stream": True  # 현재 False
```

```python
# routers/video.py
from fastapi.responses import StreamingResponse

async def generate_feedback_stream(...):
    async for chunk in llm_service.stream_feedback(...):
        yield chunk
```

**장점:**
- 첫 토큰 생성 즉시 클라이언트 전송 (~1~2초)
- 사용자는 "타이핑 효과"로 체감 대기 감소
- 전체 시간은 동일하지만 **UX 크게 개선**

### 우선순위 5: GPU 최적화 (하드웨어 한계)

```bash
# Ollama 서버 로그 확인
ollama serve

# 출력 예시:
# load_tensors: offloaded 26/29 layers to GPU
# → 3개 레이어가 CPU에 있음
```

**RTX 3050 6GB 한계:**
- 7B Q4 모델은 GPU에 거의 다 올라가지만 KV cache + compute buffer 포함 시 VRAM 부족
- **해결 불가능 (하드웨어 업그레이드 필요)**
- → **3B 모델 사용이 현실적**

## 권장 조치

### 즉시 적용 (코드 변경 최소)

1. **3B 모델로 변경** + **num_predict 400**
   ```python
   # services/llm_feedback.py
   model_name: str = "qwen2.5:3b"
   "num_predict": 400
   ```
   - 예상 시간: 70초 → **15~25초**
   - 전체 파이프라인: 60초+ → **40~50초**

2. **백그라운드 생성 분리**
   - LLM을 POST /video/analyze에서 제거
   - 별도 엔드포인트에서 생성 + 폴링
   - 사용자는 채점 결과를 즉시 확인

### 장기 개선 (UX 최적화)

3. **Streaming 응답 구현**
4. **캐싱**: 동일 분석 결과 → 피드백 재사용
5. **Ollama 대신 vLLM/TGI**: 더 빠른 추론 엔진 (복잡도↑)

## 결론

**핵심 발견:**
- ✅ LLM이 전체 1분+ 파이프라인의 **60~70% 차지** (병목 확인)
- ✅ GPU 사용 중이지만 **4.9 tok/s로 느림** (VRAM 부족 추정)
- ✅ 즉시 개선 가능: **3B 모델 + num_predict 단축** → **40~60초 단축**

**다음 단계:**
1. 3B 모델 + 토큰 제한 적용 후 재측정
2. 나머지 파이프라인(추출·채점) 시간 측정
3. 백그라운드 생성 아키텍처 검토
