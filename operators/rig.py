import json

import bpy

from ..bridge import mesh_io, rigify_bridge, weights
from ..core import face as face_core
from ..core import fingers as finger_core
from ..core.biped_landmarks import estimate_biped
from ..core.body_type import QUADRUPED, classify
from ..core.mesh_analysis import analyze_points
from ..core.quadruped_landmarks import estimate_quadruped

# 이 값 이상이면 좌우 대칭으로 보고 L/R 관절을 평균한다
SYMMETRY_THRESHOLD = 0.85


def _mesh_poll(context):
    obj = context.active_object
    return obj is not None and obj.type == "MESH" and context.mode == "OBJECT"


class Estimate:
    """휴리스틱 관절 추정 결과 (AI 단계 입력으로도 쓰인다)."""

    def __init__(self, kind, joints, facing, size, has_tail, symmetric, warnings, fingers=None, face=None):
        self.kind = kind
        self.joints = joints
        self.facing = facing
        self.size = size
        self.has_tail = has_tail
        self.symmetric = symmetric
        self.warnings = list(warnings)
        self.fingers = fingers or {}
        self.face = face


def estimate(context, mesh_obj):
    """체형 판별 + 휴리스틱 관절 추정. 입력 조건 위반은 ValueError."""
    verts, points = mesh_io.surface_points(context, mesh_obj)
    analysis = analyze_points(verts)
    kind = context.scene.airig.body_type
    if kind == "AUTO":
        kind, _legs = classify(points)
    # 4족은 몸길이(Y)가 높이보다 긴 것이 정상이므로 2족에만 Y-up 판정을 적용한다
    if kind != QUADRUPED and analysis.up_axis != "Z":
        raise ValueError("Y-up 메시입니다. 회전을 적용(Ctrl+A)해 Z-up 으로 맞춘 뒤 다시 실행하세요.")
    symmetric = analysis.symmetry_x >= SYMMETRY_THRESHOLD
    if kind == QUADRUPED:
        lm = estimate_quadruped(points, symmetric=symmetric)
        return Estimate(kind, lm.joints, lm.facing, lm.size, lm.has_tail, symmetric, lm.warnings)
    lm = estimate_biped(points, symmetric=symmetric)
    est = Estimate(kind, lm.joints, lm.facing, max(analysis.dimensions), False, symmetric, lm.warnings)
    if context.scene.airig.use_fingers:
        est.fingers = detect_hand_fingers(context, mesh_obj, est)
    if context.scene.airig.use_face:
        est.face = detect_face(mesh_obj, head_points(context, mesh_obj, est), est)
    return est


def head_points(context, mesh_obj, est, count=60000):
    """목 위 삼각형만 촘촘히 샘플링한다 (전신 샘플로는 얼굴 정면 띠의 밀도가 부족하다)."""
    from ..core.sampling import sample_surface

    verts, tris = mesh_io.world_geometry(context, mesh_obj)
    z0 = est.joints["neck_base"][2]
    head_tris = [t for t in tris if max(verts[i][2] for i in t) > z0]
    return sample_surface(verts, head_tris, count, seed=1) if head_tris else []


def detect_face(mesh_obj, points, est):
    """턱(입 오목이 보일 때)과 눈(눈동자가 별도 메시 조각일 때)."""
    j = est.joints
    cx = j["head_base"][0]
    jaw, why = face_core.detect_jaw(points, j["neck_base"], j["head_top"], cx, est.facing)
    if jaw is None:
        est.warnings.append(why)
    head = [p for p in points if p[2] > j["head_base"][2]]
    xs = [p[0] for p in head] or [cx]
    head_w = max(xs) - min(xs)
    center = (cx, sum(p[1] for p in head) / max(1, len(head)), 0.5 * (j["head_base"][2] + j["head_top"][2]))
    parts = mesh_io.islands(mesh_obj)
    eyes = []
    if len(parts) > 1:
        eyes = face_core.pick_eyes([(c, r, i) for i, (_v, c, r) in enumerate(parts)], center, head_w,
                                   j["head_top"][2], jaw.lip_z if jaw else None, est.facing)
    if not eyes:
        est.warnings.append("눈동자가 별도 메시 조각이 아니어서 눈 본을 만들지 않았습니다.")
    return face_core.Face(jaw, eyes)


