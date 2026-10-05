"""AI Review Rig 통합 테스트 (Claude 는 각본대로 응답하는 모의 클라이언트).

실행: scripts/dev_run.sh --background --python tests/blender_review_test.py
"""

import importlib
import json
import os
import pathlib
import sys
import types

import bpy
from mathutils import Vector

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
import humanoid  # noqa: E402

PKG = f"bl_ext.user_default.{os.environ['AIRIG_ADDON_ID']}"
claude_client = importlib.import_module(f"{PKG}.agents.claude_client")


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[review] OK  {msg}")


claude_client._sdk = lambda: types.SimpleNamespace(**{n: type(n, (Exception,), {}) for n in (
    "AuthenticationError", "PermissionDeniedError", "NotFoundError", "RateLimitError",
    "BadRequestError", "APIStatusError", "APIConnectionError")})


def block(kind, **kw):
    return types.SimpleNamespace(type=kind, **kw)


class Scripted:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=self._stream))

    def _stream(self, **params):
        # 이후 append 로 바뀌지 않도록 호출 시점 메시지 수를 기록한다
        self.calls.append(len(params["messages"]))
        stop, content = self.turns.pop(0)
        msg = types.SimpleNamespace(stop_reason=stop, content=content)
        return _Ctx(msg)


class _Ctx:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


bpy.ops.wm.read_homefile(use_empty=True)
verts, tris, gt = humanoid.build("realistic_t")
mesh = bpy.data.meshes.new("hero")
mesh.from_pydata(verts, [], tris)
obj = bpy.data.objects.new("hero", mesh)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
mod = obj.modifiers.new("remesh", "REMESH")
mod.mode = "VOXEL"
mod.voxel_size = 0.015
bpy.ops.object.modifier_apply(modifier=mod.name)
size = max(obj.dimensions)

check(bpy.ops.airig.auto_rig() == {"FINISHED"}, "자동 리깅")
state = bpy.context.scene.airig
metarig = bpy.data.objects[state.metarig_name]
knee_before = Vector(json.loads(metarig["airig_joints"])["knee_L"])
knee_r_before = Vector(json.loads(metarig["airig_joints"])["knee_R"])

fake = Scripted([
    ("tool_use", [block("tool_use", id="t1", name="render_pose", input={"pose": "squat", "view": "side"})]),
    ("tool_use", [
        block("tool_use", id="t2", name="propose_joint_move",
              input={"joint": "knee_L", "dx": 0.0, "dy": 0.0, "dz": -0.03, "reason": "knee high"}),
        block("tool_use", id="t3", name="propose_weight_smooth",
              input={"bone": "DEF-shin.L", "iterations": 3, "reason": "crease"}),
    ]),
    ("end_turn", [block("text", text="Knee pivot slightly high; shin weights have a crease.")]),
])
claude_client.make_client = lambda settings: fake

check(bpy.ops.airig.ai_review() == {"FINISHED"}, "AI 검토 실행")
check(len(fake.calls) == 3, f"API 3턴 호출 {fake.calls}")
check(len(state.proposals) == 2, f"보정안 2개 저장 ({len(state.proposals)})")
check("Knee" in state.review_summary, "검토 요약 저장")
check(not any(s.name.startswith("AIRIG_") for s in bpy.data.scenes), "임시 렌더 씬 정리")
rig = bpy.data.objects[state.rig_name]
check(all(pb.location.length == 0 for pb in rig.pose.bones), "검토 후 포즈 원복")

check(bpy.ops.airig.apply_proposals() == {"FINISHED"}, "보정안 적용")
metarig = bpy.data.objects[state.metarig_name]
joints = json.loads(metarig["airig_joints"])
moved = Vector(joints["knee_L"]) - knee_before
check(abs(moved.z + 0.03 * size) < 0.02 * size, f"knee_L 하강 {moved.z:.3f}")
check((Vector(joints["knee_R"]) - knee_r_before).z < -0.01 * size, "대칭 캐릭터라 knee_R 도 같이 이동")
arms = sorted(o.name for o in bpy.data.objects if o.type == "ARMATURE")
check(arms == sorted([state.metarig_name, state.rig_name]), f"재생성 후 아마추어는 메타리그·리그 둘뿐 {arms}")
check(len([c for c in bpy.data.collections if c.name.startswith("WGTS_")]) == 1, "위젯 컬렉션 중복 없음")
rig = bpy.data.objects[state.rig_name]
check(obj.parent == rig and any(m.type == "ARMATURE" and m.object == rig for m in obj.modifiers), "재바인딩")
check(all(pb["IK_FK"] == 0.0 for pb in rig.pose.bones if "IK_FK" in pb), "IK 모드 유지")
weights = importlib.import_module(f"{PKG}.bridge.weights")


def roughness(group):
    idx = obj.vertex_groups[group].index
    w = [next((g.weight for g in v.groups if g.group == idx), 0.0) for v in obj.data.vertices]
    return sum((w[e.vertices[0]] - w[e.vertices[1]]) ** 2 for e in obj.data.edges)


r0 = roughness("DEF-forearm.L")
check(weights.smooth_group(obj, "DEF-forearm.L", 3), "스무딩 실행")
r1 = roughness("DEF-forearm.L")
check(r1 < r0 * 0.95, f"스무딩으로 웨이트 거칠기 감소 {r0:.2f} → {r1:.2f}")
check(len(state.proposals) == 0, "적용 후 목록 비움")
print("[review] ALL PASSED")
