"""Landmark Agent 프롬프트·응답 스키마·검증 (SDK·bpy 비의존)."""

from __future__ import annotations

import json

VIEW_NAMES = ("front", "side")

CENTER_JOINTS = {
    "BIPED": ("head_top", "head_base", "neck_base", "spine_base"),
    "QUADRUPED": ("head_tip", "head_base", "neck_base", "spine_root"),
}
PAIRED_JOINTS = {
    "BIPED": ("shoulder", "elbow", "wrist", "hand_tip", "hip", "knee", "ankle", "toe_tip"),
    "QUADRUPED": ("f_shoulder", "f_elbow", "f_wrist", "f_paw", "r_hip", "r_knee", "r_hock", "r_paw"),
}
JOINT_DESCRIPTIONS = {
    "head_top": "top of the head",
    "head_base": "base of the skull where the head meets the neck",
    "neck_base": "base of the neck between the shoulders",
    "spine_base": "pelvis center, at hip-joint height",
    "head_tip": "tip of the nose or snout",
    "spine_root": "pelvis center above the hind legs",
    "shoulder": "shoulder joint (upper arm pivot)",
    "elbow": "elbow joint",
    "wrist": "wrist joint",
    "hand_tip": "tip of the hand or fingers",
    "hip": "hip joint (thigh pivot)",
    "knee": "knee joint",
    "ankle": "ankle joint",
    "toe_tip": "tip of the foot",
    "f_shoulder": "front leg shoulder joint (upper foreleg pivot)",
    "f_elbow": "front leg elbow",
    "f_wrist": "front leg wrist (carpus)",
    "f_paw": "front paw or hoof contact point",
    "r_hip": "hind leg hip joint",
    "r_knee": "hind leg knee (stifle)",
    "r_hock": "hind leg hock (ankle)",
    "r_paw": "hind paw or hoof contact point",
}


def joint_names(kind: str) -> list[str]:
    names = list(CENTER_JOINTS[kind])
    for j in PAIRED_JOINTS[kind]:
        names += [f"{j}_L", f"{j}_R"]
    return names


def response_schema(kind: str) -> dict:
    point = {
        "type": "object",
        "properties": {
            "u": {"type": "number"},
            "v": {"type": "number"},
            "visible": {"type": "boolean"},
            "confidence": {"type": "number"},
        },
        "required": ["u", "v", "visible", "confidence"],
        "additionalProperties": False,
    }
    names = joint_names(kind)
    view = {
        "type": "object",
        "properties": {n: point for n in names},
        "required": names,
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "body_type": {"type": "string", "enum": ["BIPED", "QUADRUPED", "OTHER"]},
            "front": view,
            "side": view,
            "notes": {"type": "string"},
        },
        "required": ["body_type", "front", "side", "notes"],
        "additionalProperties": False,
    }


SYSTEM_PROMPT = """You locate skeletal joints on orthographic renders of an unrigged 3D character so that a \
rigging tool can place bones. Coordinates you return are normalized image coordinates: u runs 0 (left edge) to \
1 (right edge), v runs 0 (top edge) to 1 (bottom edge). Place each joint where the bone pivot sits inside the \
body volume, not on the surface outline. Mark a joint visible=false only when it cannot be located in that view. \
confidence is your probability (0 to 1) that the point is within a few percent of the true pivot."""


def user_prompt(kind: str, facing_note: str) -> str:
    lines = [
        f"Body type expected by the geometric pre-pass: {kind}.",
        "Image 1 is the FRONT view. " + facing_note,
        "Image 2 is the SIDE view, seen from the character's left side; the character faces the image LEFT.",
        "In the side view, left and right limbs overlap: give each side's joint where that limb is, "
        "using the same position for both sides if they coincide.",
        "Joints (suffix _L = character's left, _R = character's right):",
    ]
    for name in joint_names(kind):
        base = name[:-2] if name.endswith(("_L", "_R")) else name
        lines.append(f"- {name}: {JOINT_DESCRIPTIONS[base]}")
    lines.append("If the character is not the expected body type, say so in body_type and notes.")
    return "\n".join(lines)


class LandmarkResponseError(ValueError):
    pass


def parse_response(text: str, kind: str) -> dict:
    """구조화 출력 JSON 을 파싱·검증한다. 좌표 범위·신뢰도를 0~1 로 제한한다."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LandmarkResponseError(f"JSON 파싱 실패: {exc}") from exc
    for view in VIEW_NAMES:
        joints = data.get(view)
        if not isinstance(joints, dict):
            raise LandmarkResponseError(f"{view} 뷰가 없습니다.")
        for name in joint_names(kind):
            e = joints.get(name)
            if not isinstance(e, dict) or not all(k in e for k in ("u", "v", "visible", "confidence")):
                raise LandmarkResponseError(f"{view}.{name} 항목이 올바르지 않습니다.")
            for k in ("u", "v", "confidence"):
                e[k] = min(1.0, max(0.0, float(e[k])))
            e["visible"] = bool(e["visible"])
    return data
