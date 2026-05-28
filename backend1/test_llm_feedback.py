"""LLM 피드백 서비스 단독 테스트 스크립트."""

import asyncio
import json
from services.llm_feedback import LLMFeedbackService

# 샘플 분석 결과 (간소화된 버전)
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


async def main():
    print("=" * 60)
    print("LLM 피드백 서비스 테스트")
    print("=" * 60)
    
    # LLM 서비스 초기화
    llm_service = LLMFeedbackService(
        ollama_base_url="http://localhost:11434",
        model_name="qwen2.5:7b-instruct-q4_K_M",
        timeout=60.0
    )
    
    print("\n1. 데이터 필터링 테스트...")
    filtered = llm_service.filter_analysis_data(sample_analysis_result)
    print(f"   - 원본 scores 크기: {len(str(sample_analysis_result['scores']))} chars")
    print(f"   - 필터링된 scores 크기: {len(str(filtered['scores']))} chars")
    print(f"   - 포함된 metrics: {list(filtered['scores'].keys())}")
    
    print("\n2. 프롬프트 생성 테스트...")
    prompt = llm_service.build_feedback_prompt(filtered)
    print(f"   - 프롬프트 길이: {len(prompt)} chars")
    print(f"   - 예상 토큰 수: ~{len(prompt) // 3} tokens")
    print(f"\n   [프롬프트 미리보기]")
    print("   " + "\n   ".join(prompt[:500].split("\n")))
    print("   ...")
    
    print("\n3. Ollama 서버 연결 테스트...")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://localhost:11434/api/tags")
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m.get("name") for m in models]
                print(f"   [OK] Ollama 서버 연결 성공")
                print(f"   [OK] 사용 가능한 모델: {model_names}")
            else:
                print(f"   [ERROR] Ollama 서버 응답 오류: {response.status_code}")
                return
    except Exception as e:
        print(f"   [ERROR] Ollama 서버 연결 실패: {e}")
        print("\n   힌트: 'ollama serve'가 실행 중인지 확인하세요.")
        return
    
    print("\n4. LLM 피드백 생성 테스트...")
    print("   (이 작업은 최대 60초 소요될 수 있습니다...)")
    
    feedback_result = await llm_service.generate_feedback(sample_analysis_result)
    
    print("\n" + "=" * 60)
    print("결과")
    print("=" * 60)
    
    if feedback_result.get("error"):
        print(f"오류 발생: {feedback_result['error']}")
        print(f"\n폴백 피드백:\n{feedback_result['feedback']}")
    else:
        print(f"모델: {feedback_result['model']}")
        print(f"\n생성된 피드백:")
        
        # 파일로 저장 (Unicode 출력 문제 회피)
        with open("llm_feedback_result.json", "w", encoding="utf-8") as f:
            json.dump(feedback_result, f, ensure_ascii=False, indent=2)
        print("   -> llm_feedback_result.json 파일로 저장됨")
        
        # 피드백 텍스트만 별도 저장
        with open("llm_feedback_text.txt", "w", encoding="utf-8") as f:
            f.write(feedback_result['feedback'])
        print("   -> llm_feedback_text.txt 파일로 저장됨")
        
        print(f"\n   피드백 길이: {len(feedback_result['feedback'])} chars")


if __name__ == "__main__":
    asyncio.run(main())
