"""Motion Agent: 자연어 프롬프트 → 동작 파라미터 또는 포즈 시퀀스(클립), 프레임 렌더 검토 → 보정 (bpy 비의존).

AI 는 키를 직접 찍지 않는다. 두 가지 중 하나를 고른다.
- PARAMS: 걷기·달리기 등 절차 생성기의 파라미터만 정한다 (발 고정·루프 이음새는 생성기가 보장).
- CLIP: 제한된 포즈 언어로 극점 포즈를 쓴다. 동작 사전의 비슷한 항목을 바탕으로 변형하거나 새로 설계한다.
  바닥 관통·루프 닫기·범위는 poseclip 이 보장한다.
"""

from __future__ import annotations

try:
    from ..core import locomotion, poseclip
except ImportError:  # 단위 테스트에서 애드온 패키지 밖(core 최상위)으로 불러올 때
    from core import locomotion, poseclip

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
    "attack_kind": "ATTACK trajectory: SWING (horizontal swing across the body), THRUST (straight stab), SLASH_H (high "
                   "wind-up, horizontal cut), SLASH_V (overhead to front, vertical cut), OVERHEAD (heavy chop down to the ground)",
    "two_handed": "ATTACK: true when the weapon is held with both hands (the other hand follows the grip instead of guarding)",
    "fall_dir": "DEATH: BACK (falls on the back) or FRONT (falls face down)",
    "root_motion": "true to move forward in the scene (WALK, RUN, JUMP only), false for in-place (game engines usually want false)",
}

MOTION_NOTES = ("PARAMS motions: WALK, RUN, IDLE and HAPPY (arms up, pumping, small hops) are seamless loops. JUMP (squat, "
                "launch, tuck in the air, land and recover), ATTACK (wind up one hand, twist, lunge and swing/thrust/slash/chop, "
                "recover), HIT (recoil back, arms flung out, recover) and DEATH (knees buckle, fall BACK or FRONT, lie still) "
                "are one-shot clips that play once. Each parameter description says which motions use it; the others ignore it.")

CLIP_SPEC = """CLIP format (pose sequence): {"name": "snake_case id", "loop": bool, "frames": int, "root_distance": number, \
"keys": [key, ...]} with at most 12 keys. Each key: {"t": 0..1 fraction of the clip, "ease": "BEZIER" or "LINEAR" (to the \
next key), "rest": true to put every control at the rest pose at that time, and one entry per control: "torso", "hips", \
"chest", "head", "hand_L", "hand_R", "foot_L", "foot_R", each either null (no key for that control at this time) or an object. \
Position fields side/fwd/up are character-relative offsets from the rest pose: side>0 = character's left, fwd>0 = in front, \
up>0 = higher; units are leg lengths for torso and feet and arm lengths for hands. Rotation fields pitch/roll/yaw are degrees: \
pitch>0 bends forward (for a hand: tilts the held weapon tip down), roll>0 tilts to the character's right, yaw>0 turns to the \
left. torso has side/fwd/up/pitch/roll/yaw (hips/chest/head only rotations, relative to their parent). hand_L/hand_R \
positions are relative to the moving torso, so a hand that keeps its offset moves with the body; the rest pose is an A-pose \
with the hands beside the hips, so hands in front of the chest need fwd~0.5, up~0.4 and side toward the body center \
(hand_R side>0, hand_L side<0, ~0.3-0.6 when both hands meet). foot_L/foot_R have side/fwd/up/pitch/roll/yaw/heel (heel>0 \
lifts the heel for a toe roll); up==0 means planted, and planted feet never slide. A control with no key at all stays at \
rest. Loops must not include t=1 (the generator closes them); one-shot clips start at t=0 and hold their last key, so end with \
"rest": true unless the pose should stay (sitting, lying). Controls omitted from a key are null."""

SYSTEM = ("You design character animation clips for a game. You never key bones directly: you either set parameters of a "
          "procedural generator (PARAMS mode) or write a short pose sequence in a constrained pose language (CLIP mode). "
          "Rigify control rig, feet stay planted unless lifted, loops are seamless, floor penetration is prevented, values "
          "are clamped to the given ranges. Use PARAMS for walking, running, idling and the listed one-shot motions when they "
          "match; use CLIP for anything else (weapon attacks, social and emote animations, poses) by adapting the closest "
          "library clip or designing a new one with 4-8 expressive key poses. Keep timing readable: wind-up, main action, "
          "follow-through, recovery.")

REVIEW_SYSTEM = SYSTEM + (" You are now reviewing rendered frames of the current clip against the request, together with "
                          "measured values of the generated clip. The renders and the measurements come from the same "
                          "animation: small motions can look almost identical between frames, so judge their size from the "
                          "measurements rather than assuming the pipeline is broken. If the motion already matches, set "
                          "done=true and return the same mode and content. Otherwise return the adjusted params or clip "
                          "(for a motion that is too subtle, enlarge the offsets, angles, stride or swings) and done=false. "
                          "Change only what is needed and keep the same mode unless the other one clearly fits better.")


def _num(nullable=False):
    return {"type": ["number", "null"]} if nullable else {"type": "number"}


