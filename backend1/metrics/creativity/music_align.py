"""
동일 곡(촬영 시 BGM 강제 일치) 전제 — 크로마로 비교 구간 [시작, 끝] 검출.

- ref 곡 구간 길이를 기준 창으로 사용
- user 시작: ref 지문에 대한 짧은 슬라이딩(인트로 지연만 보정)
- 끝: 매칭 시작 후 user↔ref 크로마 연속성으로 동일 곡 구간 확정
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

_AUDIO_SR = 22050
_HOP = 512
_FINGERPRINT_SEC = 6.0
_MIN_MUSIC_SEC = 4.0
_SELF_SIM_WIN_SEC = 2.0
_SELF_SIM_THRESH = 0.72
_CONTINUITY_THRESH = 0.58
_CONTINUITY_END_THRESH = 0.52
_CONTINUITY_WIN_SEC = 2.0
_END_LOW_STREAK = 2
_SEARCH_MAX_SEC = 90.0


def _resolve_ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def load_audio_mono(video_path: str, sr: int = _AUDIO_SR) -> tuple[np.ndarray, int, float]:
    import librosa

    path = Path(video_path)
    if not path.is_file():
        raise ValueError(f"영상을 찾을 수 없습니다: {video_path}")

    try:
        y, loaded_sr = librosa.load(str(path), sr=sr, mono=True)
        if len(y) > 0:
            return y.astype(np.float64), int(loaded_sr), len(y) / loaded_sr
    except Exception:
        pass

    ffmpeg = _resolve_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "오디오 추출 실패: ffmpeg 또는 imageio-ffmpeg 가 필요합니다."
        )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    try:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(path),
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                str(sr),
                "-ac",
                "1",
                wav_path,
            ],
            check=True,
            capture_output=True,
        )
        y, loaded_sr = librosa.load(wav_path, sr=sr, mono=True)
        return y.astype(np.float64), int(loaded_sr), len(y) / loaded_sr
    finally:
        Path(wav_path).unlink(missing_ok=True)


def _chroma_matrix(y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    import librosa

    chroma = librosa.feature.chroma_cqt(
        y=y,
        sr=sr,
        hop_length=_HOP,
        n_chroma=12,
    )
    chroma = librosa.util.normalize(chroma, axis=0)
    times = librosa.frames_to_time(
        np.arange(chroma.shape[1]),
        sr=sr,
        hop_length=_HOP,
    )
    return chroma.astype(np.float64), times.astype(np.float64)


def _window_vec(chroma: np.ndarray, i0: int, i1: int) -> np.ndarray:
    w = chroma[:, i0:i1].reshape(-1)
    n = np.linalg.norm(w)
    return w / n if n > 1e-9 else w


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) != len(b) or len(a) == 0:
        return 0.0
    return float(np.dot(a, b))


def _self_similarity_forward(
    chroma: np.ndarray,
    start_idx: int,
    win_frames: int,
) -> float:
    n = chroma.shape[1]
    i0 = start_idx
    i1 = min(n, start_idx + win_frames)
    i2 = min(n, start_idx + 2 * win_frames)
    if i1 - i0 < 4 or i2 - i1 < 4:
        return 0.0
    return _cosine(_window_vec(chroma, i0, i1), _window_vec(chroma, i1, i2))


def detect_music_segment(video_path: str) -> dict[str, Any]:
    """단일 영상에서 크로마 연속 구간(동일 곡 패턴) 추정."""
    y, sr, duration = load_audio_mono(video_path)
    if duration < 1.0:
        return {
            "start_sec": 0.0,
            "end_sec": duration,
            "duration_sec": duration,
            "method": "chroma_continuity",
            "note": "audio_too_short",
        }

    chroma, times = _chroma_matrix(y, sr)
    n = chroma.shape[1]
    win_frames = max(4, int(_SELF_SIM_WIN_SEC * sr / _HOP))
    min_frames = max(4, int(_MIN_MUSIC_SEC * sr / _HOP))

    sims = np.array(
        [_self_similarity_forward(chroma, i, win_frames) for i in range(n)],
        dtype=np.float64,
    )
    active = sims >= _SELF_SIM_THRESH
    if not np.any(active):
        return {
            "start_sec": 0.0,
            "end_sec": round(duration, 4),
            "duration_sec": round(duration, 4),
            "method": "chroma_continuity",
            "note": "no_stable_music_pattern",
            "peak_self_similarity": round(float(np.max(sims)), 4),
        }

    idx = np.where(active)[0]
    best_len = 0
    best_start = int(idx[0])
    best_end = int(idx[0])
    cur_start = int(idx[0])
    cur_end = int(idx[0])
    for i in range(1, len(idx)):
        if idx[i] == cur_end + 1:
            cur_end = int(idx[i])
        else:
            if cur_end - cur_start + 1 > best_len:
                best_len = cur_end - cur_start + 1
                best_start, best_end = cur_start, cur_end
            cur_start = cur_end = int(idx[i])
    if cur_end - cur_start + 1 > best_len:
        best_start, best_end = cur_start, cur_end

    if best_end - best_start + 1 < min_frames:
        best_start, best_end = int(idx[0]), int(idx[-1])

    start_sec = float(times[best_start])
    end_sec = float(times[min(best_end, n - 1)])
    if end_sec <= start_sec:
        end_sec = duration

    return {
        "start_sec": round(start_sec, 4),
        "end_sec": round(min(end_sec, duration), 4),
        "active_duration_sec": round(max(0.0, end_sec - start_sec), 4),
        "duration_sec": round(duration, 4),
        "method": "chroma_continuity",
        "peak_self_similarity": round(float(np.max(sims)), 4),
    }


def _slide_match_user_start(
    user_chroma: np.ndarray,
    user_times: np.ndarray,
    ref_chroma: np.ndarray,
    ref_start_idx: int,
    fp_frames: int,
) -> tuple[int, float]:
    n_u = user_chroma.shape[1]
    n_r = ref_chroma.shape[1]
    r0 = ref_start_idx
    r1 = min(n_r, r0 + fp_frames)
    if r1 - r0 < 4:
        return 0, 0.0
    ref_vec = _window_vec(ref_chroma, r0, r1)

    best_i = 0
    best_sim = -1.0
    max_i = n_u - fp_frames
    if max_i < 0:
        return 0, 0.0

    for i in range(max_i + 1):
        if user_times[i] > _SEARCH_MAX_SEC:
            break
        u1 = min(n_u, i + fp_frames)
        if u1 - i < 4:
            continue
        sim = _cosine(ref_vec, _window_vec(user_chroma, i, u1))
        if sim > best_sim:
            best_sim = sim
            best_i = i
    return best_i, best_sim


def _cross_similarity(
    user_chroma: np.ndarray,
    ref_chroma: np.ndarray,
    user_start_idx: int,
    ref_start_idx: int,
    offset_frames: int,
    cont_win: int,
) -> float | None:
    n_u = user_chroma.shape[1]
    n_r = ref_chroma.shape[1]
    ui0 = user_start_idx + offset_frames
    ui1 = min(n_u, ui0 + cont_win)
    ri0 = ref_start_idx + offset_frames
    ri1 = min(n_r, ri0 + cont_win)
    if ui1 - ui0 < 2 or ri1 - ri0 < 2:
        return None
    return _cosine(
        _window_vec(user_chroma, ui0, ui1),
        _window_vec(ref_chroma, ri0, ri1),
    )


def _find_common_extent(
    user_chroma: np.ndarray,
    ref_chroma: np.ndarray,
    user_start_idx: int,
    ref_start_idx: int,
    target_frames: int,
) -> tuple[int, list[float]]:
    """ref 창 길이(동일 곡) 동안 user↔ref 크로마 연속성으로 실제 끝 보정."""
    n_u = user_chroma.shape[1]
    cont_win = max(2, int(_CONTINUITY_WIN_SEC * _AUDIO_SR / _HOP))
    max_k = min(target_frames, n_u - user_start_idx - cont_win)

    window_sims: list[float] = []
    last_good = user_start_idx + cont_win
    low_streak = 0
    k = 0

    while k <= max_k:
        sim = _cross_similarity(
            user_chroma, ref_chroma, user_start_idx, ref_start_idx, k, cont_win
        )
        if sim is None:
            break
        window_sims.append(sim)
        ui1 = min(n_u, user_start_idx + k + cont_win)
        if sim >= _CONTINUITY_END_THRESH:
            last_good = ui1
            low_streak = 0
        else:
            low_streak += 1
            if low_streak >= _END_LOW_STREAK and len(window_sims) >= 2:
                break
        k += cont_win

    if not window_sims:
        last_good = min(n_u, user_start_idx + cont_win)
    return last_good, window_sims


def align_music_segment(
    user_video: str,
    ref_video: str,
) -> dict[str, Any]:
    """
    동일 곡 전제: ref 구간을 기준 길이로, user는 시작 지연·끝 연속성만 보정.
    """
    ref_seg = detect_music_segment(ref_video)
    user_seg = detect_music_segment(user_video)

    user_y, sr_u, user_dur = load_audio_mono(user_video)
    ref_y, sr_r, _ = load_audio_mono(ref_video)
    if sr_u != sr_r:
        import librosa

        ref_y = librosa.resample(ref_y, orig_sr=sr_r, target_sr=sr_u)
        sr_r = sr_u

    user_chroma, user_times = _chroma_matrix(user_y, sr_u)
    ref_chroma, ref_times = _chroma_matrix(ref_y, sr_r)

    ref_start_sec = float(ref_seg["start_sec"])
    ref_end_sec = float(ref_seg["end_sec"])
    ref_start_idx = int(np.searchsorted(ref_times, ref_start_sec))
    ref_dur_sec = max(_MIN_MUSIC_SEC, ref_end_sec - ref_start_sec)

    fp_frames = max(8, int(_FINGERPRINT_SEC * sr_u / _HOP))
    target_frames = max(4, int(ref_dur_sec * sr_u / _HOP))

    user_start_idx, peak_match = _slide_match_user_start(
        user_chroma, user_times, ref_chroma, ref_start_idx, fp_frames
    )
    user_start_sec = float(user_times[user_start_idx])

    user_end_idx, extent_sims = _find_common_extent(
        user_chroma,
        ref_chroma,
        user_start_idx,
        ref_start_idx,
        target_frames,
    )
    user_end_sec = float(user_times[min(user_end_idx, user_chroma.shape[1] - 1)])

    common_dur = max(0.0, user_end_sec - user_start_sec)
    if common_dur < _MIN_MUSIC_SEC:
        common_dur = min(
            ref_dur_sec,
            float(user_seg.get("active_duration_sec", _MIN_MUSIC_SEC) or _MIN_MUSIC_SEC),
        )
        user_end_sec = min(user_start_sec + common_dur, user_dur)

    ref_end_sec = min(ref_start_sec + common_dur, float(ref_seg["end_sec"]))
    user_end_sec = min(
        user_start_sec + common_dur,
        float(user_seg.get("end_sec", user_end_sec)),
        user_dur,
    )
    common_dur = min(user_end_sec - user_start_sec, ref_end_sec - ref_start_sec)

    cont = float(np.mean(extent_sims)) if extent_sims else 0.0
    music_ok = peak_match >= _SELF_SIM_THRESH and cont >= _CONTINUITY_THRESH

    return {
        "user_start_sec": round(user_start_sec, 4),
        "user_end_sec": round(user_end_sec, 4),
        "ref_start_sec": round(ref_start_sec, 4),
        "ref_end_sec": round(ref_end_sec, 4),
        "common_duration_sec": round(common_dur, 4),
        "music_match_peak": round(peak_match, 4),
        "music_continuity": round(cont, 4),
        "music_extent_mean_similarity": round(cont, 4),
        "music_extent_windows": len(extent_sims),
        "music_verified": music_ok,
        "same_track_assumed": True,
        "user_segment": user_seg,
        "ref_segment": ref_seg,
        "alignment": {
            "method": "same_track_chroma_window",
            "fingerprint_sec": _FINGERPRINT_SEC,
            "continuity_threshold": _CONTINUITY_THRESH,
        },
    }


def resolve_music_offsets(
    user_video: str,
    ref_video: str,
    *,
    manual_user_offset: float = 0.0,
    manual_ref_offset: float = 0.0,
    manual_user_end: float | None = None,
    manual_ref_end: float | None = None,
    use_music_align: bool = True,
) -> tuple[float, float | None, float, float | None, dict[str, Any] | None]:
    """(user_start, user_end, ref_start, ref_end, info). end None = 샘플 상한 없음."""
    if manual_user_offset != 0.0 or manual_ref_offset != 0.0:
        return manual_user_offset, manual_user_end, manual_ref_offset, manual_ref_end, None
    if not use_music_align:
        return manual_user_offset, manual_user_end, manual_ref_offset, manual_ref_end, None
    try:
        info = align_music_segment(user_video, ref_video)
        u_end = manual_user_end if manual_user_end is not None else float(info["user_end_sec"])
        r_end = manual_ref_end if manual_ref_end is not None else float(info["ref_end_sec"])
        return (
            float(info["user_start_sec"]),
            u_end,
            float(info["ref_start_sec"]),
            r_end,
            info,
        )
    except Exception as exc:
        return manual_user_offset, manual_user_end, manual_ref_offset, manual_ref_end, {
            "error": str(exc),
        }
