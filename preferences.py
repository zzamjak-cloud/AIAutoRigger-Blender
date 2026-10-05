import os

import bpy

from .agents.claude_client import DEFAULT_MODEL, AgentSettings


class AIRIG_AP_preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    api_key: bpy.props.StringProperty(
        name="Anthropic API Key",
        description="비워 두면 ANTHROPIC_API_KEY 환경 변수를 사용합니다",
        subtype="PASSWORD",
    )
    model: bpy.props.StringProperty(name="Model", default=DEFAULT_MODEL)
    effort: bpy.props.EnumProperty(
        name="Effort",
        items=(("low", "Low", ""), ("medium", "Medium", ""), ("high", "High", ""), ("xhigh", "Extra High", "")),
        default="medium",
    )
    review_effort: bpy.props.EnumProperty(
        name="Review Effort",
        items=(("medium", "Medium", ""), ("high", "High", ""), ("xhigh", "Extra High", "")),
        default="high",
    )
    review_max_turns: bpy.props.IntProperty(name="Review Max Turns", default=6, min=1, max=20)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "api_key")
        if not self.api_key and not os.environ.get("ANTHROPIC_API_KEY"):
            layout.label(text="키가 없으면 ANTHROPIC_API_KEY 또는 ant 로그인 프로필을 사용하고, 없으면 AI 기능은 실패합니다.", icon="INFO")
        layout.label(text="키는 Blender 사용자 설정 파일(userpref.blend)에 평문으로 저장됩니다.", icon="LOCKED")
        layout.prop(self, "model")
        row = layout.row()
        row.prop(self, "effort")
        row.prop(self, "review_effort")
        layout.prop(self, "review_max_turns")


def get_prefs(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def agent_settings(context, review=False) -> AgentSettings:
    p = get_prefs(context)
    if p is None:
        return AgentSettings()
    return AgentSettings(api_key=p.api_key, model=p.model or DEFAULT_MODEL, effort=p.review_effort if review else p.effort)


def has_credentials(context) -> bool:
    p = get_prefs(context)
    return bool((p and p.api_key) or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


classes = (AIRIG_AP_preferences,)
