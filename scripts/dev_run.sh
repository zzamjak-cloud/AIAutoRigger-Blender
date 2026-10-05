#!/usr/bin/env bash
# macOS 격리 개발 프로필 실행기.
# 저장소 소스를 전용 프로필의 extensions/user_default/<id> 로 심링크해 일상 프로필을 건드리지 않는다.
#
# 사용 예:
#   scripts/dev_run.sh                                    # GUI
#   scripts/dev_run.sh --link-only                        # 링크만 갱신
#   scripts/dev_run.sh --background --python tests/blender_smoke.py
#   scripts/dev_run.sh --background --python-expr "import bpy"
#
# 환경 변수:
#   AIRIG_BLENDER_BINARY  Blender 실행 파일 (기본: /Applications/Blender.app/Contents/MacOS/Blender)
#   AIRIG_PROFILE_ROOT    프로필 루트 (기본: ~/Library/Application Support/Blender/AIAutoRiggerDev)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
MANIFEST="$REPO_ROOT/blender_manifest.toml"
if [[ ! -f "$MANIFEST" ]]; then
  echo "[dev_run] blender_manifest.toml 을 찾을 수 없습니다: $MANIFEST" >&2
  exit 1
fi

ADDON_ID="$(sed -n 's/^id[[:space:]]*=[[:space:]]*"\([A-Za-z0-9_]*\)".*/\1/p' "$MANIFEST" | head -n 1)"
if [[ -z "$ADDON_ID" ]]; then
  echo "[dev_run] 매니페스트에서 id 를 읽지 못했습니다." >&2
  exit 1
fi

BLENDER="${AIRIG_BLENDER_BINARY:-/Applications/Blender.app/Contents/MacOS/Blender}"
if [[ ! -x "$BLENDER" ]]; then
  echo "[dev_run] Blender 실행 파일이 없습니다: $BLENDER (AIRIG_BLENDER_BINARY 로 지정)" >&2
  exit 1
fi

BLENDER_VERSION="$("$BLENDER" --factory-startup --version 2>/dev/null | sed -n 's/^Blender \([0-9]*\.[0-9]*\).*/\1/p' | head -n 1)"
if [[ -z "$BLENDER_VERSION" ]]; then
  echo "[dev_run] Blender 버전을 확인하지 못했습니다." >&2
  exit 1
fi

PROFILE_ROOT="${AIRIG_PROFILE_ROOT:-$HOME/Library/Application Support/Blender/AIAutoRiggerDev}"
USER_RESOURCES="$PROFILE_ROOT/$BLENDER_VERSION"
EXT_DIR="$USER_RESOURCES/extensions/user_default"
LINK="$EXT_DIR/$ADDON_ID"
mkdir -p "$EXT_DIR"

# 링크 자리에 실제 폴더/파일이 있으면 사용자 데이터일 수 있으므로 삭제하지 않고 중단한다
if [[ -e "$LINK" && ! -L "$LINK" ]]; then
  echo "[dev_run] 링크 위치에 실제 파일/폴더가 있어 중단합니다: $LINK" >&2
  exit 1
fi
if [[ ! -L "$LINK" || "$(readlink "$LINK")" != "$REPO_ROOT" ]]; then
  TMP_LINK="$EXT_DIR/.$ADDON_ID.tmp.$$"
  ln -s "$REPO_ROOT" "$TMP_LINK"
  # -h: 기존 심링크가 가리키는 디렉터리 안으로 이동하지 않고 링크 자체를 교체한다
  mv -f -h "$TMP_LINK" "$LINK"
fi

export BLENDER_USER_RESOURCES="$USER_RESOURCES"
export AIRIG_ADDON_ID="$ADDON_ID"
echo "[dev_run] profile: $USER_RESOURCES"
echo "[dev_run] link:    $LINK -> $REPO_ROOT"

PRE_ARGS=()
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --link-only) exit 0 ;;
    # 백그라운드 플래그는 부트스트랩보다 먼저 와야 GUI 초기화 없이 실행된다
    -b|--background) PRE_ARGS+=("--background") ;;
    *) ARGS+=("$arg") ;;
  esac
done

exec "$BLENDER" ${PRE_ARGS[@]+"${PRE_ARGS[@]}"} \
  --python-exit-code 1 \
  --python "$REPO_ROOT/scripts/dev_bootstrap.py" \
  ${ARGS[@]+"${ARGS[@]}"}
