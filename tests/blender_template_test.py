"""모션 템플릿 통합 테스트: 내장 템플릿(Zombie_Thin)을 체형이 다른 캐릭터에 적용, 손으로 고친 액션 등록 → 같은 리그 재적용
왕복 일치, 버전·히스토리, Auto(체형) 타입 고르기.

실행: scripts/dev_run.sh --background --python tests/blender_template_test.py -- <출력 폴더>
"""

import json
import os
import pathlib
import sys
import tempfile

import bpy

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
import humanoid  # noqa: E402

PKG = f"bl_ext.user_default.{os.environ['AIRIG_ADDON_ID']}"
animate = __import__(f"{PKG}.bridge.animate", fromlist=["x"])
template = __import__(f"{PKG}.bridge.template", fromlist=["x"])
motion_template = __import__(f"{PKG}.core.motion_template", fromlist=["x"])
# 사용자 템플릿은 임시 폴더에 둔다 (실제 설정 폴더를 건드리지 않음)
TPL_DIR = pathlib.Path(tempfile.mkdtemp(prefix="airig_tpl_test_"))
os.environ["AIRIG_TEMPLATE_DIR"] = str(TPL_DIR)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[template] OK  {msg}")


bpy.ops.wm.read_homefile(use_empty=True)
verts, tris, _gt = humanoid.build("realistic_a")
me = bpy.data.meshes.new("hero")
me.from_pydata(verts, [], tris)
obj = bpy.data.objects.new("hero", me)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
mod = obj.modifiers.new("remesh", "REMESH")
mod.mode, mod.voxel_size = "VOXEL", 0.015
bpy.ops.object.modifier_apply(modifier=mod.name)
check(bpy.ops.airig.auto_rig() == {"FINISHED"}, "자동 리깅")
st = bpy.context.scene.airig
rig = bpy.data.objects[st.rig_name]
scene = bpy.context.scene
DEF = [b.name for b in rig.data.bones if b.use_deform]


def world(name, frame):
    scene.frame_set(frame)
    return (rig.matrix_world @ rig.pose.bones[name].head).copy()


def pose_at(frame):
    scene.frame_set(frame)
    return [(rig.matrix_world @ rig.pose.bones[n].matrix).copy() for n in DEF]


def max_diff(a, b):
    return max(abs(x[i][j] - y[i][j]) for x, y in zip(a, b) for i in range(3) for j in range(4))


# 1) 내장 템플릿: 체형이 다른 캐릭터(사실적 비율)에 적용
builtin = motion_template.load(None)
names = sorted(n for t, n in builtin if t == "Zombie_Thin")
check({"walk", "Run", "Idle", "Attack_R", "Attack_L", "Attack_C"} <= set(names), f"내장 Zombie_Thin 템플릿 {names}")
arm_len = animate.measure(rig)[1]
for name in names:
    st.anim_template_type, st.anim_template_motion = "Zombie_Thin", name
    check(bpy.ops.airig.apply_template() == {"FINISHED"}, f"{name}: 적용")
    action = bpy.data.actions[st.anim_action]
    data = builtin[("Zombie_Thin", name)]
    n = data["frames"]
    check(int(action.frame_end - action.frame_start) == n and action.use_cyclic == data["loop"], f"{name}: 길이 {n}·루프 {data['loop']}")
    curves = animate.fcurves(rig)
    check(len(curves) >= len(data["channels"]), f"{name}: 커브 {len(curves)}개")
    reach = max(animate.leg_reach(bpy.context, rig, range(1, n + 2)).values())
    check(reach <= animate.REACH_LIMIT + 0.002, f"{name}: 발이 다리 길이 안 (최대 {reach:.3f})")
    stretch = max(((world(f"hand_ik.{s}", f) - world(f"ORG-upper_arm.{s}", f)).length / arm_len)
                  for s in "LR" for f in range(1, n + 2, 3))
    check(stretch < 1.15, f"{name}: 손이 팔 길이 안 (어깨→손 최대 {stretch:.2f}×)")
    if data["loop"]:
        # 손으로 고친 원본 그대로 옮긴다 (Zombie_Thin Run 원본은 이음새에서 몸통 4mm·머리 0.6° 어긋나 있다)
        seam = max_diff(pose_at(1), pose_at(1 + n))
        check(seam < 0.03, f"{name}: 루프 이음새 ({seam:.4f})")
    moved = max((world("hand_ik.R", f) - world("hand_ik.R", 1)).length for f in range(1, n + 2, 3))
    check(moved > 0.01, f"{name}: 손이 움직임 ({100 * moved:.0f}cm)")

