"""Rig Review Agent: 테스트 포즈 렌더를 보고 리그 결함을 찾아 보정안을 제안한다 (bpy 비의존).

CLI 백엔드는 Blender 안의 도구를 직접 호출할 수 없으므로 라운드 방식으로 동작한다.
매 라운드 AI 는 JSON 으로 {추가 렌더 요청, 보정안, 완료 여부, 요약} 을 돌려주고, Blender 가 요청된
포즈를 렌더해 다음 라운드에 누적 맥락(이미지·이전 보정안)과 함께 다시 보낸다. 세션 재개에 의존하지
않으므로 Claude Code CLI·Codex CLI·API 가 같은 경로를 쓴다. 보정안은 사용자가 승인해야 적용된다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

MAX_MOVE = 0.1  # 관절 이동 한도 (모델 크기 대비)
MAX_SMOOTH_ITER = 10
MAX_RENDER_REQUESTS = 4
MAX_IMAGES = 12  # 한 라운드에 보내는 이미지 상한 (처음 포즈 세트 + 최근 요청분)

SYSTEM_PROMPT = """You review an automatically generated Rigify control rig on a 3D character. You see \
orthographic renders of the skinned mesh in test poses driven by the rig's IK controls, plus deformation \
metrics. Find real defects: joints placed outside the limb or at the wrong height, bending at the wrong place, \
candy-wrapper twisting, collapsing or tearing volume, body parts dragged by the wrong bone. You may request more \
renders (render_requests) and continue in another round, or finish (done=true). Proposals are shown to the user, \
who decides whether to apply them. Names ending in _L / .L are the character's anatomical LEFT, which appears on \
the IMAGE RIGHT of the front view. Joint offsets are fractions of the model's largest dimension in the front-view \
frame: dx toward the front image's right edge, dy toward the front camera (the character's front), dz up. \
Prefer few, high-confidence proposals; an empty list is fine when the rig looks correct."""


@dataclass
class Proposal:
    kind: str  # "move_joint" | "smooth_weights"
    target: str
    delta: tuple[float, float, float] = (0.0, 0.0, 0.0)
    iterations: int = 0
    reason: str = ""


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


@dataclass
class ReviewSession:
    backend: object
    joints: list[str]
    deform_bones: list[str]
    poses: list[str]
    max_rounds: int = 4
    kind: str = ""
    metrics: str = ""
    base_images: list = field(default_factory=list)
    extra_images: list = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    summary: str = ""
    rounds: int = 0
    done: bool = False

    def schema(self) -> dict:
        targets = sorted(set(self.joints) | set(self.deform_bones))
        request = {
            "type": "object",
            "properties": {"pose": {"type": "string", "enum": self.poses},
                           "view": {"type": "string", "enum": ["front", "side"]}},
            "required": ["pose", "view"],
            "additionalProperties": False,
        }
        proposal = {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["move_joint", "smooth_weights"]},
                "target": {"type": "string", "enum": targets},
                "dx": {"type": "number"}, "dy": {"type": "number"}, "dz": {"type": "number"},
                "iterations": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["kind", "target", "dx", "dy", "dz", "iterations", "reason"],
            "additionalProperties": False,
        }
        return {
            "type": "object",
            "properties": {
                "render_requests": {"type": "array", "items": request},
                "proposals": {"type": "array", "items": proposal},
                "done": {"type": "boolean"},
                "summary": {"type": "string"},
            },
            "required": ["render_requests", "proposals", "done", "summary"],
            "additionalProperties": False,
        }

    def start(self, images: list[tuple[str, bytes]], metrics: str, kind: str):
        self.base_images = list(images)
        self.metrics = metrics
        self.kind = kind

    def prompt(self) -> str:
        lines = [
            f"Body type: {self.kind}. Review round {self.rounds + 1} of at most {self.max_rounds}.",
            "Images (in order): " + ", ".join(label for label, _ in self._images()),
            f"Deformation metrics:\n{self.metrics}",
            "Movable joints (move_joint targets): " + ", ".join(self.joints),
            "Deform bones (smooth_weights targets, iterations 1-10): " + ", ".join(self.deform_bones),
            f"Joint offsets must be within ±{MAX_MOVE}; for smooth_weights set dx=dy=dz=0, for move_joint set iterations=0.",
        ]
        if self.proposals:
            prev = [{"kind": p.kind, "target": p.target, "delta": p.delta, "iterations": p.iterations} for p in self.proposals]
            lines.append("Proposals already queued (repeat one only to replace it): " + json.dumps(prev))
        if self.rejected:
            lines.append("Rejected last round (fix and resend if still needed): " + "; ".join(self.rejected[-6:]))
        if self.rounds + 1 >= self.max_rounds:
            lines.append("This is the final round: set done=true and leave render_requests empty.")
        return "\n".join(lines)

    def _images(self):
        keep = MAX_IMAGES - len(self.base_images)
        return self.base_images + (self.extra_images[-keep:] if keep > 0 else [])

    def validate(self, p) -> str | None:
        if not isinstance(p, dict):
            return "proposal must be an object"
        kind, target = p.get("kind"), p.get("target")
        if not isinstance(p.get("reason"), str):
            return f"{target}: reason must be a string"
        if kind == "move_joint":
            if target not in self.joints:
                return f"{target}: unknown joint"
            for k in ("dx", "dy", "dz"):
                if not _is_num(p.get(k)) or abs(p[k]) > MAX_MOVE:
                    return f"{target}: {k} must be within ±{MAX_MOVE}"
        elif kind == "smooth_weights":
            if target not in self.deform_bones:
                return f"{target}: unknown bone"
            it = p.get("iterations")
            if not isinstance(it, int) or isinstance(it, bool) or not 1 <= it <= MAX_SMOOTH_ITER:
                return f"{target}: iterations must be 1..{MAX_SMOOTH_ITER}"
        else:
            return f"unknown proposal kind {kind}"
        return None

    def step(self) -> list[tuple[str, str]]:
        """AI 1라운드 (스레드 안전, bpy 미사용). 추가로 렌더할 (포즈, 뷰) 목록을 반환하고 끝나면 done=True."""
        result = self.backend.run_json(SYSTEM_PROMPT, self.prompt(), self._images(), self.schema())
        self.rounds += 1
        if not isinstance(result, dict):
            raise ValueError("검토 응답이 JSON 객체가 아닙니다.")
        self.rejected = []
        for p in result.get("proposals") or []:
            error = self.validate(p)
            if error:
                self.rejected.append(error)
                continue
            if p["kind"] == "move_joint":
                new = Proposal("move_joint", p["target"], (float(p["dx"]), float(p["dy"]), float(p["dz"])), 0, p["reason"])
            else:
                new = Proposal("smooth_weights", p["target"], iterations=int(p["iterations"]), reason=p["reason"])
            # 같은 대상·종류의 이전 제안은 최신 것으로 바꾼다
            self.proposals = [q for q in self.proposals if (q.kind, q.target) != (new.kind, new.target)] + [new]
        if isinstance(result.get("summary"), str) and result["summary"].strip():
            self.summary = result["summary"].strip()
        requests = []
        for r in result.get("render_requests") or []:
            if isinstance(r, dict) and r.get("pose") in self.poses and r.get("view") in ("front", "side"):
                key = (r["pose"], r["view"])
                if key not in requests:
                    requests.append(key)
        requests = requests[:MAX_RENDER_REQUESTS]
        # 거부된 제안이 있으면 렌더 요청이 없어도 한 라운드 더 줘서 고쳐 보낼 기회를 준다
        if result.get("done") is True or self.rounds >= self.max_rounds or (not requests and not self.rejected):
            self.done = True
            if not self.summary:
                self.summary = "검토 라운드 한도에 도달했습니다." if self.rounds >= self.max_rounds else "검토를 마쳤습니다."
            return []
        return requests

    def add_renders(self, renders: list[tuple[str, bytes]]):
        self.extra_images.extend(renders)
