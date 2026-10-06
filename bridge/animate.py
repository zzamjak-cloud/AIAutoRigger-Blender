"""애니메이션 키 포즈(루프·단발)를 Rigify 컨트롤에 베지어 키로 넣는다.

발·손·몸통 IK 컨트롤과 루트는 모두 Root 를 부모로 따르므로(Rigify 기본), 캐릭터 기준 오프셋을
본 레스트 축으로 바꾸기만 하면 키 값을 바로 계산할 수 있다(프레임별 평가 불필요).
"""

import json
from math import atan2, degrees, radians

import bpy
from bpy_extras import anim_utils
from mathutils import Matrix, Quaternion, Vector

from ..core import handshape, locomotion, poseclip

START_FRAME = 1
# 엉덩이 → 발목 IK 목표 거리의 상한 (다리 길이 비율). Rigify 레스트 다리는 거의 펴져 있어(0.999) 여유가 없다
REACH_LIMIT = 0.999
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


def measure_body(rig, facing="-Y"):
    """포즈 클립용 실측: 다리·팔 길이와 손 IK 레스트 → 어깨 오프셋(캐릭터 기준), 손 레스트 높이."""
    leg, arm = measure(rig)
    mw = rig.matrix_world
    b = rig.data.bones
    left, front, up = char_axes(facing)
    shoulder, hand_height, pivot = {}, {}, {}
    torso = mw @ b["torso"].head_local
    for side in ("L", "R"):
        hand = mw @ b[f"hand_ik.{side}"].head_local
        d = (mw @ b[f"DEF-upper_arm.{side}"].head_local) - hand
        shoulder[side] = (d.dot(left), d.dot(front), d.dot(up))
        hand_height[side] = hand.z
        pv = torso - hand
        pivot[side] = (pv.dot(left), pv.dot(front), pv.dot(up))
    return poseclip.Body(leg, arm, shoulder, hand_height, pivot)


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
    curl_axes = finger_axes(context, rig) if any(c.kind == "curl" for c in motion.channels) else {}
    for channel in motion.channels:
        if channel.kind == "curl":
            # 손 모양: 손가락별 굽힘(0~1)을 마디 컨트롤 세 개의 손바닥 쪽 회전으로 바꾼다(부모를 따라 누적되어 말린다).
            # 없는 손가락은 건너뛴다
            side = channel.bone[-1]
            for i, finger in enumerate(handshape.FINGERS):
                found = curl_axes.get((finger, side))
                if found is None:
                    continue
                segments, rest_bend = found
                for key in channel.keys:
                    # 굽힘은 곧은 손가락 기준 절대 각도다. 갈고리처럼 굽은 채 모델링된 손가락은 그만큼 덜 돌린다
                    angle = radians(key.value[i] * handshape.MAX_CURL_DEG[finger] - rest_bend)
                    for pb, axis in segments:
                        planned.append((pb, "rotation_quaternion", Quaternion(axis, angle), START_FRAME + key.t * n, key.interp))
            continue
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
    loop = motion.loop
    for fc in fcurves(rig):
        for kp in fc.keyframe_points:
            kp.interpolation = interp.get((fc.data_path, round(kp.co.x, 3)), locomotion.BEZIER)
            kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"
        if loop:
            # 단발 동작(점프·공격·피격·사망)은 반복하지 않고 마지막 키 값을 유지한다
            mod = fc.modifiers.new("CYCLES")
            if fc.data_path == root_path:
                # 전진은 주기마다 이동 거리를 이어 붙인다
                mod.mode_before = mod.mode_after = "REPEAT_OFFSET"
        fc.update()

    action.use_frame_range = True
    action.frame_start = START_FRAME
    action.frame_end = START_FRAME + n
    action.use_cyclic = loop
    action["airig_motion"] = json.dumps(p.to_dict())
    rig.animation_data.use_nla = False
    reach = limit_leg_reach(context, rig, n, loop, up)
    rig.animation_data.use_nla = use_nla
    action["airig_leg_reach"] = round(reach, 4)
    if reach > REACH_LIMIT + 0.002:
        print(f"[AIRig] 경고: {name} 에서 발이 다리 길이를 넘는 프레임이 남음 (최대 {reach:.3f})")
    scene = context.scene
    # 루프 재생은 마지막 프레임(=첫 프레임 복제)을 빼야 이음새에서 한 프레임 멈추지 않는다. 단발은 끝 프레임까지 재생
    scene.frame_start, scene.frame_end = START_FRAME, START_FRAME + (n - 1 if loop else n)
    scene.frame_set(START_FRAME)
    if old is not None and old.users == 0 and not old.use_fake_user:
        bpy.data.actions.remove(old)
    return action


