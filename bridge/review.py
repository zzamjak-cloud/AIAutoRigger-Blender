"""리그 검토용 테스트 포즈, 변형 지표, 승인된 보정안 적용."""

import json
import math
from collections import defaultdict

import bpy
from mathutils import Euler, Matrix, Vector

from ..core import fingers
from ..core.landmark_merge import enforce_bends
from . import rigify_bridge, views, weights

# 포즈 이름 → [(제어 본, 이동량(크기 대비, x/정면/z), 회전 Euler 또는 None)]
# 이동량의 두 번째 성분은 정면 방향 기준이며 실제 Y 부호는 캐릭터 정면에 맞춰 바꾼다
POSES = {
    "BIPED": {
        "rest": [],
        "arms_up": [("hand_ik.L", (-0.12, 0.0, 0.3), None), ("hand_ik.R", (0.12, 0.0, 0.3), None)],
        "arms_forward": [("hand_ik.L", (-0.22, 0.28, 0.0), None), ("hand_ik.R", (0.22, 0.28, 0.0), None)],
        "squat": [("torso", (0.0, 0.0, -0.15), None)],
        "knee_lift": [("foot_ik.L", (0.0, 0.12, 0.2), None)],
    },
    "QUADRUPED": {
        "rest": [],
        "front_leg_lift": [("front_foot_ik.L", (0.0, 0.08, 0.12), None)],
        "hind_leg_lift": [("foot_ik.L", (0.0, -0.04, 0.12), None)],
        "crouch": [("torso", (0.0, 0.0, -0.08), None)],
        "head_down": [("head", (0.0, 0.0, 0.0), (0.6, 0.0, 0.0))],
    },
}


def _rig_context(context):
    state = context.scene.airig
    mesh = bpy.data.objects.get(state.target_mesh)
    rig = bpy.data.objects.get(state.rig_name)
    metarig = bpy.data.objects.get(state.metarig_name)
    if mesh is None or rig is None or metarig is None:
        raise RuntimeError("먼저 리그를 생성하세요.")
    if "airig_joints" not in metarig:
        raise RuntimeError("이 메타리그는 이전 버전에서 만들어졌습니다. Fit Metarig 를 다시 실행하세요.")
    return mesh, rig, metarig


def reset_pose(rig):
    for pb in rig.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)


def apply_pose(context, rig, kind, facing, pose, size):
    reset_pose(rig)
    fwd = -1.0 if facing == "-Y" else 1.0
    for bone, (dx, df, dz), rot in POSES[kind][pose]:
        pb = rig.pose.bones.get(bone)
        if pb is None:
            continue
        world = rig.matrix_world @ pb.matrix
        if rot is not None:
            # X축 회전 방향도 정면에 맞춘다 (정면 -Y 기준 값)
            rot = (rot[0] * -fwd, rot[1], rot[2])
            loc = world.to_translation()
            world = Matrix.Translation(loc) @ Euler(rot).to_matrix().to_4x4() @ Matrix.Translation(-loc) @ world
        world = Matrix.Translation(Vector((dx, df * fwd, dz)) * size) @ world
        pb.matrix = rig.matrix_world.inverted() @ world
        context.view_layer.update()
    context.view_layer.update()


def render_pose(context, pose, view):
    mesh, rig, metarig = _rig_context(context)
    kind = metarig["airig_kind"]
    facing = metarig["airig_facing"]
    size = max(mesh.dimensions)
    try:
        apply_pose(context, rig, kind, facing, pose, size)
        images, _, _ = views.render_views(context, mesh, facing, extra_objects=[rig], which=(view,))
    finally:
        reset_pose(rig)
        context.view_layer.update()
    return images[view]


