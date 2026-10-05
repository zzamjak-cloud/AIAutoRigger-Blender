import bpy
from bpy_extras.io_utils import ExportHelper

from ..bridge import export


class AIRIG_OT_export_fbx(bpy.types.Operator, ExportHelper):
    """DEF 본 계층을 정리한 게임용 FBX 로 내보낸다 (애니메이션은 DEF 본으로 굽는다)"""

    bl_idname = "airig.export_fbx"
    bl_label = "Export Game FBX"
    bl_options = {"REGISTER"}

    filename_ext = ".fbx"
    filter_glob: bpy.props.StringProperty(default="*.fbx", options={"HIDDEN"})
    naming: bpy.props.EnumProperty(
        name="Bone Names",
        items=(
            ("UNITY", "Unity Humanoid", "2족 본을 Unity Humanoid 이름으로 바꾸고 매핑 JSON 을 함께 쓴다"),
            ("RIGIFY", "Rigify DEF", "Rigify DEF 본 이름 유지 (4족·Generic)"),
        ),
        default="UNITY",
    )
    bake_anim: bpy.props.BoolProperty(name="Bake Animation", default=True)

    @classmethod
    def poll(cls, context):
        state = context.scene.airig
        return context.mode == "OBJECT" and bool(state.rig_name) and state.rig_name in bpy.data.objects

    def invoke(self, context, event):
        if context.scene.airig.detected_type == "QUADRUPED":
            self.naming = "RIGIFY"
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        state = context.scene.airig
        rig = bpy.data.objects.get(state.rig_name)
        mesh = bpy.data.objects.get(state.target_mesh)
        metarig = bpy.data.objects.get(state.metarig_name)
        if rig is None or mesh is None or metarig is None:
            self.report({"ERROR"}, "리그 또는 메시를 찾을 수 없습니다.")
            return {"CANCELLED"}
        naming = self.naming if state.detected_type != "QUADRUPED" else "RIGIFY"
        try:
            count = export.export_fbx(context, rig, metarig, mesh, self.filepath, naming, self.bake_anim)
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"FBX 내보내기 완료: 본 {count}개 → {self.filepath}")
        return {"FINISHED"}


classes = (AIRIG_OT_export_fbx,)
