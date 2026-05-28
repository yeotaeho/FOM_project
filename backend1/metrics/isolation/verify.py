"""통합 검증 — 음악 싱크 · beat 정렬 · isolation 점수 · 기준 요약."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from metrics.isolation.align import align_from_paths
from metrics.isolation.align.beat_detect import (
    beats_for_extraction,
    beats_from_music_start,
    detect_beats_from_video,
    estimate_beat_lag_sec,
    save_beat_map,
)
from metrics.isolation.config import (
    ALIGN_TO_MUSIC_START,
    DATA_ARTIFACTS,
    DATA_RAW,
    DEFAULT_ALIGNMENT_METHOD,
    REF_COMPARE_DURATION_SEC,
    REF_VIDEO_NAME,
    USER_VIDEO_NAME,
)
from metrics.isolation.score import score_from_alignment

REF_BEATS_PATH = DATA_ARTIFACTS / "ref_beats.json"
USER_BEATS_PATH = DATA_ARTIFACTS / "user_beats.json"
REF_JSON = DATA_ARTIFACTS / "ref.json"
USER_JSON = DATA_ARTIFACTS / "user.json"

BPM_WARN_DELTA = 8.0
BEAT_LAG_WARN_SEC = 2.0
MIN_BEATS_IN_WINDOW = 4

SCORING_CRITERIA: List[Dict[str, str]] = [
    {
        "id": "music_start",
        "title": "음악 시작 시각",
        "detail": "영상 0초가 아니라 오디오 onset/첫 비트로 music_start_sec 를 잡고, 그 시점부터 비교합니다.",
    },
    {
        "id": "compare_window",
        "title": "비교 구간",
        "detail": f"ref: music_start ~ music_start+{REF_COMPARE_DURATION_SEC}s 구간의 포즈·비트만 사용합니다.",
    },
    {
        "id": "beat_align",
        "title": "박자 정렬",
        "detail": "같은 비트 인덱스끼리 user/ref 프레임을 매칭합니다 (beat_lag_sec 로 곡 간 오프셋 보정).",
    },
    {
        "id": "isolation_score",
        "title": "Isolation 점수",
        "detail": "각 전환마다 ref에서 가장 많이 움직인 bone 대비, user의 비목표 bone 연동(coupling)이 크면 감점. 박자 정확도 자체를 직접 채점하지 않습니다.",
    },
    {
        "id": "coupling",
        "title": "연동(coupling)",
        "detail": "mean_user_coupling > mean_ref_coupling 이면 목표 부위 외에 몸이 더 같이 움직이는 경향입니다.",
    },
]


def _check(label: str, ok: bool, detail: str, *, warn: bool = False) -> Dict[str, Any]:
    status = "ok" if ok else ("warn" if warn else "fail")
    return {"label": label, "status": status, "detail": detail}


def run_verify(
    *,
    ref_video: Path,
    user_video: Path,
    ref_json: Path = REF_JSON,
    user_json: Path = USER_JSON,
    ref_beats_path: Path = REF_BEATS_PATH,
    user_beats_path: Path = USER_BEATS_PATH,
    alignment_method: str = DEFAULT_ALIGNMENT_METHOD,
    ref_compare_duration_sec: float = REF_COMPARE_DURATION_SEC,
    user_offset_sec: float = 0.0,
    ref_offset_sec: float = 0.0,
    auto_detect_start: bool = False,
    skip_beats_refresh: bool = False,
    run_pose_score: bool = True,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "status": "ok",
        "videos": {
            "ref": str(ref_video.resolve()) if ref_video.is_file() else str(ref_video),
            "user": str(user_video.resolve()) if user_video.is_file() else str(user_video),
        },
        "config": {
            "alignment_method": alignment_method,
            "align_to_music_start": ALIGN_TO_MUSIC_START,
            "ref_compare_duration_sec": ref_compare_duration_sec,
        },
        "scoring_criteria": SCORING_CRITERIA,
        "checks": [],
        "music_sync": None,
        "alignment": None,
        "isolation": None,
        "hints": [],
    }

    def add_check(c: Dict[str, Any]) -> None:
        report["checks"].append(c)
        if c["status"] == "fail":
            report["status"] = "fail"
        elif c["status"] == "warn" and report["status"] == "ok":
            report["status"] = "warn"

    if not ref_video.is_file():
        add_check(_check("ref 영상", False, f"없음: {ref_video}"))
        return report
    if not user_video.is_file():
        add_check(_check("user 영상", False, f"없음: {user_video}"))
        return report
    add_check(_check("ref/user mp4", True, "로컬 파일 확인"))

    # --- beats / music sync ---
    try:
        if skip_beats_refresh and ref_beats_path.is_file() and user_beats_path.is_file():
            from metrics.isolation.align.beat_detect import load_beat_map

            ref_bd = load_beat_map(ref_beats_path)
            user_bd = load_beat_map(user_beats_path)
        else:
            ref_bd = detect_beats_from_video(ref_video)
            save_beat_map(ref_bd, ref_beats_path)
            user_bd = detect_beats_from_video(user_video)
            save_beat_map(user_bd, user_beats_path)
    except Exception as e:
        add_check(_check("비트 추출", False, str(e)))
        report["hints"].append("librosa, soundfile, imageio-ffmpeg 설치 및 mp4 오디오 확인")
        return report

    compare_dur = ref_compare_duration_sec or REF_COMPARE_DURATION_SEC
    ref_start, ref_beats_w = beats_from_music_start(ref_bd, max_duration_sec=compare_dur)
    user_start, user_beats_w = beats_from_music_start(
        user_bd, max_duration_sec=compare_dur + 6.0
    )
    beat_lag = estimate_beat_lag_sec(ref_beats_w, user_beats_w)
    ref_bpm = float(ref_bd.get("bpm") or 0)
    user_bpm = float(user_bd.get("bpm") or 0)
    bpm_delta = abs(ref_bpm - user_bpm) if ref_bpm and user_bpm else None

    report["music_sync"] = {
        "ref_music_start_sec": ref_start,
        "user_music_start_sec": user_start,
        "ref_bpm": ref_bpm,
        "user_bpm": user_bpm,
        "bpm_delta": round(bpm_delta, 2) if bpm_delta is not None else None,
        "beat_lag_sec": round(beat_lag, 4),
        "ref_beats_in_window": len(ref_beats_w),
        "user_beats_in_window": len(user_beats_w),
        "ref_beats_path": str(ref_beats_path),
        "user_beats_path": str(user_beats_path),
    }

    add_check(
        _check(
            "비트 추출",
            len(ref_beats_w) >= MIN_BEATS_IN_WINDOW
            and len(user_beats_w) >= MIN_BEATS_IN_WINDOW,
            f"ref={len(ref_beats_w)} user={len(user_beats_w)} beats (음악 시작 후 {compare_dur}s)",
        )
    )
    if bpm_delta is not None:
        add_check(
            _check(
                "BPM 유사",
                bpm_delta <= BPM_WARN_DELTA,
                f"ref={ref_bpm} user={user_bpm} delta={bpm_delta:.1f}",
                warn=bpm_delta > BPM_WARN_DELTA,
            )
        )
    add_check(
        _check(
            "beat_lag",
            abs(beat_lag) <= BEAT_LAG_WARN_SEC,
            f"beat_lag_sec={beat_lag:.4f} (|lag|<={BEAT_LAG_WARN_SEC}s 권장)",
            warn=abs(beat_lag) > BEAT_LAG_WARN_SEC,
        )
    )

    if not ref_json.is_file():
        add_check(_check("ref.json", False, f"없음: {ref_json} — 먼저 extract ref"))
        report["hints"].append(
            "python -m metrics.isolation.cli extract  # ref.mp4 → ref.json"
        )
        return report
    add_check(_check("ref.json", True, ref_json.name))

    if not run_pose_score:
        add_check(
            _check(
                "isolation 점수",
                True,
                "beats-only 모드 — user.json·정렬·score 생략 (음악 싱크만 확인)",
            )
        )
        return report

    if not user_json.is_file():
        add_check(
            _check(
                "user.json",
                False,
                f"없음: {user_json}",
                warn=True,
            )
        )
        report["status"] = "partial" if report["status"] != "fail" else "fail"
        report["hints"].append(
            "점수까지: python -m metrics.isolation.cli verify --with-extract "
            "또는 extract user 후 verify"
        )
        return report

    add_check(_check("user.json", True, user_json.name))

    # --- align + score ---
    try:
        from metrics.isolation.pipeline.io import load_extraction_json

        aligned = align_from_paths(
            user_json,
            ref_json,
            method=alignment_method,  # type: ignore[arg-type]
            user_offset_sec=user_offset_sec,
            ref_offset_sec=ref_offset_sec,
            auto_detect_start=auto_detect_start,
            ref_compare_duration_sec=ref_compare_duration_sec,
            user_video_path=user_video,
            ref_video_path=ref_video,
        )
        scored = score_from_alignment(aligned)
    except Exception as e:
        add_check(_check("정렬·채점", False, str(e)))
        return report

    al = scored.get("alignment") or {}
    bd = scored.get("breakdown") or {}
    report["alignment"] = al
    report["isolation"] = {
        "score": scored.get("score"),
        "breakdown": bd,
    }

    pair_count = int(al.get("pair_count") or 0)
    dup = float(al.get("duplicate_ref_ratio") or 0)
    add_check(
        _check(
            "프레임 쌍",
            pair_count > 0,
            f"pair_count={pair_count}",
        )
    )
    if dup > 0.3:
        add_check(
            _check(
                "ref 중복 매칭",
                False,
                f"duplicate_ref_ratio={dup:.2f} (30% 초과)",
                warn=True,
            )
        )
    if al.get("warning"):
        add_check(_check("정렬 경고", True, str(al["warning"]), warn=True))

    mean_u = bd.get("mean_user_coupling")
    mean_r = bd.get("mean_ref_coupling")
    if mean_u is not None and mean_r is not None:
        add_check(
            _check(
                "연동 비교",
                float(mean_u) <= float(mean_r) * 1.15,
                f"user_coupling={mean_u} ref_coupling={mean_r}",
                warn=float(mean_u) > float(mean_r),
            )
        )

    score_val = scored.get("score")
    if score_val is not None:
        add_check(
            _check(
                "isolation 점수",
                True,
                f"score={score_val} / 100 (높을수록 ref 대비 분리·연동 양호)",
            )
        )

    return report


def format_report_text(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append(f"ISOLATION VERIFY  status={report.get('status', '?')}")
    lines.append("=" * 60)

    ms = report.get("music_sync")
    if ms:
        lines.append("\n[음악 싱크]")
        lines.append(f"  ref music_start : {ms.get('ref_music_start_sec')}s")
        lines.append(f"  user music_start: {ms.get('user_music_start_sec')}s")
        lines.append(f"  BPM ref/user    : {ms.get('ref_bpm')} / {ms.get('user_bpm')}  (delta={ms.get('bpm_delta')})")
        lines.append(f"  beat_lag_sec    : {ms.get('beat_lag_sec')}")
        lines.append(f"  beats in window : ref={ms.get('ref_beats_in_window')} user={ms.get('user_beats_in_window')}")

    al = report.get("alignment")
    if al:
        lines.append("\n[박자 정렬]")
        for k in (
            "method",
            "align_to_music_start",
            "ref_music_start_sec",
            "user_music_start_sec",
            "ref_compare_duration_sec",
            "beat_lag_sec",
            "pair_count",
            "duplicate_ref_ratio",
        ):
            if k in al:
                lines.append(f"  {k}: {al[k]}")
        if al.get("warning"):
            lines.append(f"  warning: {al['warning']}")

    iso = report.get("isolation")
    if iso:
        lines.append("\n[Isolation 점수]")
        lines.append(f"  score: {iso.get('score')}")
        bd = iso.get("breakdown") or {}
        lines.append(f"  mean_user_coupling: {bd.get('mean_user_coupling')}")
        lines.append(f"  mean_ref_coupling : {bd.get('mean_ref_coupling')}")
        lines.append(f"  scored_transitions: {bd.get('scored_transitions')}")
        wf = bd.get("worst_frames") or []
        if wf:
            lines.append("  worst_frames (상위 3):")
            for w in wf[:3]:
                lines.append(
                    f"    user_f={w.get('user_frame')} ref_f={w.get('ref_frame')} "
                    f"target={w.get('target_bone')} score={w.get('score')}"
                )

    lines.append("\n[채점 기준 요약]")
    for c in report.get("scoring_criteria") or []:
        lines.append(f"  · {c.get('title')}: {c.get('detail')}")

    lines.append("\n[체크리스트]")
    for ch in report.get("checks") or []:
        mark = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}.get(ch.get("status"), "?")
        lines.append(f"  [{mark}] {ch.get('label')}: {ch.get('detail')}")

    hints = report.get("hints") or []
    if hints:
        lines.append("\n[다음 단계]")
        for h in hints:
            lines.append(f"  - {h}")

    lines.append("")
    return "\n".join(lines)
