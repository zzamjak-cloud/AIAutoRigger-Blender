"""격리 프로필 Blender 런타임 자동 리깅 테스트 (Rigify 생성·바인딩·IK 동작).

실행: scripts/dev_run.sh --background --python tests/blender_rig_test.py
AIRIG_RENDER_DIR 를 지정하면 변형별 포즈 렌더(PNG)를 저장한다.
"""

import os
import pathlib
import sys
from math import dist

import bpy
from mathutils import Matrix, Vector

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
import humanoid  # noqa: E402
import quadruped  # noqa: E402

RENDER_DIR = os.environ.get("AIRIG_RENDER_DIR")
# 정답 관절 대비 허용 오차 (높이 비율)
JOINT_TOL = 0.06


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[rig] OK  {msg}")


def make_mesh(variant, module=humanoid):
    verts, tris, gt = module.build(variant)
    mesh = bpy.data.meshes.new(variant)
    mesh.from_pydata(verts, [], tris)
    mesh.update()
    obj = bpy.data.objects.new(variant, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    # 겹친 박스를 하나의 다양체 표면으로 합쳐 실제 캐릭터 메시와 유사하게 만든다
    mod = obj.modifiers.new("remesh", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = 0.015
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return obj, gt


def rest_displacement(obj):
    """바인딩 직후(rest) 메시 변형량. 0 이어야 한다."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    d = max((me.vertices[i].co - v.co).length for i, v in enumerate(obj.data.vertices))
    ev.to_mesh_clear()
    return d


def world_head(rig, bone):
    return rig.matrix_world @ rig.pose.bones[bone].head


def nearest_vertex(obj, point):
    mw = obj.matrix_world
    return min(range(len(obj.data.vertices)), key=lambda i: ((mw @ obj.data.vertices[i].co) - point).length)


def eval_vertex(obj, index):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    co = obj.matrix_world @ me.vertices[index].co
    ev.to_mesh_clear()
    return co


def render(variant, tag):
    if not RENDER_DIR:
        return
    scene = bpy.context.scene
    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 2.4
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    # 4족은 측면(+X)에서 본다
    if variant in quadruped.VARIANTS:
        cam.location = (5.0, 0.0, 0.6)
        cam.rotation_euler = (1.5708, 0.0, 1.5708)
    else:
        cam.location = (0.0, -5.0, 0.9)
        cam.rotation_euler = (1.5708, 0.0, 0.0)
    scene.camera = cam
    try:
        scene.render.engine = "BLENDER_WORKBENCH"
    except TypeError:
        pass
    scene.display.shading.show_xray = True
    scene.render.resolution_x = 600
    scene.render.resolution_y = 600
    scene.render.filepath = os.path.join(RENDER_DIR, f"{variant}_{tag}.png")
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam)


def run_variant(variant):
    bpy.ops.wm.read_homefile(use_empty=True)
    obj, gt = make_mesh(variant)
    H = obj.dimensions.z

    result = bpy.ops.airig.auto_rig()
    check(result == {"FINISHED"}, f"{variant}: airig.auto_rig 실행")
    state = bpy.context.scene.airig
    rig = bpy.data.objects[state.rig_name]
    metarig = bpy.data.objects[state.metarig_name]

    for bone, key in (("upper_arm.L", "shoulder_L"), ("forearm.L", "elbow_L"), ("hand.L", "wrist_L"),
                      ("thigh.L", "hip_L"), ("shin.L", "knee_L"), ("foot.L", "ankle_L")):
        err = dist(metarig.matrix_world @ metarig.data.bones[bone].head_local, gt[key]) / H
        check(err < JOINT_TOL, f"{variant}: 메타리그 {bone} 위치 오차 {err:.3f}")

    for name in ("upper_arm_parent.L", "upper_arm_parent.R", "thigh_parent.L", "thigh_parent.R"):
        check(rig.pose.bones[name]["IK_FK"] == 0.0, f"{variant}: {name} IK 모드")
    check(obj.parent == rig and any(m.type == "ARMATURE" and m.object == rig for m in obj.modifiers),
          f"{variant}: 메시가 리그에 바인딩")
    ratio = state.unweighted_vertices / len(obj.data.vertices)
    check(ratio < 0.01, f"{variant}: 웨이트 없는 정점 비율 {ratio:.4f}")
    rest = rest_displacement(obj)
    check(rest < 1e-4, f"{variant}: rest 자세 메시 변형 없음 {rest:.6f}")
    render(variant, "rest")

    # 손 IK 컨트롤 이동 → DEF 손이 따라오고 팔꿈치가 굽으며 메시가 변형되는지
    wrist_v = nearest_vertex(obj, Vector(gt["wrist_L"]))
    before_v = eval_vertex(obj, wrist_v)
    elbow_before = world_head(rig, "DEF-forearm.L")
    hand_ik = rig.pose.bones["hand_ik.L"]
    target = rig.matrix_world @ hand_ik.head + Vector((-0.1 * H, -0.05 * H, 0.1 * H))
    hand_ik.matrix = rig.matrix_world.inverted() @ (
        Matrix.Translation(target) @ (rig.matrix_world @ hand_ik.matrix).to_3x3().to_4x4()
    )
    bpy.context.view_layer.update()
    err = (world_head(rig, "DEF-hand.L") - target).length / H
    check(err < 0.01, f"{variant}: 손 IK 목표 도달 오차 {err:.4f}")
    moved = (world_head(rig, "DEF-forearm.L") - elbow_before).length / H
    check(moved > 0.01, f"{variant}: 팔꿈치가 IK 로 이동 {moved:.3f}")
    vmoved = (eval_vertex(obj, wrist_v) - before_v).length / H
    check(vmoved > 0.05, f"{variant}: 손목 메시 정점 변형 {vmoved:.3f}")

    # 발 IK 컨트롤 들어올림 → 무릎이 앞으로 굽는지 (IK 극 방향 검증)
    foot_ik = rig.pose.bones["foot_ik.L"]
    knee_before = world_head(rig, "DEF-shin.L")
    foot_target = rig.matrix_world @ foot_ik.head + Vector((0.0, 0.0, 0.15 * H))
    foot_ik.matrix = rig.matrix_world.inverted() @ (
        Matrix.Translation(foot_target) @ (rig.matrix_world @ foot_ik.matrix).to_3x3().to_4x4()
    )
    bpy.context.view_layer.update()
    knee_after = world_head(rig, "DEF-shin.L")
    check(knee_after.y < knee_before.y - 0.02 * H, f"{variant}: 무릎이 앞(-Y)으로 굽음 Δy={knee_after.y - knee_before.y:.3f}")
    render(variant, "ik_pose")


def move_control(rig, bone, delta):
    pb = rig.pose.bones[bone]
    world = rig.matrix_world @ pb.matrix
    world = Matrix.Translation(delta) @ world
    pb.matrix = rig.matrix_world.inverted() @ world
    bpy.context.view_layer.update()


def run_quadruped(variant):
    bpy.ops.wm.read_homefile(use_empty=True)
    obj, gt = make_mesh(variant, quadruped)
    size = max(obj.dimensions)

    result = bpy.ops.airig.auto_rig()
    check(result == {"FINISHED"}, f"{variant}: airig.auto_rig 실행")
    state = bpy.context.scene.airig
    check(state.detected_type == "QUADRUPED", f"{variant}: 4족 자동 판별")
    rig = bpy.data.objects[state.rig_name]
    metarig = bpy.data.objects[state.metarig_name]
    for bone, key in (("thigh.L", "r_hip_L"), ("shin.L", "r_knee_L"), ("foot.L", "r_hock_L"),
                      ("front_thigh.L", "f_shoulder_L"), ("front_shin.L", "f_elbow_L"), ("front_foot.L", "f_wrist_L")):
        err = dist(metarig.matrix_world @ metarig.data.bones[bone].head_local, gt[key]) / size
        check(err < JOINT_TOL, f"{variant}: 메타리그 {bone} 위치 오차 {err:.3f}")
    ik = [pb for pb in rig.pose.bones if "IK_FK" in pb]
    check(len(ik) == 4 and all(pb["IK_FK"] == 0.0 for pb in ik), f"{variant}: 다리 4개 IK 모드")
    ratio = state.unweighted_vertices / len(obj.data.vertices)
    check(ratio < 0.01, f"{variant}: 웨이트 없는 정점 비율 {ratio:.4f}")
    rest = rest_displacement(obj)
    check(rest < 1e-4, f"{variant}: rest 자세 메시 변형 없음 {rest:.6f}")
    render(variant, "rest")

    for ctrl, paw_bone, thigh_bone in (("foot_ik.L", "DEF-toe.L", "DEF-thigh.L"),
                                       ("front_foot_ik.L", "DEF-front_toe.L", "DEF-front_thigh.L")):
        paw_before = world_head(rig, paw_bone)
        thigh_before = rig.pose.bones[thigh_bone].matrix.to_quaternion()
        delta = Vector((0.0, -0.05 * size, 0.12 * size))
        move_control(rig, ctrl, delta)
        err = ((world_head(rig, paw_bone) - paw_before) - delta).length / size
        check(err < 0.02, f"{variant}: {ctrl} 이동을 발이 따라감 오차 {err:.4f}")
        angle = thigh_before.rotation_difference(rig.pose.bones[thigh_bone].matrix.to_quaternion()).angle
        check(angle > 0.05, f"{variant}: {thigh_bone} IK 회전 {angle:.2f} rad")
    render(variant, "ik_pose")


def run_rotated():
    """정면 +Y 캐릭터(Z축 180° 회전): .L 은 해부학적 왼쪽(-X), 무릎은 +Y 로 굽어야 한다."""
    bpy.ops.wm.read_homefile(use_empty=True)
    verts, tris, gt = humanoid.build("realistic_t")
    verts = [(-v[0], -v[1], v[2]) for v in verts]
    gt = {k: (-v[0], -v[1], v[2]) for k, v in gt.items()}
    mesh = bpy.data.meshes.new("rot")
    mesh.from_pydata(verts, [], tris)
    obj = bpy.data.objects.new("rot", mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    mod = obj.modifiers.new("remesh", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = 0.015
    bpy.ops.object.modifier_apply(modifier=mod.name)
    H = obj.dimensions.z
    check(bpy.ops.airig.auto_rig() == {"FINISHED"}, "+Y 정면: auto_rig")
    state = bpy.context.scene.airig
    rig = bpy.data.objects[state.rig_name]
    metarig = bpy.data.objects[state.metarig_name]
    check(metarig["airig_facing"] == "+Y", "+Y 정면 감지")
    err = dist(metarig.matrix_world @ metarig.data.bones["upper_arm.L"].head_local, gt["shoulder_L"]) / H
    check(err < JOINT_TOL and gt["shoulder_L"][0] < 0, f"+Y 정면: upper_arm.L 이 해부학적 왼쪽(-X) 오차 {err:.3f}")
    rest = rest_displacement(obj)
    check(rest < 1e-4, f"+Y 정면: rest 변형 없음 {rest:.6f}")
    foot_ik = rig.pose.bones["foot_ik.L"]
    knee_before = world_head(rig, "DEF-shin.L")
    foot_target = rig.matrix_world @ foot_ik.head + Vector((0.0, 0.0, 0.15 * H))
    foot_ik.matrix = rig.matrix_world.inverted() @ (Matrix.Translation(foot_target) @ (rig.matrix_world @ foot_ik.matrix).to_3x3().to_4x4())
    bpy.context.view_layer.update()
    dy = world_head(rig, "DEF-shin.L").y - knee_before.y
    check(dy > 0.02 * H, f"+Y 정면: 무릎이 정면(+Y)으로 굽음 Δy={dy:.3f}")


for v in humanoid.VARIANTS:
    run_variant(v)
run_rotated()
for v in quadruped.VARIANTS:
    run_quadruped(v)
print("[rig] ALL PASSED")
