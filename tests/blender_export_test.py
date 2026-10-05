"""게임용 FBX 내보내기 테스트: 계층·이름·웨이트·애니메이션 굽기를 재임포트로 검증.

실행: scripts/dev_run.sh --background --python tests/blender_export_test.py -- <출력 폴더>
"""

import json
import pathlib
import sys

import bpy
from mathutils import Matrix, Vector

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
import humanoid  # noqa: E402
import quadruped  # noqa: E402

OUT = pathlib.Path(sys.argv[sys.argv.index("--") + 1]) if "--" in sys.argv else ROOT / "dist" / "export_test"


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[export] OK  {msg}")


def rig_fixture(module, variant):
    bpy.ops.wm.read_homefile(use_empty=True)
    verts, tris, _ = module.build(variant)
    mesh = bpy.data.meshes.new(variant)
    mesh.from_pydata(verts, [], tris)
    obj = bpy.data.objects.new(variant, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    mod = obj.modifiers.new("remesh", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = 0.02
    bpy.ops.object.modifier_apply(modifier=mod.name)
    check(bpy.ops.airig.auto_rig() == {"FINISHED"}, f"{variant}: 자동 리깅")
    state = bpy.context.scene.airig
    return obj, bpy.data.objects[state.rig_name]


def key_ik(rig, bone, delta):
    pb = rig.pose.bones[bone]
    pb.keyframe_insert("location", frame=1)
    bpy.context.scene.frame_set(1)
    world = Matrix.Translation(Vector(delta)) @ (rig.matrix_world @ pb.matrix)
    pb.matrix = rig.matrix_world.inverted() @ world
    pb.keyframe_insert("location", frame=20)


def ancestors(bone):
    out = []
    while bone.parent:
        bone = bone.parent
        out.append(bone.name)
    return out


def reimport(path):
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(path))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    return arm, mesh


# 2족: Unity 이름 + 애니메이션
obj, rig = rig_fixture(humanoid, "realistic_t")
key_ik(rig, "hand_ik.L", (0.0, -0.3, 0.3))
path = OUT / "biped_unity.fbx"
check(bpy.ops.airig.export_fbx(filepath=str(path), naming="UNITY", bake_anim=True) == {"FINISHED"}, "2족 FBX 내보내기")
check(not [o for o in bpy.data.objects if o.get("airig_game")], "임시 게임 아마추어 정리")
mapping = json.loads(path.with_suffix(".humanoid.json").read_text())
required = ["Hips", "Spine", "Chest", "Neck", "Head"] + [f"{w}{p}" for w in ("Left", "Right")
                                                        for p in ("UpperArm", "LowerArm", "Hand", "UpperLeg", "LowerLeg", "Foot")]
check(all(r in mapping for r in required), "Humanoid 필수 본 매핑 JSON")

arm, mesh = reimport(path)
bones = arm.data.bones
roots = [b.name for b in bones if b.parent is None]
check(roots == ["Hips"], f"루트 본은 Hips 하나 {roots}")
check(bones["LeftLowerLeg"].parent.name == "LeftUpperLegTwist", "트위스트 분절 체인 유지")
for name in ("LeftUpperLeg", "RightUpperLeg", "LeftUpperArm", "Head"):
    check("Hips" in ancestors(bones[name]), f"{name} 이 Hips 계층 아래")
check("LeftShoulder" in ancestors(bones["LeftUpperArm"]), "LeftUpperArm → LeftShoulder 부모")
check(not any(b.name.startswith(("ORG-", "MCH-", "DEF-")) for b in bones), "컨트롤·DEF 접두 본 미포함")
groups = {g.name for g in mesh.vertex_groups}
check({"LeftUpperLeg", "LeftHand", "Hips"} <= groups, "메시 웨이트 그룹이 Unity 이름")
check(arm.animation_data and arm.animation_data.action, "애니메이션 액션 포함")
scene = bpy.context.scene
scene.frame_set(1)
h1 = (arm.matrix_world @ arm.pose.bones["LeftHand"].head).copy()
scene.frame_set(20)
h20 = (arm.matrix_world @ arm.pose.bones["LeftHand"].head).copy()
check((h20 - h1).length > 0.2, f"구운 애니메이션에서 LeftHand 이동 {(h20 - h1).length:.3f}")

# 4족: Rigify 이름 유지, 단일 루트
obj, rig = rig_fixture(quadruped, "dog")
path = OUT / "quadruped.fbx"
check(bpy.ops.airig.export_fbx(filepath=str(path), naming="UNITY", bake_anim=False) == {"FINISHED"}, "4족 FBX 내보내기")
arm, mesh = reimport(path)
roots = [b.name for b in arm.data.bones if b.parent is None]
check(roots == ["DEF-spine.004"], f"4족 루트는 몸통 시작 본 {roots}")
check(arm.data.bones["DEF-spine.003"].parent.name == "DEF-spine.004", "꼬리 시작 본 → 몸통 루트")
check(arm.data.bones["DEF-spine"].parent.name == "DEF-spine.001", "꼬리 체인이 끝 방향으로 이어짐")
check(not path.with_suffix(".humanoid.json").exists(), "4족은 Humanoid JSON 미생성")
for name in ("DEF-thigh.L", "DEF-front_thigh.L", "DEF-spine.011"):
    check(roots[0] in ancestors(arm.data.bones[name]), f"{name} 이 루트 계층 아래")
print("[export] ALL PASSED")
