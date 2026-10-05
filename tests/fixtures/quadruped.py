"""정답 관절이 알려진 박스 조합 4족 테스트 메시 (bpy 비의존). 머리 -Y, 왼쪽 +X, 바닥 z=0."""

from __future__ import annotations

from humanoid import _BOX_TRIS, _box, _segment_box

VARIANTS = {
    # 개 비율
    "dog": dict(leg=1.0, head=1.0, tail=1.0, body=1.0),
    # 과장 비율: 큰 머리, 짧은 다리, 긴 몸통
    "stylized_quad": dict(leg=0.55, head=1.8, tail=0.6, body=1.3),
}


def build(variant: str = "dog"):
    return build_from(VARIANTS[variant])


def build_from(cfg: dict):
    leg_h = 0.55 * cfg["leg"]
    body_half = 0.4 * cfg["body"]
    belly = leg_h
    back = belly + 0.3
    front_y, rear_y = -body_half + 0.1, body_half - 0.1
    parts = []
    gt = {}
    for side, s in (("L", 1.0), ("R", -1.0)):
        x = s * 0.1
        # 뒷다리: 엉덩이 → 무릎(앞) → 비절(뒤) → 발
        hip = (x, rear_y, belly + 0.12)
        knee = (x, rear_y - 0.04, 0.64 * hip[2])
        hock = (x, rear_y + 0.03, 0.33 * hip[2])
        paw = (x, rear_y, 0.03)
        for a, b in ((hip, knee), (knee, hock), (hock, paw)):
            parts.append(_segment_box(a, b, 0.07))
        parts.append(_box((x, rear_y - 0.04, 0.025), (0.04, 0.07, 0.025)))
        # 앞다리: 어깨 → 팔꿈치(뒤) → 손목 → 발
        shoulder = (x, front_y, belly + 0.14)
        elbow = (x, front_y + 0.03, belly)
        wrist = (x, front_y, 0.19 * shoulder[2])
        fpaw = (x, front_y, 0.03)
        for a, b in ((shoulder, elbow), (elbow, wrist), (wrist, fpaw)):
            parts.append(_segment_box(a, b, 0.07))
        parts.append(_box((x, front_y - 0.04, 0.025), (0.04, 0.07, 0.025)))
        gt.update({
            f"r_hip_{side}": hip, f"r_knee_{side}": knee, f"r_hock_{side}": hock,
            f"f_shoulder_{side}": shoulder, f"f_elbow_{side}": elbow, f"f_wrist_{side}": wrist,
        })
    parts.append(_box((0.0, 0.0, 0.5 * (belly + back)), (0.15, body_half, 0.15)))
    neck_base = (0.0, -body_half + 0.05, back - 0.05)
    head_base = (0.0, -body_half - 0.15, back + 0.12)
    parts.append(_segment_box(neck_base, head_base, 0.1))
    hs = 0.12 * cfg["head"]
    parts.append(_box((0.0, head_base[1] - hs, head_base[2] + 0.02), (0.08 * cfg["head"], hs, 0.08 * cfg["head"])))
    tail_base = (0.0, body_half - 0.02, back - 0.05)
    tail_tip = (0.0, body_half + 0.35 * cfg["tail"], back - 0.1)
    parts.append(_segment_box(tail_base, tail_tip, 0.04))
    gt["head_base"] = head_base
    gt["tail_tip"] = tail_tip

    verts, tris = [], []
    for p in parts:
        base = len(verts)
        verts.extend(p)
        tris.extend((base + a, base + b, base + c) for a, b, c in _BOX_TRIS)
    return verts, tris, gt
