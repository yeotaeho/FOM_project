#!/usr/bin/env python3
"""dance_app/video_data MP4 → 세로 480p (_480.mp4) 프리뷰 생성."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2

TARGET_H = 480
VIDEO_DATA = Path(__file__).resolve().parents[1] / "video_data"

SOURCES = [
    VIDEO_DATA / "card1" / "gBR_sBM_c01_d06_mBR3_ch03.mp4",
    VIDEO_DATA / "card2" / "card2_reference.mp4",
    VIDEO_DATA / "card2" / "card2_user.mp4",
    VIDEO_DATA / "card3" / "gHO_sBM_c01_d19_mHO3_ch03.mp4",
    VIDEO_DATA / "card4" / "gJB_sBM_c01_d07_mJB3_ch03.mp4",
    VIDEO_DATA / "card5" / "gMH_sBM_c01_d24_mMH3_ch03.mp4",
]


def output_path(src: Path) -> Path:
    return src.with_name(f"{src.stem}_480{src.suffix}")


def encode_480(src: Path) -> Path:
    dst = output_path(src)
    if not src.is_file():
        raise FileNotFoundError(src)

    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {src}")

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    out_w = max(2, int(w * TARGET_H / h))
    out_h = TARGET_H
    if out_w % 2:
        out_w += 1

    writer = cv2.VideoWriter(
        str(dst),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (out_w, out_h),
    )
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"cannot write {dst}")

    n = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        resized = cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA)
        writer.write(resized)
        n += 1

    cap.release()
    writer.release()
    print(f"{src.name} ({w}x{h}) -> {dst.name} ({out_w}x{out_h}) frames={n}")
    return dst


def main() -> int:
    errors = 0
    for src in SOURCES:
        try:
            encode_480(src)
        except Exception as exc:
            print(f"FAIL {src}: {exc}", file=sys.stderr)
            errors += 1
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