def _dorsal(rig, side):
    """손가락 감지가 기록한 손등 방향(월드). 메타리그(rigify_target_rig 가 이 리그)에 있다. 없으면 None."""
    for o in bpy.data.objects:
        if o.type == "ARMATURE" and getattr(o.data, "rigify_target_rig", None) == rig and o.get("airig_fingers"):
            try:
                return Vector(json.loads(o["airig_fingers"])[side]["dorsal"]).normalized()
            except (KeyError, TypeError, ValueError):
                return None
    return None


def _rest_bend(rig, finger, side, dorsal):
    """레스트에서 이미 손바닥 쪽으로 굽은 정도를 master 가 돌리는 세 관절 하나당 각도(도)로 돌려준다.

    손 방향(엄지는 첫 마디 방향) 대비 끝마디 방향의 각도를 손등–손 방향 평면에서 잰다(옆으로 벌어진 각도는 빼고,
    검출 중심선의 지그재그는 상쇄된다). 곧은 손가락은 0 근처, 갈고리 손은 수십 도. 손등 방향을 모르면 0.
    """
    ref_bone = rig.data.bones.get(f"ORG-{finger}.01.{side}" if finger == "thumb" else f"ORG-hand.{side}")
    last = rig.data.bones.get(f"ORG-{finger}.03.{side}")
    if dorsal is None or ref_bone is None or last is None:
        return 0.0
    mw = rig.matrix_world.to_3x3()
    fwd = (mw @ ref_bone.matrix_local.to_3x3().col[1]).normalized()
    up = dorsal - fwd * dorsal.dot(fwd)
    if up.length < 1e-6:
        return 0.0
    up.normalize()
    d = (mw @ last.matrix_local.to_3x3().col[1]).normalized()
    return max(0.0, degrees(atan2(-d.dot(up), d.dot(fwd)))) / 3.0


def finger_axes(context, rig):
    """{(손가락, 쪽): ([(마디 컨트롤 포즈 본, 손바닥 쪽으로 굽는 로컬 회전축) × 3], 관절당 레스트 굽힘 도)}.

    Rigify 손가락 master 는 손가락 전체를 뿌리에서 통째로 돌리므로, 말아 쥐려면 마디 컨트롤(f_index.01~03)을 각각 돌린다.
    0.7.5 이전 리그는 굽힘 축이 'automatic' 이라 손가락마다 축·부호가 달랐다. 그래서 마디를 후보 축(±X, ±Z)으로 잠깐
    돌려 보고 손끝이 손바닥 쪽(손등 반대)으로 가장 많이 가는 축을 고른다. 손등 방향을 모르면 -X(현재 리그 규칙).
    """
    out = {}
    candidates = (Vector((-1.0, 0.0, 0.0)), Vector((1.0, 0.0, 0.0)), Vector((0.0, 0.0, -1.0)), Vector((0.0, 0.0, 1.0)))
    for side in ("L", "R"):
        dorsal = _dorsal(rig, side)
        for finger in handshape.FINGERS:
            controls = [rig.pose.bones.get(f"{finger}.{k}.{side}") for k in ("01", "02", "03")]
            tip = rig.pose.bones.get(f"DEF-{finger}.03.{side}") or rig.pose.bones.get(f"ORG-{finger}.03.{side}")
            if any(pb is None for pb in controls):
                continue
            segments = []
            for pb in controls:
                pb.rotation_mode = "QUATERNION"
                if dorsal is None or tip is None:
                    segments.append((pb, candidates[0]))
                    continue
                context.view_layer.update()
                t0 = rig.matrix_world @ tip.tail
                best, best_axis = None, candidates[0]
                for axis in candidates:
                    pb.rotation_quaternion = Quaternion(axis, 0.5)
                    context.view_layer.update()
                    toward_palm = -(rig.matrix_world @ tip.tail - t0).dot(dorsal)
                    if best is None or toward_palm > best:
                        best, best_axis = toward_palm, axis
                pb.rotation_quaternion = Quaternion()
                segments.append((pb, best_axis))
            out[(finger, side)] = (segments, _rest_bend(rig, finger, side, dorsal))
    context.view_layer.update()
    return out