def params_schema() -> dict:
    props = {}
    for name in locomotion.GaitParams.__dataclass_fields__:
        if name == "motion":
            props[name] = {"type": "string", "enum": list(locomotion.MOTIONS)}
        elif name == "limp_side":
            props[name] = {"type": "string", "enum": ["NONE", "L", "R"]}
        elif name == "attack_side":
            props[name] = {"type": "string", "enum": ["L", "R"]}
        elif name == "attack_kind":
            props[name] = {"type": "string", "enum": list(locomotion.ATTACK_KINDS)}
        elif name == "fall_dir":
            props[name] = {"type": "string", "enum": ["BACK", "FRONT"]}
        elif name in ("root_motion", "two_handed"):
            props[name] = {"type": "boolean"}
        elif name == "cycle_frames":
            props[name] = {"type": "integer"}
        else:
            props[name] = {"type": "number"}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def clip_schema() -> dict:
    def control(fields):
        return {"type": ["object", "null"], "properties": {f: _num() for f in fields}, "required": list(fields),
                "additionalProperties": False}

    key_props = {"t": _num(), "ease": {"type": "string", "enum": [locomotion.BEZIER, locomotion.LINEAR]}, "rest": {"type": "boolean"}}
    for c in poseclip.CONTROLS:
        key_props[c] = control(poseclip.FIELDS[c])
    key = {"type": "object", "properties": key_props, "required": list(key_props), "additionalProperties": False}
    props = {"name": {"type": "string"}, "loop": {"type": "boolean"}, "frames": {"type": "integer"},
             "root_distance": _num(), "keys": {"type": "array", "items": key}}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def schema() -> dict:
    """응답 스키마: mode 에 따라 params 또는 clip 중 하나를 채우고 나머지는 null."""
    params = params_schema()
    params["type"] = ["object", "null"]
    clip = clip_schema()
    clip["type"] = ["object", "null"]
    return {
        "type": "object",
        "properties": {"mode": {"type": "string", "enum": ["PARAMS", "CLIP"]}, "params": params, "clip": clip,
                       "done": {"type": "boolean"}, "summary": {"type": "string"}},
        "required": ["mode", "params", "clip", "done", "summary"],
        "additionalProperties": False,
    }


def _param_lines(current) -> list[str]:
    lines = [MOTION_NOTES, "PARAMS parameters (name: meaning [range]):"]
    for name, desc in DESCRIPTIONS.items():
        rng = locomotion.RANGES.get(name)
        lines.append(f"- {name}: {desc}" + (f" [{rng[0]}..{rng[1]}]" if rng else ""))
    lines.append(CLIP_SPEC)
    if isinstance(current, poseclip.ClipParams):
        lines.append("Current clip (CLIP mode, omitted controls are null): " + poseclip.compact(current.clip))
    elif current is not None:
        lines.append("Current parameters (PARAMS mode): " + str(current.to_dict()))
    return lines


def _library_lines(library) -> list[str]:
    if not library:
        return []
    lines = ["Motion library (CLIP examples you can copy and adapt; omitted controls are null):"]
    for e in library:
        lines.append(f"- {e.name}: {e.description} => {poseclip.compact(e.clip)}")
    return lines


def request_prompt(prompt: str, motion_hint: str, leg: float, arm: float, base, fps: int = 24, library=()) -> str:
    lines = [f'Request: "{prompt}"', f"Selected motion type in the UI: {motion_hint} (follow the request if it clearly asks for another).",
             f"Character: leg length {leg:.2f} m, arm length {arm:.2f} m. Scene frame rate: {fps} fps."]
    lines += _param_lines(base)
    lines += _library_lines(library)
    lines.append("Return mode PARAMS with params (clip null) or mode CLIP with clip (params null). done is ignored here; "
                 "summary: one short sentence naming the mode and, for CLIP, which library clip it was based on if any.")
    return "\n".join(lines)


def review_prompt(prompt: str, params, labels: list[str], measured: str = "", library=()) -> str:
    lines = [f'Request: "{prompt}"', "Images (in order; side views from the character's left, t = fraction of the "
             "cycle or clip): " + ", ".join(labels)]
    if measured:
        lines.append("Measured from the generated clip: " + measured)
    lines += _param_lines(params)
    lines += _library_lines(library)
    return "\n".join(lines)


def parse(data) -> tuple[object, bool, str]:
    """응답 → (GaitParams 또는 ClipParams, done, summary). mode 가 없으면 채워진 쪽을 쓴다."""
    if not isinstance(data, dict):
        raise ValueError("응답이 JSON 객체가 아닙니다.")
    mode = data.get("mode")
    clip, params = data.get("clip"), data.get("params")
    if mode is None:
        mode = "CLIP" if isinstance(clip, dict) and not isinstance(params, dict) else "PARAMS"
    done, summary = data.get("done") is True, str(data.get("summary") or "")
    if mode == "CLIP":
        if not isinstance(clip, dict):
            raise ValueError("응답에 clip 이 없습니다.")
        return poseclip.ClipParams(poseclip.clamp(clip)), done, summary
    if not isinstance(params, dict):
        raise ValueError("응답에 params 가 없습니다.")
    return locomotion.clamp(params), done, summary


def ask_params(backend, prompt, motion_hint, leg, arm, base, fps=24, library=()):
    data = backend.run_json(SYSTEM, request_prompt(prompt, motion_hint, leg, arm, base, fps, library), [], schema())
    return parse(data)


def ask_review(backend, prompt, params, images, measured="", library=()):
    data = backend.run_json(REVIEW_SYSTEM, review_prompt(prompt, params, [n for n, _ in images], measured, library), images, schema())
    return parse(data)
