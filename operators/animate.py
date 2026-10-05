"""이동 루프 생성: 프리셋(AI 없음)과 AI Motion(프롬프트 → 파라미터 → 프레임 렌더 검토 라운드)."""

import threading

import bpy

from .. import preferences
from ..agents import backends, motion_agent
from ..bridge import animate, views
from ..core import locomotion

POLL_INTERVAL = 0.25
REVIEW_TIMES = (0.0, 0.25, 0.5, 0.75)


def _targets(context):
    state = context.scene.airig
    rig = bpy.data.objects.get(state.rig_name)
    mesh = bpy.data.objects.get(state.target_mesh)
    metarig = bpy.data.objects.get(state.metarig_name)
    if rig is None or mesh is None or metarig is None:
        raise RuntimeError("먼저 리그를 생성하세요.")
    if metarig.get("airig_kind") != "BIPED":
        raise RuntimeError("이동 루프는 현재 2족 리그만 지원합니다.")
    return rig, mesh, metarig.get("airig_facing", "-Y")


def _apply(context, rig, facing, params, label, name=None):
    leg, arm = animate.measure(rig)
    motion = locomotion.generate(params, leg, arm)
    context.scene.airig.anim_facts = locomotion.facts(motion, context.scene.render.fps)
    name = name or f"{rig.name}_{params.motion.lower()}_{label}"
    action = animate.apply_motion(context, rig, motion, name, facing)
    state = context.scene.airig
    state.anim_action = action.name
    state.anim_keys = motion.key_count()
    return action


def _poll(context):
    state = context.scene.airig
    return context.mode in {"OBJECT", "POSE"} and bool(state.rig_name) and state.detected_type == "BIPED"


