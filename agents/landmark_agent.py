"""Landmark Agent: 직교 렌더 2장 → Claude 비전 → 뷰별 관절 좌표 → 3D 복원·휴리스틱 병합."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.landmark_merge import enforce_bends, merge, triangulate_joints
from ..core.triangulate import OrthoView
from . import claude_client, landmark_schema

FRONT_NOTE = "The character faces the camera, so the character's LEFT side appears on the IMAGE RIGHT."


@dataclass
class LandmarkResult:
    joints: dict
    used_joints: list[str]
    body_type: str
    notes: str
    warnings: list[str] = field(default_factory=list)
    request_id: str = ""


def ask(client, settings, kind: str, images: dict[str, bytes]) -> tuple[dict, str]:
    """Claude 호출만 수행한다 (백그라운드 스레드에서 실행 가능, bpy 접근 없음)."""
    content = [
        claude_client.image_block(images["front"]),
        claude_client.image_block(images["side"]),
        {"type": "text", "text": landmark_schema.user_prompt(kind, FRONT_NOTE)},
    ]
    text, message = claude_client.request_json(
        client, settings, landmark_schema.SYSTEM_PROMPT, content, landmark_schema.response_schema(kind)
    )
    return landmark_schema.parse_response(text, kind), getattr(message, "airig_request_id", "") or ""


def combine(kind: str, facing: str, heuristic: dict, ai: dict, views: dict[str, OrthoView], size: float, symmetric: bool):
    """AI 응답을 3D 로 복원해 휴리스틱과 병합한다 (메인 스레드)."""
    warnings = []
    # 프롬프트의 _L 과 리그 .L 은 모두 해부학적 왼쪽이므로 정면 방향과 무관하게 그대로 쓴다
    ai3d = triangulate_joints(ai, views)
    merged, used = merge(heuristic, ai3d, size)
    if symmetric:
        cx = sum(v[0] for k, v in merged.items() if not k.endswith(("_L", "_R"))) / max(
            1, sum(1 for k in merged if not k.endswith(("_L", "_R")))
        )
        for k in [k for k in merged if k.endswith("_L")]:
            r = k[:-2] + "_R"
            if r in merged:
                lp, rp = merged[k], merged[r]
                off = 0.5 * ((lp[0] - cx) - (rp[0] - cx))
                y, z = 0.5 * (lp[1] + rp[1]), 0.5 * (lp[2] + rp[2])
                merged[k], merged[r] = (cx + off, y, z), (cx - off, y, z)
    merged = enforce_bends(merged, kind, facing)
    if ai.get("body_type") not in (kind, None):
        warnings.append(f"AI 가 체형을 {ai.get('body_type')} 로 판단했습니다: {ai.get('notes', '')}")
    if not used:
        warnings.append("AI 관절 추정이 신뢰도·일관성 기준을 통과하지 못해 휴리스틱 결과만 사용했습니다.")
    return LandmarkResult(merged, used, ai.get("body_type", ""), ai.get("notes", ""), warnings)
