# AI Auto Rigger (Blender Extension)

캐릭터 메시를 분석해 Rigify 컨트롤 리그(팔다리 IK)를 자동 생성하고, 로컬 AI 에이전트(Claude Code CLI·Codex CLI) 또는 Claude API 로 관절 위치를 보정·검토하는 Blender Extension. 설계와 단계별 계획은 [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) 참고.

- Extension id: `ai_auto_rigger` · 최소 Blender 4.2 (개발 검증: 5.2 LTS, macOS arm64)
- 대상: 인간형 2족(사실·과장 비율, T/A-포즈, 손가락 1~5개 자동 감지), 4족(네 발 선 자세, 꼬리 자동 감지)
- 입력 조건: Z-up, 정면 -Y 또는 +Y(자동 감지), 좌우 대칭 권장

## 기능 (3D 뷰 사이드바 **AI Rig** 탭)

| 버튼 | 동작 |
|---|---|
| **Body Type** | Auto(다리 수로 판별) / Biped / Quadruped |
| **Jaw / Eyes** | 2족 턱·눈 본(기본 켬). 턱은 입 오목(입술 선)이 보일 때 만들고 아래턱 웨이트를 직접 부여한다(로컬 +X 회전 = 입 열림). 눈은 눈동자가 별도 메시 조각일 때만 만든다(눈이 머리와 한 덩어리로 조각된 모델은 눈 본을 돌리면 눈두덩이가 찌그러지므로 생략) |
| **Fingers** | 2족 손가락 감지 켜기/끄기(기본 켬). 손가락 끝을 표면 거리로 찾아 Rigify 손가락(palm + 3마디)을 만들고 엄지를 자동 판별. 손가락 끝이 손바닥에 붙은 주먹 자세는 감지하지 못한다 |
| **AI Auto Rig** | 휴리스틱 관절 추정 → 정면·측면 렌더를 AI(Claude Code CLI·Codex CLI·API)가 분석 → 신뢰도 가중 병합 → Rigify 생성·바인딩. AI 실패·거절 시 휴리스틱으로 계속 |
| **Auto Rig** | AI 없이 휴리스틱만으로 메타리그 피팅 → Rigify 컨트롤 리그 → 자동 웨이트 |
| **Fit Metarig** / **Generate Control Rig** | 위 과정을 나눠 실행 (생성 전 메타리그 수동 보정 가능) |
| **AI Review Rig** | 테스트 포즈 렌더·변형 지표를 AI 가 라운드 방식으로 검토(필요하면 추가 포즈 렌더 요청)해 관절 이동·웨이트 스무딩 보정안을 제안. **체크한 항목만 Apply Selected 로 적용** |
| **Export Game FBX** | DEF 본 계층을 정리한 게임용 FBX. 2족은 Unity Humanoid 이름 + 매핑 JSON, 4족은 Generic. 애니메이션은 DEF 본으로 굽고, NLA 에 올린 액션과 활성 액션을 액션 이름의 테이크로 모두 담는다. **Simplify Bones** 로 트위스트·손바닥·골반 본을 합쳐 본 수를 줄일 수 있다 |

생성 리그는 Rigify 표준이므로 IK/FK 전환, 발 구르기, 폴 타깃 등은 Rigify 리그 UI 에서 사용한다. 팔다리는 IK 모드로 생성된다.

### AI 설정 (로컬 CLI 또는 API)

**Edit > Preferences > Add-ons > AI Auto Rigger** 의 **AI Backend** 에서 고른다.

| 백엔드 | 인증 | 호출 방식 |
|---|---|---|
| **Auto** (기본) | — | 설치된 Claude Code CLI → Codex CLI → API 키 순으로 사용 |
| **Claude Code CLI** | `claude` 에 로그인된 계정(구독) | `claude -p --json-schema …`, Read 도구만 허용, 사용자 설정·MCP 미사용 |
| **Codex CLI** | `codex` 에 로그인된 계정 | `codex exec -i <렌더> --output-schema …`, 읽기 전용 샌드박스 |
| **Anthropic API** | API 키 또는 `ANTHROPIC_API_KEY` | 번들 anthropic SDK, 기본 모델 `claude-opus-5-5` |

