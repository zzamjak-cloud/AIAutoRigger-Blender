"""AI Auto Rig 통합 테스트 (Claude 호출은 모의 클라이언트로 대체, 네트워크·비용 없음).

실행: scripts/dev_run.sh --background --python tests/blender_ai_test.py
"""

import importlib
import json
import os
import pathlib
import sys
import types
from math import dist

import bpy

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
import humanoid  # noqa: E402
import quadruped  # noqa: E402

PKG = f"bl_ext.user_default.{os.environ['AIRIG_ADDON_ID']}"
claude_client = importlib.import_module(f"{PKG}.agents.claude_client")
landmark_schema = importlib.import_module(f"{PKG}.agents.landmark_schema")
views_mod = importlib.import_module(f"{PKG}.bridge.views")

METARIG_JOINTS = {
    "BIPED": {"thigh": "hip", "shin": "knee", "foot": "ankle", "upper_arm": "shoulder", "forearm": "elbow", "hand": "wrist"},
    "QUADRUPED": {"thigh": "r_hip", "shin": "r_knee", "foot": "r_hock",
                  "front_thigh": "f_shoulder", "front_shin": "f_elbow", "front_foot": "f_wrist"},
}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[ai] OK  {msg}")


class _StubErr(Exception):
    def __init__(self, *a, **k):
        super().__init__(*a)
        self.message = str(a[0]) if a else ""
        self.status_code = 0


STUB_SDK = types.SimpleNamespace(**{n: type(n, (_StubErr,), {}) for n in (
    "AuthenticationError", "PermissionDeniedError", "NotFoundError", "RateLimitError",
    "BadRequestError", "APIStatusError", "APIConnectionError")})


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


class FakeClient:
    """요청 파라미터를 기록하고 정답 관절을 투영한 응답을 돌려준다."""

    def __init__(self, truth, specs, kind, conf=1.0, stop_reason="end_turn"):
        self.calls = []
        payload = {"body_type": kind, "notes": ""}
        for spec in specs:
            entries = {}
            for name in landmark_schema.joint_names(kind):
                p = truth.get(name)
                if p is None:
                    entries[name] = {"u": 0.5, "v": 0.5, "visible": False, "confidence": 0.0}
                else:
                    u, v = spec.project(p)
                    entries[name] = {"u": u, "v": v, "visible": True, "confidence": conf}
            payload[spec.name] = entries
        text = types.SimpleNamespace(type="text", text=json.dumps(payload))
        self.message = types.SimpleNamespace(stop_reason=stop_reason, content=[text], _request_id="req_test")
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=self._stream))

    def _stream(self, **params):
        self.calls.append(params)
        return FakeStream(self.message)


def make_mesh(module, variant):
    verts, tris, gt = module.build(variant)
    mesh = bpy.data.meshes.new(variant)
    mesh.from_pydata(verts, [], tris)
    obj = bpy.data.objects.new(variant, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    mod = obj.modifiers.new("remesh", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = 0.015
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return obj, gt


def metarig_error(kind, gt, size):
    state = bpy.context.scene.airig
    mr = bpy.data.objects[state.metarig_name]
    errs = []
    for bone in mr.data.bones:
        base, _, side = bone.name.rpartition(".")
        key = f"{METARIG_JOINTS[kind].get(base)}_{side}"
        if side in ("L", "R") and base in METARIG_JOINTS[kind] and key in gt:
            errs.append(dist(mr.matrix_world @ bone.head_local, gt[key]) / size)
    return sum(errs) / len(errs)


def run(module, variant, kind):
    bpy.ops.wm.read_homefile(use_empty=True)
    obj, gt = make_mesh(module, variant)
    size = max(obj.dimensions)

    # 기준선: 휴리스틱만
    check(bpy.ops.airig.auto_rig() == {"FINISHED"}, f"{variant}: 휴리스틱 Auto Rig")
    base_err = metarig_error(kind, gt, size)

    bpy.context.view_layer.objects.active = obj
    specs, _ = views_mod.view_specs(obj, "-Y")
    fake = FakeClient(gt, specs, kind)
    claude_client.make_client = lambda settings: fake
    claude_client._sdk = lambda: STUB_SDK
    check(bpy.ops.airig.ai_auto_rig() == {"FINISHED"}, f"{variant}: AI Auto Rig (모의 Claude)")
    state = bpy.context.scene.airig
    params = fake.calls[0]
    images = [c for c in params["messages"][0]["content"] if c["type"] == "image"]
    check(len(images) == 2 and all(len(i["source"]["data"]) > 1000 for i in images), f"{variant}: 정면·측면 렌더 2장 전송")
    if os.environ.get("AIRIG_RENDER_DIR"):
        import base64
        for spec, img in zip(specs, images):
            pathlib.Path(os.environ["AIRIG_RENDER_DIR"], f"ai_{variant}_{spec.name}.png").write_bytes(
                base64.standard_b64decode(img["source"]["data"]))
    check(params["model"] == "claude-opus-5-5" and params["thinking"] == {"type": "adaptive"}, f"{variant}: 모델·적응형 사고")
    check(params["output_config"]["format"]["type"] == "json_schema", f"{variant}: 구조화 출력 스키마")
    check(params["fallbacks"] == "default" and claude_client.FALLBACK_BETA in params["betas"], f"{variant}: 서버 측 fallback")
    check(state.ai_joints_used >= 8, f"{variant}: AI 반영 관절 {state.ai_joints_used}개")
    ai_err = metarig_error(kind, gt, size)
    check(ai_err < base_err, f"{variant}: AI 병합으로 오차 감소 {base_err:.4f} → {ai_err:.4f}")
    rig = bpy.data.objects[state.rig_name]
    check(all(pb["IK_FK"] == 0.0 for pb in rig.pose.bones if "IK_FK" in pb), f"{variant}: IK 모드 유지")
    check(not any(s.name.startswith("AIRIG_") for s in bpy.data.scenes), f"{variant}: 임시 렌더 씬 정리")

    # 실패 경로: 거절 응답이면 휴리스틱으로 계속한다
    fake_refusal = FakeClient(gt, specs, kind, stop_reason="refusal")
    claude_client.make_client = lambda settings: fake_refusal
    bpy.context.view_layer.objects.active = obj
    check(bpy.ops.airig.ai_auto_rig() == {"FINISHED"}, f"{variant}: 거절 시 휴리스틱으로 완료")
    check(state.ai_joints_used == 0 and "AI 단계 실패" in state.warnings, f"{variant}: 실패 경고 기록")


run(humanoid, "stylized_t", "BIPED")
run(quadruped, "dog", "QUADRUPED")
print("[ai] ALL PASSED")
