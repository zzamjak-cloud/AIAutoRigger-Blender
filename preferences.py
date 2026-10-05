import os

import bpy

from .agents import backends
from .agents.claude_client import DEFAULT_MODEL


class AIRIG_AP_preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    backend: bpy.props.EnumProperty(
        name="AI Backend",
        items=(
            ("AUTO", "Auto", "설치된 Claude Code CLI → Codex CLI → API 키 순으로 사용"),
            (backends.CLAUDE_CODE, "Claude Code CLI", "로컬에 로그인된 claude CLI 계정 사용 (ANTHROPIC_API_KEY 는 넘기지 않음)"),
            (backends.CODEX, "Codex CLI", "로컬에 로그인된 codex CLI 계정 사용 (OPENAI_API_KEY 는 넘기지 않음)"),
            (backends.API, "Anthropic API", "API 키로 Claude API 직접 호출"),
        ),
        default="AUTO",
    )
    claude_path: bpy.props.StringProperty(name="claude 경로", description="비우면 자동 탐색", subtype="FILE_PATH")
    codex_path: bpy.props.StringProperty(name="codex 경로", description="비우면 자동 탐색", subtype="FILE_PATH")
    cli_model: bpy.props.StringProperty(name="CLI Model", description="비우면 각 CLI 의 기본 모델")
    timeout: bpy.props.IntProperty(name="Timeout (s)", default=600, min=30, max=3600)
    api_key: bpy.props.StringProperty(
        name="Anthropic API Key",
        description="비워 두면 ANTHROPIC_API_KEY 환경 변수를 사용합니다",
        subtype="PASSWORD",
    )
    model: bpy.props.StringProperty(name="API Model", default=DEFAULT_MODEL)
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
    review_max_turns: bpy.props.IntProperty(name="Review Max Rounds", default=4, min=1, max=10)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "backend")
        box = layout.box()
        for label, name, override in (("Claude Code CLI", "claude", self.claude_path), ("Codex CLI", "codex", self.codex_path)):
            found = backends.find_executable(name, override)
            box.label(text=f"{label}: {found or '찾지 못함'}", icon="CHECKMARK" if found else "X")
        box.prop(self, "claude_path")
        box.prop(self, "codex_path")
        box.prop(self, "cli_model")
        box.prop(self, "timeout")
        box = layout.box()
        box.prop(self, "api_key")
        box.prop(self, "model")
        if self.backend == backends.API:
            box.label(text="키는 Blender 사용자 설정 파일(userpref.blend)에 평문으로 저장됩니다.", icon="LOCKED")
        row = layout.row()
        row.prop(self, "effort")
        row.prop(self, "review_effort")
        layout.prop(self, "review_max_turns")
        layout.label(text="렌더 이미지(메시 형상)가 선택한 AI 서비스로 전송됩니다.", icon="INFO")


def get_prefs(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def backend_settings(context, review=False) -> backends.BackendSettings:
    p = get_prefs(context)
    if p is None:
        return backends.BackendSettings()
    return backends.BackendSettings(
        kind=p.backend, claude_path=p.claude_path, codex_path=p.codex_path, model=p.cli_model,
        effort=p.review_effort if review else p.effort, timeout=float(p.timeout),
        api_key=p.api_key or os.environ.get("ANTHROPIC_API_KEY", ""), api_model=p.model or DEFAULT_MODEL,
    )


classes = (AIRIG_AP_preferences,)
