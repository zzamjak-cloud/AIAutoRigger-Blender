"""손가락 애니메이션 통합 테스트: 손 모양이 Rigify 손가락 master 키로 들어가 손바닥 쪽으로 굽는지, 무기 쥐기·좀비 갈퀴 손,
동작 사전 손 모양, 손가락 없는 손(벙어리장갑) 처리, 게임 FBX 손가락 애니메이션.

실행: scripts/dev_run.sh --background --python tests/blender_hand_test.py -- <출력 폴더>
"""

import json
import os
import pathlib
import sys
import tempfile

import bpy
from mathutils import Vector

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
import humanoid  # noqa: E402

PKG = f"bl_ext.user_default.{os.environ['AIRIG_ADDON_ID']}"
OUT = pathlib.Path(sys.argv[sys.argv.index("--") + 1]) if "--" in sys.argv else ROOT / "dist" / "hand_test"
animate = __import__(f"{PKG}.bridge.animate", fromlist=["x"])
os.environ["AIRIG_LIBRARY_DIR"] = tempfile.mkdtemp(prefix="airig_lib_test_")


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[hand] OK  {msg}")


def make_obj(name, verts, tris, voxel):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], tris)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new("remesh", "REMESH")
    mod.mode, mod.voxel_size = "VOXEL", voxel
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return obj


def build(variant):
    bpy.ops.wm.read_homefile(use_empty=True)
    bv, bt, _gt, hv, ht = humanoid.build_from(humanoid.FINGER_VARIANTS[variant], split_hands=True)
    body = make_obj(variant, bv, bt, 0.015)
    hands = make_obj(variant + "_hands", hv, ht, 0.004)
    for o in bpy.context.view_layer.objects:
        o.select_set(o in (body, hands))
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    check(bpy.ops.airig.auto_rig() == {"FINISHED"}, f"{variant}: 자동 리깅")
    st = bpy.context.scene.airig
    return bpy.data.objects[st.rig_name], json.loads(bpy.data.objects[st.metarig_name]["airig_fingers"])


def curl(rig, side, finger, frame):
    """손가락 오므림 = 1 - (손끝~뿌리 거리 / 손가락 길이). 곧게 편 손가락 0, 주먹이면 크다."""
    bpy.context.scene.frame_set(frame)
    segs = [rig.pose.bones[f"DEF-{finger}.{k}.{side}"] for k in ("01", "02", "03")]
    length = sum(b.bone.length for b in segs)
    return 1.0 - (segs[2].tail - segs[0].head).length / length


def generate(motion, style="NORMAL", hands="AUTO"):
    st = bpy.context.scene.airig
    st.anim_motion, st.anim_style, st.anim_root_motion, st.anim_hand_shape = motion, style, False, hands
    check(bpy.ops.airig.generate_motion() == {"FINISHED"}, f"{motion}/{style}/{hands}: 생성")
    action = bpy.data.actions[st.anim_action]
    return action, int(action.frame_end - action.frame_start)


def masters(rig):
    """손가락 마디 컨트롤 (f_index.01.L 등). 손가락당 3개."""
    import re
    return [pb for pb in rig.pose.bones if re.fullmatch(r"(thumb|f_\w+)\.0[123]\.[LR]", pb.name)]


def keyed_masters(rig):
    paths = {fc.data_path for fc in animate.fcurves(rig)}
    return [pb for pb in masters(rig) if f'pose.bones["{pb.name}"].rotation_quaternion' in paths]


