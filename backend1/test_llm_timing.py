"""LLM 피드백 생성 시간 측정 테스트."""

import asyncio
import json
import time
from pathlib import Path
from services.llm_feedback import LLMFeedbackService

# 실제 분석 결과 로드 (있으면) 또는 샘플 사용
sample_analysis_result = {
    "user_json": "20260521_155225_a8cc4d5b.json",
    "reference_json": "20260521_134352_bed9b6d2.json",
    "scores": {
        "accuracy": {
            "score": 78.5,
            "grade": "B",
            "breakdown": {
                "mean_similarity": 78.5,
                "joint_angle_errors": {"left_elbow": 12.5, "right_knee": 15.3}
            }
        },
        "creativity": {
            "score": 65.2,
            "breakdown": {
                "mean_divergence": 0.45,
                "std_divergence": 0.32,
                "mean_motion": 0.58
            }
        },
        "isolation": {
            "score": 72.1,
            "breakdown": {
                "mean_coupling_ratio": 0.28,
                "region_isolation": {"arms": 85.0, "legs": 70.0}
            }
        },
        "power": {
            "score": 82.3,
            "breakdown": {
                "composite": 2.8,
                "w_vel_mean": 1.2,
                "w_vel_p95": 3.5,
                "w_acc_mean": 0.8
            }
        },
        "rhythm": {
            "score": 68.9,
            "breakdown": {
                "consistency_score": 70.0,
                "dtw_score": 67.8,
                "peak_count": 24,
                "cv": 0.25
            }
        },
        "rom": {
            "score": 75.6,
            "grade": "B",
            "breakdown": {
                "mean_coverage": 82.0,
                "active_joints": 15,
                "static_joints": 3
            }
        },
        "total_score": 73.8,
        "grade": "B"
    },
    "alignment": {
        "method": "dtw",
        "aligned_pairs": 120,
        "user_frames": 125,
        "ref_frames": 118,
        "duplicate_ratio": 0.04,
        "warning": None
    },
    "meta": {
        "metrics_run": ["accuracy", "creativity", "isolation", "power", "rhythm", "rom"],
        "detail_level": "summary",
        "user_fps": 30.0,
        "user_total_frames": 125,
        "reference_fps": 30.0,
        "reference_total_frames": 118,
        "warnings": []
    }
}


def load_real_analysis_if_exists():
    """실제 분석 결과가 있으면 로드."""
    json_dir = Path("metrics/rom/domain/domain1/video_data/video_json")
    if json_dir.exists():
        json_files = sorted(json_dir.glob("*.json"))
        if len(json_files) >= 2:
            # 가장 최근 user/ref JSON 로드 시도
            try:
                user_file = json_files[-1]
                ref_file = json_files[-2]
                
                with open(user_file, 'r', encoding='utf-8') as f:
                    user_data = json.load(f)
                with open(ref_file, 'r', encoding='utf-8') as f:
                    ref_data = json.load(f)
                    
                print(f"   실제 분석 데이터 로드: {user_file.name}, {ref_file.name}")
                return {
                    "user_json": user_file.name,
                    "reference_json": ref_file.name,
                    "scores": sample_analysis_result["scores"],  # scores는 샘플 사용
                    "alignment": sample_analysis_result["alignment"],
                    "meta": sample_analysis_result["meta"]
                }
            except Exception as e:
                print(f"   실제 데이터 로드 실패 ({e}), 샘플 사용")
    
    return sample_analysis_result


