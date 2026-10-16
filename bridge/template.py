"""모션 템플릿 등록·적용: 액션 F-커브 ↔ 캐릭터 기준 템플릿 (core.motion_template 형식).

등록은 모든 포즈를 레스트로 둔 채 각 키의 로컬 값을 포즈 공간으로 바꾸고(convert_space), 캐릭터 축
(왼쪽·정면·위)과 다리·팔 길이로 정규화한다. 적용은 그 반대다. 그래서 레스트 자세·본 축·크기가 다른
캐릭터에도 같은 움직임이 된다 (손은 어깨 기준이라 A-포즈와 팔 내린 레스트가 달라도 같은 높이로 뻗는다).
"""

import json
import re

import bpy
from bpy_extras import anim_utils
from mathutils import Matrix, Quaternion, Vector

from ..core import locomotion, motion_template
from . import animate

BONE_PATH = re.compile(r'^pose\.bones\["((?:[^"\\]|\\.)+)"\]\.(location|rotation_quaternion)$')
BONE_ANY = re.compile(r'^pose\.bones\["((?:[^"\\]|\\.)+)"\]')
# 팔 길이로 정규화하는 본 (그 밖의 위치는 다리 길이)
ARM_WORDS = ("arm", "hand", "palm", "thumb", "f_", "shoulder")


def _arm_bone(name):
    return any(w in name for w in ARM_WORDS)


def body_info(rig, mesh, facing):
    """체형 실측 (m): 다리·팔 길이, 메시 키·폭·두께 (캐릭터 축).

    메시는 아마추어 변형 전(레스트) 정점으로 잰다. bound_box 는 현재 프레임 포즈로 변형된 상자라 팔을 뻗은
    프레임에서 재면 두께가 커지고, 체형 비교(Auto)가 프레임마다 달라진다.
    """
    leg, arm = animate.measure(rig)
    left, front, up = animate.char_axes(facing)
    out = {"leg": round(leg, 4), "arm": round(arm, 4)}
    if mesh is not None and mesh.type == "MESH" and len(mesh.data.vertices):
        mw = mesh.matrix_world
        for key, axis in (("height", up), ("width", left), ("depth", front)):
            vals = [(mw @ v.co).dot(axis) for v in mesh.data.vertices]
            out[key] = round(max(vals) - min(vals), 4)
    return out


