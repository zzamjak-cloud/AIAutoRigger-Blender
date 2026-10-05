"""평가 하네스 실데이터 경로 검증용 샘플 생성기.

정답 관절 위치에 Mixamo 이름 규칙 아마추어를 만들어 바인딩한 뒤 FBX/GLB 로 내보낸다.
    scripts/dev_run.sh --background --python tests/make_eval_sample.py -- <출력 폴더>
"""

import pathlib
import sys

import bpy

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
import humanoid  # noqa: E402

OUT = pathlib.Path(sys.argv[sys.argv.index("--") + 1])

# Mixamo 본 이름 → (head 관절, tail 관절)
MIXAMO = {}
for side, word in (("L", "Left"), ("R", "Right")):
    MIXAMO.update({
        f"mixamorig:{word}UpLeg": (f"hip_{side}", f"knee_{side}"),
        f"mixamorig:{word}Leg": (f"knee_{side}", f"ankle_{side}"),
        f"mixamorig:{word}Arm": (f"shoulder_{side}", f"elbow_{side}"),
        f"mixamorig:{word}ForeArm": (f"elbow_{side}", f"wrist_{side}"),
        f"mixamorig:{word}Hand": (f"wrist_{side}", f"hand_tip_{side}"),
    })


def build(variant, out_dir):
    bpy.ops.wm.read_homefile(use_empty=True)
    verts, tris, gt = humanoid.build(variant)
    mesh = bpy.data.meshes.new(variant)
    mesh.from_pydata(verts, [], tris)
    obj = bpy.data.objects.new(variant, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new("remesh", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = 0.02
    bpy.ops.object.modifier_apply(modifier=mod.name)

    arm_data = bpy.data.armatures.new("Armature")
    arm = bpy.data.objects.new("Armature", arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    hips = arm_data.edit_bones.new("mixamorig:Hips")
    hips.head = (0.0, 0.0, gt["hip_L"][2])
    hips.tail = (0.0, 0.0, gt["shoulder_L"][2])
    head = arm_data.edit_bones.new("mixamorig:Head")
    head.head = gt["head_base"]
    head.tail = gt["head_top"]
    head.parent = hips
    for name, (h, t) in MIXAMO.items():
        eb = arm_data.edit_bones.new(name)
        eb.head = gt[h]
        eb.tail = gt[t]
        eb.parent = hips
    bpy.ops.object.mode_set(mode="OBJECT")

    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    bpy.ops.export_scene.fbx(filepath=str(out_dir / f"{variant}.fbx"), use_selection=False)
    bpy.ops.export_scene.gltf(filepath=str(out_dir / f"{variant}.glb"), export_format="GLB")


for category, variant in (("biped_realistic", "realistic_a"), ("biped_stylized", "stylized_t")):
    d = OUT / category
    d.mkdir(parents=True, exist_ok=True)
    build(variant, d)
print(f"[sample] written: {OUT}")