def _legs(rig):
    """(엉덩이 본, 발목 IK 목표 본, 다리 길이) 목록. Rigify 2족 다리가 아니면 빈 목록."""
    legs = []
    for side in ("L", "R"):
        names = (f"ORG-thigh.{side}", f"ORG-shin.{side}", f"MCH-thigh_ik_target.{side}")
        if all(x in rig.pose.bones for x in names):
            length = rig.data.bones[names[0]].length + rig.data.bones[names[1]].length
            legs.append((rig.pose.bones[names[0]], rig.pose.bones[names[2]], length))
    return legs


def leg_reach(context, rig, frames):
    """프레임별 최대 (엉덩이 → 발목 목표 거리 / 다리 길이). 1 을 넘으면 IK 스트레치로 다리가 늘어난다."""
    legs = _legs(rig)
    out = {}
    for f in frames:
        context.scene.frame_set(f)
        out[f] = max(((t.head - h.head).length / length for h, t, length in legs), default=0.0)
    return out


def _bracket(keys, f, n, loop):
    """프레임 f 를 감싸는 (앞 키, 뒤 키). 루프는 키 범위 밖의 프레임을 한 주기로 접는다."""
    if loop and f < keys[0]:
        f += n
    if f <= keys[0]:
        return keys[0], keys[0], f
    if f >= keys[-1]:
        return keys[-1], keys[-1], f
    for a, b in zip(keys, keys[1:]):
        if a <= f <= b:
            return a, b, f
    return keys[-1], keys[-1], f


def _loc_curves(rig, bone):
    path = f'pose.bones["{bone}"].location'
    curves = sorted((fc for fc in fcurves(rig) if fc.data_path == path), key=lambda fc: fc.array_index)
    return curves if len(curves) == 3 else []


def _shift_keys(rig, bone, shifts, down_pose):
    """bone 의 위치 키 중 shifts {프레임: 내릴 거리(m)} 에 있는 키를 캐릭터 아래로 옮긴다."""
    pb = rig.pose.bones.get(bone)
    curves = _loc_curves(rig, bone)
    if pb is None or not curves:
        return
    rest = pb.bone.matrix_local
    base = rig.convert_space(pose_bone=pb, matrix=rest, from_space="POSE", to_space="LOCAL").to_translation()
    for frame, amount in shifts.items():
        if amount <= 0.0:
            continue
        # 부모(Root 계열)는 이동만 하므로 레스트 기준 차이가 곧 로컬 이동량이다
        moved = rig.convert_space(pose_bone=pb, matrix=Matrix.Translation(down_pose * amount) @ rest,
                                  from_space="POSE", to_space="LOCAL").to_translation()
        delta = moved - base
        for fc in curves:
            for kp in fc.keyframe_points:
                if abs(kp.co.x - frame) < 1e-3:
                    kp.co.y += delta[fc.array_index]
                    kp.handle_left.y += delta[fc.array_index]
                    kp.handle_right.y += delta[fc.array_index]
    for fc in curves:
        fc.update()


def _shift_at(shifts, keys, f, n, loop):
    """몸통 키 보정량을 키 사이 선형 보간한 프레임 f 의 보정량 (손 키처럼 다른 시점의 키를 함께 내릴 때)."""
    k1, k2, ff = _bracket(keys, f, n, loop)
    a1, a2 = shifts.get(k1, 0.0), shifts.get(k2, 0.0)
    return a1 if k1 == k2 else a1 + (a2 - a1) * (ff - k1) / (k2 - k1)