class _RestSpace:
    """모든 포즈를 레스트로 둔 상태에서 로컬 ↔ 포즈 공간을 바꾼다.

    with 블록이 끝나면 활성 액션·슬롯·NLA·IK 부모 전환 값·모든 본의 포즈(키 없는 수정 포함)를 되돌린다.
    블록 안에서는 IK 컨트롤이 Root 를 따르게 한다(키 값이 Root 기준이라는 가정). 원래 Root 가 아니던 전환은
    non_root 에 남긴다 (그런 리그에서 손으로 넣은 키는 다른 부모 기준이라 등록 값이 어긋날 수 있다).
    """

    def __init__(self, context, rig, facing, keep_root=False):
        # keep_root: 적용할 때는 키가 Root 기준이므로 IK 부모 전환을 Root 로 남긴다 (생성기와 같다)
        self.context, self.rig, self.keep_root = context, rig, keep_root
        left, front, up = animate.char_axes(facing)
        self.char = Matrix((left, front, up)).transposed()  # 열 = 캐릭터 축 (월드)
        mw = rig.matrix_world
        self.world = mw.to_3x3()
        self.world_rot = mw.to_3x3().normalized()

    def __enter__(self):
        ad = self.rig.animation_data_create()
        if getattr(ad, "use_tweak_mode", False):
            raise RuntimeError("NLA 트윅 모드에서는 템플릿을 등록·적용할 수 없습니다. 트윅 모드를 끄세요.")
        self.saved = (ad.action, getattr(ad, "action_slot", None), ad.use_nla)
        self.pose = {pb.name: pb.matrix_basis.copy() for pb in self.rig.pose.bones}
        self.switches = {}
        for bone, prop in animate.PARENT_SWITCHES.items():
            pb = self.rig.pose.bones.get(bone)
            if pb is not None and prop in pb:
                self.switches[(bone, prop)] = pb[prop]
        ad.use_nla = False
        if ad.action is not None:
            ad.action = None
        animate.prepare_rig(self.rig)
        self.non_root = [bone for (bone, prop), v in self.switches.items() if self.rig.pose.bones[bone][prop] != v]
        self.context.view_layer.update()
        self._rest = {}
        return self

    def __exit__(self, *exc):
        ad = self.rig.animation_data
        action, slot, use_nla = self.saved
        ad.action = action
        if slot is not None and getattr(ad, "action_slot", None) != slot:
            try:
                ad.action_slot = slot
            except (TypeError, RuntimeError, ValueError):
                pass
        ad.use_nla = use_nla
        if not self.keep_root:
            for (bone, prop), v in self.switches.items():
                self.rig.pose.bones[bone][prop] = v
        for pb in self.rig.pose.bones:
            m = self.pose.get(pb.name)
            if m is not None:
                pb.matrix_basis = m
        self.context.view_layer.update()
        return False

    def rest(self, pb):
        m = self._rest.get(pb.name)
        if m is None:
            m = self._rest[pb.name] = self.rig.convert_space(pose_bone=pb, matrix=Matrix.Identity(4),
                                                             from_space="LOCAL", to_space="POSE")
        return m

    def to_pose(self, pb, matrix):
        return self.rig.convert_space(pose_bone=pb, matrix=matrix, from_space="LOCAL", to_space="POSE")

    def to_local(self, pb, matrix):
        return self.rig.convert_space(pose_bone=pb, matrix=matrix, from_space="POSE", to_space="LOCAL")

    # 위치: 로컬 ↔ 캐릭터 축 (m)
    def loc_to_char(self, pb, v):
        d = self.to_pose(pb, Matrix.Translation(v)).to_translation() - self.rest(pb).to_translation()
        return self.char.transposed() @ (self.world @ d)

    def char_to_loc(self, pb, c):
        d = self.world.inverted() @ (self.char @ Vector(c))
        target = Matrix.Translation(d) @ self.rest(pb)
        return self.to_local(pb, target).to_translation()

    # 회전: 로컬 사원수 ↔ 캐릭터 축 사원수. 사원수 곱만 쓰므로 선형이고 부호가 보존된다
    # (사용자가 키를 넣으며 생긴 부호 뒤집힘도 그대로 옮겨져 보간 경로가 같다. 핸들 기울기도 같은 식으로 바뀐다).
    # 포즈 회전 = 레스트 회전 @ 로컬 회전 (Root 를 따르는 컨트롤, 부모가 레스트일 때)
    @property
    def _qk(self):
        """포즈 공간 → 캐릭터 축 회전. 캐릭터 축(왼쪽·정면·위)은 왼손 좌표계라 -1 을 곱해 회전으로 만든다
        (켤레 변환은 부호와 무관하다)."""
        rc = self.char if self.char.determinant() > 0 else self.char * -1.0
        return (rc.transposed() @ self.world_rot).to_quaternion()

    def _qrest(self, pb):
        return self.rest(pb).to_3x3().normalized().to_quaternion()

    def rot_to_char(self, pb, q, absolute=False):
        qk, qr = self._qk, self._qrest(pb)
        q = Quaternion(q)
        if absolute:
            # 절대 방향: 캐릭터 축 기준 본 방향 (손 IK — 레스트 손 방향이 캐릭터마다 달라도 같은 방향을 가리킨다)
            return qk @ qr @ q
        return qk @ qr @ q @ qr.inverted() @ qk.inverted()

    def char_to_rot(self, pb, q, absolute=False):
        qk, qr = self._qk, self._qrest(pb)
        q = Quaternion(q)
        if absolute:
            return qr.inverted() @ qk.inverted() @ q
        return qr.inverted() @ qk.inverted() @ q @ qk @ qr


