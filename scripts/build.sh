#!/usr/bin/env bash
# 소스·ZIP 을 공식 Blender CLI 로 검증하고 dist/ 에 Extension ZIP 을 빌드한다.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BLENDER="${AIRIG_BLENDER_BINARY:-/Applications/Blender.app/Contents/MacOS/Blender}"
OUT_DIR="$REPO_ROOT/dist"
rm -f "$OUT_DIR"/*.zip
mkdir -p "$OUT_DIR"

"$BLENDER" --factory-startup --command extension validate "$REPO_ROOT"
"$BLENDER" --factory-startup --command extension build --split-platforms --source-dir "$REPO_ROOT" --output-dir "$OUT_DIR"
for zip in "$OUT_DIR"/*.zip; do
  "$BLENDER" --factory-startup --command extension validate "$zip"
done
