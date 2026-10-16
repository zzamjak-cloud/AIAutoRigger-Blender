"""모션 템플릿 등록·적용: 손으로 다듬은 액션을 타입(체형)별로 저장하고 다른 캐릭터에 그대로 다시 쓴다 (AI 없음)."""

import json
import os

import bpy

from ..bridge import animate, template
from ..core import motion_template
from .animate import _poll, _targets


def template_dir(context=None):
    """사용자 템플릿 폴더. 환경 변수 AIRIG_TEMPLATE_DIR → 환경 설정 → Blender 사용자 설정 폴더 순."""
    env = os.environ.get("AIRIG_TEMPLATE_DIR")
    if env:
        return env
    try:
        prefs = (context or bpy.context).preferences.addons[__package__.rpartition(".")[0]].preferences
        if prefs.template_dir.strip():
            return bpy.path.abspath(prefs.template_dir.strip())
    except (KeyError, AttributeError):
        pass
    return bpy.utils.user_resource("CONFIG", path="ai_auto_rigger/templates", create=True)


_cache = {"key": None, "data": {}}


def templates(context=None):
    """템플릿 목록. UI 가 다시 그릴 때마다 불리므로 파일 목록·수정 시각이 같으면 다시 읽지 않는다."""
    import pathlib

    folder = template_dir(context)
    stamp = []
    for root in (motion_template.BUILTIN_DIR, pathlib.Path(folder)):
        if root.is_dir():
            for f in root.glob("*/*.json"):
                try:
                    stamp.append((str(f), f.stat().st_mtime_ns))
                except OSError:
                    pass
    key = (folder, tuple(sorted(stamp)))
    if _cache["key"] != key:
        _cache["key"], _cache["data"] = key, motion_template.load(folder)
    return _cache["data"]


def default_type(context):
    """등록할 타입 이름: 입력값, 없으면 메시 이름 (예: Zombie_Thin)."""
    state = context.scene.airig
    return motion_template.safe_name(state.anim_template_new_type.strip() or state.target_mesh, "Default")


def _rig_actions(rig):
    """리그의 활성 액션과 NLA 스트립 액션 (중복 없이, 활성 액션 먼저)."""
    out = []
    ad = rig.animation_data
    if ad is None:
        return out
    if ad.action is not None:
        out.append(ad.action)
    for track in ad.nla_tracks:
        for strip in track.strips:
            if strip.action is not None and strip.action not in out:
                out.append(strip.action)
    return out


