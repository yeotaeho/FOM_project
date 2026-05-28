from typing import Any, Dict, List, Optional

import numpy as np
from scipy.signal import find_peaks

UPPER_JOINTS = ["left_wrist", "right_wrist", "left_elbow", "right_elbow"]
LOWER_JOINTS = ["left_ankle", "right_ankle", "left_knee", "right_knee"]
ALL_JOINTS = UPPER_JOINTS + LOWER_JOINTS


def velocity_series(
    frames: List[Dict[str, Any]],
    joints: List[str],
) -> np.ndarray:
    """Per-frame mean displacement magnitude across specified joints."""
    velocities: List[float] = []
    prev: Optional[Dict[str, tuple]] = None

    for frame in frames:
        nl = frame.get("normalized_landmarks", {})
        curr = {
            j: (nl[j]["x"], nl[j]["y"], nl[j]["z"])
            for j in joints
            if j in nl
        }
        if prev is not None and curr:
            dists = [
                ((curr[j][0] - prev[j][0]) ** 2
                 + (curr[j][1] - prev[j][1]) ** 2
                 + (curr[j][2] - prev[j][2]) ** 2) ** 0.5
                for j in joints
                if j in curr and j in prev
            ]
            velocities.append(sum(dists) / len(dists) if dists else 0.0)
        else:
            velocities.append(0.0)
        prev = curr

    return np.array(velocities, dtype=float)


def detect_peaks(velocities: np.ndarray, fps: float) -> np.ndarray:
    """Find motion peaks — minimum 0.2 s apart, prominence above 0.3 σ."""
    min_dist = max(1, int(fps * 0.2))
    prominence = float(np.std(velocities)) * 0.3
    peaks, _ = find_peaks(velocities, distance=min_dist, prominence=prominence)
    return peaks
