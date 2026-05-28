"""Isolation 로컬 CLI — download · track · extract · align · score · run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BACKEND1 = Path(__file__).resolve().parents[2]
if str(_BACKEND1) not in sys.path:
    sys.path.insert(0, str(_BACKEND1))
_ROM_ROOT = _BACKEND1 / "metrics" / "rom"
if str(_ROM_ROOT) not in sys.path:
    sys.path.append(str(_ROM_ROOT))

from metrics.isolation.align import align_and_save, detect_beats_from_video, save_beat_map
from metrics.isolation.config import (
    DATA_ARTIFACTS,
    DATA_RAW,
    DEFAULT_ALIGNMENT_METHOD,
    REF_COMPARE_DURATION_SEC,
    REF_VIDEO_NAME,
    USER_VIDEO_NAME,
    USER_VIDEO_URL,
    YOLO_MODEL,
)
from metrics.isolation.pipeline.extract import extract_and_save
from metrics.isolation.pipeline.io import save_json
from metrics.isolation.pipeline.tracker import PersonTracker
from metrics.isolation.score import (
    score_from_alignment,
    score_from_paths,
    score_isolation,
)


def cmd_download(args: argparse.Namespace) -> None:
    from metrics.isolation.scripts.download_videos import download
    from metrics.isolation.config import REF_VIDEO_URL

    force = getattr(args, "force", False)
    if getattr(args, "ref_only", False):
        ref_path = DATA_RAW / REF_VIDEO_NAME
        print(f"[ref] {args.ref_url or REF_VIDEO_URL}")
        download(args.ref_url or REF_VIDEO_URL, ref_path, force=force)
        print(f"  → {ref_path.resolve()}")
        return
    if getattr(args, "user_only", False):
        user_path = DATA_RAW / USER_VIDEO_NAME
        user_url = args.user_url or USER_VIDEO_URL
        print(f"[user] {user_url}")
        download(user_url, user_path, force=force)
        print(f"  → {user_path.resolve()}")
        return

    ref_path = DATA_RAW / REF_VIDEO_NAME
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[ref] {args.ref_url or REF_VIDEO_URL}")
    download(args.ref_url or REF_VIDEO_URL, ref_path, force=force)
    print(f"  → {ref_path.resolve()}")

    if not args.no_user:
        user_url = args.user_url or USER_VIDEO_URL
        user_path = DATA_RAW / USER_VIDEO_NAME
        print(f"[user] {user_url}")
        download(user_url, user_path, force=force)
        print(f"  → {user_path.resolve()}")


def cmd_track(args: argparse.Namespace) -> None:
    video = Path(args.video)
    if not video.is_file():
        print(f"영상 없음: {video}", file=sys.stderr)
        sys.exit(1)

    try:
        tracker = PersonTracker(
            model_name=args.model,
            padding_ratio=args.padding,
            device=args.device,
            vid_stride=args.vid_stride,
        )
    except ImportError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    print(f"tracking: {video} (stride={args.vid_stride}, device={args.device or 'auto'})")
    frames = tracker.track_all(video)
    print(f"video: {video}")
    print(f"tracked frames: {len(frames)}")
    if frames:
        print(
            f"  first bbox: {frames[0].bbox_xyxy} "
            f"track_id={frames[0].track_id} conf={frames[0].confidence:.2f}"
        )
        print(
            f"  last  bbox: {frames[-1].bbox_xyxy} "
            f"track_id={frames[-1].track_id} conf={frames[-1].confidence:.2f}"
        )

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "frame_index": f.frame_index,
                "time_sec": f.time_sec,
                "bbox_xyxy": list(f.bbox_xyxy),
                "track_id": f.track_id,
                "confidence": f.confidence,
                "frame_width": f.frame_width,
                "frame_height": f.frame_height,
            }
            for f in frames
        ]
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"  saved: {out.resolve()}")


def cmd_extract(args: argparse.Namespace) -> None:
    video = Path(args.video)
    if not video.is_file():
        print(f"영상 없음: {video}", file=sys.stderr)
        sys.exit(1)

    out = Path(args.out)
    tracks_path = Path(args.tracks) if args.tracks else None
    if tracks_path and not tracks_path.is_file():
        print(f"tracks JSON 없음: {tracks_path}", file=sys.stderr)
        sys.exit(1)

    print(f"extract: {video}")
    if tracks_path:
        print(f"  tracks: {tracks_path} (YOLO 생략)")
    elif args.no_tracks_cache:
        print("  tracks: YOLO 재실행")
    else:
        default_tracks = DATA_ARTIFACTS / "ref_tracks.json"
        if video.resolve() == (DATA_RAW / REF_VIDEO_NAME).resolve() and default_tracks.is_file():
            tracks_path = default_tracks
            print(f"  tracks: {tracks_path} (자동)")

    data = extract_and_save(
        video,
        out,
        tracks_json_path=tracks_path,
        reuse_yolo=not args.no_tracks_cache,
        progress_every=args.progress_every,
        device=args.device,
        vid_stride=1,
    )
    n = len(data.get("frames", []))
    print(f"  frames: {n}")
    print(f"  saved: {out.resolve()}")
    if out.resolve() == (DATA_ARTIFACTS / "ref.json").resolve():
        from metrics.isolation.integration import publish_local_ref_to_video_json

        vj = publish_local_ref_to_video_json()
        print(f"  video_json: {vj}")


def _align_kwargs(args: argparse.Namespace, *, user_video: Path | None = None) -> dict:
    ref_dur = getattr(args, "ref_compare_sec", None)
    if ref_dur is None:
        ref_dur = REF_COMPARE_DURATION_SEC
    kw: dict = {
        "method": args.alignment_method,
        "user_offset_sec": args.user_offset,
        "ref_offset_sec": args.ref_offset,
        "auto_detect_start": args.auto_detect_start,
        "ref_compare_duration_sec": ref_dur,
    }
    if user_video is not None:
        kw["user_video_path"] = user_video
    return kw


def cmd_beats(args: argparse.Namespace) -> None:
    video = Path(args.video)
    if not video.is_file():
        print(f"영상 없음: {video}", file=sys.stderr)
        sys.exit(1)
    print(f"beats: {video}")
    try:
        data = detect_beats_from_video(video)
    except Exception as e:
        print(f"비트 추출 실패: {e}", file=sys.stderr)
        print("ffmpeg 설치 여부를 확인하세요.", file=sys.stderr)
        sys.exit(1)
    out = Path(args.out)
    save_beat_map(data, out)
    print(f"  bpm~{data.get('bpm')} beats={data.get('beat_count')}")
    print(f"  saved: {out.resolve()}")


def cmd_align(args: argparse.Namespace) -> None:
    user_json = Path(args.user)
    ref_json = Path(args.ref)
    for p in (user_json, ref_json):
        if not p.is_file():
            print(f"JSON 없음: {p}", file=sys.stderr)
            sys.exit(1)

    print(f"align ({args.alignment_method}): user={user_json.name} ref={ref_json.name}")
    try:
        result = align_and_save(
            user_json,
            ref_json,
            Path(args.out),
            **_align_kwargs(args),
        )
    except Exception as e:
        print(f"정렬 실패: {e}", file=sys.stderr)
        sys.exit(1)
    align_meta = result["alignment"]
    print(f"  pairs: {align_meta['pair_count']}")
    if align_meta.get("method") == "beat":
        print(
            f"  beat_lag={align_meta.get('beat_lag_sec')}s "
            f"ref_bpm={align_meta.get('ref_bpm')} user_bpm={align_meta.get('user_bpm')}"
        )
    else:
        print(
            f"  offsets: user={align_meta['user_offset_sec']}s "
            f"ref={align_meta['ref_offset_sec']}s"
        )
    if align_meta.get("warning"):
        print(f"  warning: {align_meta['warning']}")
    print(f"  saved: {Path(args.out).resolve()}")


def _score_output_payload(result: dict, include_frame_diffs: bool) -> dict:
    if include_frame_diffs:
        return result
    return {k: v for k, v in result.items() if k != "frame_diffs"}


def _cli_log(msg: str, *, json_mode: bool) -> None:
    """--json 일 때 진행 메시지는 stderr, 최종 점수 JSON만 stdout."""
    print(msg, file=sys.stderr if json_mode else sys.stdout)


def _emit_score_result(result: dict, args: argparse.Namespace) -> None:
    payload = _score_output_payload(result, getattr(args, "include_frame_diffs", False))
    json_mode = getattr(args, "json", False)

    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif not getattr(args, "quiet", False):
        print(f"isolation score: {result['score']}")
        bd = result.get("breakdown", {})
        if bd.get("mean_user_coupling") is not None:
            print(
                f"coupling user={bd.get('mean_user_coupling')} "
                f"ref={bd.get('mean_ref_coupling')}"
            )

    out_path = getattr(args, "out", None) or getattr(args, "score_out", None)
    if out_path:
        save_json(result if getattr(args, "include_frame_diffs", False) else payload, out_path)
        if not json_mode and not getattr(args, "quiet", False):
            print(f"saved: {Path(out_path).resolve()}", file=sys.stderr)


def cmd_score(args: argparse.Namespace) -> None:
    """추출 JSON(또는 aligned JSON)만으로 isolation 점수 산출."""
    if args.pairs:
        pairs_path = Path(args.pairs)
        if not pairs_path.is_file():
            print(f"없음: {pairs_path}", file=sys.stderr)
            sys.exit(1)
        data = json.loads(pairs_path.read_text(encoding="utf-8"))
        pairs = data.get("pairs", data if isinstance(data, list) else [])
        result = score_isolation(pairs)
        if isinstance(data, dict) and "alignment" in data:
            result["alignment"] = data["alignment"]
    else:
        user_json = Path(args.user)
        ref_json = Path(args.ref)
        for p in (user_json, ref_json):
            if not p.is_file():
                print(f"JSON 없음: {p}", file=sys.stderr)
                sys.exit(1)
        user_vp = Path(getattr(args, "user_video", None) or DATA_RAW / "user.mp4")
        beat_video = (
            user_vp
            if args.alignment_method == "beat" and user_vp.is_file()
            else None
        )
        if not args.quiet and not args.json:
            print(
                f"score ({args.alignment_method}): "
                f"user={user_json.name} ref={ref_json.name}",
                file=sys.stderr,
            )
        result = score_from_paths(
            str(user_json),
            str(ref_json),
            aligned_out=str(args.aligned_out) if args.aligned_out else None,
            score_out=None,
            alignment_method=args.alignment_method,
            user_offset_sec=args.user_offset,
            ref_offset_sec=args.ref_offset,
            auto_detect_start=args.auto_detect_start,
            user_video_path=beat_video,
        )

    _emit_score_result(result, args)


def cmd_verify(args: argparse.Namespace) -> None:
    """beats + 음악 싱크 + (user.json 있으면) 정렬·isolation 점수·기준 통합 리포트."""
    from metrics.isolation.verify import format_report_text, run_verify

    ref_video = Path(args.ref_video)
    user_video = Path(args.user_video)
    user_json = Path(args.user_json)

    if args.with_extract:
        if not (DATA_ARTIFACTS / "ref.json").is_file() and ref_video.is_file():
            _cli_log("=== verify: extract ref ===", json_mode=args.json)
            extract_and_save(
                ref_video,
                DATA_ARTIFACTS / "ref.json",
                reuse_yolo=True,
                progress_every=args.progress_every,
                device=args.device,
            )
        if user_video.is_file():
            _cli_log("=== verify: extract user ===", json_mode=args.json)
            tracks = Path(args.user_tracks) if args.user_tracks else DATA_ARTIFACTS / "user_tracks.json"
            extract_and_save(
                user_video,
                user_json,
                tracks_json_path=tracks if tracks.is_file() else None,
                reuse_yolo=True,
                progress_every=args.progress_every,
                device=args.device,
            )

    report = run_verify(
        ref_video=ref_video,
        user_video=user_video,
        user_json=user_json,
        alignment_method=args.alignment_method,
        ref_compare_duration_sec=args.ref_compare_sec,
        user_offset_sec=args.user_offset,
        ref_offset_sec=args.ref_offset,
        auto_detect_start=args.auto_detect_start,
        skip_beats_refresh=args.skip_beats_refresh,
        run_pose_score=not args.beats_only,
    )

    if args.out:
        save_json(report, args.out)
        if not args.json:
            print(f"saved: {Path(args.out).resolve()}", file=sys.stderr)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_report_text(report))

    status = report.get("status", "fail")
    if status == "fail":
        sys.exit(1)
    if status == "partial" and not args.json:
        print(
            "(status=partial: 음악 싱크는 OK, isolation 점수는 user.json 필요 — 빨간 줄은 WARN)",
            file=sys.stderr,
        )


def cmd_run(args: argparse.Namespace) -> None:
    """user mp4 → (tracks) → extract → align → score 한 번에."""
    jout = args.json
    user_video = Path(args.user_video)
    ref_json = Path(args.ref_json)
    user_json = Path(args.user_json)
    user_tracks = Path(args.user_tracks) if args.user_tracks else DATA_ARTIFACTS / "user_tracks.json"

    if not ref_json.is_file():
        print(f"기준 JSON 없음: {ref_json} (먼저 extract ref)", file=sys.stderr)
        sys.exit(1)
    if not user_video.is_file():
        print(f"사용자 영상 없음: {user_video}", file=sys.stderr)
        sys.exit(1)

    if args.skip_extract and not user_json.is_file():
        print(f"user JSON 없음: {user_json}", file=sys.stderr)
        sys.exit(1)

    if not args.skip_extract:
        _cli_log("=== extract user ===", json_mode=jout)
        tracks_arg = user_tracks if user_tracks.is_file() else None
        extract_and_save(
            user_video,
            user_json,
            tracks_json_path=tracks_arg,
            reuse_yolo=True,
            progress_every=args.progress_every,
            device=args.device,
        )
        _cli_log(f"  → {user_json}", json_mode=jout)

    aligned_path = Path(args.aligned_out)

    _cli_log(f"=== align ({args.alignment_method}) ===", json_mode=jout)
    try:
        align_and_save(
            user_json,
            ref_json,
            aligned_path,
            **_align_kwargs(args, user_video=user_video),
        )
    except Exception as e:
        print(f"정렬 실패: {e}", file=sys.stderr)
        sys.exit(1)
    _cli_log(f"  → {aligned_path}", json_mode=jout)

    _cli_log("=== score ===", json_mode=jout)
    aligned_data = json.loads(aligned_path.read_text(encoding="utf-8"))
    result = score_from_alignment(aligned_data)
    if isinstance(result, dict) and "alignment" not in result:
        result["alignment"] = aligned_data.get("alignment")

    _emit_score_result(result, args)


def main() -> None:
    parser = argparse.ArgumentParser(description="isolation 로컬 검증 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_dl = sub.add_parser("download", help="기준(·user) 영상 다운로드")
    p_dl.add_argument("--ref-url", default=None)
    p_dl.add_argument(
        "--user-url",
        default=None,
        help=f"사용자 영상 URL (기본 config: {USER_VIDEO_URL})",
    )
    p_dl.add_argument(
        "--no-user",
        action="store_true",
        help="사용자 영상 다운로드 생략 (ref 만)",
    )
    p_dl.add_argument("--ref-only", action="store_true", help="ref Shorts 만")
    p_dl.add_argument("--user-only", action="store_true", help="user Shorts 만")
    p_dl.add_argument(
        "--force",
        action="store_true",
        help="기존 mp4 삭제 후 Shorts 다시 다운로드",
    )
    p_dl.set_defaults(func=cmd_download)

    p_tr = sub.add_parser("track", help="YOLO11 트래킹")
    p_tr.add_argument("--video", type=Path, default=DATA_RAW / REF_VIDEO_NAME)
    p_tr.add_argument("--model", default=YOLO_MODEL)
    p_tr.add_argument("--padding", type=float, default=0.0)
    p_tr.add_argument("--device", default=None)
    p_tr.add_argument("--vid-stride", type=int, default=1)
    p_tr.add_argument("--out", type=Path, default=None)
    p_tr.set_defaults(func=cmd_track)

    p_ex = sub.add_parser("extract", help="YOLO crop + MediaPipe Heavy → JSON")
    p_ex.add_argument("--video", type=Path, default=DATA_RAW / REF_VIDEO_NAME)
    p_ex.add_argument("--out", type=Path, default=DATA_ARTIFACTS / "ref.json")
    p_ex.add_argument("--tracks", type=Path, default=None)
    p_ex.add_argument("--no-tracks-cache", action="store_true")
    p_ex.add_argument("--device", default=None)
    p_ex.add_argument("--progress-every", type=int, default=50)
    p_ex.set_defaults(func=cmd_extract)

    def _add_align_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--alignment-method",
            choices=("beat", "time"),
            default=DEFAULT_ALIGNMENT_METHOD,
            help="beat=음악 박자(기본), time=시각만",
        )
        p.add_argument(
            "--ref-compare-sec",
            type=float,
            default=REF_COMPARE_DURATION_SEC,
            help="기준(ref) 영상 앞 N초만 비교 (0=전체)",
        )
        p.add_argument("--user-offset", type=float, default=0.0)
        p.add_argument("--ref-offset", type=float, default=0.0)
        p.add_argument("--auto-detect-start", action="store_true")

    p_bt = sub.add_parser("beats", help="영상에서 비트 맵 JSON 추출")
    p_bt.add_argument("--video", type=Path, default=DATA_RAW / REF_VIDEO_NAME)
    p_bt.add_argument("--out", type=Path, default=DATA_ARTIFACTS / "ref_beats.json")
    p_bt.set_defaults(func=cmd_beats)

    p_al = sub.add_parser("align", help="beat/time 정렬 → aligned_pairs JSON")
    p_al.add_argument("--user", type=Path, required=True)
    p_al.add_argument("--ref", type=Path, default=DATA_ARTIFACTS / "ref.json")
    p_al.add_argument("--out", type=Path, default=DATA_ARTIFACTS / "aligned_pairs.json")
    _add_align_flags(p_al)
    p_al.set_defaults(func=cmd_align)

    p_sc = sub.add_parser(
        "score",
        help="추출 JSON 2개(또는 aligned JSON) → isolation 점수 JSON",
    )
    p_sc.add_argument("--pairs", type=Path, default=None, help="aligned_pairs.json")
    p_sc.add_argument("--user", type=Path, default=DATA_ARTIFACTS / "user.json")
    p_sc.add_argument("--ref", type=Path, default=DATA_ARTIFACTS / "ref.json")
    p_sc.add_argument(
        "--user-video",
        type=Path,
        default=None,
        help="beat 정렬 시 오디오 소스 (기본 data/raw/user.mp4)",
    )
    p_sc.add_argument("--aligned-out", type=Path, default=None, help="정렬 결과 저장")
    p_sc.add_argument(
        "--out",
        type=Path,
        default=None,
        help="점수 JSON 파일 저장 (미지정 시 저장 안 함)",
    )
    p_sc.add_argument(
        "--json",
        action="store_true",
        help="점수 JSON 전체를 stdout 에 출력 (터미널 확인용)",
    )
    p_sc.add_argument(
        "--include-frame-diffs",
        action="store_true",
        help="frame_diffs 포함 (기본: score·breakdown·alignment 만)",
    )
    p_sc.add_argument("--quiet", action="store_true", help="--json 일 때 stderr 요약 숨김")
    _add_align_flags(p_sc)
    p_sc.set_defaults(func=cmd_score)

    p_run = sub.add_parser("run", help="user 영상 전체 파이프라인")
    p_run.add_argument("--user-video", type=Path, default=DATA_RAW / "user.mp4")
    p_run.add_argument("--ref-json", type=Path, default=DATA_ARTIFACTS / "ref.json")
    p_run.add_argument("--user-json", type=Path, default=DATA_ARTIFACTS / "user.json")
    p_run.add_argument("--user-tracks", type=Path, default=None)
    p_run.add_argument("--aligned-out", type=Path, default=DATA_ARTIFACTS / "aligned_pairs.json")
    p_run.add_argument("--score-out", type=Path, default=DATA_ARTIFACTS / "isolation_score.json")
    p_run.add_argument("--skip-extract", action="store_true")
    p_run.add_argument("--device", default=None)
    p_run.add_argument("--progress-every", type=int, default=50)
    p_run.add_argument(
        "--json",
        action="store_true",
        help="최종 isolation 점수를 stdout 에 JSON 으로 출력 (진행 로그는 stderr)",
    )
    p_run.add_argument(
        "--include-frame-diffs",
        action="store_true",
        help="JSON 에 frame_diffs 포함",
    )
    p_run.add_argument("--quiet", action="store_true", help="--json 아닐 때 요약만 최소 출력")
    _add_align_flags(p_run)
    p_run.set_defaults(func=cmd_run)

    p_vf = sub.add_parser(
        "verify",
        help="통합 검증: 음악 싱크(beats) + 정렬 + isolation 점수 + 채점 기준",
    )
    p_vf.add_argument("--ref-video", type=Path, default=DATA_RAW / REF_VIDEO_NAME)
    p_vf.add_argument("--user-video", type=Path, default=DATA_RAW / USER_VIDEO_NAME)
    p_vf.add_argument("--user-json", type=Path, default=DATA_ARTIFACTS / "user.json")
    p_vf.add_argument("--user-tracks", type=Path, default=None)
    p_vf.add_argument(
        "--with-extract",
        action="store_true",
        help="user/ref 포즈 JSON 없으면 extract 실행 (느림)",
    )
    p_vf.add_argument(
        "--beats-only",
        action="store_true",
        help="비트·음악 싱크만 (user.json 불필요)",
    )
    p_vf.add_argument(
        "--skip-beats-refresh",
        action="store_true",
        help="기존 ref_beats.json / user_beats.json 재사용",
    )
    p_vf.add_argument("--out", type=Path, default=None, help="리포트 JSON 저장")
    p_vf.add_argument("--json", action="store_true", help="리포트 전체를 stdout JSON")
    p_vf.add_argument("--device", default=None)
    p_vf.add_argument("--progress-every", type=int, default=50)
    _add_align_flags(p_vf)
    p_vf.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