def _action_curves(rig, action):
    """action 의 이 리그용 F-커브. 리그에 할당하지 않고 읽는다 (활성 액션의 슬롯을 바꾸지 않게).

    Blender 4.4+ 슬롯 액션은 활성 액션이면 리그의 슬롯, NLA 스트립이면 그 스트립의 슬롯, 아니면 오브젝트용
    첫 슬롯을 쓴다. 4.2~4.3 은 레거시 action.fcurves.
    """
    if not hasattr(action, "slots") or not hasattr(anim_utils, "action_get_channelbag_for_slot"):
        return list(action.fcurves)
    ad = rig.animation_data
    slot = None
    if ad is not None and ad.action == action:
        slot = ad.action_slot
    if slot is None and ad is not None:
        for track in ad.nla_tracks:
            for strip in track.strips:
                if strip.action == action and getattr(strip, "action_slot", None) is not None:
                    slot = strip.action_slot
                    break
            if slot is not None:
                break
    if slot is None:
        slot = next((sl for sl in action.slots if getattr(sl, "target_id_type", "OBJECT") == "OBJECT"), None)
    bag = anim_utils.action_get_channelbag_for_slot(action, slot) if slot is not None else None
    return list(bag.fcurves) if bag is not None else []


def _frame(t, n):
    """템플릿 시점 → 프레임. 원래 정수 프레임이던 키가 반올림 오차로 서브프레임에 놓이지 않게 맞춘다."""
    f = animate.START_FRAME + t * n
    r = round(f)
    return float(r) if abs(f - r) < 2e-3 else f


def signature(rig, action):
    """액션 키 내용 요약 (적용 후 손으로 고쳤는지 판단용)."""
    curves = _action_curves(rig, action)
    total = sum(kp.co.x * 0.37 + kp.co.y + kp.handle_left.y * 0.11 + kp.handle_right.y * 0.13
                for fc in curves for kp in fc.keyframe_points)
    return [round(total, 4), sum(len(fc.keyframe_points) for fc in curves)]


def action_range(action, curves):
    """(시작 프레임, 길이, 루프 여부).

    루프 길이는 Cycles 가 실제로 반복하는 커브별 키 구간(첫 키 → 마지막 키)이다. 액션 프레임 범위가 남아 있어도
    키 구간을 쓴다. 생성기 루프는 커브마다 첫 키 시점이 달라(발 위상 등) 전체 키 범위가 아니라 커브별 구간의 최댓값을 쓴다.
    """
    xs = [kp.co.x for fc in curves for kp in fc.keyframe_points]
    if not xs:
        raise ValueError(f"'{action.name}' 에 키가 없습니다.")
    loop = bool(action.use_cyclic) or any(m.type == "CYCLES" for fc in curves for m in fc.modifiers)
    start = action.frame_start if action.use_frame_range else min(xs)
    if loop:
        spans = [fc.keyframe_points[-1].co.x - fc.keyframe_points[0].co.x for fc in curves
                 if len(fc.keyframe_points) > 1 and any(m.type == "CYCLES" for m in fc.modifiers)]
        length = max(spans) if spans else max(xs) - min(xs)
        start = min(start, min(xs))
    elif action.use_frame_range:
        length = action.frame_end - action.frame_start
    else:
        length = max(xs) - min(xs)
    return start, max(1.0, length), loop


def _space_name(bone, prop):
    hand = bone.startswith("hand_ik.")
    if prop == "location":
        return "hand" if hand else ("arm" if _arm_bone(bone) else "leg")
    return "hand_rot" if hand else "rot"


def _to_char(space, body, pb, space_name, raw, linear=False):
    """로컬 값 → 템플릿 값. linear 면 핸들 기울기처럼 차이 벡터라 어깨 기준 이동을 빼지 않는다."""
    if space_name in ("rot", "hand_rot"):
        return list(space.rot_to_char(pb, raw, absolute=space_name == "hand_rot"))
    c = space.loc_to_char(pb, Vector(raw))
    if space_name == "hand":
        sh = (0.0, 0.0, 0.0) if linear else body.shoulder[pb.name[-1]]
        return [(c[i] - sh[i]) / body.arm for i in range(3)]
    return [x / (body.arm if space_name == "arm" else body.leg) for x in c]


def _from_char(space, body, pb, space_name, v, linear=False):
    """템플릿 값 → 로컬 값 (Vector 또는 Quaternion)."""
    if space_name in ("rot", "hand_rot"):
        return space.char_to_rot(pb, v, absolute=space_name == "hand_rot")
    if space_name == "hand":
        sh = (0.0, 0.0, 0.0) if linear else body.shoulder[pb.name[-1]]
        c = [v[i] * body.arm + sh[i] for i in range(3)]
    else:
        c = [x * (body.arm if space_name == "arm" else body.leg) for x in v]
    return space.char_to_loc(pb, c)