def limit_leg_reach(context, rig, n, loop, up, max_iter=12):
    """발목 IK 목표가 다리 길이를 넘는 프레임이 없도록 몸통 위치 키를 내린다. 반환: 보정 후 최대 도달 비율.

    점프 도약·깡충 착지처럼 발이 바닥에 있는데 몸통이 레스트보다 높으면 Rigify IK 스트레치가 다리를 늘인다.
    Unity Humanoid 는 본 스케일을 버리므로 게임에서는 발이 뜨거나 미끄러진다. 넘친 프레임을 감싸는 몸통 키를
    필요한 만큼(가까운 키일수록 많이) 내리고, 몸통을 따르던 손 키도 같은 시점이면 함께 내린다. 키 개수는 그대로다.
    """
    legs = _legs(rig)
    torso = rig.pose.bones.get("torso")
    path = 'pose.bones["torso"].location'
    curve = next((fc for fc in fcurves(rig) if fc.data_path == path), None)
    frames = range(START_FRAME, START_FRAME + n + 1)
    if not legs or torso is None or curve is None:
        return max(leg_reach(context, rig, frames).values(), default=0.0)
    up_pose = (rig.matrix_world.inverted().to_3x3() @ up).normalized()
    keys = sorted(kp.co.x for kp in curve.keyframe_points)
    for _ in range(max_iter):
        excess = {}
        for f in frames:
            context.scene.frame_set(f)
            worst = 0.0
            for h, t, length in legs:
                v = t.head - h.head
                over = v.length - REACH_LIMIT * length
                if over > 1e-4:
                    # 몸통을 내리면 거리 중 수직 성분만큼 줄어든다
                    worst = max(worst, over / max(abs(v.normalized().dot(up_pose)), 0.5))
            if worst > 0.0:
                excess[f] = worst
        if not excess:
            break
        shifts = {}
        for f, e in excess.items():
            k1, k2, ff = _bracket(keys, f, n, loop)
            if k1 == k2:
                shifts[k1] = max(shifts.get(k1, 0.0), e)
                continue
            u = (ff - k1) / (k2 - k1)
            norm = (1.0 - u) ** 2 + u ** 2  # 두 키를 (1-u), u 비율로 내리면 그 사이 값이 e 만큼 내려가게 한다
            shifts[k1] = max(shifts.get(k1, 0.0), e * (1.0 - u) / norm)
            shifts[k2] = max(shifts.get(k2, 0.0), e * u / norm)
        # 루프의 시작 키와 한 주기 뒤 복제 키는 같은 값이어야 하므로 큰 쪽 하나로 맞춘다 (둘을 더하지 않는다)
        if loop and keys[-1] - keys[0] >= n - 1e-3:
            seam = max(shifts.get(keys[0], 0.0), shifts.get(keys[-1], 0.0))
            if seam > 0.0:
                shifts[keys[0]] = shifts[keys[-1]] = seam
        # 조금 더 내려 반복 횟수를 줄인다
        shifts = {k: 1.05 * a for k, a in shifts.items()}
        # 손 키는 몸통 키와 시점이 다를 수 있어 그 시점의 몸통 보정량만큼 내린다 (손은 몸통을 따라 움직인다)
        hands = {}
        for bone in ("hand_ik.L", "hand_ik.R"):
            curves = _loc_curves(rig, bone)
            if curves:
                hands[bone] = {kp.co.x: _shift_at(shifts, keys, kp.co.x, n, loop) for kp in curves[0].keyframe_points}
        _shift_keys(rig, "torso", shifts, -up_pose)
        for bone, hand_shifts in hands.items():
            _shift_keys(rig, bone, hand_shifts, -up_pose)
    return max(leg_reach(context, rig, frames).values(), default=0.0)


def key_count(rig):
    return sum(len(fc.keyframe_points) for fc in fcurves(rig))
