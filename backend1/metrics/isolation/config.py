"""Isolation metric — 로컬 경로·YOLO 설정."""

from pathlib import Path

ISOLATION_ROOT = Path(__file__).resolve().parent
DATA_RAW = ISOLATION_ROOT / "data" / "raw"
DATA_ARTIFACTS = ISOLATION_ROOT / "data" / "artifacts"
DATA_MODELS = ISOLATION_ROOT / "data" / "models"

# 기준 Shorts (팀 고정)
REF_VIDEO_URL = "https://www.youtube.com/shorts/YzTywjy0VXU"
REF_VIDEO_NAME = "ref.mp4"

# 사용자 비교용 (Shorts — 용량·다운로드 안정)
USER_VIDEO_URL = "https://www.youtube.com/shorts/9kLf88IksZU"
USER_VIDEO_NAME = "user.mp4"

# 기준(ref) 영상 — 앞 N초만 user 와 비교 (Shorts 앞 구간)
REF_COMPARE_DURATION_SEC = 15.0

# YOLO11 (ultralytics) — n=빠름, s/m=정확도↑ (없으면 ultralytics가 자동 다운로드)
YOLO_MODEL = str(DATA_MODELS / "yolo11n.pt")
YOLO_CONF = 0.4
YOLO_IOU = 0.5
YOLO_PERSON_CLASS = 0
CROP_PADDING_RATIO = 0.15

# MediaPipe Tasks API — Pose Landmarker Heavy (.task, Git 제외)
MP_POSE_MODEL = str(DATA_MODELS / "pose_landmarker_heavy.task")
MP_MIN_DETECTION_CONFIDENCE = 0.5
MP_MIN_TRACKING_CONFIDENCE = 0.5
MP_SMOOTH_WINDOW = 3

# FOM 통합 video_json 기준 ref (cli extract → publish 또는 자동 복사)
REF_ISOLATION_JSON_FILENAME = "ref_isolation.json"

# 정렬: beat(음악 박자, 기본) | time(시각만)
DEFAULT_ALIGNMENT_METHOD = "beat"

# 비교·박자 축: 영상 0초가 아니라 오디오에서 음악이 시작되는 시각
ALIGN_TO_MUSIC_START = True