- CLI 는 PATH 와 흔한 설치 위치(`~/.local/bin`, `~/.npm-global/bin`, `/opt/homebrew/bin` 등)에서 자동으로 찾는다. Finder·Dock 으로 연 Blender 는 셸 PATH 를 물려받지 않으므로 못 찾으면 경로를 직접 지정한다. Preferences 에 찾은 경로가 표시된다.
- CLI 모델을 비우면 각 CLI 의 기본 모델을 쓴다. 관절 분석 effort `medium`, 검토 effort `high`, 검토 최대 4라운드, 시간 제한 600초.
- CLI 백엔드는 API 요금 대신 각 구독의 사용량 한도를 쓰며, 호출마다 CLI 기동 시간(수 초 이상)이 더해진다.
- 렌더 이미지(메시 형상)가 선택한 서비스로 전송된다. API 키를 Preferences 에 넣으면 `userpref.blend` 에 평문 저장되므로 공유 PC 에서는 환경 변수를 권장한다.
- AI 백엔드를 쓸 수 없으면 Auto Rig(휴리스틱)만 사용할 수 있다.

### 애니메이션 (2족)

리그를 만든 뒤 사이드바 **애니메이션** 상자에서 만든다.

| 항목 | 동작 |
|---|---|
| **Motion / Style** | 루프: Walk·Run·Idle·Happy / 단발: Jump·Attack·Hit·Death × Normal·Zombie 프리셋 |
| **Root Motion** | 끄면 제자리(게임 엔진 권장), 켜면 전진한다. 걷기·달리기는 주기마다 이어지고 점프는 체공 중에 한 번 이동한다 |
| **Generate Motion** | 프리셋으로 바로 생성 (AI 없음) |
| **Library** | 동작 사전의 포즈 클립으로 바로 생성 (AI 없음). 내장 14종 + 사용자 저장분 |
| **프롬프트 + AI Motion** | 예: "좀비가 다리를 절며 걷는 루프", "양손 도끼 내려찍기", "손 흔들며 인사", "바닥에 앉기". AI 가 절차 생성기 파라미터(PARAMS) 또는 포즈 시퀀스(CLIP) 중 맞는 쪽으로 설계하고, **Review Rounds** 만큼 측면·정면 프레임 렌더와 실측값을 보며 보정한다 |
| **Save** | 현재 애니메이션을 포즈 클립으로 바꿔 사용자 사전에 저장한다. 이후 Library 드롭다운과 AI 설계 예시에 나타난다 |

| 동작 | 종류 | 내용 |
|---|---|---|
| Walk / Run / Idle | 루프 | 걷기·달리기·대기 |
| Happy | 루프 | 두 팔을 머리 위로 들고 흔들며 두 번 깡충 뛴다 |
| Jump | 단발 | 웅크림 → 도약 → 체공(무릎 접음) → 착지 주저앉음 → 복귀 |
| Attack | 단발 | 한 손(기본 오른손)을 뒤로 빼며 몸을 비틀고 돌진하며 휘두른 뒤 복귀. 반대 손은 방어 자세 |
| Hit | 단발 | 충격에 몸통이 뒤로 젖혀지고 밀리며 팔이 벌어졌다가 복귀 |
| Death | 단발 | 무릎이 꺾이며 뒤(Normal) 또는 앞(Zombie)으로 쓰러져 눕고 끝 자세를 유지 |

Attack 은 궤적 `attack_kind`(SWING 휘두르기 · THRUST 찌르기 · SLASH_H 가로 베기 · SLASH_V 세로 베기 · OVERHEAD 내려찍기)와 `two_handed`(양손 그립)를 AI 가 고른다.

**동작 사전 (포즈 클립)** — Library 드롭다운 또는 AI 가 변형해 쓴다.

| 이름 | 종류 | 내용 |
|---|---|---|
| punch / dagger_stab / sword_thrust | 단발 | 주먹·단검·장검 찌르기 |
| sword_slash / axe_overhead_2h | 단발 | 한손 가로 베기, 양손 도끼 내려찍기 |
| kick / block | 단발 | 앞차기, 방어 |
| wave / clap / cheer / dance | 루프 | 손 흔들기, 박수, 환호, 춤 |
| bow / point / sit_down | 단발 | 인사, 가리키기, 바닥에 앉기(앉은 자세 유지) |

- 포즈 클립은 몸통·골반·가슴·머리·양손·양발의 캐릭터 기준 오프셋과 회전(도)만 쓰는 JSON 이다. 몸통·발은 레스트 기준 다리 길이 비율, 손은 **어깨 기준 팔 길이 비율**이라(|벡터| ≤ 1 이면 닿음) 레스트 자세가 다른 캐릭터에서도 같은 클립이 같은 동작이 된다. 손은 몸통 이동·회전을 따른다. 발 접지 구간 선형, 바닥 관통 방지, 루프 닫기, 키 수 제한(12), 범위 클램프는 코드가 보장하므로 AI 가 값을 잘못 써도 캐릭터가 바닥을 뚫거나 루프가 끊기지 않는다.
- 사용자 사전은 Blender 설정 폴더의 `ai_auto_rigger/motions/*.json` 이다. 같은 이름은 사용자 항목이 내장 항목을 덮는다.
- 무기 메시는 포함하지 않는다. 손 궤적·회전만 만들므로 Unity 에서 손 본에 무기를 붙여 쓴다.

