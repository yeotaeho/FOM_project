"""영상 오디오에서 비트 타임스탬프 추출 (librosa)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from metrics.isolation.config import ALIGN_TO_MUSIC_START, DATA_ARTIFACTS, DATA_RAW

MIN_BEATS = 4


def _resolve_ffmpeg() -> Optional[str]:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _load_audio_via_ffmpeg(video_path: Path, sr: int) -> tuple[np.ndarray, int]:
    ffmpeg = _resolve_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg를 찾을 수 없습니다. PATH에 ffmpeg를 설치하거나 "
            "`pip install imageio-ffmpeg` 후 다시 시도하세요."
        )

    import librosa

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = Path(tmp.name)
    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                str(sr),
                "-ac",
                "1",
                str(wav_path),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[-400:]
            raise RuntimeError(f"ffmpeg 오디오 추출 실패: {err}")
        y, loaded_sr = librosa.load(str(wav_path), sr=sr, mono=True)
        return y, int(loaded_sr)
    finally:
        wav_path.unlink(missing_ok=True)


_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def _load_audio_mono(video_path: Path, sr: int) -> tuple[np.ndarray, int]:
    if video_path.suffix.lower() in _VIDEO_SUFFIXES:
        return _load_audio_via_ffmpeg(video_path, sr)

    import librosa

    y, loaded_sr = librosa.load(str(video_path), sr=sr, mono=True)
    return y, int(loaded_sr)


def detect_beats_from_video(
    video_path: str | Path,
    *,
    sr: int = 22050,
    hop_length: int = 512,
) -> Dict[str, Any]:
    """
    mp4 등에서 오디오를 읽어 비트 시각(초) 목록 반환.
    ffmpeg 없으면 ImportError / 파일 오류 발생.
    """
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"영상 없음: {path}")

    y, loaded_sr = _load_audio_mono(path, sr)
    import librosa

    onset_env = librosa.onset.onset_strength(y=y, sr=loaded_sr, hop_length=hop_length)
    tempo, beat_frames = librosa.beat.beat_track(
        y=y, sr=loaded_sr, hop_length=hop_length, onset_envelope=onset_env
    )
    beat_times = librosa.frames_to_time(beat_frames, sr=loaded_sr)
    times = [float(t) for t in np.asarray(beat_times).ravel() if float(t) >= 0]

    music_start_sec = _detect_music_start_sec(y, loaded_sr, onset_env, hop_length, times)

    if len(times) < MIN_BEATS:
        raise ValueError(
            f"비트가 너무 적습니다 ({len(times)}). 다른 영상이거나 음악이 거의 없을 수 있습니다."
        )

    tempo_scalar = float(np.asarray(tempo).ravel()[0]) if tempo is not None else 0.0
    bpm = tempo_scalar if tempo_scalar > 0 else 0.0
    if bpm <= 0 and len(times) >= 2:
        gaps = np.diff(times)
        bpm = 60.0 / float(np.median(gaps))

    return {
        "source_video": path.name,
        "sr": loaded_sr,
        "hop_length": hop_length,
        "bpm": round(bpm, 2),
        "music_start_sec": round(music_start_sec, 4),
        "beat_count": len(times),
        "beat_times_sec": times,
        "duration_sec": round(float(len(y) / loaded_sr), 4),
    }


def _detect_music_start_sec(
    y: np.ndarray,
    sr: int,
    onset_env: np.ndarray,
    hop_length: int,
    beat_times: List[float],
) -> float:
    """
    음악이 실제로 들리기 시작하는 시각(초). 영상 타임라인 기준.
    onset 첫 피크 + 첫 비트 중 더 앞쪽(무음 구간 제외).
    """
    import librosa

    if len(onset_env) == 0:
        return float(beat_times[0]) if beat_times else 0.0

    env = np.asarray(onset_env, dtype=np.float64)
    peak = float(np.max(env)) if len(env) else 0.0
    if peak < 1e-8:
        return float(beat_times[0]) if beat_times else 0.0

    norm = env / peak
    threshold = max(0.12, float(np.percentile(norm, 75)) * 0.35)
    onset_idx = int(np.argmax(norm >= threshold))
    frame_times = librosa.frames_to_time(
        np.arange(len(norm)), sr=sr, hop_length=hop_length
    )
    onset_start = float(frame_times[onset_idx])

    first_beat = float(beat_times[0]) if beat_times else onset_start
    # 첫 비트가 onset보다 많이 늦으면 onset 우선, 비슷하면 더 이른 쪽
    if first_beat - onset_start > 1.5:
        return onset_start
    return min(onset_start, first_beat)


def beats_from_music_start(
    beat_data: Dict[str, Any],
    *,
    max_duration_sec: Optional[float] = None,
) -> tuple[float, List[float]]:
    """music_start 이후 비트만, (music_start_sec, filtered_beats)."""
    start = float(beat_data.get("music_start_sec") or 0.0)
    beats = [
        float(b)
        for b in beat_data.get("beat_times_sec") or []
        if float(b) >= start - 0.02
    ]
    if max_duration_sec is not None and max_duration_sec > 0:
        end = start + max_duration_sec
        beats = [b for b in beats if b <= end + 0.05]
    return start, beats


def save_beat_map(data: Dict[str, Any], out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def load_beat_map(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def video_path_for_extraction(
    data: Dict[str, Any],
    *,
    video_override: Path | None = None,
) -> Path:
    if video_override is not None:
        path = Path(video_override)
        if path.is_file():
            return path
        raise FileNotFoundError(f"영상 없음: {path}")

    name = data.get("source_video") or ""
    if not name:
        raise ValueError("추출 JSON에 source_video 가 없습니다.")
    candidates = [DATA_RAW / name, DATA_ARTIFACTS.parent / "raw" / name]
    for p in candidates:
        if p.is_file():
            return p
    raise FileNotFoundError(
        f"영상 파일 없음: {name} (data/raw 또는 video_override 경로 확인)"
    )


def beats_for_extraction(
    data: Dict[str, Any],
    *,
    beats_json: Path | None = None,
    cache_path: Path | None = None,
    video_override: Path | None = None,
) -> Dict[str, Any]:
    """캐시 JSON 이 있으면 로드, 없으면 영상에서 추출 후 저장."""
    def _cache_ok(data: Dict[str, Any]) -> bool:
        if not ALIGN_TO_MUSIC_START:
            return True
        return "music_start_sec" in data

    if beats_json and Path(beats_json).is_file():
        cached = load_beat_map(beats_json)
        if _cache_ok(cached):
            return cached
    if cache_path and Path(cache_path).is_file():
        cached = load_beat_map(cache_path)
        if _cache_ok(cached):
            return cached

    video = video_path_for_extraction(data, video_override=video_override)
    beat_data = detect_beats_from_video(video)
    if cache_path:
        save_beat_map(beat_data, cache_path)
    return beat_data


def estimate_beat_lag_sec(
    ref_beats: List[float],
    user_beats: List[float],
    *,
    max_beats: int = 48,
) -> float:
    """
    user 비트축을 ref 비트축에 맞추기 위한 시각 오프셋(초).
    user_time + lag ≈ ref_time (같은 박 인덱스).
    """
    n = min(len(ref_beats), len(user_beats), max_beats)
    if n < MIN_BEATS:
        return 0.0
    deltas = [float(ref_beats[i]) - float(user_beats[i]) for i in range(n)]
    return float(np.median(deltas))
