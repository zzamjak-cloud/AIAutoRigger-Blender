# Changelog

## [0.2.0]

- AI 백엔드 선택: 로컬에 로그인된 **Claude Code CLI**·**Codex CLI** 를 API 키 없이 사용 (기본 Auto: Claude Code → Codex → API 순), Anthropic API 는 선택지로 유지
- AI Review Rig 를 라운드 방식(렌더 요청 → Blender 렌더 → 다음 라운드)으로 변경해 세 백엔드가 같은 경로를 사용
- Preferences 에 CLI 실행 파일 자동 탐색·경로 지정, CLI 모델, 시간 제한 추가. ESC 취소 시 실행 중인 CLI 프로세스 종료

## [0.1.1]

- 릴리스 패키지에 CI 용 Blender 배포본이 섞여 들어가던 문제 수정 (0.1.0 릴리스 ZIP 은 사용하지 말 것)
- 정면 +Y 캐릭터에서 .L 본이 해부학적 왼쪽이 되도록 기준 좌표를 Z축 180° 회전으로 변경, 검토 에이전트 오프셋을 정면 이미지 기준으로 변환
- AI 검토 모달 예외 처리·스레드 결과 전달 안전성, FBX 내보내기 후 씬 프레임 범위·선택 복원

## [0.1.0]

- 2족 자동 리깅: 표면 샘플링 + 단면·팔 연결 성분 기반 관절 추정(과장 비율·A/T-포즈·정면 ±Y), Rigify basic human 메타리그 피팅
- 4족 자동 리깅: 다리 기둥 추적 기반 관절 추정, 꼬리 자동 감지, Rigify basic quadruped 메타리그 피팅, 체형 자동 판별
- Rigify 컨트롤 리그 생성(팔다리 IK 기본), DEF 본 자동 웨이트 바인딩, B-Bone 롤 정렬로 rest 비틀림 방지
- AI Auto Rig: 정면·측면 직교 렌더 → Claude 비전 구조화 출력 → 광선 교차 3D 복원 → 신뢰도 가중 병합·IK 굽힘 보정
- AI Review Rig: 테스트 포즈 렌더·변형 지표 기반 보정안(관절 이동·웨이트 스무딩) 제안, 승인 후 적용
- 게임용 FBX 내보내기: DEF 계층 재구성, Unity Humanoid 이름·매핑 JSON, 애니메이션 굽기
- 평가 하네스(합성·실데이터), 격리 개발 프로필 실행기(macOS·Windows), 플랫폼별 SDK wheel 번들, GitHub 릴리스·Pages 배포 워크플로