- 키는 매 프레임이 아니라 동작 극점(접지·낮은 자세·교차·높은 자세)에만 들어간다. 커브당 최대 7개, Auto-Clamped 베지어, 루프는 Cycles 모디파이어로 반복한다. 단발 동작은 반복하지 않고 끝 키 값을 유지한다(점프·공격·피격은 레스트로 복귀, 사망은 누운 자세). 걷기 32프레임 기준 키 포즈 59개(매 프레임 방식은 352개)라 그래프 에디터에서 손으로 다듬기 쉽다.
- 발이 땅을 딛는 구간만 선형 보간이라 미끄러지지 않고, 발 굴림은 Rigify `foot_heel_ik` 로 처리해 발끝이 바닥을 뚫지 않는다.
- 결과는 `<리그>_<동작>_<스타일>` 액션(Fake User)으로 저장된다. 같은 이름으로 다시 만들면 교체되고, NLA 등 다른 곳에서 쓰는 액션은 `_old` 로 보존된다.
- **Export Game FBX** 가 NLA 에 올린 액션(뮤트 포함)과 활성 액션을 각 액션 구간대로 구워 액션 이름의 테이크로 내보내므로 Unity 에서 Humanoid 클립으로 쓴다. 루프 동작은 Loop Time 을 켜고, 단발 동작은 끈다.

### Unity 로 내보내기

- metarig(숨겨진 설계도)와 Rigify 컨트롤 리그는 Blender 안에서 애니메이션 작업용이다. 직접 내보내지 말고 **Export Game FBX** 를 쓴다.
- 내보내기는 DEF(변형) 본만 Hips 아래 한 계층으로 다시 엮은 임시 아마추어를 만들어 메시와 함께 FBX 로 쓰고, 컨트롤 리그 애니메이션은 이 본들에 굽는다. 컨트롤 본 수백 개는 FBX 에 들어가지 않는다(예: 리그 366본 → FBX 63본, Simplify 시 47본). Unity 이름일 때 트위스트·손바닥 본은 Humanoid 본 사이에 끼지 않도록 부모 Humanoid 본의 곁가지로 둔다(사이에 끼면 Unity 가 "Inbetween bone rotation ... does not match" 리그 오류를 낸다). 또 Unity 이름일 때는 본 스케일을 굽지 않는다(Humanoid 는 스케일 애니메이션을 버리며 경고를 낸다. Rigify IK 스트레치로 생기는 사지 길이 변화는 Unity 에서 반영되지 않는다).
- Unity: FBX 의 **Rig > Animation Type = Humanoid**, **Avatar Definition = Create From This Model**. 손가락·턱·눈까지 자동 매핑되며 `<이름>.humanoid.json` 에 매핑 표가 함께 저장된다.
- 본 수: 스키닝 비용은 본 수보다 정점 수 × 정점당 영향 본 수(Unity 기본 4)에 좌우된다. 60본대는 일반적인 휴머노이드 수준이며, 모바일·군중용은 Simplify Bones 를 권장한다.
- 정면이 +Y 인 모델은 Unity 에서 뒤를 보고 들어오므로 Blender 에서 Z축 180° 회전을 적용한 뒤 리깅하는 것을 권장한다.

## 사용자 설치 (원격 저장소)

1. **Edit > Preferences > Get Extensions > Repositories > + > Add Remote Repository** 에 아래 URL 등록

   ```text
   https://zzamjak-cloud.github.io/AIAutoRigger-Blender/index.json
   ```

2. 목록에서 **AI Auto Rigger** 설치 (플랫폼별 SDK 가 포함된 패키지가 자동 선택됨)
3. 저장소 설정의 **Check for Updates on Startup** 을 켜면 Blender 시작 시 새 버전을 확인해 알려 준다. 업데이트 설치는 사용자가 **Update** 를 눌러 승인한다.

## 개발 (격리 프로필)

일상 Blender 프로필과 설치된 릴리스를 건드리지 않고, 저장소 소스를 전용 프로필에 링크해 바로 로드한다. 소스 수정 후 Blender 만 다시 시작하면 된다. AI 기능용 SDK 는 처음 한 번 wheel 을 받아 둔다.

```bash
/Applications/Blender.app/Contents/Resources/5.2/python/bin/python3.13 scripts/fetch_wheels.py   # wheels/ 채우고 매니페스트 갱신
```

