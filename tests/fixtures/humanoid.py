"""정답 관절이 알려진 박스 조합 인간형 테스트 메시 (bpy 비의존).

Blender 런타임 테스트와 순수 Python 단위 테스트가 같은 형상·정답을 공유한다.
"""

from __future__ import annotations

from math import cos, radians, sin, sqrt

VARIANTS = {
    # 사실 비율 T-포즈
    "realistic_t": dict(head=1.0, leg=1.0, arm=1.0, arm_angle=0.0),
    # 사실 비율 A-포즈(팔 40° 하강)
    "realistic_a": dict(head=1.0, leg=1.0, arm=1.0, arm_angle=40.0),
    # 과장 비율: 큰 머리, 짧은 다리·팔
    "stylized_t": dict(head=2.0, leg=0.6, arm=0.75, arm_angle=0.0),
}


def _norm(v):
    length = sqrt(sum(c * c for c in v))
    return tuple(c / length for c in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _box(center, half):
    cx, cy, cz = center
    hx, hy, hz = half
    verts = [(cx + sx * hx, cy + sy * hy, cz + sz * hz) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    return verts


def _segment_box(a, b, thick, depth=None):
    """a→b 축을 따라 단면 thick×depth 인 직육면체 정점 8개."""
    depth = depth or thick
    d = _norm((b[0] - a[0], b[1] - a[1], b[2] - a[2]))
    ref = (0.0, 1.0, 0.0) if abs(d[1]) < 0.9 else (1.0, 0.0, 0.0)
    u = _norm(_cross(d, ref))
    v = _norm(_cross(d, u))
    verts = []
    for p in (a, b):
        for su in (-1, 1):
            for sv in (-1, 1):
                verts.append(tuple(p[i] + su * u[i] * thick / 2 + sv * v[i] * depth / 2 for i in range(3)))
    # _box 와 같은 인덱스 규칙(축 인덱스: 0=길이, 1=u, 2=v)으로 정렬
    return [verts[i] for i in (0, 1, 2, 3, 4, 5, 6, 7)]


# 정점 8개(인덱스 비트: 4=첫째 축, 2=둘째 축, 1=셋째 축)의 12개 삼각형
_BOX_TRIS = [
    (0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5),
    (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6),
    (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3),
]


def build(variant: str = "realistic_t"):
    """(vertices, triangles, ground_truth_joints) 반환. 정면 -Y, 왼쪽 +X, 바닥 z=0."""
    return build_from(VARIANTS[variant])


def build_from(cfg: dict):
    leg_len = 0.82 * cfg["leg"]
    hip_z = leg_len + 0.08
    torso_top = hip_z + 0.65
    head_h = 0.22 * cfg["head"]
    head_hw = 0.1 * cfg["head"]

    gt = {}
    parts = []
    for name, s in (("L", 1.0), ("R", -1.0)):
        hip = (s * 0.1, 0.0, hip_z)
        knee = (s * 0.1, 0.0, 0.08 + 0.5 * leg_len)
        ankle = (s * 0.1, 0.0, 0.08)
        parts.append(_segment_box(hip, knee, 0.12))
        parts.append(_segment_box(knee, ankle, 0.1))
        parts.append(_box((s * 0.1, -0.06, 0.04), (0.05, 0.12, 0.04)))
        shoulder = (s * 0.19, 0.0, torso_top - 0.08)
        ang = radians(cfg["arm_angle"])
        direction = (s * cos(ang), 0.0, -sin(ang))
        arm_len = 0.7 * cfg["arm"]
        elbow = tuple(shoulder[i] + direction[i] * 0.42 * arm_len for i in range(3))
        wrist = tuple(shoulder[i] + direction[i] * 0.78 * arm_len for i in range(3))
        tip = tuple(shoulder[i] + direction[i] * arm_len for i in range(3))
        parts.append(_segment_box(shoulder, elbow, 0.09))
        parts.append(_segment_box(elbow, wrist, 0.08))
        parts.append(_segment_box(wrist, tip, 0.07, 0.03))
        gt.update({
            f"hip_{name}": hip, f"knee_{name}": knee, f"ankle_{name}": ankle,
            f"shoulder_{name}": shoulder, f"elbow_{name}": elbow, f"wrist_{name}": wrist,
            f"hand_tip_{name}": tip,
        })
    # 골반이 다리 상단을 덮도록 몸통을 hip 아래까지 내린다
    parts.append(_box((0.0, 0.0, 0.5 * (hip_z - 0.06 + torso_top)), (0.17, 0.1, 0.5 * (torso_top - hip_z + 0.06))))
    parts.append(_box((0.0, 0.0, torso_top + 0.04), (0.05, 0.05, 0.04)))
    head_base = torso_top + 0.08
    parts.append(_box((0.0, 0.0, head_base + head_h / 2), (head_hw, 0.11 * cfg["head"], head_h / 2)))
    gt["head_base"] = (0.0, 0.0, head_base)
    gt["head_top"] = (0.0, 0.0, head_base + head_h)

    verts, tris = [], []
    for p in parts:
        base = len(verts)
        verts.extend(p)
        tris.extend((base + a, base + b, base + c) for a, b, c in _BOX_TRIS)
    return verts, tris, gt