for variant in ("fingers_straight_t", "fingers_claw_a"):
    rig, fingers = build(variant)
    names = [f["name"] for f in fingers["L"]["fingers"]]
    regular = [n for n in names if n != "thumb"]

    # 걷기: 힘을 뺀 손 — 모든 손가락 master 에 키, 조금 굽음
    action, n = generate("WALK")
    check(len(keyed_masters(rig)) == len(masters(rig)) == 6 * len(names), f"{variant}: 손가락 마디 컨트롤 {len(masters(rig))}개 모두 키")
    relaxed = min(curl(rig, "L", f, 1) for f in regular)
    check(relaxed > 0.01, f"{variant}: 걷기 손가락이 조금 굽음 (오므림 {relaxed:.2f})")

    # 맨손 공격: 타격 순간 주먹 — 레스트보다 손바닥 쪽으로 크게 굽고, 걷기보다 더 굽는다
    action, n = generate("ATTACK")
    strike = 1 + round(n * min(0.8, json.loads(action["airig_motion"])["anticipation"] + 0.15))
    for side in ("L", "R"):
        fist = [curl(rig, side, f, strike) for f in regular]
        check(min(fist) > relaxed + 0.15, f"{variant} {side}: 공격 손가락이 주먹 쪽으로 굽음 (최소 오므림 {min(fist):.2f})")
    attack_hand = json.loads(action["airig_motion"])["attack_side"]
    fist_r = min(curl(rig, attack_hand, f, strike) for f in regular)
    end = min(curl(rig, attack_hand, f, 1 + n) for f in regular)
    check(end < fist_r, f"{variant}: 복귀하며 주먹을 풂 ({fist_r:.2f} → {end:.2f})")

    # 좀비는 갈퀴 손, Hands 를 고르면 그 모양으로 고정
    generate("WALK", "ZOMBIE")
    claw = min(curl(rig, "R", f, 1) for f in regular)
    check(claw > relaxed, f"{variant}: 좀비 갈퀴 손이 힘 뺀 손보다 굽음")
    generate("WALK", hands="OPEN")
    opened = max(abs(curl(rig, "R", f, 1)) for f in regular)
    # 갈고리 손은 레스트 굽힘을 손가락 단위 평균으로 보정하므로 마디별 차이가 조금 남는다
    check(opened < (0.01 if variant.startswith("fingers_straight") else relaxed),
          f"{variant}: Hands=Open 이면 손가락을 편다 (오므림 {opened:.3f}, 힘 뺀 손 {relaxed:.3f})")

    # 동작 사전: 가리키기는 검지만 펴고 나머지는 접는다
    if "f_index" in names and len(regular) >= 2:
        st = bpy.context.scene.airig
        st.anim_library = "point"
        check(bpy.ops.airig.generate_library_motion() == {"FINISHED"}, f"{variant}: 사전 point 생성")
        action = bpy.data.actions[st.anim_action]
        mid = 1 + round(0.5 * (action.frame_end - action.frame_start))
        index = curl(rig, "R", "f_index", mid)
        others = min(curl(rig, "R", f, mid) for f in regular if f != "f_index")
        check(others > index + 0.2, f"{variant}: 가리키기 — 검지 오므림 {index:.2f}, 나머지 {others:.2f}")

# 벙어리장갑형(엄지 + 덩어리): 있는 손가락만 움직이고 오류 없이 생성
rig, fingers = build("mitten_thumb_t")
generate("ATTACK")
check(len(keyed_masters(rig)) == len(masters(rig)), f"벙어리장갑: 손가락 마디 컨트롤 {len(masters(rig))}개 키")

# 게임 FBX: 손가락 본이 함께 구워진다 (Unity Humanoid 손가락 뼈 이름)
rig, fingers = build("fingers_straight_t")
action, n = generate("ATTACK")
OUT.mkdir(parents=True, exist_ok=True)
path = OUT / "hand_attack_unity.fbx"
check(bpy.ops.airig.export_fbx(filepath=str(path), naming="UNITY", bake_anim=True) == {"FINISHED"}, "손가락 공격 FBX 내보내기")
strike = 1 + round(n * min(0.8, json.loads(action["airig_motion"])["anticipation"] + 0.15))
bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(path))
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
act = next(a for a in bpy.data.actions if "attack" in a.name)
arm.animation_data.action = act
lo = int(act.frame_range[0])
pb = arm.pose.bones["RightIndexIntermediate"]  # 공격 손 (기본 R)
bpy.context.scene.frame_set(lo)
q0 = pb.matrix_basis.to_quaternion()
bpy.context.scene.frame_set(lo + strike - 1)
bend = q0.rotation_difference(pb.matrix_basis.to_quaternion()).angle
check(bend > 0.5, f"FBX 손가락 마디가 주먹으로 굽음 ({bend * 57.3:.0f}°)")
print("[hand] 완료")
