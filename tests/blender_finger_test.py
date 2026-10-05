"""손가락 검출·Rigify 손가락 리그 테스트 (엄지 + 손가락 3개, 곧은 손·갈고리 손).

실행: scripts/dev_run.sh --background --python tests/blender_finger_test.py
"""

import os
import pathlib
import sys
from math import dist

import bpy
from mathutils import Euler, Matrix, Vector

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
import humanoid  # noqa: E402

RENDER_DIR = os.environ.get("AIRIG_RENDER_DIR")
TOL = 0.02  # m (키 1.8m 대비 약 1.1%)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[finger] OK  {msg}")


def make_obj(name, verts, tris, voxel):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], tris)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new("remesh", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = voxel
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return obj


def build(variant):
    bpy.ops.wm.read_homefile(use_empty=True)
    bv, bt, gt, hv, ht = humanoid.build_from(humanoid.FINGER_VARIANTS[variant], split_hands=True)
    body = make_obj(variant, bv, bt, 0.015)
    # 손가락 두께(약 1.6cm)보다 충분히 작은 복셀로 손만 따로 리메시한 뒤 합친다
    hands = make_obj(variant + "_hands", hv, ht, 0.004)
    for o in bpy.context.view_layer.objects:
        o.select_set(o in (body, hands))
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    return body, gt


def eval_coords(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    co = [obj.matrix_world @ v.co for v in me.vertices]
    ev.to_mesh_clear()
    return co


def render(name):
    if not RENDER_DIR:
        return
    scene = bpy.context.scene
    cd = bpy.data.cameras.new("cam")
    cd.type = "ORTHO"
    cd.ortho_scale = 0.32
    cam = bpy.data.objects.new("cam", cd)
    scene.collection.objects.link(cam)
    st = bpy.context.scene.airig
    rig = bpy.data.objects[st.rig_name]
    hand = rig.matrix_world @ rig.data.bones["DEF-hand.L"].head_local
    cam.location = hand + Vector((0.08, -3.0, -0.05))
    cam.rotation_euler = (1.5708, 0.0, 0.0)
    scene.camera = cam
    try:
        scene.render.engine = "BLENDER_WORKBENCH"
    except TypeError:
        pass
    scene.display.shading.show_xray = True
    scene.render.resolution_x = scene.render.resolution_y = 500
    scene.render.filepath = os.path.join(RENDER_DIR, f"{name}.png")
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam)


def run(variant):
    obj, gt = build(variant)
    check(bpy.ops.airig.auto_rig() == {"FINISHED"}, f"{variant}: auto_rig")
    st = bpy.context.scene.airig
    expected = humanoid.EXPECTED_FINGERS[variant]
    check(st.finger_count == 2 * len(expected), f"{variant}: 손가락 {2 * len(expected)}개 감지 ({st.finger_count})")
    mr = bpy.data.objects[st.metarig_name]
    rig = bpy.data.objects[st.rig_name]
    mw = mr.matrix_world
    for side in ("L", "R"):
        for f in expected:
            first, last = mr.data.bones.get(f"{f}.01.{side}"), mr.data.bones.get(f"{f}.03.{side}")
            check(first is not None and last is not None, f"{variant}: 메타리그 {f}.01~03.{side}")
            eb = dist(mw @ first.head_local, gt[f"{f}_base_{side}"])
            et = dist(mw @ last.tail_local, gt[f"{f}_tip_{side}"])
            # 갈라지지 않은 덩어리는 폭이 손바닥과 비슷해 관절선이 형상으로 정해지지 않으므로 뿌리 허용폭을 넓힌다
            base_tol = 2.0 * TOL if len(expected) == 2 and f != "thumb" else 1.5 * TOL
            check(eb < base_tol and et < TOL, f"{variant}: {f}.{side} 뿌리 오차 {eb:.3f}m, 끝 오차 {et:.3f}m")
        for k in range(1, len(expected)):
            check(f"palm.{k:02d}.{side}" in mr.data.bones, f"{variant}: palm.{k:02d}.{side}")
        palm_type = "limbs.super_palm" if len(expected) >= 3 else "basic.super_copy"
        check(mr.pose.bones[f"palm.01.{side}"].rigify_type == palm_type, f"{variant}: palm.01.{side} {palm_type}")
        check(all(mr.pose.bones[f"{f}.01.{side}"].rigify_type == "limbs.super_finger" for f in expected),
              f"{variant}: 손가락 super_finger {side}")
        check(all(f"DEF-{f}.01.{side}" in rig.data.bones for f in expected), f"{variant}: 리그 DEF 손가락 {side}")
    check(st.unweighted_vertices == 0, f"{variant}: 웨이트 없는 정점 0")
    rest = max((a - b).length for a, b in zip(eval_coords(obj), [obj.matrix_world @ v.co for v in obj.data.vertices]))
    check(rest < 1e-4, f"{variant}: rest 변형 없음 {rest:.6f}")
    render(f"{variant}_rest")

    # 손가락 마스터 컨트롤을 굽히면 끝마디 DEF 와 손가락 끝 메시가 움직여야 한다
    bend, other = ("f_index", "f_ring") if "f_index" in expected else ("f_middle", "thumb")
    master = next(n for n in (f"{bend}.01_master.L", f"{bend}_master.L") if n in rig.pose.bones)
    pb = rig.pose.bones[master]
    tip_before = rig.matrix_world @ rig.pose.bones[f"DEF-{bend}.03.L"].tail
    tip_v = min(range(len(obj.data.vertices)), key=lambda i: (obj.matrix_world @ obj.data.vertices[i].co - Vector(gt[f"{bend}_tip_L"])).length)
    v_before = eval_coords(obj)[tip_v]
    pb.rotation_mode = "XYZ"
    pb.rotation_euler = Euler((0.9, 0.0, 0.0))
    bpy.context.view_layer.update()
    moved = ((rig.matrix_world @ rig.pose.bones[f"DEF-{bend}.03.L"].tail) - tip_before).length
    check(moved > 0.01, f"{variant}: {master} 회전으로 {bend} 끝 이동 {moved:.3f}m")
    vm = (eval_coords(obj)[tip_v] - v_before).length
    check(vm > 0.01, f"{variant}: {bend} 끝 메시 변형 {vm:.3f}m")
    others = (rig.matrix_world @ rig.pose.bones[f"DEF-{other}.03.L"].tail)
    render(f"{variant}_bent")
    pb.rotation_euler = Euler((0.0, 0.0, 0.0))
    bpy.context.view_layer.update()
    check((rig.matrix_world @ rig.pose.bones[f"DEF-{other}.03.L"].tail - others).length < 1e-4, f"{variant}: 다른 손가락은 영향 없음")


for v in humanoid.FINGER_VARIANTS:
    run(v)

# 손가락 끄기 옵션
obj, _ = build("fingers_straight_t")
bpy.context.scene.airig.use_fingers = False
check(bpy.ops.airig.auto_rig() == {"FINISHED"}, "손가락 끄고 auto_rig")
mr = bpy.data.objects[bpy.context.scene.airig.metarig_name]
check(not any(b.name.startswith(("f_", "thumb", "palm")) for b in mr.data.bones), "손가락 끄면 손가락 본 없음")
print("[finger] ALL PASSED")
