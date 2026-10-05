"""Motion Agent: 자연어 프롬프트 → 이동 루프 파라미터, 프레임 렌더 검토 → 파라미터 보정 (bpy 비의존).

AI 는 키를 직접 찍지 않고 걸음 생성기의 파라미터만 정한다. 발 고정·루프 이음새는 생성기가 보장한다.
"""

from __future__ import annotations

try:
    from ..core import locomotion
except ImportError:  # 단위 테스트에서 애드온 패키지 밖(core 최상위)으로 불러올 때
    from core import locomotion

DESCRIPTIONS = {
    "motion": "WALK, RUN or IDLE",
    "cycle_frames": "frames per loop (at 24 fps: walk 28-48, run 16-26, idle 60-120; scale for other fps)",
    "duty": "fraction of the cycle each foot is on the ground (walk ~0.6, run ~0.35)",
    "stride": "distance a planted foot travels per step / leg length (walk ~0.55, shuffle ~0.3, run ~0.75)",
    "step_height": "foot lift / leg length",
    "bounce": "vertical body bob / leg length",
    "sway": "side-to-side body sway / leg length",
    "crouch": "how much the body is lowered with bent knees / leg length",
    "lean_deg": "forward torso lean in degrees",
    "hip_yaw_deg": "hip twist following the legs, degrees",
    "chest_counter_deg": "chest counter-twist, degrees",
    "toe_roll_deg": "heel-toe roll of the feet, degrees",
    "arm_swing": "arm swing amplitude / arm length",
    "arm_forward": "hands held forward / arm length (zombie reach ~0.6)",
    "arm_raise": "hands raised / arm length",
    "arm_inward": "hands brought toward the body center / arm length (bring A-pose arms in front of the chest)",
    "head_pitch_deg": "head bent forward (+) or back (-), degrees",
    "head_roll_deg": "head tilted to the side, degrees",
    "head_bob_deg": "head bobbing amplitude, degrees",
    "limp_side": "NONE, L or R: which leg is dragged",
    "limp": "0..1 strength of the limp / dragged leg",
    "root_motion": "true to move forward in the scene, false for in-place loop (game engines usually want false)",
}

SYSTEM = """You design looping character locomotion for a game. A procedural gait generator turns your parameters \
into a clean Bezier-keyed loop on a Rigify control rig: feet stay planted and the loop is seamless, so only choose \
parameters that express the requested style. Stay inside the given ranges."""

REVIEW_SYSTEM = SYSTEM + """ You are now reviewing rendered frames of the current loop against the request, together \
with measured values of the generated loop. The renders and the measurements come from the same animation: small \
motions can look almost identical between frames, so judge their size from the measurements rather than assuming the \
pipeline is broken. If the motion already matches, set done=true and keep the parameters. Otherwise return adjusted \
parameters (for a motion that is too subtle, increase stride, step_height, bounce or swings) and done=false. Change \
only what is needed."""


def schema() -> dict:
    props = {}
    for name in locomotion.GaitParams.__dataclass_fields__:
        if name == "motion":
            props[name] = {"type": "string", "enum": list(locomotion.MOTIONS)}
        elif name == "limp_side":
            props[name] = {"type": "string", "enum": ["NONE", "L", "R"]}
        elif name == "root_motion":
            props[name] = {"type": "boolean"}
        elif name == "cycle_frames":
            props[name] = {"type": "integer"}
        else:
            props[name] = {"type": "number"}
    params = {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}
    return {
        "type": "object",
        "properties": {"params": params, "done": {"type": "boolean"}, "summary": {"type": "string"}},
        "required": ["params", "done", "summary"],
        "additionalProperties": False,
    }


def _param_lines(current: locomotion.GaitParams | None) -> list[str]:
    lines = ["Parameters (name: meaning [range]):"]
    for name, desc in DESCRIPTIONS.items():
        rng = locomotion.RANGES.get(name)
        lines.append(f"- {name}: {desc}" + (f" [{rng[0]}..{rng[1]}]" if rng else ""))
    if current is not None:
        lines.append("Current parameters: " + str(current.to_dict()))
    return lines


def request_prompt(prompt: str, motion_hint: str, leg: float, arm: float, base: locomotion.GaitParams, fps: int = 24) -> str:
    lines = [f'Request: "{prompt}"', f"Selected motion type in the UI: {motion_hint} (follow the request if it clearly asks for another).",
             f"Character: leg length {leg:.2f} m, arm length {arm:.2f} m. Scene frame rate: {fps} fps."]
    lines += _param_lines(base)
    lines.append("Return the parameters for the requested loop. done is ignored here; summary: one short sentence.")
    return "\n".join(lines)


def review_prompt(prompt: str, params: locomotion.GaitParams, labels: list[str], measured: str = "") -> str:
    lines = [f'Request: "{prompt}"', "Images (in order; side views from the character's left, t = fraction of the "
             "cycle): " + ", ".join(labels)]
    if measured:
        lines.append("Measured from the generated loop: " + measured)
    lines += _param_lines(params)
    return "\n".join(lines)


def parse(data) -> tuple[locomotion.GaitParams, bool, str]:
    if not isinstance(data, dict) or not isinstance(data.get("params"), dict):
        raise ValueError("응답에 params 가 없습니다.")
    return locomotion.clamp(data["params"]), data.get("done") is True, str(data.get("summary") or "")


def ask_params(backend, prompt, motion_hint, leg, arm, base, fps=24):
    data = backend.run_json(SYSTEM, request_prompt(prompt, motion_hint, leg, arm, base, fps), [], schema())
    return parse(data)


def ask_review(backend, prompt, params, images, measured=""):
    data = backend.run_json(REVIEW_SYSTEM, review_prompt(prompt, params, [n for n, _ in images], measured), images, schema())
    return parse(data)
