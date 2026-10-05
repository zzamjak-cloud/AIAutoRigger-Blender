#!/usr/bin/env bash
# 내보낸 2족 FBX 를 임시 Unity 프로젝트에 넣고 Humanoid 아바타 자동 매핑을 검사한다.
#   scripts/unity_avatar_check.sh <fbx> [unity-editor-version]
# 결과: 임시 프로젝트의 avatar_report.json 을 출력하고, 유효하면 종료 코드 0.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
FBX="${1:?FBX 경로가 필요합니다}"
EDITOR_VERSION="${2:-${AIRIG_UNITY_VERSION:-}}"
if [[ -z "$EDITOR_VERSION" ]]; then
  # 설치된 에디터 중 첫 번째를 쓴다
  EDITOR_VERSION="$(unity editors --installed --format json --no-banner | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"][0]["version"])')"
fi
PROJECT="$(mktemp -d "${TMPDIR:-/tmp}/airig_unity.XXXXXX")"
trap 'rm -rf "$PROJECT"' EXIT

mkdir -p "$PROJECT/Assets/Editor" "$PROJECT/Assets/Models" "$PROJECT/Packages" "$PROJECT/ProjectSettings"
echo '{"dependencies":{}}' > "$PROJECT/Packages/manifest.json"
echo "m_EditorVersion: $EDITOR_VERSION" > "$PROJECT/ProjectSettings/ProjectVersion.txt"
cp "$REPO_ROOT/tests/unity/AvatarCheck.cs" "$PROJECT/Assets/Editor/"
cp "$FBX" "$PROJECT/Assets/Models/"

status=0
unity run "$PROJECT" --editor-version "$EDITOR_VERSION" --no-banner --non-interactive \
  -- -executeMethod AvatarCheck.Run -logFile "$PROJECT/unity.log" || status=$?
if [[ -f "$PROJECT/avatar_report.json" ]]; then
  cat "$PROJECT/avatar_report.json"; echo
else
  echo "[unity_avatar_check] 리포트가 없습니다. 로그 끝부분:" >&2
  tail -n 40 "$PROJECT/unity.log" >&2 || true
fi
exit "$status"