class AIRIG_OT_register_template(bpy.types.Operator):
    """리그의 액션을 지금 상태 그대로(손으로 고친 키·타이밍·턱 등 추가 본 포함) 모션 템플릿으로 등록한다.
    같은 타입·이름이 있으면 이전 버전은 _history 폴더에 보관하고 버전을 올린다"""

    bl_idname = "airig.register_template"
    bl_label = "Register Template"

    all_actions: bpy.props.BoolProperty(name="All Actions", description="활성 액션과 NLA 의 모든 액션을 등록", default=False)

    @classmethod
    def poll(cls, context):
        state = context.scene.airig
        rig = bpy.data.objects.get(state.rig_name)
        return _poll(context) and rig is not None and bool(_rig_actions(rig))

    def execute(self, context):
        state = context.scene.airig
        try:
            rig, mesh, facing = _targets(context)
        except (RuntimeError, KeyError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        actions = _rig_actions(rig) if self.all_actions else _rig_actions(rig)[:1]
        type_name = default_type(context)
        prefixes = (mesh.name, rig.name, state.target_mesh, type_name)
        frame = context.scene.frame_current
        saved, notes, used = [], [], set()
        for action in actions:
            if self.all_actions or not state.anim_template_name.strip():
                name = motion_template.motion_name(action.name, prefixes)
            else:
                name = motion_template.safe_name(state.anim_template_name.strip())
            base, k = name, 2
            while name in used:  # 한 번에 등록하는 액션끼리 이름이 겹치면 번호를 붙인다 (서로 덮어쓰지 않게)
                name, k = f"{base}_{k}", k + 1
            used.add(name)
            try:
                data, info = template.capture(context, rig, mesh, action, facing, type_name, name)
                path = motion_template.save(template_dir(context), data)
                version = json.loads(path.read_text(encoding="utf-8")).get("version", 1)
            except (ValueError, OSError, KeyError, RuntimeError) as exc:
                notes.append(f"{action.name}: {exc}")
                continue
            saved.append(f"{name} v{version}" + (f" ({action.name})" if name != base else ""))
            if info["non_root"]:
                notes.append(f"{action.name}: IK 부모가 Root 가 아닌 컨트롤({', '.join(info['non_root'][:3])}) — "
                             "그 부모 기준으로 넣은 키는 템플릿에서 어긋날 수 있음")
            if info["stale_range"]:
                notes.append(f"{action.name}: 루프 키 구간 {info['frames']}프레임과 액션 프레임 범위 "
                             f"{info['range'][0]:.0f}-{info['range'][1]:.0f} 가 다름 (키 구간으로 등록)")
            print(f"[AIRig] 템플릿 등록: {path}")
        context.scene.frame_set(frame)
        try:
            state.anim_template_type = type_name
        except TypeError:  # 목록 갱신 전
            pass
        for note in notes:
            self.report({"WARNING"}, note)
        if not saved:
            self.report({"ERROR"}, "등록한 템플릿이 없습니다.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"템플릿 등록 ({type_name}): " + ", ".join(saved))
        return {"FINISHED"}


class AIRIG_OT_apply_template(bpy.types.Operator):
    """고른 모션 템플릿으로 이 캐릭터의 액션을 만든다. 위치는 다리·팔 길이, 손은 어깨 기준으로 맞춘다.
    타입이 Auto 면 체형(다리·팔·폭 비율)이 가장 비슷한 타입의 템플릿을 쓴다"""

    bl_idname = "airig.apply_template"
    bl_label = "Apply Template"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll(context) and bool(context.scene.airig.anim_template_motion)

    def execute(self, context):
        state = context.scene.airig
        try:
            rig, mesh, facing = _targets(context)
            body = template.body_info(rig, mesh, facing)
            data = motion_template.resolve(templates(context), state.anim_template_type, state.anim_template_motion, body)
            action, skipped = template.apply(context, rig, data, f"{mesh.name}_{data['name']}", facing)
        except (ValueError, RuntimeError, KeyError) as exc:
            self.report({"ERROR"}, str(exc.args[0] if exc.args else exc))
            return {"CANCELLED"}
        state.anim_action = action.name
        state.anim_keys = sum(len(fc.keyframe_points) for fc in animate.fcurves(rig))
        state.anim_summary = f"템플릿 {data['type']}/{data['name']} v{data.get('version', 1)}"
        if skipped:
            self.report({"WARNING"}, f"이 리그에 없는 채널 {len(skipped)}개 건너뜀: {', '.join(sorted(set(skipped))[:4])}")
        kind = "루프" if data["loop"] else "단발 동작"
        self.report({"INFO"}, f"템플릿 적용: {action.name} ← {data['type']}/{data['name']} v{data.get('version', 1)} "
                              f"({kind}, {data['frames']}프레임)")
        return {"FINISHED"}


class AIRIG_OT_open_template_dir(bpy.types.Operator):
    """사용자 템플릿 폴더를 연다 (팀 공유 폴더는 애드온 환경 설정에서 바꾼다)"""

    bl_idname = "airig.open_template_dir"
    bl_label = "Open Template Folder"

    def execute(self, context):
        path = template_dir(context)
        os.makedirs(path, exist_ok=True)
        bpy.ops.wm.path_open(filepath=path)
        return {"FINISHED"}


classes = (AIRIG_OT_register_template, AIRIG_OT_apply_template, AIRIG_OT_open_template_dir)
