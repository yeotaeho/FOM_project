import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from domain.domain1.hub.services.extraction_service import extract_rom_data

test_video = 'test_sample.mp4'
print(f'Testing ROM extraction on: {test_video}')
print('=' * 60)

try:
    result = extract_rom_data(test_video, target_fps=15)
    print(f'[SUCCESS] ROM extraction completed!')
    print(f'  Schema: {result["schema"]}')
    print(f'  Source FPS: {result["fps"]}')
    print(f'  Total frames extracted: {result["total_frames"]}')
    print(f'  Sample stride: {result["sample_stride"]}')
    print(f'  Effective sample FPS: {result["effective_sample_fps"]}')
    
    if result['frames']:
        print(f'  Total frames in result: {len(result["frames"])}')
        first = result['frames'][0]
        print(f'  First frame keys: {list(first.keys())}')
        print(f'  Joint angles count: {len(first["joint_angles"])}')
        print(f'  Joint angles: {list(first["joint_angles"].keys())}')
        print(f'  Sample values: {dict(list(first["joint_angles"].items())[:3])}')
    print('\n[OK] All checks passed!')
except Exception as e:
    print(f'[ERROR] {type(e).__name__}: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
