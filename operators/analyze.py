import bpy

from ..core.mesh_analysis import analyze_points


class AIRIG_OT_analyze_mesh(bpy.types.Operator):
    """활성 메시의 경계·높이 축·좌우 대칭도를 분석한다"""

    bl_idname = "airig.analyze_mesh"
    bl_label = "Analyze Mesh"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH"

    def execute(self, context):
        obj = context.active_object
        # 모디파이어 적용 결과 기준으로 분석해야 실제 리깅 대상 형상과 일치한다
        depsgraph = context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        try:
            mw = obj.matrix_world
            points = [tuple(mw @ v.co) for v in mesh.vertices]
        finally:
            eval_obj.to_mesh_clear()

        try:
            result = analyze_points(points)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        state = context.scene.airig
        state.analyzed_object = obj.name
        state.vertex_count = result.vertex_count
        state.dimensions = result.dimensions
        state.up_axis = result.up_axis
        state.symmetry_x = result.symmetry_x
        self.report(
            {"INFO"},
            f"{obj.name}: 정점 {result.vertex_count}, 높이축 {result.up_axis}, 대칭도 {result.symmetry_x:.2f}",
        )
        return {"FINISHED"}


classes = (AIRIG_OT_analyze_mesh,)
