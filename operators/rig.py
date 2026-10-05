import bpy

from ..bridge import mesh_io, rigify_bridge
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

    def __init__(self, kind, joints, facing, size, has_tail, symmetric, warnings):
        self.kind = kind
        self.joints = joints
        self.facing = facing
        self.size = size
        self.has_tail = has_tail
        self.symmetric = symmetric
        self.warnings = list(warnings)


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
    return Estimate(kind, lm.joints, lm.facing, max(analysis.dimensions), False, symmetric, lm.warnings)


def apply_metarig(op, context, mesh_obj, est):
    metarig = rigify_bridge.build_metarig(
        context, est.kind, est.joints, f"{mesh_obj.name}_metarig",
        has_tail=est.has_tail, facing=est.facing, symmetric=est.symmetric,
    )
    state = context.scene.airig
    state.detected_type = est.kind
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
