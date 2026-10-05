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
    """점 배열 형식 스키마. 관절마다 속성을 두는 형식보다 훨씬 작아
    (Windows cmd.exe 명령줄 한도 8191자 안에 들어가도록) CLI 인자로 넘길 수 있다."""
    point = {
        "type": "object",
        "properties": {
            "view": {"type": "string", "enum": list(VIEW_NAMES)},
            "joint": {"type": "string", "enum": joint_names(kind)},
            "u": {"type": "number"},
            "v": {"type": "number"},
            "visible": {"type": "boolean"},
            "confidence": {"type": "number"},
        },
        "required": ["view", "joint", "u", "v", "visible", "confidence"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "body_type": {"type": "string", "enum": ["BIPED", "QUADRUPED", "OTHER"]},
            "points": {"type": "array", "items": point},
            "notes": {"type": "string"},
        },
        "required": ["body_type", "points", "notes"],
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
    lines.append("Return one entry in points for every joint in each of the two views (view = front or side).")
    lines.append("If the character is not the expected body type, say so in body_type and notes.")
    return "\n".join(lines)


class LandmarkResponseError(ValueError):
    pass


def parse_response(text: str, kind: str) -> dict:
    """구조화 출력 JSON 텍스트를 파싱·검증한다."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LandmarkResponseError(f"JSON 파싱 실패: {exc}") from exc
    return validate(data, kind)


def validate(data, kind: str) -> dict:
    """점 배열 응답을 뷰별 dict({view: {joint: entry}})로 정리·검증한다.

    좌표·신뢰도는 0~1 로 제한하고, 빠진 관절은 보이지 않음으로 둔다 (CLI 백엔드는 스키마 강제가 느슨할 수 있다).
    """
    if not isinstance(data, dict) or not isinstance(data.get("points"), list):
        raise LandmarkResponseError("응답에 points 배열이 없습니다.")
    names = set(joint_names(kind))
    out = {"body_type": data.get("body_type"), "notes": data.get("notes") if isinstance(data.get("notes"), str) else ""}
    views = {v: {} for v in VIEW_NAMES}
    for e in data["points"]:
        if not isinstance(e, dict) or e.get("view") not in views or e.get("joint") not in names:
            continue
        try:
            entry = {k: min(1.0, max(0.0, float(e[k]))) for k in ("u", "v", "confidence")}
        except (KeyError, TypeError, ValueError):
            continue
        entry["visible"] = e.get("visible") is True
        views[e["view"]][e["joint"]] = entry
    if not any(views.values()):
        raise LandmarkResponseError("유효한 관절 좌표가 하나도 없습니다.")
    for v in VIEW_NAMES:
        for n in names:
            views[v].setdefault(n, {"u": 0.5, "v": 0.5, "visible": False, "confidence": 0.0})
    out.update(views)
    return out