# 2) 손으로 고친 액션 등록 → 같은 리그 재적용 왕복 (키 타이밍·추가 커브·선형 키·정렬 핸들·부호 뒤집힌 사원수 보존)
st.anim_motion, st.anim_style = "WALK", "ZOMBIE"
check(bpy.ops.airig.generate_motion() == {"FINISHED"}, "걷기 생성")
src = bpy.data.actions[st.anim_action]
fcs = {(fc.data_path, fc.array_index): fc for fc in animate.fcurves(rig)}
fc = fcs[('pose.bones["hand_ik.L"].location', 2)]
mid = round(0.5 * (fc.keyframe_points[1].co.x + fc.keyframe_points[2].co.x))
fc.keyframe_points.insert(mid, fc.evaluate(mid) + 0.08)  # 한 성분에만, 그 커브의 주기 안에 키 추가
fc.keyframe_points[3].handle_left_type = fc.keyframe_points[3].handle_right_type = "ALIGNED"
fc.keyframe_points[3].handle_right.y += 0.03
q = fcs[('pose.bones["head"].rotation_quaternion', 0)]
for i in range(4):  # 머리 사원수 키 하나의 부호를 뒤집는다 (보간 경로가 바뀐다 — 사용자가 본 그대로 옮겨야 한다)
    kp = fcs[('pose.bones["head"].rotation_quaternion', i)].keyframe_points[1]
    kp.co.y, kp.handle_left.y, kp.handle_right.y = -kp.co.y, -kp.handle_left.y, -kp.handle_right.y
jaw = rig.pose.bones.get("jaw") or rig.pose.bones["neck"]
jaw.rotation_mode = "QUATERNION"
for f, ang in ((1, 0.0), (10, 0.3), (20, 0.0)):
    jaw.rotation_quaternion = (1.0, ang, 0.0, 0.0)
    jaw.keyframe_insert("rotation_quaternion", frame=f)
for c in animate.fcurves(rig):
    c.update()
rig["airig_test_prop"] = 0.0  # 오브젝트 사용자 속성 키 (경로 ["airig_test_prop"])
for f, v in ((1, 0.0), (15, 1.0)):
    rig["airig_test_prop"] = v
    rig.keyframe_insert('["airig_test_prop"]', frame=f)
for c in animate.fcurves(rig):
    c.update()
