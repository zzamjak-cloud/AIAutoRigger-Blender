import bpy


class AIRIG_PG_proposal(bpy.types.PropertyGroup):
    """Rig Review Agent 보정안 (사용자 승인 대기)"""

    kind: bpy.props.StringProperty(name="Kind")
    target: bpy.props.StringProperty(name="Target")
    delta: bpy.props.FloatVectorProperty(name="Delta", size=3)
    iterations: bpy.props.IntProperty(name="Iterations", min=0)
    reason: bpy.props.StringProperty(name="Reason")
    enabled: bpy.props.BoolProperty(name="Apply", default=True)


class AIRIG_PG_state(bpy.types.PropertyGroup):
    """씬 단위 리깅 파이프라인 상태"""

    analyzed_object: bpy.props.StringProperty(name="Analyzed Object")
    vertex_count: bpy.props.IntProperty(name="Vertex Count", min=0)
    dimensions: bpy.props.FloatVectorProperty(name="Dimensions", size=3, subtype="XYZ")
    up_axis: bpy.props.StringProperty(name="Up Axis")
    symmetry_x: bpy.props.FloatProperty(name="Symmetry X", min=0.0, max=1.0)
    body_type: bpy.props.EnumProperty(
        name="Body Type",
        items=(
            ("AUTO", "Auto", "다리 수로 자동 판별"),
            ("BIPED", "Biped", "2족 (인간형)"),
            ("QUADRUPED", "Quadruped", "4족"),
        ),
        default="AUTO",
    )
    detected_type: bpy.props.StringProperty(name="Detected Type")
    use_fingers: bpy.props.BoolProperty(name="Fingers", description="2족 손가락을 감지해 Rigify 손가락 리그를 만든다", default=True)
    finger_count: bpy.props.IntProperty(name="Finger Count", min=0)
    target_mesh: bpy.props.StringProperty(name="Target Mesh")
    metarig_name: bpy.props.StringProperty(name="Metarig")
    rig_name: bpy.props.StringProperty(name="Control Rig")
    unweighted_vertices: bpy.props.IntProperty(name="Unweighted Vertices", min=0)
    warnings: bpy.props.StringProperty(name="Warnings")
    ai_joints_used: bpy.props.IntProperty(name="AI Joints Used", min=0)
    ai_backend_used: bpy.props.StringProperty(name="AI Backend Used")
    proposals: bpy.props.CollectionProperty(type=AIRIG_PG_proposal)
    review_summary: bpy.props.StringProperty(name="Review Summary")


classes = (AIRIG_PG_proposal, AIRIG_PG_state)


def register_props():
    bpy.types.Scene.airig = bpy.props.PointerProperty(type=AIRIG_PG_state)


def unregister_props():
    del bpy.types.Scene.airig