async def test_llm_timing():
    print("=" * 80)
    print("LLM 피드백 생성 시간 측정 테스트")
    print("=" * 80)
    
    # 분석 데이터 준비
    print("\n[준비] 분석 데이터 로드...")
    analysis_result = load_real_analysis_if_exists()
    
    # LLM 서비스 초기화
    llm_service = LLMFeedbackService(
        ollama_base_url="http://localhost:11434",
        model_name="qwen2.5:7b-instruct-q4_K_M",
        timeout=120.0  # 넉넉하게
    )
    
    print(f"\n[설정]")
    print(f"   Ollama URL: {llm_service.ollama_base_url}")
    print(f"   Model: {llm_service.model_name}")
    print(f"   Timeout: {llm_service.timeout}초")
    
    # Ollama 서버 연결 확인
    print(f"\n[연결 확인] Ollama 서버...")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{llm_service.ollama_base_url}/api/tags")
            if response.status_code != 200:
                print(f"   [ERROR] HTTP {response.status_code}")
                return
            models = response.json().get("models", [])
            model_names = [m.get("name") for m in models]
            print(f"   [OK] 연결 성공")
            print(f"   사용 가능 모델: {', '.join(model_names[:3])}")
            
            # 모델 존재 확인
            if llm_service.model_name not in model_names:
                print(f"   [WARNING] {llm_service.model_name} 모델이 목록에 없습니다.")
    except Exception as e:
        print(f"   [ERROR] 연결 실패: {e}")
        print(f"\n   힌트: 'ollama serve' 실행 확인")
        return
    
    print("\n" + "=" * 80)
    print("시간 측정 시작")
    print("=" * 80)
    
    timings = {}
    
    # 1. 데이터 필터링
    print("\n[1/4] 데이터 필터링...")
    t0 = time.perf_counter()
    filtered_data = llm_service.filter_analysis_data(analysis_result)
    t1 = time.perf_counter()
    timings['filter'] = t1 - t0
    print(f"   시간: {timings['filter']*1000:.2f}ms")
    print(f"   필터된 metrics: {list(filtered_data['scores'].keys())}")
    print(f"   데이터 크기: {len(json.dumps(filtered_data))} bytes")
    
    # 2. 프롬프트 생성
    print("\n[2/4] 프롬프트 생성...")
    t0 = time.perf_counter()
    prompt = llm_service.build_feedback_prompt(filtered_data)
    t1 = time.perf_counter()
    timings['prompt'] = t1 - t0
    print(f"   시간: {timings['prompt']*1000:.2f}ms")
    print(f"   프롬프트 길이: {len(prompt)} chars (~{len(prompt)//3} tokens)")
    print(f"\n   [프롬프트 미리보기]")
    lines = prompt.split('\n')[:8]
    for line in lines:
        print(f"   {line[:70]}...")
    
    # 3. Ollama API 호출 (핵심 측정)
    print("\n[3/4] Ollama API 호출 (LLM 추론)...")
    print("   추론 중... (최대 2분 대기)")
    
    t0 = time.perf_counter()
    try:
        feedback_text = await llm_service._call_ollama(prompt)
        t1 = time.perf_counter()
        timings['ollama'] = t1 - t0
        print(f"   시간: {timings['ollama']:.2f}초 = {timings['ollama']*1000:.0f}ms")
        print(f"   생성된 텍스트 길이: {len(feedback_text)} chars")
        
        # 토큰 속도 추정
        estimated_tokens = len(feedback_text) // 2  # 한글은 대략 2 chars/token
        tokens_per_sec = estimated_tokens / timings['ollama'] if timings['ollama'] > 0 else 0
        print(f"   생성 속도: ~{tokens_per_sec:.1f} tokens/sec")
        
    except Exception as e:
        print(f"   [ERROR] Ollama 호출 실패: {e}")
        return
    
    # 4. 전체 generate_feedback (오버헤드 확인)
    print("\n[4/4] 전체 generate_feedback() 호출...")
    t0 = time.perf_counter()
    feedback_result = await llm_service.generate_feedback(analysis_result)
    t1 = time.perf_counter()
    timings['total'] = t1 - t0
    print(f"   시간: {timings['total']:.2f}초 = {timings['total']*1000:.0f}ms")
    
    if feedback_result.get('error'):
        print(f"   [WARNING] 오류: {feedback_result['error']}")
    
    # 결과 저장
    output_file = "llm_timing_result.json"
    result_data = {
        "timings_ms": {
            "filter": round(timings['filter'] * 1000, 2),
            "prompt_build": round(timings['prompt'] * 1000, 2),
            "ollama_inference": round(timings['ollama'] * 1000, 2),
            "total_generate": round(timings['total'] * 1000, 2),
        },
        "timings_sec": {
            "ollama_inference": round(timings['ollama'], 2),
            "total_generate": round(timings['total'], 2),
        },
        "metadata": {
            "model": llm_service.model_name,
            "prompt_length": len(prompt),
            "feedback_length": len(feedback_text),
            "estimated_tokens": len(feedback_text) // 2,
            "tokens_per_sec": round(tokens_per_sec, 2),
        },
        "feedback": feedback_result.get('feedback', '')
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)
    
    # 피드백만 별도 저장
    with open("llm_timing_feedback.txt", 'w', encoding='utf-8') as f:
        f.write(feedback_result.get('feedback', ''))
    
    # 요약
    print("\n" + "=" * 80)
    print("[시간 측정 요약]")
    print("=" * 80)
    performance = "느림 (CPU 추론)" if tokens_per_sec < 10 else "빠름 (GPU 추론)"
    print(f"""
   단계별 시간:
   - 데이터 필터링:     {timings['filter']*1000:7.2f}ms
   - 프롬프트 생성:     {timings['prompt']*1000:7.2f}ms
   - Ollama 추론:       {timings['ollama']:7.2f}초  <--- 병목
   - 전체 (오버헤드):   {timings['total']:7.2f}초
   
   Ollama 비율: {timings['ollama']/timings['total']*100:.1f}% 
   
   성능 지표:
   - 생성 토큰 수 (추정): ~{len(feedback_text)//2} tokens
   - 생성 속도:           ~{tokens_per_sec:.1f} tokens/sec
   - 평가:                {performance}
   
   저장 파일:
   - {output_file}
   - llm_timing_feedback.txt
""")
    
    # 개선 제안
    print("=" * 80)
    print("[개선 제안]")
    print("=" * 80)
    
    if timings['ollama'] > 30:
        print("""
   Ollama 추론이 30초 이상 소요됩니다.
   
   개선 방법:
   1. GPU 사용 확인:
      - ollama ps (추론 중 실행)
      - PROCESSOR 열에 GPU 비율 확인
      
   2. 더 작은 모델 사용:
      - ollama pull qwen2.5:3b  (현재: 7b)
      - llm_feedback.py에서 model_name 변경
      
   3. 프롬프트 단축:
      - num_predict를 800 → 400으로 줄이기
      - 불필요한 breakdown 필드 제거
      
   4. Streaming 응답 고려:
      - 첫 토큰 생성 즉시 클라이언트에 전송
      - 전체 대기 시간 체감 감소
""")
    elif tokens_per_sec < 10:
        print("""
   GPU를 사용하지 않거나 레이어 일부만 GPU에 올라간 것 같습니다.
   
   확인:
   - ollama ps (추론 중)
   - nvidia-smi
   - Ollama 로그 (ggml_cuda_init, offloaded X/29 layers)
""")
    else:
        print("""
   [OK] LLM 추론 성능이 양호합니다.
   
   전체 analyze 파이프라인(1분+)의 병목은 LLM이 아니라,
   영상 추출·정렬·채점 단계일 가능성이 높습니다.
   
   다음 측정 권장:
   - POST /video/analyze 전체 타이밍
   - extract_coordinator (ROM/rhythm/power/creativity 병렬)
   - orchestrator (6 metric 채점 병렬)
""")


if __name__ == "__main__":
    asyncio.run(test_llm_timing())
