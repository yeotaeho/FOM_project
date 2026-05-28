"""
LLM 기반 댄스 피드백 생성 서비스.

Ollama qwen2.5:7b-instruct-q4_K_M을 이용하여
전문가-사용자 비교 분석 데이터를 기반으로 한국어 피드백 생성.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional
import httpx


class LLMFeedbackService:
    """Ollama를 통한 댄스 피드백 생성."""
    
    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434",
        model_name: str = "qwen2.5:7b-instruct-q4_K_M",
        timeout: float = 60.0,
    ):
        self.ollama_base_url = ollama_base_url
        self.model_name = model_name
        self.timeout = timeout
    
    def filter_analysis_data(
        self, 
        analysis_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        LLM 컨텍스트 제한에 맞춰 분석 데이터 필터링.
        
        Args:
            analysis_result: orchestrator.orchestrate_analysis_pipeline() 결과
        
        Returns:
            필터링된 데이터 (토큰 절약)
        """
        scores = analysis_result.get("scores", {})
        alignment = analysis_result.get("alignment", {})
        meta = analysis_result.get("meta", {})
        
        # 각 metric별 요약 정보만 추출
        filtered_scores = {
            "accuracy": self._extract_accuracy_summary(scores.get("accuracy")),
            "creativity": self._extract_creativity_summary(scores.get("creativity")),
            "isolation": self._extract_isolation_summary(scores.get("isolation")),
            "power": self._extract_power_summary(scores.get("power")),
            "rhythm": self._extract_rhythm_summary(scores.get("rhythm")),
            "rom": self._extract_rom_summary(scores.get("rom")),
            "total_score": scores.get("total_score"),
            "grade": scores.get("grade"),
        }
        
        # None 값 제거 (실행되지 않은 metric)
        filtered_scores = {k: v for k, v in filtered_scores.items() if v is not None}
        
        filtered_alignment = {
            "method": alignment.get("method"),
            "aligned_pairs": alignment.get("aligned_pairs"),
            "user_frames": alignment.get("user_frames"),
            "ref_frames": alignment.get("ref_frames"),
            "duplicate_ratio": alignment.get("duplicate_ratio"),
            "warning": alignment.get("warning"),
        }
        
        filtered_meta = {
            "metrics_run": meta.get("metrics_run"),
            "detail_level": meta.get("detail_level"),
            "user_fps": meta.get("user_fps"),
            "user_total_frames": meta.get("user_total_frames"),
            "reference_fps": meta.get("reference_fps"),
            "reference_total_frames": meta.get("reference_total_frames"),
            "warnings": meta.get("warnings", []),
        }
        
        return {
            "scores": filtered_scores,
            "alignment": filtered_alignment,
            "meta": filtered_meta,
        }
    
    def _extract_accuracy_summary(self, accuracy_data: Optional[Dict]) -> Optional[Dict]:
        """Accuracy metric 요약."""
        if not accuracy_data:
            return None
        breakdown = accuracy_data.get("breakdown", {})
        return {
            "score": accuracy_data.get("score"),
            "grade": accuracy_data.get("grade"),
            "mean_similarity": breakdown.get("mean_similarity"),
            "joint_angle_errors": breakdown.get("joint_angle_errors", {}) if isinstance(breakdown.get("joint_angle_errors"), dict) else None,
        }
    
    def _extract_creativity_summary(self, creativity_data: Optional[Dict]) -> Optional[Dict]:
        """Creativity metric 요약."""
        if not creativity_data:
            return None
        breakdown = creativity_data.get("breakdown", {})
        return {
            "score": creativity_data.get("score"),
            "mean_divergence": breakdown.get("mean_divergence"),
            "std_divergence": breakdown.get("std_divergence"),
            "mean_motion": breakdown.get("mean_motion"),
        }
    
    def _extract_isolation_summary(self, isolation_data: Optional[Dict]) -> Optional[Dict]:
        """Isolation metric 요약."""
        if not isolation_data:
            return None
        breakdown = isolation_data.get("breakdown", {})
        return {
            "score": isolation_data.get("score"),
            "mean_coupling_ratio": breakdown.get("mean_coupling_ratio"),
            "region_isolation": breakdown.get("region_isolation", {}),
        }
    
    def _extract_power_summary(self, power_data: Optional[Dict]) -> Optional[Dict]:
        """Power metric 요약."""
        if not power_data:
            return None
        breakdown = power_data.get("breakdown", {})
        return {
            "score": power_data.get("score"),
            "composite_score": breakdown.get("composite"),
            "weighted_velocity_mean": breakdown.get("w_vel_mean"),
            "weighted_velocity_p95": breakdown.get("w_vel_p95"),
            "weighted_accel_mean": breakdown.get("w_acc_mean"),
        }
    
    def _extract_rhythm_summary(self, rhythm_data: Optional[Dict]) -> Optional[Dict]:
        """Rhythm metric 요약."""
        if not rhythm_data:
            return None
        breakdown = rhythm_data.get("breakdown", {})
        return {
            "score": rhythm_data.get("score"),
            "consistency_score": breakdown.get("consistency_score"),
            "dtw_score": breakdown.get("dtw_score"),
            "peak_count": breakdown.get("peak_count"),
            "cv": breakdown.get("cv"),
        }
    
    def _extract_rom_summary(self, rom_data: Optional[Dict]) -> Optional[Dict]:
        """ROM metric 요약."""
        if not rom_data:
            return None
        breakdown = rom_data.get("breakdown", {})
        return {
            "score": rom_data.get("score"),
            "grade": rom_data.get("grade"),
            "mean_coverage": breakdown.get("mean_coverage"),
            "active_joints": breakdown.get("active_joints"),
            "static_joints": breakdown.get("static_joints"),
        }
    
    def build_feedback_prompt(
        self, 
        filtered_data: Dict[str, Any]
    ) -> str:
        """
        한국어 피드백 생성을 위한 프롬프트 구성.
        
        Args:
            filtered_data: filter_analysis_data() 결과
        
        Returns:
            LLM에 전달할 프롬프트 문자열
        """
        scores = filtered_data.get("scores", {})
        
        # JSON 직렬화 (읽기 쉽게)
        data_json = json.dumps(filtered_data, ensure_ascii=False, indent=2)
        
        total_score = scores.get("total_score", 0)
        grade = scores.get("grade", "N/A")
        
        # 각 metric 설명
        metric_descriptions = {
            "accuracy": "정확성 - 전문가 동작과 자세 일치도",
            "creativity": "창의성 - 동작의 다양성과 독창성",
            "isolation": "아이솔레이션 - 신체 부위별 독립적 움직임",
            "power": "파워 - 동작의 폭발력과 운동 강도",
            "rhythm": "리듬 - 박자 정확도와 동작 규칙성",
            "rom": "가동범위 - 관절 움직임 범위"
        }
        
        prompt = f"""당신은 전문 댄스 코치입니다. 아래는 사용자의 댄스 영상과 전문가 영상을 비교 분석한 결과입니다.

# 분석 데이터
{data_json}

# 평가 항목 설명
"""
        for metric_key, desc in metric_descriptions.items():
            if metric_key in scores:
                prompt += f"- {desc}\n"
        
        prompt += f"""
# 요청사항
위 분석 결과를 바탕으로 사용자에게 구체적이고 실용적인 피드백을 한국어로 작성해주세요.

## 피드백 구성 요구사항:
1. **전체 평가** (2-3문장): 총점 {total_score:.1f}점, 등급 {grade}에 대한 종합 평가
2. **강점** (1-2가지): 가장 점수가 높은 항목을 언급하고 구체적으로 칭찬
3. **개선점** (2-3가지): 점수가 낮은 항목을 중심으로 구체적인 개선 방법 제시
4. **우선 연습 포인트** (1-2가지): 가장 먼저 집중해야 할 부분

## 주의사항:
- 전문적이면서도 친근한 톤 유지
- 구체적인 수치나 기술 용어는 최소화하고 이해하기 쉽게 설명
- 부정적 표현보다는 발전 가능성을 강조
- 200-400자 정도의 간결한 피드백

피드백:"""
        
        return prompt
    
    async def generate_feedback(
        self, 
        analysis_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        분석 데이터로부터 LLM 피드백 생성.
        
        Args:
            analysis_result: orchestrator.orchestrate_analysis_pipeline() 결과
        
        Returns:
            {
                "feedback": str,  # 생성된 피드백 텍스트
                "model": str,     # 사용된 모델명
                "filtered_data": dict,  # LLM에 전달된 데이터
                "error": Optional[str]  # 오류 발생 시
            }
        """
        try:
            # 1. 데이터 필터링
            filtered_data = self.filter_analysis_data(analysis_result)
            
            # 2. 프롬프트 생성
            prompt = self.build_feedback_prompt(filtered_data)
            
            # 3. Ollama API 호출
            feedback_text = await self._call_ollama(prompt)
            
            return {
                "feedback": feedback_text,
                "model": self.model_name,
                "filtered_data": filtered_data,
                "error": None,
            }
        
        except Exception as e:
            return {
                "feedback": self._get_fallback_feedback(analysis_result),
                "model": self.model_name,
                "filtered_data": None,
                "error": str(e),
            }
    
    async def _call_ollama(self, prompt: str) -> str:
        """
        Ollama API 호출.
        
        Args:
            prompt: LLM에 전달할 프롬프트
        
        Returns:
            생성된 텍스트
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.ollama_base_url}/api/generate",
                json={
                    "model": self.model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "num_predict": 800,  # 피드백 길이 제한
                    },
                },
            )
            response.raise_for_status()
            result = response.json()
            return result.get("response", "").strip()
    
    def _get_fallback_feedback(self, analysis_result: Dict[str, Any]) -> str:
        """
        LLM 호출 실패 시 기본 피드백 생성.
        
        Args:
            analysis_result: 분석 결과
        
        Returns:
            기본 피드백 텍스트
        """
        scores = analysis_result.get("scores", {})
        total_score = scores.get("total_score", 0)
        grade = scores.get("grade", "N/A")
        
        # 가장 높은 점수와 낮은 점수 찾기
        metric_scores = {
            k: v.get("score", 0) if isinstance(v, dict) else 0
            for k, v in scores.items()
            if k not in ["total_score", "grade"]
        }
        
        if metric_scores:
            best_metric = max(metric_scores.items(), key=lambda x: x[1])
            worst_metric = min(metric_scores.items(), key=lambda x: x[1])
            
            metric_names = {
                "accuracy": "정확성",
                "creativity": "창의성",
                "isolation": "아이솔레이션",
                "power": "파워",
                "rhythm": "리듬",
                "rom": "가동범위"
            }
            
            return f"""분석이 완료되었습니다.

총점: {total_score:.1f}점 (등급: {grade})

강점: {metric_names.get(best_metric[0], best_metric[0])} 항목에서 {best_metric[1]:.1f}점으로 우수한 성과를 보였습니다.

개선 포인트: {metric_names.get(worst_metric[0], worst_metric[0])} 항목({worst_metric[1]:.1f}점)에 집중하여 연습하시면 더욱 발전할 수 있습니다.

계속해서 연습하시면 실력이 향상될 것입니다!"""
        
        return f"""분석이 완료되었습니다.

총점: {total_score:.1f}점 (등급: {grade})

더 자세한 피드백은 각 항목별 점수를 참고해주세요.
계속해서 연습하시면 실력이 향상될 것입니다!"""


# 싱글톤 인스턴스 (필요시)
_llm_service: Optional[LLMFeedbackService] = None


def get_llm_feedback_service() -> LLMFeedbackService:
    """LLMFeedbackService 싱글톤 인스턴스 반환."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMFeedbackService()
    return _llm_service
