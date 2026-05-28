"""음악 시작·박자·정렬 스모크 체크 (extract 없이 beats + ref.json)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND1 = Path(__file__).resolve().parents[3]
if str(_BACKEND1) not in sys.path:
    sys.path.insert(0, str(_BACKEND1))

from metrics.isolation.align import align_from_paths
from metrics.isolation.align.beat_detect import (
    beats_from_music_start,
    estimate_beat_lag_sec,
    load_beat_map,
)
from metrics.isolation.config import REF_COMPARE_DURATION_SEC
from metrics.isolation.pipeline.io import load_extraction_json
from metrics.isolation.score import score_from_alignment

DATA = Path(__file__).resolve().parents[1] / "data"


def main() -> None:
    ref_beats = load_beat_map(DATA / "artifacts" / "ref_beats.json")
    user_beats_path = DATA / "artifacts" / "user_beats.json"
    ref_json = DATA / "artifacts" / "ref.json"
    user_json = DATA / "artifacts" / "user.json"

    print("=== beats / music start ===")
    for label, bd in [("ref", ref_beats), ("user", load_beat_map(user_beats_path))]:
        start, window = beats_from_music_start(bd, max_duration_sec=REF_COMPARE_DURATION_SEC)
        print(
            f"  {label}: music_start={start:.3f}s bpm={bd.get('bpm')} "
            f"beats_in_{REF_COMPARE_DURATION_SEC}s={len(window)}"
        )

    rs, rb = beats_from_music_start(ref_beats, max_duration_sec=REF_COMPARE_DURATION_SEC)
    us, ub = beats_from_music_start(
        load_beat_map(user_beats_path), max_duration_sec=REF_COMPARE_DURATION_SEC
    )
    lag = estimate_beat_lag_sec(rb, ub)
    print(f"  beat_lag_sec (ref-user): {lag:.4f}")

    if not ref_json.is_file():
        print("ref.json 없음 — extract ref 먼저")
        sys.exit(1)

    print("\n=== align ref vs ref (smoke) ===")
    aligned = align_from_paths(ref_json, ref_json, method="beat")
    a = aligned["alignment"]
    print(f"  pairs={a.get('pair_count')} ref_music_start={a.get('ref_music_start_sec')} "
          f"user_music_start={a.get('user_music_start_sec')} beat_lag={a.get('beat_lag_sec')}")
    if a.get("warning"):
        print(f"  warning: {a['warning']}")

    scored = score_from_alignment(aligned)
    print(f"  self-score={scored.get('score')}")

    if not user_json.is_file():
        print("\n=== user.json 없음 ===")
        print("  conda activate aiproject 후:")
        print("  python -m metrics.isolation.cli extract --video metrics/isolation/data/raw/user.mp4")
        print("  python -m metrics.isolation.cli run --user-video metrics/isolation/data/raw/user.mp4 --json")
        return

    print("\n=== align ref vs user + score ===")
    aligned_u = align_from_paths(user_json, ref_json, method="beat")
    au = aligned_u["alignment"]
    print(f"  pairs={au.get('pair_count')} beat_lag={au.get('beat_lag_sec')} "
          f"ref_bpm={au.get('ref_bpm')} user_bpm={au.get('user_bpm')}")
    if au.get("warning"):
        print(f"  warning: {au['warning']}")
    scored_u = score_from_alignment(aligned_u)
    print(f"  isolation score={scored_u.get('score')}")
    bd = scored_u.get("breakdown") or {}
    print(f"  coupling user={bd.get('mean_user_coupling')} ref={bd.get('mean_ref_coupling')}")


if __name__ == "__main__":
    main()
