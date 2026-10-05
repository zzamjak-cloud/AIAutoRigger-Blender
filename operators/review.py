"""AI 리그 검토 (모달: AI 라운드 호출은 스레드, 렌더는 메인 스레드) 와 보정안 승인 적용."""

import json
import threading

import bpy

from .. import preferences
from ..agents import backends
from ..agents.review_agent import Proposal, ReviewSession
from ..bridge import review

POLL_INTERVAL = 0.25


def _session_inputs(context):
    state = context.scene.airig
    metarig = bpy.data.objects.get(state.metarig_name)
    mesh = bpy.data.objects.get(state.target_mesh)
    if metarig is None or mesh is None or not state.rig_name:
        raise RuntimeError("먼저 리그를 생성하세요.")
    if "airig_joints" not in metarig:
        raise RuntimeError("이 메타리그는 이전 버전에서 만들어졌습니다. Fit Metarig 를 다시 실행하세요.")
    kind = metarig["airig_kind"]
    joints = sorted(json.loads(metarig["airig_joints"]).keys())
    bones = sorted(g.name for g in mesh.vertex_groups if g.name.startswith("DEF-"))
    return kind, joints, bones


class AIRIG_OT_ai_review(bpy.types.Operator):
    """AI(Claude Code CLI·Codex CLI·API)가 테스트 포즈 렌더를 보고 리그 결함과 보정안을 제안한다 (적용은 승인 후)"""

    bl_idname = "airig.ai_review"
    bl_label = "AI Review Rig"
    # 재실행 패널을 두지 않아 Redo 가 API 호출을 반복하지 않게 한다
    bl_options = {"UNDO"}

    _timer = None

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.scene.airig.rig_name)

    def invoke(self, context, event):
        return self.execute(context)

    def execute(self, context):
        try:
            kind, joints, bones = _session_inputs(context)
            self.backend = backends.create(preferences.backend_settings(context, review=True))
            prefs = preferences.get_prefs(context)
            poses = list(review.POSES[kind])
            self.session = ReviewSession(self.backend, joints, bones, poses,
                                         max_rounds=prefs.review_max_turns if prefs else 4)
            # 이미지 이름은 CLI 백엔드에서 파일 이름으로도 쓰인다
            images = [(f"{p}_front", review.render_pose(context, p, "front")) for p in poses]
            self.session.start(images, review.deformation_metrics(context), kind)
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        # 스레드는 연산자(RNA 객체)를 건드리지 않고 일반 dict 에만 결과를 쓴다
        self.box = {"calls": [], "error": None}
        self._start_step()
        if bpy.app.background or context.window is None:
            # 백그라운드(테스트)에서는 동기 루프
            while True:
                self._thread.join()
                state = self._safe_advance(context)
                if state != "CONTINUE":
                    return state
        wm = context.window_manager
        self._timer = wm.event_timer_add(POLL_INTERVAL, window=context.window)
        wm.modal_handler_add(self)
        context.workspace.status_text_set(f"AI Review: {self.backend.label} 가 리그를 검토하는 중… (ESC 취소)")
        return {"RUNNING_MODAL"}

    def _start_step(self):
        box, session = self.box, self.session

        def work():
            try:
                box["calls"] = session.step()
            except Exception as exc:  # 메인 스레드에서 보고
                box["error"] = exc

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()

    def _safe_advance(self, context):
        try:
            return self._advance(context)
        except Exception as exc:  # 메인 스레드 처리 중 예외도 타이머·상태 표시를 정리하고 끝낸다
            self.report({"ERROR"}, f"AI 검토 중 오류: {exc!r}")
            self._store(context)
            return {"CANCELLED"}

    def _advance(self, context):
        """스레드 한 단계가 끝난 뒤 처리. 'CONTINUE' 또는 연산자 결과 집합."""
        error = self.box["error"]
        if error is not None:
            msg = str(error) if isinstance(error, (backends.BackendError, ValueError, RuntimeError)) else repr(error)
            self.report({"ERROR"}, f"AI 검토 실패: {msg}")
            self._store(context)
            return {"CANCELLED"}
        if self.session.done:
            self._store(context)
            n = len(self.session.proposals)
            self.report({"INFO"}, f"AI 검토 완료: 보정안 {n}개" + (" — 패널에서 확인 후 적용하세요." if n else ""))
            return {"FINISHED"}
        requests = self.box["calls"]
        if requests:
            rnd = self.session.rounds
            self.session.add_renders([(f"r{rnd}_{pose}_{view}", review.render_pose(context, pose, view)) for pose, view in requests])
            self.box["calls"] = []
        self._start_step()
        return "CONTINUE"

    def _store(self, context):
        state = context.scene.airig
        state.proposals.clear()
        for p in self.session.proposals:
            item = state.proposals.add()
            item.kind, item.target, item.delta = p.kind, p.target, p.delta
            item.iterations, item.reason, item.enabled = p.iterations, p.reason, True
        state.review_summary = self.session.summary[:1000]

    def modal(self, context, event):
        if event.type == "ESC":
            self.backend.cancel()
            self._cleanup(context)
            self._store(context)
            self.report({"WARNING"}, "AI 검토를 취소했습니다. 그때까지의 보정안만 남깁니다.")
            return {"CANCELLED"}
        if event.type == "TIMER" and not self._thread.is_alive():
            state = self._safe_advance(context)
            if state != "CONTINUE":
                self._cleanup(context)
                return state
        return {"PASS_THROUGH"}

    def _cleanup(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        if context.workspace is not None:
            context.workspace.status_text_set(None)


class AIRIG_OT_apply_proposals(bpy.types.Operator):
    """체크된 보정안을 적용한다 (관절 이동은 리그 재생성·재바인딩)"""

    bl_idname = "airig.apply_proposals"
    bl_label = "Apply Selected"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and any(p.enabled for p in context.scene.airig.proposals)

    def execute(self, context):
        state = context.scene.airig
        chosen = [Proposal(p.kind, p.target, tuple(p.delta), p.iterations, p.reason) for p in state.proposals if p.enabled]
        try:
            moves, smoothed = review.apply_proposals(context, chosen)
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        state.proposals.clear()
        self.report({"INFO"}, f"보정안 적용: 관절 이동 {moves}개, 웨이트 스무딩 {smoothed}개")
        return {"FINISHED"}


class AIRIG_OT_clear_proposals(bpy.types.Operator):
    """보정안 목록을 비운다"""

    bl_idname = "airig.clear_proposals"
    bl_label = "Clear"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        context.scene.airig.proposals.clear()
        context.scene.airig.review_summary = ""
        return {"FINISHED"}


classes = (AIRIG_OT_ai_review, AIRIG_OT_apply_proposals, AIRIG_OT_clear_proposals)