class AIRIG_OT_generate_motion(bpy.types.Operator):
    """선택한 동작·스타일 프리셋으로 루프 애니메이션을 만든다 (AI 없음)"""

    bl_idname = "airig.generate_motion"
    bl_label = "Generate Loop"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def execute(self, context):
        state = context.scene.airig
        try:
            rig, _mesh, facing = _targets(context)
            params = locomotion.preset(state.anim_motion, state.anim_style, root_motion=state.anim_root_motion)
            action = _apply(context, rig, facing, params, state.anim_style.lower())
        except (ValueError, RuntimeError, KeyError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        state.anim_summary = ""
        self.report({"INFO"}, f"루프 생성: {action.name} ({params.cycle_frames}프레임, 키 포즈 {state.anim_keys}개)")
        return {"FINISHED"}


def render_review(context, rig, mesh, facing, n):
    """검토용 프레임: 측면 4장 + 정면 2장. 전진 이동은 잠시 끄고 제자리로 렌더한다."""
    root = [fc for fc in animate.fcurves(rig) if fc.data_path == 'pose.bones["root"].location']
    for fc in root:
        fc.mute = True
    images = []
    try:
        for t in REVIEW_TIMES:
            frame = animate.START_FRAME + round(t * n)
            imgs, _, _ = views.render_views(context, mesh, facing, extra_objects=[rig], which=("side",), frame=frame, margin=1.15)
            images.append((f"side_t{int(t * 100):03d}", imgs["side"]))
        for t in (0.0, 0.5):
            frame = animate.START_FRAME + round(t * n)
            imgs, _, _ = views.render_views(context, mesh, facing, extra_objects=[rig], which=("front",), frame=frame, margin=1.15)
            images.append((f"front_t{int(t * 100):03d}", imgs["front"]))
    finally:
        for fc in root:
            fc.mute = False
        context.scene.frame_set(animate.START_FRAME)
    return images


class AIRIG_OT_ai_motion(bpy.types.Operator):
    """프롬프트대로 AI 가 걸음 파라미터를 정하고, 렌더한 프레임을 보며 보정해 루프를 만든다 (ESC 취소)"""

    bl_idname = "airig.ai_motion"
    bl_label = "AI Motion"
    bl_options = {"UNDO"}

    _timer = None

    @classmethod
    def poll(cls, context):
        return _poll(context) and bool(context.scene.airig.anim_prompt.strip())

    def invoke(self, context, event):
        return self.execute(context)

    def execute(self, context):
        state = context.scene.airig
        try:
            self.rig, self.mesh, self.facing = _targets(context)
            self.backend = backends.create(preferences.backend_settings(context))
        except (ValueError, RuntimeError, KeyError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.prompt = state.anim_prompt.strip()
        self.rounds_left = state.anim_review_rounds
        self.params = None
        self.summary = ""
        leg, arm = animate.measure(self.rig)
        # UI 의 동작·스타일을 AI 기준값으로 준다
        base = locomotion.preset(state.anim_motion, state.anim_style, root_motion=state.anim_root_motion)
        backend, prompt, hint, fps = self.backend, self.prompt, state.anim_motion, context.scene.render.fps
        self.action_name = None
        self._start(lambda: motion_agent.ask_params(backend, prompt, hint, leg, arm, base, fps))
        if bpy.app.background or context.window is None:
            while True:
                self._thread.join()
                result = self._safe_advance(context)
                if result != "CONTINUE":
                    return result
        wm = context.window_manager
        self._timer = wm.event_timer_add(POLL_INTERVAL, window=context.window)
        wm.modal_handler_add(self)
        context.workspace.status_text_set(f"AI Motion: {self.backend.label} 가 동작을 설계하는 중… (ESC 취소)")
        return {"RUNNING_MODAL"}

    def _start(self, fn):
        # 스레드는 연산자(RNA 객체)를 건드리지 않고 일반 dict 에만 결과를 쓴다
        self.box = box = {"result": None, "error": None}

        def work():
            try:
                box["result"] = fn()
            except Exception as exc:  # 메인 스레드에서 보고
                box["error"] = exc

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()

    def _safe_advance(self, context):
        try:
            return self._advance(context)
        except Exception as exc:  # 렌더·키 적용 오류도 타이머를 정리하고 끝낸다
            self.report({"ERROR"}, f"AI Motion 오류: {exc}")
            return {"CANCELLED"}

    def _advance(self, context):
        error = self.box["error"]
        if error is not None:
            if self.params is None:
                self.report({"ERROR"}, f"AI Motion 실패: {error}")
                return {"CANCELLED"}
            # 검토 단계 실패는 이미 만든 루프를 남기고 끝낸다
            self.report({"WARNING"}, f"AI 검토 실패, 현재 루프 유지: {error}")
            return self._finish(context)
        params, done, summary = self.box["result"]
        params.root_motion = context.scene.airig.anim_root_motion
        changed = self.params is None or params.to_dict() != self.params.to_dict()
        self.params = params
        self.summary = summary or self.summary
        if changed:
            # 라운드 중 AI 가 동작 종류를 바꿔도 같은 액션을 교체하도록 첫 이름을 고정한다
            action = _apply(context, self.rig, self.facing, params, "ai", self.action_name)
            self.action_name = action.name
        if (self.rounds_left <= 0) or (done and not changed):
            return self._finish(context)
        self.rounds_left -= 1
        images = render_review(context, self.rig, self.mesh, self.facing, params.cycle_frames)
        backend, prompt, measured = self.backend, self.prompt, context.scene.airig.anim_facts
        self._start(lambda: motion_agent.ask_review(backend, prompt, params, images, measured))
        return "CONTINUE"

    def _finish(self, context):
        state = context.scene.airig
        state.anim_summary = self.summary[:500]
        self.report({"INFO"}, f"AI 루프 완료: {state.anim_action} ({self.params.cycle_frames}프레임, 키 포즈 {state.anim_keys}개)")
        return {"FINISHED"}

    def modal(self, context, event):
        if event.type == "ESC":
            self.backend.cancel()
            self._cleanup(context)
            self.report({"WARNING"}, "AI Motion 을 취소했습니다.")
            return {"CANCELLED"}
        if event.type == "TIMER" and not self._thread.is_alive():
            result = self._safe_advance(context)
            if result != "CONTINUE":
                self._cleanup(context)
                return result
        return {"PASS_THROUGH"}

    def _cleanup(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        if context.workspace is not None:
            context.workspace.status_text_set(None)


classes = (AIRIG_OT_generate_motion, AIRIG_OT_ai_motion)
