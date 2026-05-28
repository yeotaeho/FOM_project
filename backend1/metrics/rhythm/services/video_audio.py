"""ffmpeg를 이용해 무음 영상에 오디오 트랙을 붙이는 유틸."""

import os
import subprocess
import tempfile
from pathlib import Path


def attach_audio(
    silent_video_path: Path,
    audio_source_path: str,
    output_path: Path,
) -> Path:
    """
    silent_video_path 의 영상 트랙 + audio_source_path 의 오디오 트랙을
    합쳐 output_path 에 저장한다.

    - 영상 길이에 맞게 오디오를 자름 (-shortest)
    - 원본 영상 코덱은 재인코딩 없이 복사 (-c:v copy)
    - 오디오는 AAC 128k 로 인코딩
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(silent_video_path),   # 영상 소스
        "-i", str(audio_source_path),   # 오디오 소스
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 오디오 합성 실패:\n{result.stderr}")
    return output_path


def render_with_audio(
    silent_video_path: Path,
    audio_source_path: str,
    final_path: Path,
) -> Path:
    """
    무음 영상을 임시 파일에 유지하면서 오디오를 붙인 최종 파일을 생성.
    성공하면 임시 무음 파일을 삭제하고 final_path 를 반환.
    """
    # 임시 파일로 무음 영상 이동 후 오디오 합성 → final_path
    suffix = silent_video_path.suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        os.replace(str(silent_video_path), str(tmp_path))
        attach_audio(tmp_path, audio_source_path, final_path)
    finally:
        if tmp_path.exists():
            os.remove(tmp_path)

    return final_path
