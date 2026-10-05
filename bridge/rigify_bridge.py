"""Rigify 메타리그 피팅·컨트롤 리그 생성·스키닝."""

import json

import addon_utils
import bpy

# Rigify basic human 메타리그 본 → (head 관절, tail 관절)
BIPED_BONE_MAP = {
    "spine": ("spine_base", "spine_1"),
    "spine.001": ("spine_1", "spine_2"),
    "spine.002": ("spine_2", "spine_3"),
    "spine.003": ("spine_3", "neck_base"),
    "spine.004": ("neck_base", "neck_mid"),
    "spine.005": ("neck_mid", "head_base"),
    "spine.006": ("head_base", "head_top"),
}
for _s in ("L", "R"):
    BIPED_BONE_MAP.update({
        f"shoulder.{_s}": (f"clavicle_{_s}", f"shoulder_{_s}"),
        f"upper_arm.{_s}": (f"shoulder_{_s}", f"elbow_{_s}"),
        f"forearm.{_s}": (f"elbow_{_s}", f"wrist_{_s}"),
        f"hand.{_s}": (f"wrist_{_s}", f"hand_tip_{_s}"),
        f"pelvis.{_s}": ("spine_base", f"pelvis_tip_{_s}"),
        f"thigh.{_s}": (f"hip_{_s}", f"knee_{_s}"),
        f"shin.{_s}": (f"knee_{_s}", f"ankle_{_s}"),
        f"foot.{_s}": (f"ankle_{_s}", f"toe_base_{_s}"),
        f"toe.{_s}": (f"toe_base_{_s}", f"toe_tip_{_s}"),
        f"heel.02.{_s}": (f"heel_in_{_s}", f"heel_out_{_s}"),
    })

# Rigify basic quadruped 메타리그 본 → (head 관절, tail 관절)
QUADRUPED_BONE_MAP = {
    "spine.004": ("spine_root", "spine_1"),
    "spine.005": ("spine_1", "spine_2"),
    "spine.006": ("spine_2", "spine_3"),
    "spine.007": ("spine_3", "spine_4"),
    "spine.008": ("spine_4", "neck_base"),
    "spine.009": ("neck_base", "neck_mid"),
    "spine.010": ("neck_mid", "head_base"),
    "spine.011": ("head_base", "head_tip"),
}
QUADRUPED_TAIL_MAP = {
    "spine.003": ("spine_root", "tail_1"),
    "spine.002": ("tail_1", "tail_2"),
    "spine.001": ("tail_2", "tail_3"),
    "spine": ("tail_3", "tail_4"),
}
for _s in ("L", "R"):
    QUADRUPED_BONE_MAP.update({
        f"shoulder.{_s}": (f"scapula_{_s}", f"f_shoulder_{_s}"),
        f"front_thigh.{_s}": (f"f_shoulder_{_s}", f"f_elbow_{_s}"),
        f"front_shin.{_s}": (f"f_elbow_{_s}", f"f_wrist_{_s}"),
        f"front_foot.{_s}": (f"f_wrist_{_s}", f"f_paw_{_s}"),
        f"front_toe.{_s}": (f"f_paw_{_s}", f"f_toe_{_s}"),
        f"pelvis.{_s}": ("spine_root", f"pelvis_tip_{_s}"),
        f"thigh.{_s}": (f"r_hip_{_s}", f"r_knee_{_s}"),
        f"shin.{_s}": (f"r_knee_{_s}", f"r_hock_{_s}"),
        f"foot.{_s}": (f"r_hock_{_s}", f"r_paw_{_s}"),
        f"toe.{_s}": (f"r_paw_{_s}", f"r_toe_{_s}"),
    })

# 과장 비율 캐릭터에서 형상과 무관하게 웨이트를 왜곡하므로 제거
BREAST_BONES = ("breast.L", "breast.R")

METARIG_SPECS = {
    "BIPED": ("armature_basic_human_metarig_add", BIPED_BONE_MAP),
    "QUADRUPED": ("armature_basic_quadruped_metarig_add", QUADRUPED_BONE_MAP),
}
GENERATED_TAG = "airig_generated"


def _raise(exc):
    raise exc


def ensure_rigify():
    # default_set=True 가 아니면 Rigify register() 가 Preferences 조회에 실패한다
    if "rigify" not in bpy.context.preferences.addons:
        addon_utils.enable("rigify", default_set=True, handle_error=_raise)
    if not hasattr(bpy.ops.pose, "rigify_generate"):
        raise RuntimeError("Rigify 를 활성화하지 못했습니다.")


