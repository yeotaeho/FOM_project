"""
기준·사용자 영상을 data/raw/ 에 저장.

사용 (backend1 루트 또는 isolation 폴더에서):
  python -m metrics.isolation.scripts.download_videos
  python -m metrics.isolation.scripts.download_videos --user-url "https://..."
  python metrics/isolation/scripts/download_videos.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# metrics.isolation.config import (스크립트 직접 실행 대비)
_ISOLATION_ROOT = Path(__file__).resolve().parents[1]
if str(_ISOLATION_ROOT.parents[1]) not in sys.path:
    sys.path.insert(0, str(_ISOLATION_ROOT.parents[1]))

from metrics.isolation.config import (  # noqa: E402
    DATA_RAW,
    REF_COMPARE_DURATION_SEC,
    REF_VIDEO_NAME,
    REF_VIDEO_URL,
    USER_VIDEO_NAME,
    USER_VIDEO_URL,
)

# Shorts 가 아닌 긴 mp4(재생목록 실수 등) 차단
MAX_SHORTS_DURATION_SEC = max(90.0, REF_COMPARE_DURATION_SEC * 4)


def _ensure_yt_dlp() -> None:
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        print("yt-dlp가 필요합니다: pip install yt-dlp", file=sys.stderr)
        sys.exit(1)


def normalize_youtube_url(url: str) -> str:
    """재생목록·watch URL → 단일 Shorts/watch (playlist 파라미터 제거)."""
    from urllib.parse import parse_qs, urlparse

    url = url.strip()
    parsed = urlparse(url)
    if "youtube.com" not in parsed.netloc and "youtu.be" not in parsed.netloc:
        return url

    if "/shorts/" in parsed.path:
        vid = parsed.path.split("/shorts/")[-1].split("/")[0]
        return f"https://www.youtube.com/shorts/{vid}"

    if parsed.path == "/watch":
        qs = parse_qs(parsed.query)
        vid = (qs.get("v") or [None])[0]
        if vid:
            return f"https://www.youtube.com/shorts/{vid}"

    return url.split("&list=")[0].split("?list=")[0]


def video_duration_sec(path: Path) -> float:
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return 0.0
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    return n / fps if fps > 0 else 0.0


def assert_shorts_duration(path: Path, *, label: str = "영상") -> None:
    dur = video_duration_sec(path)
    if dur <= 0:
        raise ValueError(f"{label} 길이를 읽을 수 없습니다: {path}")
    if dur > MAX_SHORTS_DURATION_SEC:
        raise ValueError(
            f"{label}이 너무 깁니다 ({dur:.1f}s > {MAX_SHORTS_DURATION_SEC}s). "
            "재생목록이 아닌 Shorts URL 인지 확인하고, "
            "기존 mp4 를 지운 뒤 download --force 로 다시 받으세요."
        )


def download(
    url: str,
    out_path: Path,
    *,
    force: bool = False,
    max_duration_sec: float = MAX_SHORTS_DURATION_SEC,
) -> Path:
    """URL → mp4 (단일 Shorts)."""
    _ensure_yt_dlp()
    url = normalize_youtube_url(url)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_template = str(out_path.with_suffix("")) + ".%(ext)s"

    if force:
        for old in out_path.parent.glob(out_path.stem + ".*"):
            if old.is_file():
                old.unlink()

    opts = {
        "format": "best[ext=mp4][height<=1080]/best[ext=mp4]/best",
        "outtmpl": out_template,
        "quiet": False,
        "no_warnings": False,
        "noplaylist": True,
        "playlist_items": "1",
        "overwrites": True,
        "nooverwrites": False,
    }
    import yt_dlp

    print(f"  URL(normalized): {url}")
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    if out_path.is_file():
        assert_shorts_duration(out_path, label=out_path.name)
        dur = video_duration_sec(out_path)
        print(f"  duration: {dur:.1f}s")
        return out_path
    candidates = list(out_path.parent.glob(out_path.stem + ".*"))
    mp4s = [p for p in candidates if p.suffix.lower() in {".mp4", ".webm", ".mkv"}]
    if not mp4s:
        raise FileNotFoundError(f"다운로드 실패: {url} → {out_path}")
    found = mp4s[0]
    if found != out_path and found.suffix.lower() == ".mp4":
        found.rename(out_path)
    elif found != out_path:
        return found
    assert_shorts_duration(out_path, label=out_path.name)
    print(f"  duration: {video_duration_sec(out_path):.1f}s")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="isolation 검증용 영상 다운로드")
    parser.add_argument(
        "--ref-url",
        default=REF_VIDEO_URL,
        help="기준(레퍼런스) YouTube URL",
    )
    parser.add_argument(
        "--user-url",
        default=USER_VIDEO_URL,
        help="사용자 비교용 URL",
    )
    parser.add_argument(
        "--no-user",
        action="store_true",
        help="사용자 영상 다운로드 생략",
    )
    parser.add_argument(
        "--ref-only",
        action="store_true",
        help="기준(ref) Shorts 만",
    )
    parser.add_argument(
        "--user-only",
        action="store_true",
        help="사용자(user) Shorts 만",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="기존 mp4 삭제 후 다시 다운로드",
    )
    parser.add_argument(
        "--user-file",
        type=Path,
        default=None,
        help="이미 있는 로컬 mp4를 data/raw/user.mp4 로 복사",
    )
    args = parser.parse_args()

    do_ref = not args.user_only
    do_user = not args.ref_only and not args.no_user

    if do_ref:
        ref_path = DATA_RAW / REF_VIDEO_NAME
        print(f"[ref] {args.ref_url} → {ref_path}")
        download(args.ref_url, ref_path, force=args.force)
        print(f"  저장: {ref_path.resolve()}")

    if do_user:
        user_path = DATA_RAW / USER_VIDEO_NAME
        print(f"[user] {args.user_url} → {user_path}")
        download(args.user_url, user_path, force=args.force)
        print(f"  저장: {user_path.resolve()}")

    if args.user_file:
        import shutil

        user_path = DATA_RAW / USER_VIDEO_NAME
        if not args.user_file.is_file():
            print(f"파일 없음: {args.user_file}", file=sys.stderr)
            sys.exit(1)
        shutil.copy2(args.user_file, user_path)
        print(f"[user] 복사: {user_path.resolve()}")


if __name__ == "__main__":
    main()
