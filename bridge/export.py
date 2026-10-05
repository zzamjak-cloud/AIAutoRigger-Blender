"""게임 엔진용 FBX 내보내기.

Rigify 의 DEF 본은 허벅지·어깨 등이 디폼 부모 없이 떨어져 있어 Unity Humanoid 계층으로 쓸 수 없다.
DEF 본만 복제한 게임 아마추어를 만들어 ORG 계층을 따라 다시 부모를 잇고, Copy Transforms 로
컨트롤 리그를 따라가게 한 뒤 메시 복제본과 함께 내보낸다(애니메이션은 FBX 내보내기에서 굽는다).
"""

import json
import pathlib

import bpy

# Rigify DEF 본 → Unity Humanoid 친화 이름 (2족). 트위스트 분절(.001)은 접미사를 붙인다
UNITY_BIPED = {
    "DEF-spine": "Hips", "DEF-spine.001": "Spine", "DEF-spine.002": "Chest", "DEF-spine.003": "UpperChest",
    "DEF-spine.004": "Neck", "DEF-spine.005": "Neck2", "DEF-spine.006": "Head",
}
for _s, _w in (("L", "Left"), ("R", "Right")):
    UNITY_BIPED.update({
        f"DEF-shoulder.{_s}": f"{_w}Shoulder", f"DEF-upper_arm.{_s}": f"{_w}UpperArm",
        f"DEF-upper_arm.{_s}.001": f"{_w}UpperArmTwist", f"DEF-forearm.{_s}": f"{_w}LowerArm",
        f"DEF-forearm.{_s}.001": f"{_w}LowerArmTwist", f"DEF-hand.{_s}": f"{_w}Hand",
        f"DEF-thigh.{_s}": f"{_w}UpperLeg", f"DEF-thigh.{_s}.001": f"{_w}UpperLegTwist",
        f"DEF-shin.{_s}": f"{_w}LowerLeg", f"DEF-shin.{_s}.001": f"{_w}LowerLegTwist",
        f"DEF-foot.{_s}": f"{_w}Foot", f"DEF-toe.{_s}": f"{_w}Toes", f"DEF-pelvis.{_s}": f"{_w}Pelvis",
    })
for _s, _w in (("L", "Left"), ("R", "Right")):
    for _rigify, _unity in (("thumb", "Thumb"), ("f_index", "Index"), ("f_middle", "Middle"), ("f_ring", "Ring"), ("f_pinky", "Little")):
        for _n, _part in (("01", "Proximal"), ("02", "Intermediate"), ("03", "Distal")):
            UNITY_BIPED[f"DEF-{_rigify}.{_n}.{_s}"] = f"{_w}{_unity}{_part}"
        UNITY_BIPED[f"DEF-{_rigify}.01.{_s}.001"] = f"{_w}{_unity}ProximalTwist"

UNITY_BIPED.update({"DEF-jaw": "Jaw", "DEF-eye.L": "LeftEye", "DEF-eye.R": "RightEye"})
for _s, _w in (("L", "Left"), ("R", "Right")):
    for _k in range(1, 5):
        UNITY_BIPED[f"DEF-palm.{_k:02d}.{_s}"] = f"{_w}Palm{_k}"
# Unity 이름일 때 항상 합치는 본: 목 보조 본이 남으면 Unity 자동 매핑이 Head 자리에 Neck2 를 넣는다
UNITY_MERGE = ("DEF-spine.005",)
TWIST_BASES = ("upper_arm", "forearm", "thigh", "shin", "front_thigh", "front_shin")

# Unity HumanBodyBones → 위 이름 (아바타 수동 매핑용 JSON)
HUMANOID_BONES = (
    "Hips", "Spine", "Chest", "UpperChest", "Neck", "Head",
    *[f"{w}{p}" for w in ("Left", "Right") for p in
      ("Shoulder", "UpperArm", "LowerArm", "Hand", "UpperLeg", "LowerLeg", "Foot", "Toes")],
    *[f"{w}{f}{p}" for w in ("Left", "Right") for f in ("Thumb", "Index", "Middle", "Ring", "Little")
      for p in ("Proximal", "Intermediate", "Distal")],
    "Jaw", "LeftEye", "RightEye",
)
GAME_TAG = "airig_game"


