"""영상에서 오디오 비트를 추출한다 (librosa + ffmpeg 백엔드)."""

import time
from typing import Any, Dict

import librosa
import numpy as np


def extract_beats(video_path: str) -> Dict[str, Any]:
    """
    librosa로 영상의 오디오 트랙에서 비트 타임스탬프를 추출한다.

    반환:
        {
          "tempo_bpm": float,
          "beat_count": int,
          "beat_times_sec": [float, ...],
          "extraction_sec": float,
        }
    """
    t0 = time.perf_counter()

    y, sr = librosa.load(video_path, sr=None, mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times: np.ndarray = librosa.frames_to_time(beat_frames, sr=sr)

    # librosa 버전에 따라 tempo가 배열로 반환될 수 있음
    tempo_val = float(np.atleast_1d(tempo)[0])

    return {
        "tempo_bpm": round(tempo_val, 2),
        "beat_count": int(len(beat_times)),
        "beat_times_sec": [round(float(t), 4) for t in beat_times],
        "extraction_sec": round(time.perf_counter() - t0, 3),
    }
