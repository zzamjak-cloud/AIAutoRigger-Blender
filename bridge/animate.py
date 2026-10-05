"""이동 루프 키 포즈를 Rigify 컨트롤에 베지어 키로 넣는다.

발·손·몸통 IK 컨트롤과 루트는 모두 Root 를 부모로 따르므로(Rigify 기본), 캐릭터 기준 오프셋을
본 레스트 축으로 바꾸기만 하면 키 값을 바로 계산할 수 있다(프레임별 평가 불필요).
"""

import json
from math import radians

import bpy
from bpy_extras import anim_utils
from mathutils import Matrix, Vector

from ..core import locomotion

START_FRAME = 1
# 키를 넣는 IK 컨트롤의 부모 전환 속성 (1 = Root)
PARENT_SWITCHES = {"thigh_parent.L": "IK_parent", "thigh_parent.R": "IK_parent",
                   "upper_arm_parent.L": "IK_parent", "upper_arm_parent.R": "IK_parent", "torso": "torso_parent"}


def measure(rig):
    """(다리 길이, 팔 길이) m. 왼쪽 DEF 본 기준."""
    mw = rig.matrix_world
    b = rig.data.bones
    leg = (mw @ b["DEF-thigh.L"].head_local - mw @ b["DEF-foot.L"].head_local).length
    arm = (mw @ b["DEF-upper_arm.L"].head_local - mw @ b["DEF-hand.L"].head_local).length
    return leg, arm


def char_axes(facing):
    """(왼쪽, 정면, 위) 월드 단위 벡터."""
    if facing == "+Y":
        return Vector((-1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)), Vector((0.0, 0.0, 1.0))
    return Vector((1.0, 0.0, 0.0)), Vector((0.0, -1.0, 0.0)), Vector((0.0, 0.0, 1.0))


def char_rotation(pitch, roll, yaw, axes):
    left, front, up = axes
    return (Matrix.Rotation(radians(yaw), 3, up) @ Matrix.Rotation(radians(pitch), 3, left)
            @ Matrix.Rotation(radians(roll), 3, front))


def fcurves(rig):
    """액션 F-커브. Blender 4.4+ 슬롯 액션은 채널백, 4.2~4.3 은 레거시 action.fcurves."""
    ad = rig.animation_data
    if hasattr(ad, "action_slot") and hasattr(anim_utils, "action_get_channelbag_for_slot"):
        bag = anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)
        return list(bag.fcurves) if bag is not None else []
    return list(ad.action.fcurves)


