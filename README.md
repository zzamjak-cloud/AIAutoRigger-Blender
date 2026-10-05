# AI Auto Rigger (Blender Extension)

캐릭터 메시를 분석해 Rigify 컨트롤 리그(팔다리 IK)를 자동 생성하고, Claude 비전 에이전트로 관절 위치를 보정·검토하는 Blender Extension. 설계와 단계별 계획은 [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) 참고.

- Extension id: `ai_auto_rigger` · 최소 Blender 4.2 (개발 검증: 5.2 LTS, macOS arm64)
- 대상: 인간형 2족(사실·과장 비율, T/A-포즈), 4족(네 발 선 자세, 꼬리 자동 감지)
- 입력 조건: Z-up, 정면 -Y 또는 +Y(자동 감지), 좌우 대칭 권장

## 기능 (3D 뷰 사이드바 **AI Rig** 탭)

| 버튼 | 동작 |
|---|---|
| **Body Type** | Auto(다리 수로 판별) / Biped / Quadruped |
| **AI Auto Rig** | 휴리스틱 관절 추정 → 정면·측면 렌더를 Claude 가 분석 → 신뢰도 가중 병합 → Rigify 생성·바인딩. AI 실패·거절 시 휴리스틱으로 계속 |
| **Auto Rig** | AI 없이 휴리스틱만으로 메타리그 피팅 → Rigify 컨트롤 리그 → 자동 웨이트 |
| **Fit Metarig** / **Generate Control Rig** | 위 과정을 나눠 실행 (생성 전 메타리그 수동 보정 가능) |
| **AI Review Rig** | 테스트 포즈 렌더·변형 지표를 Claude 가 검토해 관절 이동·웨이트 스무딩 보정안을 제안. **체크한 항목만 Apply Selected 로 적용** |
| **Export Game FBX** | DEF 본 계층을 정리한 게임용 FBX. 2족은 Unity Humanoid 이름 + 매핑 JSON, 4족은 Generic. 애니메이션은 DEF 본으로 굽는다 |

생성 리그는 Rigify 표준이므로 IK/FK 전환, 발 구르기, 폴 타깃 등은 Rigify 리그 UI 에서 사용한다. 팔다리는 IK 모드로 생성된다.

### AI 설정

**Edit > Preferences > Add-ons > AI Auto Rigger** 에서 Anthropic API 키를 입력한다(비우면 `ANTHROPIC_API_KEY` 환경 변수 사용). 기본 모델 `claude-opus-5-5`, 관절 분석 effort `medium`, 검토 effort `high`, 검토 최대 턴 6. 렌더 이미지(메시 형상)가 Anthropic API 로 전송된다. 키가 없으면 Auto Rig(휴리스틱)만 사용할 수 있다. Preferences 에 입력한 키는 Blender 사용자 설정 파일(`userpref.blend`)에 평문으로 저장되므로, 공유 PC 에서는 환경 변수를 권장한다.

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
scripts/dev_run.sh --background --python tests/blender_ai_test.py   # AI Auto Rig (모의 Claude, 비용 없음)
scripts/dev_run.sh --background --python tests/blender_review_test.py  # AI 검토·보정안 적용 (모의 Claude)
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