### macOS

```bash
scripts/dev_run.sh                                   # GUI 실행
scripts/dev_run.sh --link-only                       # 링크만 갱신
scripts/dev_run.sh --background --python tests/blender_smoke.py
```

- 프로필: `~/Library/Application Support/Blender/AIAutoRiggerDev/<버전>/`
- 링크: `extensions/user_default/ai_auto_rigger -> <저장소>`
- 환경 변수: `AIRIG_BLENDER_BINARY`(기본 `/Applications/Blender.app/Contents/MacOS/Blender`), `AIRIG_PROFILE_ROOT`

### Windows

프로젝트 전용 포터블 Blender(ZIP 버전)를 별도 폴더에 풀고 그 경로를 지정한다.

```powershell
$env:AIRIG_BLENDER_DIR = "D:\Blender\AIAutoRiggerDev\blender-5.2"
scripts\dev_run.ps1                                  # GUI
scripts\dev_run.ps1 -LinkOnly
scripts\dev_run.ps1 -Background -PythonFile tests\blender_smoke.py
scripts\dev_run.ps1 -Background -PythonExpr "import bpy"
```

명령 프롬프트에서는 `scripts\dev_run.bat` 에 같은 인자를 넘긴다. 링크는 `<포터블>\portable\extensions\user_default\ai_auto_rigger` Junction 이며, 그 자리에 실제 폴더가 있으면 삭제하지 않고 중단한다. Blender 단축 인자(`-b`, `-P`)는 PowerShell 파라미터와 충돌하므로 `--` 뒤에 긴 형식으로 넘긴다.

## 테스트

```bash
python3 -m unittest discover -s tests                               # 순수 Python 단위·정적 검사
scripts/dev_run.sh --background --python tests/blender_smoke.py     # 등록·분석·해제
scripts/dev_run.sh --background --python tests/blender_rig_test.py  # 2족·4족 자동 리깅, IK 동작, rest 변형 0
scripts/dev_run.sh --background --python tests/blender_finger_test.py  # 손가락 검출·Rigify 손가락 굽힘 (곧은 손·갈고리 손·벙어리장갑형)
scripts/dev_run.sh --background --python tests/blender_face_test.py -- dist/face_test  # 턱·눈 리깅, Unity 이름·간소화 내보내기
scripts/dev_run.sh --background --python tests/blender_motion_test.py -- dist/motion_test  # 루프·단발·공격 궤적·동작 사전·FBX 굽기·AI Motion(가짜 CLI)
scripts/dev_run.sh --background --python tests/blender_ai_test.py   # AI Auto Rig: API(모의 SDK)·Claude Code·Codex(가짜 CLI), 비용 없음
scripts/dev_run.sh --background --python tests/blender_review_test.py  # AI 검토 라운드·보정안 적용 (가짜 Codex CLI)
scripts/dev_run.sh --background --python tests/blender_export_test.py -- dist/export_test  # 게임 FBX 재임포트 검증
scripts/unity_avatar_check.sh dist/export_test/biped_unity.fbx      # Unity Humanoid 아바타 매핑 (Unity CLI 필요)
```

`AIRIG_RENDER_DIR=<폴더>` 를 지정하면 리깅·AI 테스트가 포즈 렌더를 저장한다.

### 평가

```bash
scripts/dev_run.sh --background --python scripts/eval_run.py -- --synthetic 6 --data <eval-data> --out dist/eval
```

합성 세트(비율 무작위 2족·4족)와 실데이터(`<eval-data>/<범주>/*.fbx|glb`, 리깅된 모델에서 정답 관절 추출 → 리그 제거 → 재리깅)를 크기 대비 관절 오차로 집계해 `report.md`/`report.json` 을 쓴다. 데이터 출처·라이선스는 [tests/eval/sources.toml](tests/eval/sources.toml).

## 빌드·배포

```bash
scripts/build.sh    # validate(소스) → 플랫폼별 build → validate(ZIP), 결과는 dist/
```

- `.github/workflows/check.yml`: push·PR 에서 단위 검사, Extension 검증·빌드, Linux Blender 런타임 검사(렌더가 필요한 AI·검토 테스트 제외)
- `.github/workflows/release.yml`: `v<버전>` 태그(매니페스트 버전과 일치해야 함)에서 플랫폼별 ZIP 을 GitHub Release 에 첨부
- `.github/workflows/pages.yml`: 릴리스 성공 후 최신 릴리스 ZIP 으로 `index.json` 을 만들어 GitHub Pages 에 배포

## 라이선스

GPL-3.0-or-later. 번들 wheel 은 각 패키지 라이선스를 따른다.
