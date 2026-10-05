"""턱·눈 리깅 테스트 (입을 벌린 머리 + 별도 조각 눈동자) 와 Unity 내보내기 매핑.

실행: scripts/dev_run.sh --background --python tests/blender_face_test.py -- <출력 폴더>
"""

import json
import os
import pathlib
import sys

import bpy
from mathutils import Euler, Vector

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
import humanoid  # noqa: E402

OUT = pathlib.Path(sys.argv[sys.argv.index("--") + 1]) if "--" in sys.argv else ROOT / "dist" / "face_test"


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[face] OK  {msg}")


def make_obj(name, verts, tris, voxel=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], tris)
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    if voxel:
        mod = obj.modifiers.new("remesh", "REMESH")
        mod.mode, mod.voxel_size = "VOXEL", voxel
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return obj


def weight(obj, group, index):
    g = obj.vertex_groups.get(group)
    return next((x.weight for x in obj.data.vertices[index].groups if g and x.group == g.index), 0.0)


def nearest(obj, p):
    return min(range(len(obj.data.vertices)), key=lambda i: (obj.matrix_world @ obj.data.vertices[i].co - Vector(p)).length)


def evaluated(obj, index):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    co = obj.matrix_world @ me.vertices[index].co
    ev.to_mesh_clear()
    return co


bpy.ops.wm.read_homefile(use_empty=True)
bv, bt, gt, hv, ht, ev, et = humanoid.build_face_variant()
parts = [make_obj("body", bv, bt, 0.015), make_obj("head", hv, ht, 0.005), make_obj("eyes", ev, et)]
for o in bpy.context.view_layer.objects:
    o.select_set(o in parts)
bpy.context.view_layer.objects.active = parts[0]
bpy.ops.object.join()
obj = parts[0]

st = bpy.context.scene.airig
check(bpy.ops.airig.auto_rig() == {"FINISHED"}, "auto_rig")
check("턱" in st.face_summary and "눈" in st.face_summary, f"턱·눈 감지 ({st.face_summary})")
mr = bpy.data.objects[st.metarig_name]
rig = bpy.data.objects[st.rig_name]
face = json.loads(mr["airig_face"])
check(abs(face["jaw"]["lip_z"] - gt["lip_z"]) < 0.012, f"입술 선 높이 오차 {abs(face['jaw']['lip_z'] - gt['lip_z']):.4f}m")
check(abs(face["jaw"]["chin_bottom_z"] - gt["chin_bottom_z"]) < 0.012, "턱 아래면 높이")
for side in ("L", "R"):
    e = next(x for x in face["eyes"] if x["side"] == side)
    check((Vector(e["center"]) - Vector(gt[f"eye_{side}"])).length < 0.005, f"눈 {side} 중심")
for name in ("jaw", "eye.L", "eye.R"):
    check(name in mr.data.bones and f"DEF-{name}" in rig.data.bones, f"메타리그·리그 {name}")
check(st.unweighted_vertices == 0, "웨이트 없는 정점 0")

hb, lip = gt["chin_bottom_z"], gt["lip_z"]
chin_v = nearest(obj, (0.0, -0.1, hb + 0.01))
brow_v = nearest(obj, (0.0, -0.11, lip + 0.13))
# 얼굴 앞으로 튀어나온 눈동자 모서리 (눈 중심은 정점이 아니고 얼굴 표면이 더 가깝다)
eye_v = nearest(obj, Vector(gt["eye_L"]) + Vector((0.015, -0.015, 0.015)))
check(weight(obj, "DEF-jaw", chin_v) > 0.9, f"턱 앞 아래 정점 턱 웨이트 {weight(obj, 'DEF-jaw', chin_v):.2f}")
check(weight(obj, "DEF-jaw", brow_v) == 0.0, "이마 정점 턱 웨이트 0")
check(weight(obj, "DEF-eye.L", eye_v) == 1.0 and weight(obj, "DEF-jaw", eye_v) == 0.0, "눈동자 조각은 눈 본에만")

# 턱 +X 회전 = 입 열림: 턱 끝은 내려가고 이마는 그대로
chin0, brow0, eye0 = evaluated(obj, chin_v), evaluated(obj, brow_v), evaluated(obj, eye_v)
pb = rig.pose.bones["jaw"]
pb.rotation_mode = "XYZ"
pb.rotation_euler = Euler((0.35, 0.0, 0.0))
bpy.context.view_layer.update()
check(evaluated(obj, chin_v).z < chin0.z - 0.01, f"턱 +X 회전으로 입이 열림 Δz={evaluated(obj, chin_v).z - chin0.z:.3f}")
check((evaluated(obj, brow_v) - brow0).length < 1e-4, "턱을 움직여도 이마는 고정")
pb.rotation_euler = Euler((0.0, 0.0, 0.0))
eb = rig.pose.bones["eye.L"]
eb.rotation_mode = "XYZ"
eb.rotation_euler = Euler((0.0, 0.0, 0.5))
bpy.context.view_layer.update()
check((evaluated(obj, eye_v) - eye0).length > 0.002, "눈 본 회전으로 눈동자 이동")
check((evaluated(obj, brow_v) - brow0).length < 1e-4, "눈을 움직여도 이마는 고정")
eb.rotation_euler = Euler((0.0, 0.0, 0.0))
bpy.context.view_layer.update()

# Unity 내보내기: Jaw·Eye 이름, Neck2 합침, 간소화 옵션
OUT.mkdir(parents=True, exist_ok=True)
for simplify in (False, True):
    path = OUT / f"face_unity_{int(simplify)}.fbx"
    bpy.context.view_layer.objects.active = obj
    check(bpy.ops.airig.export_fbx(filepath=str(path), naming="UNITY", bake_anim=False, simplify=simplify) == {"FINISHED"},
          f"FBX 내보내기 simplify={simplify}")
mapping = json.loads((OUT / "face_unity_0.humanoid.json").read_text())
check(all(k in mapping for k in ("Jaw", "LeftEye", "RightEye")), "Humanoid JSON 에 Jaw·LeftEye·RightEye")
counts = {}
for simplify in (False, True):
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(OUT / f"face_unity_{int(simplify)}.fbx"))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    names = {b.name for b in arm.data.bones}
    counts[simplify] = len(names)
    check("Neck2" not in names and "Head" in names and "Jaw" in names, f"simplify={simplify}: Neck2 없음, Head·Jaw 있음")
    check(arm.data.bones["Jaw"].parent.name == "Head", f"simplify={simplify}: Jaw → Head")
    if simplify:
        check(not any(n.endswith("Twist") or "palm" in n or "Pelvis" in n for n in names), "간소화: 트위스트·손바닥·골반 없음")
check(counts[True] < counts[False], f"간소화로 본 수 감소 {counts[False]} → {counts[True]}")
print("[face] ALL PASSED")