def _deselect_all(context):
    # 방금 제거한 오브젝트가 뷰 레이어 동기화 전까지 None 으로 남을 수 있다
    for o in context.view_layer.objects:
        if o is not None:
            o.select_set(False)


def _set_active(context, obj):
    _deselect_all(context)
    obj.hide_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def remove_generated(name):
    obj = bpy.data.objects.get(name)
    if obj is not None and obj.get(GENERATED_TAG):
        data = obj.data
        bpy.data.objects.remove(obj)
        if data is not None and data.users == 0:
            bpy.data.armatures.remove(data)


def _add_fingers(metarig, ebones, side, hand):
    """Rigify 정식 손가락 구조: hand → palm.0N (super_palm 은 palm.01) → 손가락 3마디 (super_finger), 엄지는 palm.01 아래."""
    from mathutils import Vector

    wrist = Vector(hand.wrist)
    dorsal = Vector(hand.dorsal)
    regular = [f for f in hand.fingers if f.name != "thumb"]
    thumb = next((f for f in hand.fingers if f.name == "thumb"), None)
    hand_bone = ebones[f"hand.{side}"]
    if regular:
        mean_base = sum((Vector(f.base) for f in regular), Vector()) / len(regular)
        # 손 본은 손바닥 앞쪽에서 끝나야 손가락·손바닥 본과 겹치지 않는다
        hand_bone.tail = wrist.lerp(mean_base, 0.45)
        hand_bone.align_roll(dorsal)
    palms = []
    for k, f in enumerate(regular):
        palm = ebones.new(f"palm.{k + 1:02d}.{side}")
        palm.head = wrist.lerp(Vector(f.base), 0.15)
        palm.tail = Vector(f.base)
        palm.parent = hand_bone
        palm.align_roll(dorsal)
        palms.append(palm)
    created = [p.name for p in palms]
    for f in hand.fingers:
        parent = palms[0] if (f.name == "thumb" and palms) else (palms[regular.index(f)] if f in regular else hand_bone)
        prev = None
        for seg in range(3):
            eb = ebones.new(f"{f.name}.{seg + 1:02d}.{side}")
            eb.head = Vector(f.points[seg])
            eb.tail = Vector(f.points[seg + 1])
            if prev is None:
                eb.parent = parent
            else:
                eb.parent = prev
                eb.use_connect = True
            eb.align_roll(dorsal)
            created.append(eb.name)
            prev = eb
    return created, palms[0].name if palms else None, [f"{f.name}.01.{side}" for f in hand.fingers]


