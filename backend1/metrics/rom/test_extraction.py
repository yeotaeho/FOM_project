"""
MediaPipe 0.10.31 Tasks API 마이그레이션 테스트 스크립트
"""
import sys
from pathlib import Path

# ROM 모듈 경로 추가
rom_path = Path(__file__).parent
sys.path.insert(0, str(rom_path))

import mediapipe as mp
print(f"MediaPipe version: {mp.__version__}")
print(f"Has solutions: {hasattr(mp, 'solutions')}")
print(f"Has tasks: {hasattr(mp, 'tasks')}")

# 모델 파일 확인
model_path = rom_path / "models" / "pose_landmarker_full.task"
print(f"\nModel file exists: {model_path.exists()}")
if model_path.exists():
    print(f"Model size: {model_path.stat().st_size:,} bytes")

# extraction_service import 테스트
try:
    from domain.domain1.hub.services.extraction_service import (
        extract_rom_data,
        extract_dance_data,
        LANDMARK_NAMES,
    )
    print(f"\n[OK] extraction_service import success")
    print(f"  - LANDMARK_NAMES: {len(LANDMARK_NAMES)} landmarks")
    print(f"  - extract_rom_data: {extract_rom_data.__doc__.strip()}")
except Exception as e:
    print(f"\n[ERROR] extraction_service import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 간단한 추출 테스트 (테스트 영상 있을 경우)
test_video = rom_path / "domain" / "domain1" / "video_data" / "test.mp4"
if test_video.exists():
    print(f"\nTest video found: {test_video}")
    try:
        print("Testing ROM extraction...")
        result = extract_rom_data(str(test_video), target_fps=15)
        print(f"[OK] Extraction successful!")
        print(f"  - Schema: {result['schema']}")
        print(f"  - FPS: {result['fps']}")
        print(f"  - Total frames: {result['total_frames']}")
        print(f"  - Sample stride: {result['sample_stride']}")
        if result['frames']:
            first_frame = result['frames'][0]
            print(f"  - First frame keys: {list(first_frame.keys())}")
            print(f"  - Joint angles: {list(first_frame['joint_angles'].keys())}")
    except Exception as e:
        print(f"[ERROR] Extraction failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
else:
    print(f"\nNo test video found (skipping extraction test): {test_video}")

print("\n=== Migration validation completed ===")

