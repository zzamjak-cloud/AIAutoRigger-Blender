"""AI 보조 자동 리깅: 휴리스틱 → 직교 렌더 → Claude Landmark Agent(백그라운드 스레드) → 병합 → Rigify."""

import threading

import bpy

from .. import preferences
from ..agents import claude_client, landmark_agent
from ..bridge import views
from . import rig

POLL_INTERVAL = 0.25


class AIRIG_OT_ai_auto_rig(bpy.types.Operator):
    """Claude 비전으로 관절 위치를 보정한 뒤 Rigify 컨트롤 리그를 생성한다 (ESC 로 취소)"""

    bl_idname = "airig.ai_auto_rig"
    bl_label = "AI Auto Rig"
    # REGISTER(재실행 패널)를 빼서 F9/Redo 가 API 호출을 반복하지 않게 한다
    bl_options = {"UNDO"}

    _timer = None
    _thread = None

    @classmethod
    def poll(cls, context):
        return rig._mesh_poll(context)

    def invoke(self, context, event):
        return self.execute(context)

    def execute(self, context):
        self.mesh_name = context.active_object.name
        try:
            self.est = rig.estimate(context, context.active_object)
            images, self.views, _size = views.render_views(context, context.active_object, self.est.facing)
            settings = preferences.agent_settings(context)
            client = claude_client.make_client(settings)
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # 스레드는 연산자(RNA 객체)를 건드리지 않고 일반 dict 에만 결과를 쓴다
        self.box = box = {"result": None, "error": None}
        kind = self.est.kind

        def work():
            # bpy 접근 금지: 네트워크 호출만 수행한다
            try:
                box["result"] = landmark_agent.ask(client, settings, kind, images)
            except Exception as exc:  # 스레드 예외는 메인 스레드에서 보고한다
                box["error"] = exc

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()
        wm = context.window_manager
        if bpy.app.background or context.window is None:
            # 백그라운드 실행(테스트)에서는 모달 이벤트가 없으므로 동기 대기한다
            self._thread.join()
            return self.finish(context)
        self._timer = wm.event_timer_add(POLL_INTERVAL, window=context.window)
        wm.modal_handler_add(self)
        context.workspace.status_text_set("AI Auto Rig: Claude 가 관절을 분석하는 중… (ESC 취소)")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            self.cleanup(context)
            self.report({"WARNING"}, "AI Auto Rig 를 취소했습니다. (진행 중인 요청 결과는 버립니다)")
            return {"CANCELLED"}
        if event.type == "TIMER" and not self._thread.is_alive():
            self.cleanup(context)
            return self.finish(context)
        return {"PASS_THROUGH"}

    def cleanup(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        if context.workspace is not None:
            context.workspace.status_text_set(None)

    def finish(self, context):
        mesh_obj = bpy.data.objects.get(self.mesh_name)
        if mesh_obj is None:
            self.report({"ERROR"}, "대상 메시가 사라졌습니다.")
            return {"CANCELLED"}
        est = self.est
        state = context.scene.airig
        error = self.box["error"]
        if error is not None:
            msg = str(error) if isinstance(error, (claude_client.AgentError, ValueError)) else repr(error)
            est.warnings.append(f"AI 단계 실패, 휴리스틱만 사용: {msg}")
            state.ai_joints_used = 0
            state.ai_request_id = ""
        else:
            ai, request_id = self.box["result"]
            merged = landmark_agent.combine(est.kind, est.facing, est.joints, ai, self.views, est.size, est.symmetric)
            est.joints = merged.joints
            est.warnings.extend(merged.warnings)
            state.ai_joints_used = len(merged.used_joints)
            state.ai_request_id = request_id
        try:
            rig.apply_metarig(self, context, mesh_obj, est)
            result = rig.generate_and_bind(self, context)
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if result is None:
            return {"CANCELLED"}
        self.report({"INFO"}, f"AI 자동 리깅 완료: {result.name} (AI 반영 관절 {state.ai_joints_used}개)")
        return {"FINISHED"}


classes = (AIRIG_OT_ai_auto_rig,)
