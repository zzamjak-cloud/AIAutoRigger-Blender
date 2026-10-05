"""Rig Review Agent: 테스트 포즈 렌더를 보고 리그 결함을 찾아 보정안을 제안한다 (bpy 비의존).

도구는 허용 목록만 제공한다. 렌더 요청만 즉시 실행되고, 리그를 바꾸는 도구는 제안으로만 쌓여
사용자가 승인한 뒤 적용된다. API 호출(step)은 백그라운드 스레드에서, 도구 실행은 메인 스레드에서 한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import claude_client

MAX_MOVE = 0.1  # 관절 이동 한도 (모델 크기 대비)
MAX_SMOOTH_ITER = 10

SYSTEM_PROMPT = """You review an automatically generated Rigify control rig on a 3D character. You see \
orthographic renders of the skinned mesh in test poses driven by the rig's IK controls, plus deformation \
metrics. Find real defects: joints placed outside the limb or at the wrong height, bending at the wrong place, \
candy-wrapper twisting, collapsing or tearing volume, body parts dragged by the wrong bone. Use render_pose to \
look at more poses or views when needed. Propose fixes only with the propose_* tools; each proposal is shown to \
the user, who decides whether to apply it. Names ending in _L / .L are the character's anatomical LEFT, which \
appears on the IMAGE RIGHT of the front view. Joint offsets are fractions of the model's largest dimension in the \
front-view frame: dx toward the front image's right edge, dy toward the front camera (the character's front), \
dz up. Prefer few, high-confidence proposals. When finished, reply with a short summary of what you found."""


@dataclass
class Proposal:
    kind: str  # "move_joint" | "smooth_weights"
    target: str
    delta: tuple[float, float, float] = (0.0, 0.0, 0.0)
    iterations: int = 0
    reason: str = ""


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ReviewSession:
    client: object
    settings: claude_client.AgentSettings
    joints: list[str]
    deform_bones: list[str]
    poses: list[str]
    max_turns: int = 6
    messages: list = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)
    summary: str = ""
    turns: int = 0
    done: bool = False

    def tools(self) -> list[dict]:
        def tool(name, desc, props, required):
            return {
                "name": name,
                "description": desc,
                "strict": True,
                "eager_input_streaming": True,
                "input_schema": {"type": "object", "properties": props, "required": required, "additionalProperties": False},
            }

        return [
            tool("render_pose", "Render the skinned mesh in a named test pose from the front or side view.",
                 {"pose": {"type": "string", "enum": self.poses}, "view": {"type": "string", "enum": ["front", "side"]}},
                 ["pose", "view"]),
            tool("propose_joint_move", "Propose moving one joint of the metarig; the rig is regenerated if the user accepts.",
                 {"joint": {"type": "string", "enum": self.joints},
                  "dx": {"type": "number"}, "dy": {"type": "number"}, "dz": {"type": "number"},
                  "reason": {"type": "string"}},
                 ["joint", "dx", "dy", "dz", "reason"]),
            tool("propose_weight_smooth", "Propose smoothing the skin weights of one deform bone.",
                 {"bone": {"type": "string", "enum": self.deform_bones},
                  "iterations": {"type": "integer"}, "reason": {"type": "string"}},
                 ["bone", "iterations", "reason"]),
        ]

    def start(self, images: list[tuple[str, bytes]], metrics: str, kind: str):
        content = []
        for label, png in images:
            content.append({"type": "text", "text": label})
            content.append(claude_client.image_block(png))
        content.append({"type": "text", "text": f"Body type: {kind}.\nDeformation metrics:\n{metrics}"})
        self.messages.append({"role": "user", "content": content})

    def validate(self, call: ToolCall) -> str | None:
        """오류 메시지 또는 None. eager 스트리밍은 서버 검증이 없으므로 직접 검사한다."""
        i = call.input
        if not isinstance(i, dict):
            return "input must be an object"

        def is_num(x):
            return isinstance(x, (int, float)) and not isinstance(x, bool)

        if call.name.startswith("propose_") and not isinstance(i.get("reason"), str):
            return "reason must be a string"
        if call.name == "render_pose":
            if i.get("pose") not in self.poses or i.get("view") not in ("front", "side"):
                return "unknown pose or view"
        elif call.name == "propose_joint_move":
            if i.get("joint") not in self.joints:
                return "unknown joint"
            for k in ("dx", "dy", "dz"):
                if not is_num(i.get(k)) or abs(i[k]) > MAX_MOVE:
                    return f"{k} must be a number within ±{MAX_MOVE}"
        elif call.name == "propose_weight_smooth":
            if i.get("bone") not in self.deform_bones:
                return "unknown bone"
            it = i.get("iterations")
            if not isinstance(it, int) or isinstance(it, bool) or not 1 <= it <= MAX_SMOOTH_ITER:
                return f"iterations must be 1..{MAX_SMOOTH_ITER}"
        else:
            return "unknown tool"
        return None

    def step(self) -> list[ToolCall]:
        """API 1회 호출. 실행할 도구 호출 목록을 반환하고, 끝났으면 done=True (스레드 안전, bpy 미사용)."""
        if self.turns >= self.max_turns:
            self.done = True
            self.summary = self.summary or "검토 턴 한도에 도달했습니다."
            return []
        self.turns += 1
        message = claude_client.request_tools(self.client, self.settings, SYSTEM_PROMPT, self.messages, self.tools())
        if message is None:
            # 도구 입력 JSON 을 SDK 가 해석하지 못함: 같은 요청을 다음 턴에 다시 보낸다
            return []
        self.messages.append({"role": "assistant", "content": message.content})
        calls = [ToolCall(b.id, b.name, b.input) for b in message.content if b.type == "tool_use"]
        if message.stop_reason in ("refusal", "max_tokens"):
            # 잘린 도구 입력은 실행하지 않는다
            self.done = True
            self.summary = "검토 응답이 중단되었습니다." if message.stop_reason == "refusal" else "검토 응답이 길이 제한에 걸렸습니다."
            return []
        if not calls:
            self.done = True
            self.summary = "\n".join(b.text for b in message.content if b.type == "text").strip()
        return calls

    def handle(self, call: ToolCall, render) -> dict:
        """도구 하나를 실행해 tool_result 블록을 만든다 (메인 스레드). render(pose, view) → PNG."""
        error = self.validate(call)
        if error:
            return {"type": "tool_result", "tool_use_id": call.id, "is_error": True,
                    "content": json.dumps({"INVALID_INPUT": error, "input": call.input}, ensure_ascii=False, default=str)}
        i = call.input
        if call.name == "render_pose":
            try:
                png = render(i["pose"], i["view"])
            except (RuntimeError, ValueError, KeyError) as exc:
                return {"type": "tool_result", "tool_use_id": call.id, "is_error": True, "content": f"render failed: {exc}"}
            return {"type": "tool_result", "tool_use_id": call.id, "content": [claude_client.image_block(png)]}
        if call.name == "propose_joint_move":
            self.proposals.append(Proposal("move_joint", i["joint"], (float(i["dx"]), float(i["dy"]), float(i["dz"])), 0, i["reason"]))
        else:
            self.proposals.append(Proposal("smooth_weights", i["bone"], iterations=int(i["iterations"]), reason=i["reason"]))
        return {"type": "tool_result", "tool_use_id": call.id, "content": "queued for user approval"}

    def submit(self, results: list[dict]):
        # 병렬 도구 호출 결과는 하나의 user 메시지로 돌려준다
        self.messages.append({"role": "user", "content": results})