def deformation_metrics(context, top=8):
    """포즈별 간선 길이 비율로 본별 최대 늘어남/줄어듦을 집계한 텍스트."""
    mesh, rig, metarig = _rig_context(context)
    kind = metarig["airig_kind"]
    facing = metarig["airig_facing"]
    size = max(mesh.dimensions)
    me = mesh.data
    deform = {g.index: g.name for g in mesh.vertex_groups if g.name.startswith("DEF-")}
    dominant = []
    for v in me.vertices:
        best = max((g for g in v.groups if g.group in deform), key=lambda g: g.weight, default=None)
        dominant.append(deform[best.group] if best else None)
    rest = [v.co.copy() for v in me.vertices]
    rest_len = [(rest[e.vertices[0]] - rest[e.vertices[1]]).length for e in me.edges]
    # 리메시 등에서 생긴 극히 짧은 간선은 비율이 폭주하므로 제외한다
    lengths = sorted(rest_len)
    min_len = 0.1 * lengths[len(lengths) // 2] if lengths else 0.0
    rows = []
    try:
        for pose in POSES[kind]:
            if pose == "rest":
                continue
            apply_pose(context, rig, kind, facing, pose, size)
            dg = context.evaluated_depsgraph_get()
            ev = mesh.evaluated_get(dg)
            em = ev.to_mesh()
            co = [v.co.copy() for v in em.vertices]
            ev.to_mesh_clear()
            if len(co) != len(rest):
                return "deformation metrics unavailable: modifiers change the vertex count"
            stats = defaultdict(lambda: [1.0, 1.0])
            for e, l0 in zip(me.edges, rest_len):
                if l0 <= min_len:
                    continue
                a, b = e.vertices
                ratio = (co[a] - co[b]).length / l0
                bone = dominant[a] or dominant[b]
                if bone:
                    s = stats[bone]
                    s[0] = max(s[0], ratio)
                    s[1] = min(s[1], ratio)
            for bone, (mx, mn) in stats.items():
                score = max(math.log(mx), -math.log(max(mn, 1e-6)))
                rows.append((score, pose, bone, mx, mn))
    finally:
        reset_pose(rig)
        context.view_layer.update()
    rows.sort(reverse=True)
    unweighted = sum(1 for d in dominant if d is None)
    lines = [f"vertices: {len(me.vertices)}, unweighted: {unweighted}"]
    lines += [f"pose={p} bone={b} max_stretch={mx:.2f} max_compress={mn:.2f}" for _, p, b, mx, mn in rows[:top]]
    return "\n".join(lines)


def apply_proposals(context, proposals):
    """승인된 보정안 적용: 관절 이동 → 메타리그 재구성·리그 재생성·재바인딩 → 웨이트 스무딩."""
    mesh, rig, metarig = _rig_context(context)
    kind = metarig["airig_kind"]
    facing = metarig["airig_facing"]
    joints = {k: tuple(v) for k, v in json.loads(metarig["airig_joints"]).items()}
    symmetric = bool(metarig.get("airig_symmetric", False))
    size = max(mesh.dimensions)
    moves = [p for p in proposals if p.kind == "move_joint" and p.target in joints]
    targets = {p.target for p in moves}
    # 제안 오프셋은 정면 이미지 기준(dx: 이미지 오른쪽, dy: 정면 카메라 쪽)이다
    right_x = 1.0 if facing == "-Y" else -1.0
    front_y = -1.0 if facing == "-Y" else 1.0
    for p in moves:
        d = Vector((p.delta[0] * right_x, p.delta[1] * front_y, p.delta[2])) * size
        joints[p.target] = tuple(Vector(joints[p.target]) + d)
        if symmetric and p.target.endswith(("_L", "_R")):
            mirror = p.target[:-1] + ("R" if p.target.endswith("L") else "L")
            if mirror in joints and mirror not in targets:
                joints[mirror] = tuple(Vector(joints[mirror]) + Vector((-d.x, d.y, d.z)))
    if moves:
        joints = enforce_bends(joints, kind, facing)
        has_tail = bool(metarig.get("airig_has_tail", False))
        name = metarig.name
        hands = {s: fingers.HandFingers.from_dict(d) for s, d in json.loads(metarig.get("airig_fingers", "{}")).items()}
        new_meta = rigify_bridge.build_metarig(context, kind, joints, name, has_tail=has_tail,
                                               facing=facing, symmetric=symmetric, fingers=hands)
        rig = rigify_bridge.generate_rig(context, new_meta, rig.name)
        context.scene.airig.unweighted_vertices = rigify_bridge.bind_mesh(context, mesh, rig)
    smoothed = 0
    for p in proposals:
        if p.kind == "smooth_weights" and weights.smooth_group(mesh, p.target, p.iterations):
            smoothed += 1
    return len(moves), smoothed
