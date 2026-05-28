# MediaPipe 0.10.31 마이그레이션 완료

## 변경 사항 요약

### 1. MediaPipe API 변경
- **이전:** `mp.solutions.pose.Pose` (Legacy Solutions API)
- **현재:** `mp.tasks.vision.PoseLandmarker` (Tasks API, VIDEO 모드)

### 2. 주요 변경 파일
- `domain/domain1/hub/services/extraction_service.py` - Tasks API로 전환
- `backend/domain/domain1/hub/services/extraction_service.py` - Tasks API로 전환
- `requirements.txt` (두 곳) - `mediapipe>=0.10.31,<0.11`로 업데이트

### 3. 새로 추가된 파일
- `models/pose_landmarker_full.task` (9.4MB) - MediaPipe Pose Landmarker 모델

### 4. 의존성
```
mediapipe>=0.10.31,<0.11
opencv-python>=4.9.0
numpy>=1.26.0
pandas>=2.2.0
```

### 5. 테스트 결과
```
MediaPipe version: 0.10.31
[SUCCESS] ROM extraction completed!
  Schema: rom_v1
  Source FPS: 30.0
  Total frames extracted: 75
  Sample stride: 2
  Effective sample FPS: 15.0
  Joint angles count: 10
```

## 기능 검증 완료
- ✅ MediaPipe 0.10.31 설치
- ✅ Tasks API import
- ✅ 모델 파일 다운로드 및 배치
- ✅ ROM 추출 (`extract_rom_data`) 정상 작동
- ✅ Full 추출 (`extract_dance_data`) 코드 업데이트
- ✅ 33개 랜드마크 정상 추출
- ✅ 10개 관절 각도 계산
- ✅ 정규화·보간·스무딩 로직 유지
- ✅ JSON 스키마 (rom_v1, full_v1) 호환

## 주의 사항
1. **모델 파일 배포:** `models/pose_landmarker_full.task` 파일을 배포 환경에 포함해야 함
2. **수치 차이:** 기존 0.10.14 Solutions와 0.10.31 Tasks는 내부 모델이 다를 수 있어 추출된 랜드마크 좌표가 약간 다를 수 있음
3. **레퍼런스 재추출 권장:** 기존 레퍼런스 JSON과 정확히 비교하려면 같은 버전으로 재추출 필요

## 다음 단계
- [ ] 실제 댄스 영상으로 end-to-end 테스트
- [ ] 기존 레퍼런스 JSON 재추출 (optional)
- [ ] 배포 환경에 모델 파일 배치
- [ ] CI/CD 파이프라인에 모델 다운로드 스크립트 추가 (optional)
