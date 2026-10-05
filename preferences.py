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
        row = box.row()
        row.label(text="로컬 AI CLI", icon="CONSOLE")
        row.operator("airig.detect_cli", icon="FILE_REFRESH")
        for label, name, prop in (("Claude Code CLI", "claude", "claude_path"), ("Codex CLI", "codex", "codex_path")):
            found = backends.find_executable(name, getattr(self, prop))
            col = box.column(align=True)
            col.prop(self, prop, text=label)
            if not found:
                col.label(text="찾지 못함 — 경로를 지정하거나 CLI 를 설치하세요", icon="ERROR")
            elif found != getattr(self, prop):
                col.label(text=f"사용 중: {found}", icon="CHECKMARK")
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


def fill_cli_paths(prefs, overwrite=False):
    """비어 있거나 무효한 CLI 경로를 자동 탐지 결과로 채운다. 채운 개수 반환."""
    backends.clear_cache()
    filled = 0
    for name, prop in (("claude", "claude_path"), ("codex", "codex_path")):
        current = getattr(prefs, prop)
        valid = bool(current) and os.path.isfile(os.path.expanduser(current))
        if overwrite or not valid:
            found = backends.find_executable(name, "")
            if found and found != current:
                setattr(prefs, prop, found)
                filled += 1
    return filled


class AIRIG_OT_detect_cli(bpy.types.Operator):
    """Claude Code CLI·Codex CLI 를 다시 찾아 경로 칸을 채운다"""

    bl_idname = "airig.detect_cli"
    bl_label = "CLI 다시 찾기"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        prefs = get_prefs(context)
        if prefs is None:
            return {"CANCELLED"}
        fill_cli_paths(prefs, overwrite=True)
        found = [n for n, p in (("claude", prefs.claude_path), ("codex", prefs.codex_path)) if p]
        self.report({"INFO"}, f"찾은 CLI: {', '.join(found) or '없음'}")
        return {"FINISHED"}


def autofill_on_register():
    """애드온 활성화 시 빈 경로 칸을 채워 Preferences 에 실제 경로가 보이게 한다."""
    try:
        prefs = get_prefs(bpy.context)
        if prefs is not None:
            fill_cli_paths(prefs)
    except (AttributeError, RuntimeError):
        # 시작 직후처럼 Preferences 접근이 제한된 경우에는 다음 실행 때 채운다
        pass


def active_backend_label(context) -> str:
    """사이드바 표시용: 현재 설정으로 쓰게 될 백엔드와 실행 파일."""
    try:
        kind, exe = backends.resolve(backend_settings(context))
    except backends.BackendError:
        return "AI 사용 불가 — Preferences 에서 CLI 경로 확인"
    return f"AI: {backends.LABELS[kind]}" + (f" ({exe})" if exe else "")


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


classes = (AIRIG_AP_preferences, AIRIG_OT_detect_cli)
