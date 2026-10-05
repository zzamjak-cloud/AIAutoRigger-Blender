"""Motion Agent: 자연어 프롬프트 → 동작(루프·단발) 파라미터, 프레임 렌더 검토 → 파라미터 보정 (bpy 비의존).

AI 는 키를 직접 찍지 않고 동작 생성기의 파라미터만 정한다. 발 고정·루프 이음새·단발 동작 구조는 생성기가 보장한다.
"""

from __future__ import annotations

try:
    from ..core import locomotion
except ImportError:  # 단위 테스트에서 애드온 패키지 밖(core 최상위)으로 불러올 때
    from core import locomotion

DESCRIPTIONS = {
    "motion": "WALK, RUN, IDLE, HAPPY (loops) or JUMP, ATTACK, HIT, DEATH (one-shot clips)",
    "cycle_frames": "frames per loop or clip length (at 24 fps: walk 28-48, run 16-26, idle 60-120, happy 36-60, "
                    "jump 30-44, attack 22-40, hit 18-32, death 40-72; scale for other fps)",
    "duty": "WALK/RUN: fraction of the cycle each foot is on the ground (walk ~0.6, run ~0.35)",
    "stride": "WALK/RUN: distance a planted foot travels per step / leg length (walk ~0.55, shuffle ~0.3, run ~0.75); "
              "JUMP: forward distance with root motion; ATTACK: lunge distance; HIT: knockback distance",
    "step_height": "WALK/RUN: foot lift / leg length; HAPPY: hop height (0 = no hop)",
    "bounce": "vertical body bob / leg length",
    "sway": "side-to-side body sway / leg length",
    "crouch": "how much the body is lowered with bent knees / leg length; JUMP/ATTACK/DEATH: depth of the wind-up squat",
    "lean_deg": "forward torso lean in degrees; HIT: negative = thrown back",
    "hip_yaw_deg": "hip twist following the legs, degrees; ATTACK: torso twist of the swing",
    "chest_counter_deg": "chest counter-twist, degrees; ATTACK: extra chest twist; HIT: chest arch",
    "toe_roll_deg": "heel-toe roll of the feet, degrees (also the toe-off at a jump launch)",
    "arm_swing": "arm swing amplitude / arm length; HAPPY: arm pumping; HIT/DEATH: arms flung outward",
    "arm_forward": "hands held forward / arm length (zombie reach ~0.6); ATTACK: reach of the swinging hand",
    "arm_raise": "hands raised / arm length; HAPPY: how high the arms are held; JUMP: arms thrown up; ATTACK: wind-up height",
    "arm_inward": "hands brought toward the body center / arm length (bring A-pose arms in front of the chest)",
    "head_pitch_deg": "head bent forward (+) or back (-), degrees; HIT/DEATH: head snap",
    "head_roll_deg": "head tilted to the side, degrees",
    "head_bob_deg": "head bobbing amplitude, degrees",
    "limp_side": "NONE, L or R: which leg is dragged (WALK/RUN)",
    "limp": "0..1 strength of the limp / dragged leg",
    "jump_height": "JUMP: jump height / leg length",
    "anticipation": "one-shot clips: fraction of the clip spent on the wind-up (squat, pulling the arm back, knees buckling)",
    "attack_side": "ATTACK: L or R, the swinging hand",
    "fall_dir": "DEATH: BACK (falls on the back) or FRONT (falls face down)",
    "root_motion": "true to move forward in the scene (WALK, RUN, JUMP only), false for in-place (game engines usually want false)",
}

MOTION_NOTES = ("Motions: WALK, RUN, IDLE and HAPPY (arms up, pumping, small hops) are seamless loops. JUMP (squat, launch, "
                "tuck in the air, land and recover), ATTACK (wind up one hand, twist, lunge and swing, recover), HIT (recoil "
                "back, arms flung out, recover) and DEATH (knees buckle, fall BACK or FRONT, lie still) are one-shot clips "
                "that play once. Each parameter description says which motions use it; the others ignore it.")

SYSTEM = ("You design character animation clips for a game: locomotion loops and one-shot actions. A procedural "
          "generator turns your parameters into a clean Bezier-keyed clip on a Rigify control rig: feet stay planted, "
          "loops are seamless and one-shot clips start from the rest pose, so only choose parameters that express the "
          "requested motion and style. Stay inside the given ranges.")

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
        elif name == "attack_side":
            props[name] = {"type": "string", "enum": ["L", "R"]}
        elif name == "fall_dir":
            props[name] = {"type": "string", "enum": ["BACK", "FRONT"]}
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
    lines = [MOTION_NOTES, "Parameters (name: meaning [range]):"]
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
    lines.append("Return the parameters for the requested motion. done is ignored here; summary: one short sentence.")
    return "\n".join(lines)


def review_prompt(prompt: str, params: locomotion.GaitParams, labels: list[str], measured: str = "") -> str:
    lines = [f'Request: "{prompt}"', "Images (in order; side views from the character's left, t = fraction of the "
             "cycle or clip): " + ", ".join(labels)]
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
