# Changelog

## [0.5.0]

- 2족 애니메이션 루프: 걷기·달리기·대기 × Normal·Zombie 프리셋. 극점 포즈에만 키를 두는 희소 베지어 키(커브당 최대 7개, Auto-Clamped)와 Cycles 모디파이어로 끊김 없는 루프. 발 딛는 구간만 선형이라 미끄러지지 않음
- Root Motion 옵션(전진 거리 자동 계산, 주기마다 이어짐), 발 굴림은 Rigify foot_heel_ik 사용(바닥 관통 방지)
- **AI Motion**: 프롬프트("좀비가 걷는 루프")를 로컬 Claude Code/Codex CLI 또는 API 가 걸음 파라미터로 바꾸고, 측면·정면 프레임 렌더와 실측값(cm)을 보며 보정 라운드 수행
- Export Game FBX 가 루프 구간을 그대로 구워 Unity Humanoid 로 사용 가능

## [0.4.0]

- 턱(jaw) 본 자동 생성: 얼굴 정면 윤곽에서 입술 선·턱 끝을 찾아(입 오목이 보일 때) 회전축을 귀 아래에 두고, 아래턱 웨이트를 직접 부여. 로컬 +X 회전 = 입 열림. 입속 조각(아랫니·혀)은 턱에 고정
- 눈(eye) 본: 눈동자가 별도 메시 조각일 때 좌우 한 쌍을 골라 생성하고 눈동자 조각만 움직이게 함
- 손가락이 갈라지지 않은 손: 손만 있으면 손 본만, 엄지 + 손가락 덩어리면 엄지와 덩어리 체인을 생성
- Unity 내보내기: 목 보조 본(Neck2)을 Neck 에 합쳐 Head 오매핑 해결, Jaw·LeftEye·RightEye·LeftPalmN 이름 매핑
- Export Game FBX 에 **Simplify Bones** 옵션(트위스트·손바닥·골반 본을 부모에 합침, 예: 63 → 47본)

## [0.3.0]

- 2족 손가락 자동 리깅: 손목에서의 측지 거리 국소 최대점을 손가락 끝으로 보고(돌출도로 주름·평면 제외), 등고선 단면 중심을 이어 관절을 손가락 안쪽에 배치. 굽은 갈고리 손가락·로우폴리 손 대응, 손가락 수 1~5개 자동(엄지 자동 판별)
- Rigify 정식 손가락 구조 생성: palm.0N(super_palm) + 손가락 3마디(super_finger), 엄지는 palm.01 아래
- 패널에 Fingers 토글·감지된 손가락 수 표시, 손가락이 없는 손(벙어리장갑형)은 손 본까지만 생성
- Unity Humanoid 손가락 이름 매핑(Thumb/Index/Middle/Ring/Little × Proximal/Intermediate/Distal)

## [0.2.1]

- 애드온 활성화 시 Claude Code CLI·Codex CLI 경로를 자동으로 찾아 Preferences 경로 칸에 채움 (Finder·Dock 으로 실행한 Blender 포함)
- Preferences 에 **CLI 다시 찾기** 버튼, 지정 경로가 사라지면 자동 탐색으로 복귀
- 사이드바에 현재 사용할 AI 백엔드와 실행 파일 표시

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
