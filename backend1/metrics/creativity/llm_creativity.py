"""
창의성 하이브리드 채점 — 수식 점수 × LLM 보정 계수 (방안 1).

Ollama 로 경계 케이스(너무 유사·의도적 변형 등)만 소폭 조정. 실패 시 adjustment=1.0.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .pose_compare import clamp

ADJUSTMENT_MIN = 0.80
ADJUSTMENT_MAX = 1.20
DEFAULT_ADJUSTMENT = 1.0
_DEFAULT_OLLAMA_URL = "http://localhost:11434"
_DEFAULT_MODEL = "qwen2.5:7b-instruct-q4_K_M"
_DEFAULT_TIMEOUT = 60.0
_MAX_FRAME_SAMPLES = 8


def _ollama_config() -> tuple[str, str, float]:
    return _DEFAULT_OLLAMA_URL, _DEFAULT_MODEL, _DEFAULT_TIMEOUT


def summarize_for_llm(
    breakdown: dict[str, Any],
    frame_diffs: list[dict[str, Any]],
    *,
    max_frames: int = _MAX_FRAME_SAMPLES,
) -> dict[str, Any]:
    """LLM 컨텍스트용 요약 (토큰 절약)."""
    usable = [
        d
        for d in frame_diffs
        if d.get("divergence") is not None and not d.get("skipped")
    ]
    n = len(usable)
    if n <= max_frames:
        sample = usable
    else:
        step = max(1, n // max_frames)
        sample = [usable[i] for i in range(0, n, step)][:max_frames]

    divs = [float(d["divergence"]) for d in sample]
    return {
        "formula_score": breakdown.get("formula_score"),
        "mean_divergence": breakdown.get("mean_divergence"),
        "divergence_std": breakdown.get("divergence_std"),
        "motion_intensity": breakdown.get("motion_intensity"),
        "divergence_band_factor": breakdown.get("divergence_band_factor"),
        "dtw_penalty_factor": breakdown.get("dtw_penalty_factor"),
        "effective_band_factor": breakdown.get("effective_band_factor"),
        "combined_raw": breakdown.get("combined_raw"),
        "combined_after_baseline": breakdown.get("combined_after_baseline"),
        "baseline_subtracted": breakdown.get("baseline_subtracted"),
        "baseline_mean_divergence": breakdown.get("baseline_mean_divergence"),
        "dtw_mean_cost": breakdown.get("dtw_mean_cost"),
        "pairs_used": breakdown.get("pairs_used"),
        "pairs_evaluated": breakdown.get("pairs_evaluated"),
        "frame_divergence_sample": [
            {
                "user_frame": d.get("user_frame"),
                "ref_frame": d.get("ref_frame"),
                "divergence": round(float(d["divergence"]), 4),
            }
            for d in sample
        ],
        "frame_divergence_min": round(min(divs), 4) if divs else None,
        "frame_divergence_max": round(max(divs), 4) if divs else None,
    }


def build_adjustment_prompt(summary: dict[str, Any]) -> str:
    data_json = json.dumps(summary, ensure_ascii=False, indent=2)
    return f"""당신은 스트릿 댄스 창의성 평가 보조자입니다.
레퍼런스 대비 사용자 동작의 **다양성·독창성**을 수식 점수가 이미 계산했습니다.
수식 점수를 **대체하지 말고**, 경계 케이스만 소폭 보정하는 계수를 제안하세요.

## 수식 채점 요약 (0~100, formula_score)
{data_json}

## 보정 규칙
- creativity_adjustment: 0.80 ~ 1.20 (1.0 = 변경 없음)
- mean_divergence가 적정 구간(대략 0.22~0.55)이고 motion·std가 충분하면 1.05~1.15 가능
- 거의 동일 동작(낮은 divergence·낮은 std)이면 0.80~0.95
- 무작위·노이즈만 크면(높은 std, 낮은 motion) 0.85~0.95
- baseline 대비 combined_after_baseline이 매우 낮은데 frame 샘플이 다양하면 신중히 1.0~1.08
- **반드시 JSON만** 출력 (마크다운 코드블록 없이):

