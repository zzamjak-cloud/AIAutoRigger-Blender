"""격리 개발 프로필에서 개발 Extension을 활성화한다 (macOS/Windows 실행기 공용)."""

import os
import sys

import addon_utils
import bpy

ADDON_ID = os.environ.get("AIRIG_ADDON_ID", "ai_auto_rigger")
MODULE = f"bl_ext.user_default.{ADDON_ID}"


def _raise(exc):
    raise exc


def main():
    print(f"[dev_bootstrap] BLENDER_USER_RESOURCES={os.environ.get('BLENDER_USER_RESOURCES')}")
    print(f"[dev_bootstrap] resource_path(USER)={bpy.utils.resource_path('USER')}")

    prefs = bpy.context.preferences
    if not any(repo.module == "user_default" for repo in prefs.extensions.repos):
        raise RuntimeError("user_default Extension 저장소가 없습니다.")

    addon_utils.modules_refresh()
    if MODULE in prefs.addons:
        print(f"[dev_bootstrap] already enabled: {MODULE}")
        return

    mod = addon_utils.enable(MODULE, default_set=True, handle_error=_raise)
    if mod is None:
        raise RuntimeError(f"애드온 활성화 실패: {MODULE}")
    # 최초 활성화 때만 전용 프로필에 저장해 다음 GUI 실행에서도 유지한다
    bpy.ops.wm.save_userpref()
    print(f"[dev_bootstrap] enabled and saved: {MODULE}")


try:
    main()
except Exception as exc:
    print(f"[dev_bootstrap] ERROR: {exc}", file=sys.stderr)
    raise
