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
    use_face: bpy.props.BoolProperty(name="Jaw / Eyes", description="2족 턱(입 오목이 보일 때)·눈(눈동자가 별도 조각일 때) 본을 만든다", default=True)
    face_summary: bpy.props.StringProperty(name="Face")
    target_mesh: bpy.props.StringProperty(name="Target Mesh")
    metarig_name: bpy.props.StringProperty(name="Metarig")
    rig_name: bpy.props.StringProperty(name="Control Rig")
    unweighted_vertices: bpy.props.IntProperty(name="Unweighted Vertices", min=0)
    warnings: bpy.props.StringProperty(name="Warnings")
    ai_joints_used: bpy.props.IntProperty(name="AI Joints Used", min=0)
    ai_backend_used: bpy.props.StringProperty(name="AI Backend Used")
    proposals: bpy.props.CollectionProperty(type=AIRIG_PG_proposal)
    review_summary: bpy.props.StringProperty(name="Review Summary")
    anim_motion: bpy.props.EnumProperty(
        name="Motion",
        items=(("WALK", "Walk", "걷기 루프"), ("RUN", "Run", "달리기 루프"), ("IDLE", "Idle", "대기 루프"),
               ("HAPPY", "Happy", "기쁨 루프 (팔을 들고 깡충 뛰기)"), ("JUMP", "Jump", "점프 (단발)"),
               ("ATTACK", "Attack", "한 손 휘두르기 공격 (단발)"), ("HIT", "Hit", "피격 반응 (단발)"),
               ("DEATH", "Death", "쓰러져 눕는 사망 (단발, 끝 자세 유지)")),
        default="WALK",
    )
    anim_style: bpy.props.EnumProperty(
        name="Style", items=(("NORMAL", "Normal", ""), ("ZOMBIE", "Zombie", "")), default="NORMAL",
    )
    anim_root_motion: bpy.props.BoolProperty(
        name="Root Motion", description="꺼두면 제자리(게임 엔진 권장), 켜면 앞으로 이동한다 (걷기·달리기·점프만)", default=False,
    )
    anim_prompt: bpy.props.StringProperty(name="Prompt", description="예: 좀비가 다리를 절며 걷는 루프 / 크게 휘두르는 공격 / 뒤로 쓰러지는 사망")
    anim_review_rounds: bpy.props.IntProperty(
        name="Review Rounds", description="렌더한 프레임을 AI 가 보고 보정하는 횟수", default=1, min=0, max=3,
    )
    anim_summary: bpy.props.StringProperty(name="Motion Summary")
    anim_action: bpy.props.StringProperty(name="Motion Action")
    anim_keys: bpy.props.IntProperty(name="Key Poses", min=0)
    anim_facts: bpy.props.StringProperty(name="Motion Facts")


classes = (AIRIG_PG_proposal, AIRIG_PG_state)


def register_props():
    bpy.types.Scene.airig = bpy.props.PointerProperty(type=AIRIG_PG_state)


def unregister_props():
    del bpy.types.Scene.airig
