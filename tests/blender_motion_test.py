"""애니메이션 통합 테스트: 루프(걷기·달리기·대기·기쁨) 이음새·발 고정, 단발(점프·공격·피격·사망) 구조, FBX 굽기, AI Motion(가짜 Codex CLI).

실행: scripts/dev_run.sh --background --python tests/blender_motion_test.py -- <출력 폴더>
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
OUT = pathlib.Path(sys.argv[sys.argv.index("--") + 1]) if "--" in sys.argv else ROOT / "dist" / "motion_test"
animate = __import__(f"{PKG}.bridge.animate", fromlist=["x"])
locomotion = __import__(f"{PKG}.core.locomotion", fromlist=["x"])


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[motion] OK  {msg}")


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


def pose_at(frame):
    scene.frame_set(frame)
    return {n: (rig.matrix_world @ rig.pose.bones[n].matrix).copy() for n in DEF}


def max_diff(a, b, skip_root=False):
    out = 0.0
    for n in a:
        da = a[n] - b[n]
        out = max(out, max(abs(da[i][j]) for i in range(3 if skip_root else 4) for j in range(4 if not skip_root else 3)))
    return out


def world(name, frame):
    scene.frame_set(frame)
    return (rig.matrix_world @ rig.pose.bones[name].head).copy()


def mesh_min_z(frame):
    scene.frame_set(frame)
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    m = ev.to_mesh()
    z = min((obj.matrix_world @ v.co).z for v in m.vertices)
    ev.to_mesh_clear()
    return z


# 발 접지 판정은 발 IK 컨트롤 기준 (발 굴림 중에는 발목·발끝이 축을 바꿔 가며 들리므로 DEF 본은 기준이 아니다)
rest_foot_z = (rig.matrix_world @ rig.data.bones["foot_ik.L"].head_local).z
rest_spine_z = world("DEF-spine", 1).z


def airborne(n):
    """두 발이 모두 들린 프레임 목록."""
    return [f for f in range(1, n + 1)
            if world("foot_ik.L", f).z > rest_foot_z + 0.005 and world("foot_ik.R", f).z > rest_foot_z + 0.005]


for motion in locomotion.MOTIONS:
    for style in ("NORMAL", "ZOMBIE"):
        st.anim_motion, st.anim_style, st.anim_root_motion = motion, style, False
        check(bpy.ops.airig.generate_motion() == {"FINISHED"}, f"{motion}/{style}: 생성")
        action = bpy.data.actions[st.anim_action]
        n = int(action.frame_end - action.frame_start)
        loop = locomotion.is_loop(motion)
        curves = animate.fcurves(rig)
        points = [kp for fc in curves for kp in fc.keyframe_points]
        per_curve = max(len(fc.keyframe_points) for fc in curves)
        check(per_curve <= 9, f"{motion}/{style}: 커브당 키 {per_curve}개 (매 프레임 {n}개 대비)")
        check(all(kp.handle_left_type == "AUTO_CLAMPED" for kp in points), f"{motion}/{style}: Auto-Clamped 베지어 핸들")
        lowest = min(mesh_min_z(f) for f in range(1, n + 2, max(1, n // 8)))
        # 쓰러지는 동안은 IK 무릎이 잠깐 바닥에 스치는 것을 허용한다
        limit = -0.05 if motion == "DEATH" else -0.03
        check(lowest > limit, f"{motion}/{style}: 메시가 바닥을 뚫지 않음 (최저 {lowest:.3f}m)")
        if loop:
            check(all(any(m.type == "CYCLES" for m in fc.modifiers) for fc in curves), f"{motion}/{style}: 모든 커브에 Cycles")
            check(action.use_cyclic and scene.frame_end == n, f"{motion}/{style}: 루프 액션·재생 범위 1..{n}")
            if motion in ("WALK", "RUN"):
                check(any(kp.interpolation == "LINEAR" for kp in points), f"{motion}/{style}: 발 딛는 구간 선형")
            a, b = pose_at(1), pose_at(1 + n)
            check(max_diff(a, b) < 1e-4, f"{motion}/{style}: 루프 이음새 (1 == {1 + n}) {max_diff(a, b):.6f}")
            c, d = pose_at(5), pose_at(5 + 2 * n)
            check(max_diff(c, d) < 1e-4, f"{motion}/{style}: 두 주기 뒤에도 반복")
        else:
            check(not any(fc.modifiers for fc in curves), f"{motion}/{style}: 단발 동작은 Cycles 없음")
            check(not action.use_cyclic and scene.frame_end == n + 1, f"{motion}/{style}: 단발 액션·재생 범위 1..{n + 1}")
            a, b = pose_at(1 + n), pose_at(1 + 2 * n)
            check(max_diff(a, b) < 1e-4, f"{motion}/{style}: 끝 자세 유지 ({1 + n} == {1 + 2 * n})")
        if motion == "IDLE":
            moved = max((world("DEF-toe.L", f) - world("DEF-toe.L", 1)).length for f in range(1, n, 6))
            check(moved < 1e-4, f"IDLE/{style}: 발 고정")
        if motion == "RUN" and style == "NORMAL":
            air = airborne(n)
            check(0 < len(air) < n // 2, f"RUN: 체공 프레임 {len(air)}/{n}개")
        if motion == "HAPPY" and style == "NORMAL":
            air = airborne(n)
            check(0 < len(air) < n // 2, f"HAPPY: 깡충 체공 프레임 {len(air)}/{n}개")
            hand = min(world("hand_ik.L", f).z for f in range(1, n + 1))
            check(hand > rest_spine_z + 0.2, f"HAPPY: 손이 계속 들려 있음 (최저 {hand:.2f}m)")
        if motion == "JUMP":
            air = airborne(n)
            check(0 < len(air) < n // 2, f"JUMP/{style}: 체공 프레임 {len(air)}/{n}개")
            apex = max(world("DEF-spine", f).z for f in range(1, n + 2))
            check(apex > rest_spine_z + 0.05, f"JUMP/{style}: 최고점 {100 * (apex - rest_spine_z):.0f}cm 상승")
            check(abs(world("DEF-spine", 1 + n).z - rest_spine_z) < 1e-3, f"JUMP/{style}: 착지 후 레스트 높이 복귀")
        if motion == "ATTACK":
            side = json.loads(action["airig_motion"])["attack_side"]
            h0 = world(f"hand_ik.{side}", 1)
            reach = max((world(f"hand_ik.{side}", f) - h0).length for f in range(1, n + 2))
            check(reach > 0.25, f"ATTACK/{style}: {side} 손 이동 {100 * reach:.0f}cm")
            check((world(f"hand_ik.{side}", 1 + n) - h0).length < 1e-3, f"ATTACK/{style}: 손이 제자리로 복귀")
        if motion == "HIT":
            pushed = max((world("DEF-spine", f) - world("DEF-spine", 1)).length for f in range(1, n + 2))
            check(pushed > 0.03, f"HIT/{style}: 몸통 밀림 {100 * pushed:.0f}cm")
        if motion == "DEATH":
            end = world("DEF-spine", 1 + n).z
            check(end < 0.45 * rest_spine_z, f"DEATH/{style}: 골반이 바닥 근처 ({100 * end:.0f}cm, 서 있을 때 {100 * rest_spine_z:.0f}cm)")
            head_end = world("head", 1 + n).z
            check(head_end < 0.6 * rest_spine_z, f"DEATH/{style}: 머리도 누움 ({100 * head_end:.0f}cm)")

# 전진 점프: 도약 전에는 제자리, 착지 후 한 번만 전진하고 멈춘다
st.anim_motion, st.anim_style, st.anim_root_motion = "JUMP", "NORMAL", True
check(bpy.ops.airig.generate_motion() == {"FINISHED"}, "전진 점프 생성")
jp = json.loads(bpy.data.actions[st.anim_action]["airig_motion"])
jn = jp["cycle_frames"]
# 몸통은 웅크리며 앞으로 숙여지므로 전진 여부는 루트 본으로 본다
check((world("root", 1 + round(0.2 * jn)) - world("root", 1)).length < 1e-3, "전진 점프: 웅크릴 때는 제자리")
jadv = (world("root", 1 + jn) - world("root", 1)).length
check(jadv > 0.3, f"전진 점프: 착지 후 {jadv:.2f}m 전진")
check(abs((world("root", 1 + 2 * jn) - world("root", 1)).length - jadv) < 1e-3, "전진 점프: 끝난 뒤 더 가지 않음")

# 전진 걷기: 딛는 동안 발이 월드에서 미끄러지지 않는다
st.anim_motion, st.anim_style, st.anim_root_motion = "WALK", "NORMAL", True
check(bpy.ops.airig.generate_motion() == {"FINISHED"}, "전진 걷기 생성")
params = json.loads(bpy.data.actions[st.anim_action]["airig_motion"])
n = params["cycle_frames"]
stance = [world("foot_ik.L", f) for f in range(1, int(1 + 0.55 * n))]
slide = max((p - stance[0]).length for p in stance)
check(slide < 0.003, f"전진 걷기: 딛는 발 미끄러짐 {slide * 1000:.1f}mm")
adv = (world("DEF-spine", 1 + n) - world("DEF-spine", 1)).length
check(adv > 0.3, f"전진 걷기: 한 주기 전진 {adv:.2f}m")
check(abs((world("DEF-spine", 1 + 2 * n) - world("DEF-spine", 1 + n)).length - adv) < 1e-3, "전진이 주기마다 이어짐")

# 절뚝이는 좀비 + 전진: 끄는 다리(R)도 딛는 동안 미끄러지지 않는다
st.anim_motion, st.anim_style, st.anim_root_motion = "WALK", "ZOMBIE", True
check(bpy.ops.airig.generate_motion() == {"FINISHED"}, "좀비 전진 걷기 생성")
zp = json.loads(bpy.data.actions[st.anim_action]["airig_motion"])
zn, zd = zp["cycle_frames"], zp["duty"]
for side, start in (("L", 1), ("R", 1 + zn // 2)):
    seg = [world(f"foot_ik.{side}", f) for f in range(start + 1, int(start + 0.9 * zd * zn))]
    sl = max((q - seg[0]).length for q in seg)
    check(sl < 0.003, f"좀비 전진: {side} 발 미끄러짐 {sl * 1000:.1f}mm")

# FBX 굽기: 액션 구간만큼 키가 들어가고 움직임이 담긴다
OUT.mkdir(parents=True, exist_ok=True)
st.anim_root_motion = False
bpy.ops.airig.generate_motion()
n = int(bpy.data.actions[st.anim_action].frame_end - 1)
bpy.context.view_layer.objects.active = obj
path = OUT / "walk_unity.fbx"
check(bpy.ops.airig.export_fbx(filepath=str(path), naming="UNITY", bake_anim=True) == {"FINISHED"}, "걷기 FBX 내보내기")
check(scene.frame_start == 1 and scene.frame_end == n, "내보낸 뒤 씬 프레임 범위 복원")
check(len([a for a in bpy.data.actions if a.name.startswith(f"{rig.name}_walk_normal")]) == 1, "다시 만들어도 액션이 하나로 유지")

# AI Motion 은 현재 씬을 다시 쓰므로 내보낸 FBX 검사는 별도 파일에서 한다
saved = OUT / "motion_scene.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(saved), copy=True)
bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(path))
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
fbx_action = arm.animation_data.action
lo, hi = fbx_action.frame_range
check(abs((hi - lo) - n) <= 1, f"FBX 애니메이션 길이 {hi - lo:.0f}프레임 (주기 {n})")
bpy.context.scene.frame_set(int(lo))
a0 = (arm.matrix_world @ arm.pose.bones["LeftFoot"].head).copy()
bpy.context.scene.frame_set(int(lo + n // 2))
check((arm.matrix_world @ arm.pose.bones["LeftFoot"].head - a0).length > 0.1, "FBX 에 걸음 동작이 구워짐")
bpy.ops.wm.open_mainfile(filepath=str(saved))
st = bpy.context.scene.airig
scene = bpy.context.scene
rig = bpy.data.objects[st.rig_name]

# AI Motion: 가짜 Codex CLI 가 파라미터 → 검토(완료) 순서로 응답
tmp = pathlib.Path(tempfile.mkdtemp(prefix="airig_motion_test_"))
os.environ["AIRIG_FAKE_RESPONSES"] = str(tmp / "responses.json")
os.environ["AIRIG_FAKE_LOG"] = str(tmp / "log.jsonl")
prefs = bpy.context.preferences.addons[PKG].preferences
prefs.backend = "CODEX"
prefs.codex_path = str(ROOT / "tests" / "fixtures" / ("fake_ai_cli.cmd" if sys.platform == "win32" else "fake_ai_cli.py"))
first = locomotion.preset("WALK", "ZOMBIE").to_dict()
first["cycle_frames"] = 40
second = dict(first, arm_forward=0.8)
(tmp / "responses.json").write_text(json.dumps([
    {"params": first, "done": False, "summary": "slow limping zombie walk"},
    {"params": second, "done": False, "summary": "raised the arms"},
]))
(tmp / "log.jsonl").write_text("")
st.anim_prompt = "좀비가 다리를 절며 걷는 루프"
# GPU 가 없는 CI(AIRIG_NO_RENDER=1)에서는 프레임 렌더가 필요한 검토 라운드를 건너뛴다
NO_RENDER = os.environ.get("AIRIG_NO_RENDER") == "1"
st.anim_review_rounds = 0 if NO_RENDER else 1
check(bpy.ops.airig.ai_motion() == {"FINISHED"}, "AI Motion 실행")
calls = [json.loads(line) for line in (tmp / "log.jsonl").read_text().splitlines()]
if NO_RENDER:
    check(len(calls) == 1 and "좀비가 다리를 절며 걷는 루프" in calls[0]["prompt"], "AI 설계 호출 (렌더 없는 환경)")
    applied = json.loads(bpy.data.actions[st.anim_action]["airig_motion"])
    check(applied["cycle_frames"] == 40, "AI 파라미터 반영")
    print("[motion] ALL PASSED (검토 렌더 생략)")
    raise SystemExit(0)
check(len(calls) == 2, f"AI 호출 2회 (설계 + 검토) {len(calls)}")
check("좀비가 다리를 절며 걷는 루프" in calls[0]["prompt"] and calls[0]["images"] == [], "1회차: 프롬프트만 전달")
check("Measured from the generated loop" in calls[1]["prompt"] and "cm" in calls[1]["prompt"], "2회차: 실측값 전달")
check(len(calls[1]["images"]) == 6 and calls[1]["images"][0].startswith("side_t000"), f"2회차: 프레임 렌더 6장 {calls[1]['images']}")
action = bpy.data.actions[st.anim_action]
applied = json.loads(action["airig_motion"])
check(action.name.endswith("_ai") or "_ai" in action.name, f"AI 액션 이름 {action.name}")
check(applied["cycle_frames"] == 40 and abs(applied["arm_forward"] - 0.8) < 1e-6, "검토 보정 파라미터 반영")
check("raised the arms" in st.anim_summary, "요약 저장")
print("[motion] ALL PASSED")
