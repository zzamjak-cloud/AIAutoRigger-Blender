"""격리 프로필 Blender 런타임 smoke test.

실행: scripts/dev_run.sh --background --python tests/blender_smoke.py
"""

import os
import pathlib
import re

import addon_utils
import bpy

ADDON_ID = os.environ["AIRIG_ADDON_ID"]
MODULE = f"bl_ext.user_default.{ADDON_ID}"
ROOT = pathlib.Path(__file__).resolve().parents[1]


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[smoke] OK  {msg}")


user_res = os.environ.get("BLENDER_USER_RESOURCES", "")
check("AIAutoRiggerDev" in user_res, f"전용 프로필 사용: {user_res}")
check(
    os.path.realpath(bpy.utils.resource_path("USER")) == os.path.realpath(user_res),
    "resource_path(USER) 가 전용 프로필을 가리킴",
)

link = pathlib.Path(user_res) / "extensions" / "user_default" / ADDON_ID
check(link.is_symlink() and link.resolve() == ROOT, "개발 링크가 저장소 루트로 해석됨")

check(MODULE in bpy.context.preferences.addons, f"{MODULE} 활성화")
mod = __import__(MODULE, fromlist=["register"])

manifest = (ROOT / "blender_manifest.toml").read_text(encoding="utf-8")
manifest_version = re.search(r'^version\s*=\s*"([^"]+)"', manifest, re.M).group(1)
loaded_version = addon_utils.module_bl_info(mod).get("version")
check(
    ".".join(map(str, loaded_version)) == manifest_version,
    f"로드된 버전 {loaded_version} == 매니페스트 {manifest_version}",
)

# 핵심 기능: 좌우 대칭 메시 분석
bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.9))
cube = bpy.context.active_object
cube.scale = (0.4, 0.25, 1.8)
bpy.context.view_layer.update()

result = bpy.ops.airig.analyze_mesh()
check(result == {"FINISHED"}, "airig.analyze_mesh 실행")
state = bpy.context.scene.airig
check(state.analyzed_object == cube.name, "분석 대상 기록")
check(state.vertex_count == 8, f"정점 수 {state.vertex_count}")
check(state.up_axis == "Z", f"높이 축 {state.up_axis}")
check(abs(state.dimensions[2] - 1.8) < 1e-4, f"높이 {state.dimensions[2]:.4f}")
check(state.symmetry_x > 0.99, f"대칭도 {state.symmetry_x:.2f}")

# 등록 해제 후 잔여 등록 없음
addon_utils.disable(MODULE, default_set=False, handle_error=lambda e: (_ for _ in ()).throw(e))
check(not hasattr(bpy.types.Scene, "airig"), "해제 후 Scene.airig 제거")
check(getattr(bpy.types, "AIRIG_OT_analyze_mesh", None) is None, "해제 후 연산자 제거")
check(getattr(bpy.types, "AIRIG_PT_main", None) is None, "해제 후 패널 제거")
print("[smoke] ALL PASSED")
