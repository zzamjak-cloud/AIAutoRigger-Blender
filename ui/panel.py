import bpy


def _wrap(text, width):
    lines = []
    for para in text.splitlines():
        while len(para) > width:
            lines.append(para[:width])
            para = para[width:]
        if para:
            lines.append(para)
    return lines


class AIRIG_PT_main(bpy.types.Panel):
    bl_label = "AI Auto Rigger"
    bl_idname = "AIRIG_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AI Rig"

    def draw(self, context):
        layout = self.layout
        state = context.scene.airig
        layout.prop(state, "body_type")
        layout.operator("airig.ai_auto_rig", icon="LIGHT_SUN")
        layout.operator("airig.auto_rig", icon="ARMATURE_DATA")
        row = layout.row(align=True)
        row.operator("airig.fit_metarig", icon="BONE_DATA")
        row.operator("airig.generate_rig", icon="POSE_HLT")
        layout.operator("airig.analyze_mesh", icon="VIEWZOOM")

        state = context.scene.airig
        if state.rig_name:
            box = layout.box()
            box.label(text=f"리그: {state.rig_name} ({state.detected_type})")
            box.label(text=f"웨이트 없는 정점: {state.unweighted_vertices}")
            if state.ai_joints_used:
                box.label(text=f"AI 반영 관절: {state.ai_joints_used} ({state.ai_backend_used})")
        if state.rig_name:
            layout.operator("airig.ai_review", icon="VIEWZOOM")
            layout.operator("airig.export_fbx", icon="EXPORT")
        if state.review_summary or state.proposals:
            box = layout.box()
            box.label(text="AI 검토", icon="INFO")
            for line in _wrap(state.review_summary, 48)[:8]:
                box.label(text=line)
            for p in state.proposals:
                row = box.row()
                row.prop(p, "enabled", text="")
                if p.kind == "move_joint":
                    d = p.delta
                    row.label(text=f"{p.target} 이동 ({d[0]:+.3f}, {d[1]:+.3f}, {d[2]:+.3f})")
                else:
                    row.label(text=f"{p.target} 스무딩 ×{p.iterations}")
                row.label(text=p.reason[:40])
            row = box.row(align=True)
            row.operator("airig.apply_proposals", icon="CHECKMARK")
            row.operator("airig.clear_proposals", icon="X")
        if state.warnings:
            layout.label(text=state.warnings, icon="ERROR")
        if not state.analyzed_object:
            return
        box = layout.box()
        box.label(text=f"대상: {state.analyzed_object}")
        box.label(text=f"정점 수: {state.vertex_count}")
        d = state.dimensions
        box.label(text=f"크기: {d[0]:.3f} × {d[1]:.3f} × {d[2]:.3f}")
        box.label(text=f"높이 축: {state.up_axis}")
        box.label(text=f"X 대칭도: {state.symmetry_x:.2f}")


classes = (AIRIG_PT_main,)