{{
  "creativity_adjustment": 1.0,
  "rationale": "한 문장 한국어",
  "flags": ["optional_tag"]
}}

flags 예: too_similar, good_variation, repetitive, noisy, high_motion"""


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def parse_llm_adjustment_response(raw: str) -> dict[str, Any]:
    parsed = _extract_json_object(raw)
    if not parsed:
        raise ValueError("LLM 응답에서 JSON을 파싱할 수 없습니다.")

    adj = float(parsed.get("creativity_adjustment", DEFAULT_ADJUSTMENT))
    adj = clamp(adj, ADJUSTMENT_MIN, ADJUSTMENT_MAX)
    rationale = str(parsed.get("rationale", "")).strip()[:500]
    flags_raw = parsed.get("flags") or []
    flags = [str(f) for f in flags_raw if f][:8] if isinstance(flags_raw, list) else []

    return {
        "creativity_adjustment": round(adj, 4),
        "rationale": rationale,
        "flags": flags,
    }


def call_ollama_sync(prompt: str) -> str:
    base_url, model, timeout = _ollama_config()
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "top_p": 0.9,
                    "num_predict": 256,
                },
            },
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()


def request_llm_adjustment(
    breakdown: dict[str, Any],
    frame_diffs: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Ollama 호출 → 보정 계수 dict.
    실패 시 creativity_adjustment=1.0, error 필드 포함.
    """
    _, model, _ = _ollama_config()
    summary = summarize_for_llm(breakdown, frame_diffs)
    try:
        raw = call_ollama_sync(build_adjustment_prompt(summary))
        result = parse_llm_adjustment_response(raw)
        result["model"] = model
        result["error"] = None
        result["llm_input_summary"] = summary
        return result
    except Exception as exc:
        return {
            "creativity_adjustment": DEFAULT_ADJUSTMENT,
            "rationale": "",
            "flags": [],
            "model": model,
            "error": str(exc),
            "llm_input_summary": summary,
        }


def apply_llm_hybrid_to_creativity(creativity_result: dict[str, Any]) -> dict[str, Any]:
    """
    score_creativity 결과에 LLM 보정 적용.

    최종 score = clamp(formula_score * creativity_adjustment, 0, 100)
    """
    breakdown = dict(creativity_result.get("breakdown") or {})
    frame_diffs = creativity_result.get("frame_diffs") or []

    if breakdown.get("reason"):
        breakdown["llm_applied"] = False
        breakdown["llm_skip_reason"] = breakdown.get("reason")
        creativity_result["breakdown"] = breakdown
        return creativity_result

    formula_score = float(creativity_result.get("score", 0.0))
    breakdown["formula_score"] = round(formula_score, 2)
    breakdown["scoring_mode"] = "hybrid_formula_x_llm"

    llm = request_llm_adjustment(breakdown, frame_diffs)
    adjustment = float(llm["creativity_adjustment"])
    adjusted_score = clamp(formula_score * adjustment, 0.0, 100.0)

    breakdown["llm_applied"] = llm.get("error") is None
    breakdown["llm_adjustment"] = adjustment
    breakdown["llm_rationale"] = llm.get("rationale", "")
    breakdown["llm_flags"] = llm.get("flags", [])
    breakdown["llm_model"] = llm.get("model")
    breakdown["score_after_llm"] = round(adjusted_score, 2)
    if llm.get("error"):
        breakdown["llm_error"] = llm["error"]

    out = dict(creativity_result)
    out["score"] = round(adjusted_score, 2)
    out["breakdown"] = breakdown
    out["llm_hybrid"] = {
        "creativity_adjustment": adjustment,
        "formula_score": round(formula_score, 2),
        "score_after_llm": round(adjusted_score, 2),
        "rationale": llm.get("rationale", ""),
        "flags": llm.get("flags", []),
        "model": llm.get("model"),
        "error": llm.get("error"),
    }
    return out