n = int(src.frame_end - src.frame_start)
src_name = src.name
before = [pose_at(f) for f in range(1, n + 2, 2)]
# 등록은 리그 상태를 바꾸지 않는다: 키 없는 포즈 수정·IK 부모 전환·활성 액션·현재 프레임
scene.frame_set(7)
toe = rig.pose.bones["toe_ik.L"]
toe.rotation_mode = "QUATERNION"
toe.rotation_quaternion = (0.9487, 0.3162, 0.0, 0.0)  # 단위 사원수
rig.pose.bones["upper_arm_parent.R"]["IK_parent"] = 0
state_before = (toe.rotation_quaternion.copy(), rig.animation_data.action, rig.animation_data.use_nla)
st.anim_template_new_type, st.anim_template_name = "Hero", "walk_edit"
check(bpy.ops.airig.register_template(all_actions=False) == {"FINISHED"}, "활성 액션 등록")
check(abs(toe.rotation_quaternion.dot(state_before[0]) - 1.0) < 1e-4, "등록 후 키 없는 포즈 수정 유지")
check(rig.pose.bones["upper_arm_parent.R"]["IK_parent"] == 0, "등록 후 IK 부모 전환 값 유지")
check(rig.animation_data.action == state_before[1] and scene.frame_current == 7, "등록 후 활성 액션·프레임 유지")
rig.pose.bones["upper_arm_parent.R"]["IK_parent"] = 1
toe.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
saved = motion_template.load(str(TPL_DIR))[("Hero", "walk_edit")]
check(saved["version"] == 1 and saved["loop"] and saved["frames"] == n, f"등록 v1 ({saved['frames']}프레임)")
st.anim_template_type, st.anim_template_motion = "Hero", "walk_edit"
check(bpy.ops.airig.apply_template() == {"FINISHED"}, "등록본 재적용")
after = [pose_at(f) for f in range(1, n + 2, 2)]
diff = max(max_diff(a, b) for a, b in zip(before, after))
check(diff < 2e-3, f"같은 리그 왕복 일치 (최대 차이 {diff:.5f})")
applied = bpy.data.actions[st.anim_action]
frames = [kp.co.x for fc in animate.fcurves(rig) for kp in fc.keyframe_points]
check(all(abs(x - round(x)) < 1e-4 for x in frames if abs(x - round(x)) < 0.01), "정수 프레임 키는 정수 프레임에 놓인다")
check(any(fc.data_path == '["airig_test_prop"]' for fc in animate.fcurves(rig)), "오브젝트 사용자 속성 키도 옮겨짐")
# 적용한 액션을 손으로 고친 뒤 다시 적용하면 고친 액션은 '_edited' 로 남는다
applied_name = applied.name
fc0 = animate.fcurves(rig)[0]
fc0.keyframe_points[0].co.y += 0.05
fc0.update()
check(bpy.ops.airig.apply_template() == {"FINISHED"}, "다시 적용")
check(bpy.data.actions.get(applied_name + "_edited") is not None, "손으로 고친 이전 적용본 보존")
check(bpy.ops.airig.apply_template() == {"FINISHED"}, "고치지 않고 다시 적용")
check(bpy.data.actions.get(applied_name + "_edited.001") is None, "고치지 않은 적용본은 그냥 교체")

# 3) 다시 등록하면 버전이 오르고 이전 버전은 _history 에 남는다
rig.animation_data.action = bpy.data.actions[src_name]
check(bpy.ops.airig.register_template(all_actions=False) == {"FINISHED"}, "다시 등록")
saved = motion_template.load(str(TPL_DIR))[("Hero", "walk_edit")]
hist = motion_template.history(str(TPL_DIR), "Hero", "walk_edit")
check(saved["version"] == 2 and [p.name for p in hist] == ["walk_edit.v1.json"], f"v2 + 히스토리 {[p.name for p in hist]}")

# 4) Auto 타입: 체형이 가장 비슷한 타입 (등록한 Hero 는 같은 캐릭터라 가장 가깝다)
body = template.body_info(rig, obj, "-Y")
all_tpl = motion_template.load(str(TPL_DIR))
check(motion_template.nearest_type(all_tpl, body) == "Hero", "Auto: 같은 체형 타입을 고름")
st.anim_template_type, st.anim_template_motion = "AUTO", "walk"
check(bpy.ops.airig.apply_template() == {"FINISHED"}, "Auto 타입으로 walk 적용 (walk 가 있는 타입)")
check("Zombie_Thin" in st.anim_summary, f"Auto 결과: {st.anim_summary}")

# 5) NLA 의 액션까지 한 번에 등록
track = rig.animation_data.nla_tracks.new()
track.strips.new("x", 1, bpy.data.actions[src_name])
st.anim_template_new_type = "HeroAll"
check(bpy.ops.airig.register_template(all_actions=True) == {"FINISHED"}, "Register All")
got = sorted(nm for t, nm in motion_template.load(str(TPL_DIR)) if t == "HeroAll")
check(len(got) == 2, f"활성 + NLA 액션 등록 {got}")
print(json.dumps({"ok": True, "templates": names}))
