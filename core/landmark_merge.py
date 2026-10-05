"""AI 관절 추정과 휴리스틱 결과 병합, IK 굽힘 방향 보정 (bpy 비의존)."""

from __future__ import annotations

from math import dist
from typing import Mapping

from .triangulate import OrthoView, intersect_rays

Vec = tuple[float, float, float]

MIN_CONFIDENCE = 0.5
# AI 결과 최대 반영 비율 (신뢰도 1.0 일 때)
AI_WEIGHT = 0.8
# 휴리스틱과 이 거리(크기 대비) 이상 벌어진 AI 결과는 오인식으로 보고 버린다
MAX_DEVIATION = 0.2
# 굽힘 최소 오프셋 (분절 길이 대비)
MIN_BEND = 0.03

# (관절, 기준 시작, 기준 끝, 굽힘 방향 +1=정면 쪽/-1=뒤쪽)
BEND_RULES = {
    "BIPED": (("knee", "hip", "ankle", 1.0), ("elbow", "shoulder", "wrist", -1.0)),
    "QUADRUPED": (
        ("r_knee", "r_hip", "r_hock", 1.0),
        ("r_hock", "r_knee", "r_paw", -1.0),
        ("f_elbow", "f_shoulder", "f_wrist", -1.0),
    ),
}


def triangulate_joints(ai: Mapping, views: Mapping[str, OrthoView]) -> dict[str, tuple[Vec, float]]:
    """AI 응답(뷰별 정규화 좌표) → {관절: (3D 좌표, 신뢰도)}. 두 뷰 이상에서 보인 관절만."""
    out: dict[str, tuple[Vec, float]] = {}
    joint_names = set()
    for view_name in views:
        joint_names.update(ai.get(view_name, {}).keys())
    for joint in joint_names:
        rays, confs = [], []
        for view_name, view in views.items():
            entry = ai.get(view_name, {}).get(joint)
            if not entry or not entry.get("visible"):
                continue
            rays.append(view.ray(float(entry["u"]), float(entry["v"])))
            confs.append(float(entry["confidence"]))
        if len(rays) >= 2:
            try:
                out[joint] = (intersect_rays(rays), min(confs))
            except ValueError:
                continue
    return out


def merge(heuristic: Mapping[str, Vec], ai3d: Mapping[str, tuple[Vec, float]], size: float) -> tuple[dict[str, Vec], list[str]]:
    """신뢰도 가중으로 AI 관절을 휴리스틱에 섞는다. (병합 결과, 반영된 관절 목록)."""
    merged = dict(heuristic)
    used = []
    for joint, (p, conf) in ai3d.items():
        base = heuristic.get(joint)
        if base is None or conf < MIN_CONFIDENCE:
            continue
        if dist(p, base) / size > MAX_DEVIATION:
            continue
        w = AI_WEIGHT * min(1.0, (conf - MIN_CONFIDENCE) / (1.0 - MIN_CONFIDENCE))
        merged[joint] = tuple(base[i] + (p[i] - base[i]) * w for i in range(3))
        used.append(joint)
    return merged, sorted(used)


def enforce_bends(joints: dict[str, Vec], kind: str, facing: str) -> dict[str, Vec]:
    """무릎·팔꿈치 등이 IK 극 방향을 정할 만큼 올바른 쪽으로 굽어 있게 보정한다."""
    fwd = -1.0 if facing == "-Y" else 1.0  # 정면 방향의 Y 부호
    out = dict(joints)
    for joint, a, b, direction in BEND_RULES[kind]:
        for side in ("L", "R"):
            j, pa, pb = f"{joint}_{side}", f"{a}_{side}", f"{b}_{side}"
            if not all(k in out for k in (j, pa, pb)):
                continue
            mid_y = 0.5 * (out[pa][1] + out[pb][1])
            length = dist(out[pa], out[pb])
            need = MIN_BEND * length
            # 정면 방향 기준 오프셋 (양수 = 정면 쪽)
            offset = (out[j][1] - mid_y) * fwd * direction
            if offset < need:
                x, y, z = out[j]
                out[j] = (x, y + (need - offset) * fwd * direction, z)
    return out