def _key_meta(kp, n, keep_handles):
    meta = {"ip": kp.interpolation, "hl": [kp.handle_left_type, kp.handle_right_type]}
    if keep_handles and (kp.handle_left_type not in motion_template.AUTO_HANDLES
                         or kp.handle_right_type not in motion_template.AUTO_HANDLES):
        meta["hd"] = [[(kp.handle_left.x - kp.co.x) / n, kp.handle_left.y - kp.co.y],
                      [(kp.handle_right.x - kp.co.x) / n, kp.handle_right.y - kp.co.y]]
    return meta


def capture(context, rig, mesh, action, facing, type_name, name, description=""):
    """액션 → 템플릿 dict. 반환: (템플릿, 정보 dict: 길이·루프·액션 프레임 범위와 다른지)."""
    curves = _action_curves(rig, action)
    start, n, loop = action_range(action, curves)
    body = animate.measure_body(rig, facing)
    groups = {}
    for fc in curves:
        groups.setdefault(fc.data_path, []).append(fc)
    channels = []
    body_m = body_info(rig, mesh, facing)
    with _RestSpace(context, rig, facing) as space:
        non_root = list(space.non_root)
        for path, fcs in groups.items():
            m = BONE_PATH.match(path)
            pb = rig.pose.bones.get(m.group(1).replace('\\"', '"')) if m else None
            offset = any(md.type == "CYCLES" and md.mode_after == "REPEAT_OFFSET" for fc in fcs for md in fc.modifiers)
            # 루프인데 Cycles 가 없는 커브 (손으로 뺀 경우)는 적용할 때도 넣지 않는다
            cyclic = any(md.type == "CYCLES" for fc in fcs for md in fc.modifiers)
            if pb is None:
                for fc in fcs:  # 로컬 값 그대로 (굴림 오일러·스케일·사용자 속성 등)
                    keys = [{"t": round((kp.co.x - start) / n, 5), "v": [kp.co.y], **_key_meta(kp, n, True)}
                            for kp in fc.keyframe_points]
                    channels.append({"path": path, "index": fc.array_index, "prop": "raw", "space": "raw",
                                     "bone": (BONE_ANY.match(path).group(1) if BONE_ANY.match(path) else ""),
                                     "offset": offset, "cyclic": any(md.type == "CYCLES" for md in fc.modifiers),
                                     "keys": keys})
                continue
            prop = m.group(2)
            size = 3 if prop == "location" else 4
            by_index = {fc.array_index: fc for fc in fcs}
            frames = {}  # {프레임: {성분: 키}}
            for fc in fcs:
                for kp in fc.keyframe_points:
                    frames.setdefault(round(kp.co.x, 4), {})[fc.array_index] = kp
            default = (0.0, 0.0, 0.0) if size == 3 else (1.0, 0.0, 0.0, 0.0)
            bone = pb.name
            space_name = _space_name(bone, prop)
            keys = []
            for f in sorted(frames):
                kps = frames[f]
                raw = [by_index[i].evaluate(f) if i in by_index else default[i] for i in range(size)]
                val = _to_char(space, body, pb, space_name, raw)
                first = kps[min(kps)]
                key = {"t": round((f - start) / n, 5), "v": [round(x, 6) for x in val], **_key_meta(first, n, False)}
                if len(kps) < len(by_index):
                    key["m"] = sorted(kps)  # 키가 있던 성분 (나머지 성분은 값만 계산에 쓰고 키를 넣지 않는다)
                ips = {kp.interpolation for kp in kps.values()}
                hls = {(kp.handle_left_type, kp.handle_right_type) for kp in kps.values()}
                if len(ips) > 1 or len(hls) > 1:  # 성분마다 보간·핸들이 다르면 성분별로 둔다
                    key["ip"] = [kps[i].interpolation if i in kps else first.interpolation for i in range(size)]
                    key["hl"] = [[kps[i].handle_left_type, kps[i].handle_right_type] if i in kps else key["hl"]
                                 for i in range(size)]
                if any(kp.handle_left_type not in motion_template.AUTO_HANDLES
                       or kp.handle_right_type not in motion_template.AUTO_HANDLES for kp in kps.values()):
                    # 손으로 고친 핸들: 성분별 시간 간격과, 같은 선형 변환으로 캐릭터 기준으로 바꾼 값 차이
                    hd = []
                    for side in ("handle_left", "handle_right"):
                        dt = [round((getattr(kps[i], side).x - kps[i].co.x) / n, 6) if i in kps else 0.0 for i in range(size)]
                        dv = [getattr(kps[i], side).y - kps[i].co.y if i in kps else 0.0 for i in range(size)]
                        hd.append([dt, [round(x, 6) for x in _to_char(space, body, pb, space_name, dv, linear=True)]])
                    key["hd"] = hd
                keys.append(key)
            channels.append({"path": path, "bone": bone, "prop": prop, "space": space_name, "size": size,
                             "offset": offset, "cyclic": cyclic, "keys": keys})
    data = {"format": motion_template.FORMAT, "type": type_name, "name": name, "loop": loop,
            "frames": int(round(n)), "fps": context.scene.render.fps, "description": description,
            "source": {"file": bpy.path.basename(bpy.data.filepath), "rig": rig.name, "action": action.name},
            "body": body_m, "channels": channels}
    stale = action.use_frame_range and abs((action.frame_end - action.frame_start) - n) > 0.5
    return motion_template.validate(data), {"frames": int(round(n)), "loop": loop, "stale_range": stale,
                                            "range": (action.frame_start, action.frame_end), "non_root": non_root}