def detect_hand_fingers(context, mesh_obj, est):
    """양손 손가락 검출. 대칭이면 좌우를 거울 평균한다. 손가락이 보이지 않는 손은 빠진다."""
    front = (0.0, -1.0, 0.0) if est.facing == "-Y" else (0.0, 1.0, 0.0)
    hands = {}
    for side in ("L", "R"):
        wrist, tip = est.joints[f"wrist_{side}"], est.joints[f"hand_tip_{side}"]
        verts, edges = mesh_io.hand_graph(context, mesh_obj, wrist, tip)
        hand = finger_core.detect_fingers(verts, edges, wrist, tip, front=front)
        if hand is not None:
            hands[side] = hand
            est.warnings.extend(hand.warnings)
    if est.symmetric and len(hands) == 2:
        cx = 0.5 * (est.joints["hip_L"][0] + est.joints["hip_R"][0])
        hands["L"], hands["R"] = finger_core.symmetrize(hands["L"], hands["R"], cx)
    elif est.symmetric and len(hands) == 1:
        cx = 0.5 * (est.joints["hip_L"][0] + est.joints["hip_R"][0])
        side, hand = next(iter(hands.items()))
        hands["R" if side == "L" else "L"] = finger_core.mirror(hand, cx)
    if not hands:
        est.warnings.append("손가락을 찾지 못해 손 본까지만 만들었습니다.")
    return hands


def apply_metarig(op, context, mesh_obj, est):
    metarig = rigify_bridge.build_metarig(
        context, est.kind, est.joints, f"{mesh_obj.name}_metarig",
        has_tail=est.has_tail, facing=est.facing, symmetric=est.symmetric, fingers=est.fingers, face=est.face,
    )
    state = context.scene.airig
    state.detected_type = est.kind
    state.finger_count = sum(len(h.fingers) for h in est.fingers.values())
    parts = []
    if est.face and est.face.jaw:
        parts.append("턱")
    if est.face and est.face.eyes:
        parts.append("눈")
    state.face_summary = ("얼굴: " + ", ".join(parts)) if parts else ""
    state.target_mesh = mesh_obj.name
    state.metarig_name = metarig.name
    state.warnings = " / ".join(est.warnings)
    for w in est.warnings:
        op.report({"WARNING"}, w)
    return metarig


def fit_metarig(op, context, mesh_obj):
    return apply_metarig(op, context, mesh_obj, estimate(context, mesh_obj))


def generate_and_bind(op, context):
    state = context.scene.airig
    mesh_obj = bpy.data.objects.get(state.target_mesh)
    metarig = bpy.data.objects.get(state.metarig_name)
    if mesh_obj is None or metarig is None:
        op.report({"ERROR"}, "먼저 Fit Metarig 를 실행하세요.")
        return None
    rig = rigify_bridge.generate_rig(context, metarig, f"{mesh_obj.name}_rig")
    unweighted = rigify_bridge.bind_mesh(context, mesh_obj, rig)
    face_data = metarig.get("airig_face")
    if face_data:
        weights.apply_face_weights(mesh_obj, face_core.Face.from_dict(json.loads(face_data)), mesh_io.islands(mesh_obj))
        unweighted = weights.count_unweighted(mesh_obj, {b.name for b in rig.data.bones if b.use_deform})
    state.rig_name = rig.name
    state.unweighted_vertices = unweighted
    if unweighted:
        op.report({"WARNING"}, f"웨이트가 없는 정점 {unweighted}개 (메시 비다양체·겹침 확인 필요)")
    return rig


class AIRIG_OT_fit_metarig(bpy.types.Operator):
    """활성 메시 형상에서 관절을 추정해 Rigify 메타리그를 맞춘다 (생성 전 수동 보정 가능)"""

    bl_idname = "airig.fit_metarig"
    bl_label = "Fit Metarig"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _mesh_poll(context)

    def execute(self, context):
        try:
            metarig = fit_metarig(self, context, context.active_object)
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if metarig is None:
            return {"CANCELLED"}
        self.report({"INFO"}, f"메타리그 생성: {metarig.name}")
        return {"FINISHED"}


class AIRIG_OT_generate_rig(bpy.types.Operator):
    """메타리그로 Rigify 컨트롤 리그를 생성하고 메시를 자동 웨이트로 바인딩한다 (팔다리 IK 기본)"""

    bl_idname = "airig.generate_rig"
    bl_label = "Generate Control Rig"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.scene.airig.metarig_name)

    def execute(self, context):
        try:
            rig = generate_and_bind(self, context)
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if rig is None:
            return {"CANCELLED"}
        self.report({"INFO"}, f"컨트롤 리그 생성: {rig.name}")
        return {"FINISHED"}


class AIRIG_OT_auto_rig(bpy.types.Operator):
    """메타리그 피팅부터 Rigify 생성·바인딩까지 한 번에 실행한다"""

    bl_idname = "airig.auto_rig"
    bl_label = "Auto Rig"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _mesh_poll(context)

    def execute(self, context):
        try:
            if fit_metarig(self, context, context.active_object) is None:
                return {"CANCELLED"}
            rig = generate_and_bind(self, context)
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if rig is None:
            return {"CANCELLED"}
        self.report({"INFO"}, f"자동 리깅 완료: {rig.name}")
        return {"FINISHED"}


classes = (AIRIG_OT_fit_metarig, AIRIG_OT_generate_rig, AIRIG_OT_auto_rig)