def build_metarig(context, kind, joints, name, has_tail=True, facing="-Y", symmetric=False, fingers=None):
    """체형별 basic 메타리그를 만들고 관절 위치로 본을 재배치한다."""
    ensure_rigify()
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    remove_generated(name)
    op_name, bone_map = METARIG_SPECS[kind]
    bone_map = dict(bone_map)
    remove = list(BREAST_BONES)
    if kind == "QUADRUPED":
        if has_tail:
            bone_map.update(QUADRUPED_TAIL_MAP)
        else:
            remove.extend(QUADRUPED_TAIL_MAP)
    getattr(bpy.ops.object, op_name)()
    metarig = context.active_object
    metarig.name = name
    metarig.data.name = name
    metarig[GENERATED_TAG] = True
    # 검토 에이전트 보정안 적용 시 메타리그를 다시 만들 수 있도록 입력을 보관한다
    metarig["airig_kind"] = kind
    metarig["airig_facing"] = facing
    metarig["airig_symmetric"] = symmetric
    metarig["airig_has_tail"] = has_tail
    metarig["airig_joints"] = json.dumps({k: list(v) for k, v in joints.items()})
    metarig.location = (0.0, 0.0, 0.0)
    metarig.rotation_euler = (0.0, 0.0, 0.0)
    metarig.scale = (1.0, 1.0, 1.0)

    bpy.ops.object.mode_set(mode="EDIT")
    try:
        ebones = metarig.data.edit_bones
        for bone_name in remove:
            eb = ebones.get(bone_name)
            if eb is not None:
                ebones.remove(eb)
        # 본 방향이 바뀌면 같은 roll 값이라도 이웃 본과 비틀림이 생겨 B-Bone 이 rest 에서 꼬이므로,
        # 템플릿의 Z축 방향을 기억했다가 재배치 후 그 방향으로 roll 을 다시 맞춘다
        z_axes = {n: ebones[n].z_axis.copy() for n in bone_map if n in ebones}
        if facing == "+Y":
            # 템플릿은 정면 -Y 기준이므로 캐릭터와 같이 Z축 180° 회전한 방향을 쓴다
            z_axes = {n: z.__class__((-z.x, -z.y, z.z)) for n, z in z_axes.items()}
        # 연결된 본은 head 가 부모 tail 을 따라가므로 head/tail 을 모두 지정한다
        for bone_name, (h, t) in bone_map.items():
            eb = ebones.get(bone_name)
            if eb is None:
                raise RuntimeError(f"메타리그에 본이 없습니다: {bone_name}")
            eb.head = joints[h]
            eb.tail = joints[t]
        for bone_name, (h, t) in bone_map.items():
            eb = ebones[bone_name]
            eb.head = joints[h]
            eb.tail = joints[t]
        for bone_name, z in z_axes.items():
            ebones[bone_name].align_roll(z)
        rig_types = {}
        if kind == "BIPED" and fingers:
            for side, hand in fingers.items():
                _created, palm_root, finger_roots = _add_fingers(metarig, ebones, side, hand)
                if palm_root:
                    rig_types[palm_root] = "limbs.super_palm"
                for root in finger_roots:
                    rig_types[root] = "limbs.super_finger"
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    for bone_name, rig_type in rig_types.items():
        metarig.pose.bones[bone_name].rigify_type = rig_type
    metarig["airig_fingers"] = json.dumps({s: h.to_dict() for s, h in (fingers or {}).items()})
    return metarig


def generate_rig(context, metarig, rig_name):
    ensure_rigify()
    if metarig.data.rigify_target_rig is None:
        # 메타리그를 새로 만든 경우 이전 리그를 지워야 이름 충돌(.001) 없이 같은 이름으로 생성된다
        old = bpy.data.objects.get(rig_name)
        if old is not None and old.get(GENERATED_TAG):
            for child in list(old.children):
                mw = child.matrix_world.copy()
                child.parent = None
                child.matrix_world = mw
            remove_generated(rig_name)
    _set_active(context, metarig)
    bpy.ops.pose.rigify_generate()
    rig = metarig.data.rigify_target_rig or context.active_object
    if rig is None or rig.type != "ARMATURE" or rig == metarig:
        raise RuntimeError("Rigify 리그 생성 결과를 찾지 못했습니다.")
    rig.name = rig_name
    rig[GENERATED_TAG] = True
    set_ik_mode(rig)
    metarig.hide_set(True)
    return rig


def set_ik_mode(rig):
    """모든 팔다리를 IK 모드(IK_FK=0)로 둔다. 2족·4족 모두 팔다리 4개."""
    limbs = [pb for pb in rig.pose.bones if "IK_FK" in pb]
    for pb in limbs:
        pb["IK_FK"] = 0.0
    if len(limbs) < 4:
        raise RuntimeError(f"IK/FK 스위치를 가진 팔다리가 {len(limbs)}개뿐입니다.")
    return [pb.name for pb in limbs]


def bind_mesh(context, mesh_obj, rig):
    """기존 바인딩을 지우고 DEF 본 기준 자동 웨이트로 다시 바인딩한다. 웨이트 없는 정점 수를 반환."""
    for mod in [m for m in mesh_obj.modifiers if m.type == "ARMATURE"]:
        mesh_obj.modifiers.remove(mod)
    deform_names = {b.name for b in rig.data.bones if b.use_deform}
    for vg in [g for g in mesh_obj.vertex_groups if g.name in deform_names]:
        mesh_obj.vertex_groups.remove(vg)
    if mesh_obj.parent is not None:
        mw = mesh_obj.matrix_world.copy()
        mesh_obj.parent = None
        mesh_obj.matrix_world = mw

    _deselect_all(context)
    mesh_obj.select_set(True)
    rig.select_set(True)
    context.view_layer.objects.active = rig
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")

    group_idx = {g.index for g in mesh_obj.vertex_groups if g.name in deform_names}
    unweighted = 0
    for v in mesh_obj.data.vertices:
        if not any(g.group in group_idx and g.weight > 1e-4 for g in v.groups):
            unweighted += 1
    return unweighted