def _deform_parent_map(rig, metarig):
    """DEF 본 → 내보낼 부모 DEF 본.

    메타리그 본에 대응하는 DEF 본은 메타리그(해부학) 계층을 따른다. Rigify 꼬리처럼 DEF 계층이 뒤집혀 있거나
    허벅지·어깨처럼 디폼 부모가 없는 경우를 바로잡기 위함이다. 트위스트 분절(.001 등, 메타리그에 없는 본)은
    리그의 가장 가까운 디폼 조상을 유지해 체인을 잇는다.
    """
    bones = rig.data.bones
    meta = metarig.data.bones
    names = {b.name for b in bones if b.use_deform}

    def owner(def_name):
        # 분절 본의 메타리그 소유 본: 메타리그에 있을 때까지 끝의 .NNN 을 떼어 낸다
        n = def_name[4:] if def_name.startswith("DEF-") else def_name
        while n not in meta and len(n) > 4 and n[-4] == "." and n[-3:].isdigit():
            n = n[:-4]
        return n if n in meta else None

    def nearest_deform(b):
        p = b.parent
        while p is not None and not p.use_deform:
            p = p.parent
        return p.name if p else None

    parents = {}
    for name in names:
        b = bones[name]
        base = name[4:] if name.startswith("DEF-") else name
        if base not in meta:
            parents[name] = nearest_deform(b)
            continue
        mp = meta[base].parent
        while mp is not None and f"DEF-{mp.name}" not in names:
            mp = mp.parent
        target = f"DEF-{mp.name}" if mp else None
        cand = nearest_deform(b)
        # 리그 쪽 디폼 부모가 같은 메타리그 부모의 분절이면 그대로 둬 트위스트 체인을 유지한다
        parents[name] = cand if (cand and target and owner(cand) == target[4:]) else target
    roots = [n for n, p in parents.items() if p is None]
    if len(roots) > 1:
        raise RuntimeError(f"내보낼 루트 본이 여러 개입니다: {roots}")
    return parents


def merge_set(names, naming, simplify):
    """내보낼 때 부모에 합칠 DEF 본. simplify 는 트위스트 분절·손바닥·골반을 합쳐 본 수를 줄인다."""
    merged = set()
    if naming == "UNITY":
        merged.update(n for n in UNITY_MERGE if n in names)
    if simplify:
        for n in names:
            base = n[4:] if n.startswith("DEF-") else n
            stem = base.rsplit(".", 2)[0] if base.count(".") >= 2 else base.split(".")[0]
            if base.endswith(".001") and stem in TWIST_BASES:
                merged.add(n)
            elif base.startswith(("palm.", "pelvis.")):
                merged.add(n)
    return merged


def build_game_armature(context, rig, metarig, mesh, naming="RIGIFY", simplify=False):
    """(게임 아마추어, 메시 복제본). naming='UNITY' 면 2족 본을 Unity 이름으로 바꾼다.

    합칠 본(merge_set)은 만들지 않고, 그 자식은 가장 가까운 남는 조상에 붙이며 웨이트는 그 조상 그룹에 더한다.
    """
    parents = _deform_parent_map(rig, metarig)
    merged = merge_set(set(parents), naming, simplify)

    def survivor(name):
        while name in merged:
            name = parents[name]
        return name

    merge_into = {n: survivor(parents[n]) for n in merged}
    # 위 survivor 가 원래 부모 표를 참조하므로 남는 본의 부모 표는 다른 이름으로 만든 뒤 바꾼다
    kept_parents = {n: (survivor(p) if p else None) for n, p in parents.items() if n not in merged}
    parents = kept_parents
    rename = UNITY_BIPED if naming == "UNITY" else {}
    data = bpy.data.armatures.new(f"{rig.name}_game")
    game = bpy.data.objects.new(f"{rig.name}_game", data)
    game[GAME_TAG] = True
    context.scene.collection.objects.link(game)
    game.matrix_world = rig.matrix_world.copy()

    for o in context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    context.view_layer.objects.active = game
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        src = rig.data.bones
        ebones = data.edit_bones
        for name in parents:
            b = src[name]
            eb = ebones.new(rename.get(name, name))
            eb.head = b.head_local
            eb.tail = b.tail_local
            # 레스트 방향(roll 포함)을 원본과 같게 맞춘다
            eb.matrix = b.matrix_local.copy()
            eb.use_deform = True
        for name, parent in parents.items():
            if parent:
                ebones[rename.get(name, name)].parent = ebones[rename.get(parent, parent)]
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")

    for name in parents:
        pb = game.pose.bones[rename.get(name, name)]
        c = pb.constraints.new("COPY_TRANSFORMS")
        c.target = rig
        c.subtarget = name

    copy = mesh.copy()
    copy.data = mesh.data.copy()
    copy[GAME_TAG] = True
    context.scene.collection.objects.link(copy)
    copy.parent = game
    copy.matrix_parent_inverse = game.matrix_world.inverted()
    copy.matrix_world = mesh.matrix_world.copy()
    for m in copy.modifiers:
        if m.type == "ARMATURE":
            m.object = game
    _merge_weights(copy, merge_into)
    for vg in copy.vertex_groups:
        if vg.name in rename:
            vg.name = rename[vg.name]
    return game, copy


