import bpy

# EnumProperty items 콜백이 돌려준 문자열은 Blender 가 참조만 하므로 모듈에 살려 둔다
_library_items = [("", "(없음)", "")]


def library_items(self, context):
    global _library_items
    try:
        from .operators.animate import library
        entries = library()
    except Exception:  # 애드온 로드 전·사전 파일 손상
        entries = []
    items = [(e.name, e.name, e.description or e.name) for e in entries]
    _library_items = items or [("", "(없음)", "")]
    return _library_items


_template_types = [("AUTO", "Auto (체형)", "", "", 0)]
_template_motions = [("", "(없음)", "", "", 0)]


def _stable_id(name):
    """EnumProperty 항목 번호 (이름 해시, 0 은 Auto·없음 전용)."""
    import zlib
    return (zlib.crc32(name.encode("utf-8")) & 0x3FFFFFFF) or 1


def template_type_items(self, context):
    global _template_types
    try:
        from .core import motion_template
        from .operators.template import templates
        found = motion_template.types(templates(context))
    except Exception:  # 애드온 로드 전·템플릿 폴더 손상
        found = []
    # 번호를 이름에서 정해 둔다. 위치 번호면 목록이 바뀔 때(새 타입 등록) 선택이 다른 항목으로 옮겨 간다
    _template_types = [("AUTO", "Auto (체형)", "체형(다리·팔·폭 비율)이 가장 비슷한 타입의 템플릿을 쓴다", "", 0)]
    _template_types += [(t, t, f"{t} 타입 템플릿", "", _stable_id(t)) for t in found]
    return _template_types


def template_motion_items(self, context):
    global _template_motions
    try:
        from .core import motion_template
        from .operators.template import templates
        data = templates(context)
        names = motion_template.motions(data, self.anim_template_type)
    except Exception:
        data, names = {}, []
    items = []
    for n in names:
        entry = data.get((self.anim_template_type, n))
        desc = f"v{entry.get('version', 1)} · {entry['frames']}프레임 · {'루프' if entry['loop'] else '단발'}" if entry else n
        items.append((n, n, desc, "", _stable_id(n)))
    _template_motions = items or [("", "(없음)", "", "", 0)]
    return _template_motions



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
               ("DEATH", "Death", "쓰러져 눕는 사망 (단발, 끝 자세 유지)"),
               ("EMERGE", "Emerge", "땅속에서 손으로 땅을 짚고 기어 올라와 일어서기 (단발, 땅속에서 시작)")),
        default="WALK",
    )
    anim_style: bpy.props.EnumProperty(
        name="Style", items=(("NORMAL", "Normal", ""), ("ZOMBIE", "Zombie", "")), default="NORMAL",
    )
    anim_hand_shape: bpy.props.EnumProperty(
        name="Hands",
        description="손가락 모양. Auto 는 동작에 맞춰 고른다 (걷기 힘 뺀 손, 달리기 가볍게 쥔 손, 공격 주먹·무기 쥐기, 좀비 갈퀴 손)",
        items=(("AUTO", "Hands: Auto", "동작·스타일에 맞춰 고른다"), ("OPEN", "Open", "쭉 편 손"), ("RELAXED", "Relaxed", "힘을 뺀 손"),
               ("LOOSE_FIST", "Loose Fist", "가볍게 쥔 손"), ("FIST", "Fist", "주먹"), ("GRIP", "Grip", "무기 손잡이를 쥔 손"),
               ("POINT", "Point", "검지로 가리키기"), ("CLAW", "Claw", "갈퀴 손 (좀비)")),
        default="AUTO",
    )
    anim_root_motion: bpy.props.BoolProperty(
        name="Root Motion", description="꺼두면 제자리(게임 엔진 권장), 켜면 앞으로 이동한다 (걷기·달리기·점프만)", default=False,
    )
    anim_prompt: bpy.props.StringProperty(name="Prompt", description="예: 좀비가 다리를 절며 걷는 루프 / 양손 도끼 내려찍기 / 손 흔들며 인사")
    anim_library: bpy.props.EnumProperty(name="Library", description="동작 사전의 포즈 클립 (내장 + 사용자 저장)", items=library_items)
    anim_library_name: bpy.props.StringProperty(name="Name", description="사전에 저장할 이름 (영문·숫자·_)")
    anim_library_desc: bpy.props.StringProperty(name="Description", description="사전 설명 (비우면 프롬프트를 쓴다)")
    anim_template_type: bpy.props.EnumProperty(name="Template Type", description="모션 템플릿 타입 (체형)", items=template_type_items)
    anim_template_motion: bpy.props.EnumProperty(name="Template", description="타입의 모션 템플릿", items=template_motion_items)
    anim_template_new_type: bpy.props.StringProperty(
        name="Register Type", description="등록할 타입 이름 (예: Zombie_Thin, Zombie_Fat). 비우면 메시 이름",
    )
    anim_template_name: bpy.props.StringProperty(
        name="Template Name", description="활성 액션을 등록할 이름. 비우면 액션 이름에서 메시 이름을 뺀 이름 (Zombie_Thin_walk → walk)",
    )
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