def apply_motion(context, rig, motion, name, facing="-Y"):
    """새 액션을 만들어 리그에 넣는다. 반환: 액션."""
    p = motion.params
    n = p.cycle_frames
    axes = char_axes(facing)
    left, front, up = axes

    for bone, prop in PARENT_SWITCHES.items():
        pb = rig.pose.bones.get(bone)
        if pb is not None and prop in pb:
            # Root 를 따르게 해 키 값을 해석적으로 계산한다. 항목 순서는 Rigify 버전마다 다를 수 있어 이름으로 찾는다
            try:
                items = pb.id_properties_ui(prop).as_dict().get("items") or []
            except TypeError:
                items = []
            root = next((it[-1] for it in items if it[1] == "Root"), 1)
            pb[prop] = root
    for pb in rig.pose.bones:
        pb.matrix_basis.identity()

    rig.animation_data_create()
    old = rig.animation_data.action
    # 같은 이름으로 다시 만들면 이전 생성본을 교체한다 (AI 보정 라운드마다 .001 이 쌓이지 않게).
    # NLA 스트립·복제 리그 등 다른 곳에서도 쓰면 지우지 않고 이름만 바꿔 보존한다
    prev = bpy.data.actions.get(name)
    if prev is not None and "airig_motion" in prev:
        if old == prev:
            rig.animation_data.action = None
            old = None
        if prev.users - int(prev.use_fake_user) > 0:
            prev.name = name + "_old"
        else:
            bpy.data.actions.remove(prev)
    action = bpy.data.actions.new(name)
    action.use_fake_user = True
    rig.animation_data.action = action

    # 1) 모든 포즈를 레스트로 둔 채 키 값을 계산한다. Rigify 컨트롤 중에는 use_local_location 이 꺼진 본도 있어
    #    축을 직접 계산하지 않고 convert_space(POSE → LOCAL)로 바꾼다. 자식 본(hips·chest)은 부모 기준 상대값이 된다
    # NLA 가 평가되면 부모 본이 레스트가 아니게 되므로 계산하는 동안 끈다
    use_nla = rig.animation_data.use_nla
    rig.animation_data.use_nla = False
    context.view_layer.update()
    to_pose = rig.matrix_world.inverted().to_3x3()
    planned = []
    for channel in motion.channels:
        pb = rig.pose.bones.get(channel.bone)
        if pb is None:
            continue
        rest = pb.bone.matrix_local
        rest_rot, rest_loc = rest.to_3x3(), rest.to_translation()
        prev_q = None
        for key in channel.keys:
            frame = START_FRAME + key.t * n
            if channel.kind == "roll":
                planned.append((pb, "roll", radians(key.value[0]), frame, key.interp))
                continue
            if channel.kind == "loc":
                s, f, u = key.value
                delta = to_pose @ (left * s + front * f + up * u)
                target = Matrix.Translation(delta) @ rest
                local = rig.convert_space(pose_bone=pb, matrix=target, from_space="POSE", to_space="LOCAL")
                planned.append((pb, "location", local.to_translation(), frame, key.interp))
            else:
                r = to_pose @ char_rotation(*key.value, axes) @ to_pose.inverted()
                target = Matrix.Translation(rest_loc) @ (r @ rest_rot).to_4x4()
                local = rig.convert_space(pose_bone=pb, matrix=target, from_space="POSE", to_space="LOCAL")
                q = local.to_quaternion()
                if prev_q is not None and q.dot(prev_q) < 0.0:
                    q.negate()  # 보간이 반대 방향으로 돌지 않게 부호를 맞춘다
                prev_q = q
                planned.append((pb, "rotation_quaternion", q, frame, key.interp))

    # 2) 키 삽입
    interp = {}
    for pb, prop, value, frame, mode in planned:
        if prop == "roll":
            # Rigify 굴림 컨트롤은 오일러(ZXY) 로컬 X 만 읽으므로 회전 모드를 바꾸지 않고 X 채널만 키를 넣는다
            pb.rotation_euler.x = value
            pb.keyframe_insert("rotation_euler", index=0, frame=frame, group=pb.name)
            interp[(f'pose.bones["{pb.name}"].rotation_euler', round(frame, 3))] = mode
            continue
        if prop == "rotation_quaternion":
            pb.rotation_mode = "QUATERNION"
        setattr(pb, prop, value)
        pb.keyframe_insert(prop, frame=frame, group=pb.name)
        interp[(f'pose.bones["{pb.name}"].{prop}', round(frame, 3))] = mode

    rig.animation_data.use_nla = use_nla
    root_path = 'pose.bones["root"].location'
    for fc in fcurves(rig):
        for kp in fc.keyframe_points:
            kp.interpolation = interp.get((fc.data_path, round(kp.co.x, 3)), locomotion.BEZIER)
            kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"
        mod = fc.modifiers.new("CYCLES")
        if fc.data_path == root_path:
            # 전진은 주기마다 이동 거리를 이어 붙인다
            mod.mode_before = mod.mode_after = "REPEAT_OFFSET"
        fc.update()

    action.use_frame_range = True
    action.frame_start = START_FRAME
    action.frame_end = START_FRAME + n
    action.use_cyclic = True
    action["airig_motion"] = json.dumps(p.to_dict())
    scene = context.scene
    # 재생은 마지막 프레임(=첫 프레임 복제)을 빼야 이음새에서 한 프레임 멈추지 않는다
    scene.frame_start, scene.frame_end = START_FRAME, START_FRAME + n - 1
    scene.frame_set(START_FRAME)
    if old is not None and old.users == 0 and not old.use_fake_user:
        bpy.data.actions.remove(old)
    return action


def key_count(rig):
    return sum(len(fc.keyframe_points) for fc in fcurves(rig))