def _merge_weights(mesh_obj, merge_into):
    """합친 본의 웨이트를 대상 본 그룹에 더하고 원래 그룹을 지운다 (정점은 한 번만 훑는다)."""
    vgs = mesh_obj.vertex_groups
    for dst in set(merge_into.values()):
        if vgs.get(dst) is None:
            vgs.new(name=dst)
    src_to_dst = {vgs[s].index: vgs[d] for s, d in merge_into.items() if vgs.get(s) is not None}
    if not src_to_dst:
        return
    adds: dict = {}
    for v in mesh_obj.data.vertices:
        cur = {g.group: g.weight for g in v.groups}
        extra = {}
        for gi, w in cur.items():
            dg = src_to_dst.get(gi)
            if dg is not None and w > 0.0:
                extra[dg.index] = extra.get(dg.index, cur.get(dg.index, 0.0)) + w
        for di, w in extra.items():
            adds.setdefault((di, round(min(1.0, w), 6)), []).append(v.index)
    by_index = {g.index: g for g in vgs}
    for (di, w), verts in adds.items():
        by_index[di].add(verts, w, "REPLACE")
    for s in [s for s in merge_into if vgs.get(s) is not None]:
        vgs.remove(vgs[s])


def remove_game_objects():
    for o in [o for o in bpy.data.objects if o.get(GAME_TAG)]:
        data = o.data
        bpy.data.objects.remove(o)
        if isinstance(data, bpy.types.Armature) and data.users == 0:
            bpy.data.armatures.remove(data)
        elif isinstance(data, bpy.types.Mesh) and data.users == 0:
            bpy.data.meshes.remove(data)


def export_fbx(context, rig, metarig, mesh, filepath, naming="RIGIFY", bake_anim=True, simplify=False):
    """FBX 와 (UNITY 이름일 때) Humanoid 매핑 JSON 을 쓴다. 반환: 내보낸 본 수."""
    filepath = pathlib.Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    action = rig.animation_data.action if rig.animation_data else None
    scene = context.scene
    saved_range = (scene.frame_start, scene.frame_end)
    saved_selection = [o for o in context.view_layer.objects if o is not None and o.select_get()]
    saved_active = context.view_layer.objects.active
    try:
        game, copy = build_game_armature(context, rig, metarig, mesh, naming, simplify)
        for o in context.view_layer.objects:
            if o is not None:
                o.select_set(o in (game, copy))
        context.view_layer.objects.active = game
        bone_count = len(game.data.bones)
        kwargs = dict(
            filepath=str(filepath),
            use_selection=True,
            object_types={"ARMATURE", "MESH"},
            add_leaf_bones=False,
            use_armature_deform_only=True,
            armature_nodetype="NULL",
            apply_scale_options="FBX_SCALE_ALL",
            axis_forward="-Z",
            axis_up="Y",
            bake_anim=bake_anim and action is not None,
        )
        if kwargs["bake_anim"]:
            # 게임 아마추어는 제약으로만 움직이므로 리그 액션 구간을 프레임 범위로 굽는다
            start, end = action.frame_range
            context.scene.frame_start, context.scene.frame_end = int(start), int(end)
            kwargs.update(bake_anim_use_all_actions=False, bake_anim_use_nla_strips=False,
                          bake_anim_force_startend_keying=True, bake_anim_simplify_factor=0.0)
        bpy.ops.export_scene.fbx(**kwargs)
        if naming == "UNITY":
            present = {b.name for b in game.data.bones}
            mapping = {h: h for h in HUMANOID_BONES if h in present}
            filepath.with_suffix(".humanoid.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    finally:
        remove_game_objects()
        scene.frame_start, scene.frame_end = saved_range
        for o in context.view_layer.objects:
            if o is not None:
                o.select_set(o in saved_selection)
        context.view_layer.objects.active = saved_active
    return bone_count