def _setter(rig, path, index):
    """(data_path, index) → 값 설정 함수와 키 그룹 이름. 리그에 없는 경로면 (None, None)."""
    try:
        rig.path_resolve(path)
    except ValueError:
        return None, None
    m = BONE_ANY.match(path)
    group = m.group(1).replace('\\"', '"') if m else None
    head, _, attr = path.rpartition(".")
    if path.endswith('"]') and '["' in path:
        # 사용자 속성: pose.bones["x"]["prop"] 또는 오브젝트 속성 ["prop"]
        owner_path, _, key = path.rpartition('["')
        owner = rig.path_resolve(owner_path) if owner_path else rig
        key = key[:-2]

        def set_custom(v):
            cur = owner[key]
            if hasattr(cur, "__len__"):
                cur[index] = v
            else:
                owner[key] = type(cur)(v) if isinstance(cur, (int, float)) else v
        return set_custom, group
    owner = rig.path_resolve(head) if head else rig

    def set_attr(v):
        cur = getattr(owner, attr)
        if hasattr(cur, "__len__"):
            cur[index] = v
        else:
            setattr(owner, attr, type(cur)(v) if isinstance(cur, (bool, int, float)) else v)
    return set_attr, group


def apply(context, rig, data, name, facing="-Y", frames=None):
    """템플릿 → 새 액션. 반환: (액션, 건너뛴 경로 목록)."""
    n = int(frames or data["frames"])
    loop = data["loop"]
    body = animate.measure_body(rig, facing)
    planned, skipped = [], []
    meta = {}
    with _RestSpace(context, rig, facing, keep_root=True) as space:
        for ch in data["channels"]:
            if ch["space"] == "raw":
                setter, group = _setter(rig, ch["path"], ch["index"])
                if setter is not None:
                    cur = rig.path_resolve(ch["path"])
                    # 배열이 아닌 속성(사용자 속성 실수값 등)은 index 없이 키를 넣는다
                    key_index = ch["index"] if hasattr(cur, "__len__") and not isinstance(cur, str) else -1
                if setter is None:
                    skipped.append(ch["path"])
                    continue
                for k in ch["keys"]:
                    frame = _frame(k["t"], n)
                    planned.append(("raw", setter, ch["path"], key_index, group, k["v"][0], frame))
                    hd = k.get("hd")
                    meta[(ch["path"], ch["index"], round(frame, 3))] = (k, 0, [[[dt], [dv]] for dt, dv in hd] if hd else None)
                continue
            pb = rig.pose.bones.get(ch["bone"])
            if pb is None:
                skipped.append(ch["path"])
                continue
            for k in ch["keys"]:
                frame = _frame(k["t"], n)
                value = _from_char(space, body, pb, ch["space"], k["v"])
                mask = k.get("m")
                planned.append(("bone", pb, ch["prop"], mask, pb.name, value, frame))
                hd = k.get("hd")
                if hd:
                    hd = [[dt, list(_from_char(space, body, pb, ch["space"], dv, linear=True))] for dt, dv in hd]
                for i in (mask if mask is not None else range(ch["size"])):
                    meta[(ch["path"], i, round(frame, 3))] = (k, i, hd)

    # 이전에 적용한 같은 이름의 액션을 손으로 고쳤으면 교체하지 않고 '<이름>_edited' 로 남긴다
    prev = bpy.data.actions.get(name)
    if prev is not None and "airig_template" in prev:
        sig = prev.get("airig_signature")
        if sig is not None and list(sig) != signature(rig, prev):
            prev.name = name + "_edited"
    action, old = animate.new_action(rig, name, marker="airig_template")
    use_nla = rig.animation_data.use_nla
    rig.animation_data.use_nla = False
    try:
        for kind, target, prop, index, group, value, frame in planned:
            if kind == "raw":
                target(value)
                rig.keyframe_insert(prop, index=index, frame=frame, group=group or "")
                continue
            if prop == "rotation_quaternion":
                target.rotation_mode = "QUATERNION"
            setattr(target, prop, value)
            for i in (index if index is not None else (-1,)):  # index = 키를 넣을 성분 (None 이면 전부)
                target.keyframe_insert(prop, index=i, frame=frame, group=group)
    except (RuntimeError, TypeError, AttributeError, ValueError) as exc:
        # 반쯤 채운 액션을 남기지 않고 이전 상태로 되돌린다
        rig.animation_data.action = old
        bpy.data.actions.remove(action)
        rig.animation_data.use_nla = use_nla
        raise RuntimeError(f"템플릿 키를 넣지 못했습니다: {exc}") from exc

    offsets = {ch["path"] for ch in data["channels"] if ch.get("offset")}
    plain = {(ch["path"], ch.get("index")) for ch in data["channels"] if ch.get("cyclic") is False}
    for fc in animate.fcurves(rig):
        for kp in fc.keyframe_points:
            found = meta.get((fc.data_path, fc.array_index, round(kp.co.x, 3)))
            if found is None:
                continue
            k, i, hd = found
            ip, hl = k.get("ip", locomotion.BEZIER), k.get("hl") or ["AUTO_CLAMPED", "AUTO_CLAMPED"]
            kp.interpolation = ip[i] if isinstance(ip, list) else ip
            kp.handle_left_type, kp.handle_right_type = hl[i] if isinstance(hl[0], list) else hl
            if hd:
                kp.handle_left = (kp.co.x + hd[0][0][i] * n, kp.co.y + hd[0][1][i])
                kp.handle_right = (kp.co.x + hd[1][0][i] * n, kp.co.y + hd[1][1][i])
        if loop and (fc.data_path, None) not in plain and (fc.data_path, fc.array_index) not in plain:
            mod = fc.modifiers.new("CYCLES")
            if fc.data_path in offsets:
                mod.mode_before = mod.mode_after = "REPEAT_OFFSET"
        fc.update()

    action.use_frame_range = True
    action.frame_start = animate.START_FRAME
    action.frame_end = animate.START_FRAME + n
    action.use_cyclic = loop
    action["airig_template"] = json.dumps({"type": data["type"], "name": data["name"], "version": data.get("version", 1)})
    _left, _front, up = animate.char_axes(facing)
    reach = animate.limit_leg_reach(context, rig, n, loop, up)
    rig.animation_data.use_nla = use_nla
    action["airig_leg_reach"] = round(reach, 4)
    action["airig_signature"] = signature(rig, action)
    scene = context.scene
    scene.frame_start, scene.frame_end = animate.START_FRAME, animate.START_FRAME + (n - 1 if loop else n)
    scene.frame_set(animate.START_FRAME)
    if old is not None and old.users == 0 and not old.use_fake_user:
        bpy.data.actions.remove(old)
    return action, skipped
