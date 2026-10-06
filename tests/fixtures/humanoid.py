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
    # 비만 A-포즈: 넓은 몸통, 어깨 살에 묻힌 목, 발보다 깊은 굵은 다리
    "fat_a": dict(head=1.0, leg=0.8, arm=0.8, arm_angle=30.0, fat=True),
}
# 손가락 변형 (엄지 + 손가락 3개). 손은 별도 섬(hand_parts)으로 만들어 더 촘촘히 리메시한다
FINGER_VARIANTS = {
    "fingers_straight_t": dict(head=1.0, leg=1.0, arm=1.0, arm_angle=0.0, fingers="straight"),
    "fingers_claw_a": dict(head=1.0, leg=1.0, arm=1.0, arm_angle=40.0, fingers="claw"),
    # 엄지 + 갈라지지 않은 손가락 덩어리 (벙어리장갑형)
    "mitten_thumb_t": dict(head=1.0, leg=1.0, arm=1.0, arm_angle=0.0, fingers="mitten"),
}
# 변형별 손당 기대 손가락
EXPECTED_FINGERS = {
    "fingers_straight_t": ("thumb", "f_index", "f_middle", "f_ring"),
    "fingers_claw_a": ("thumb", "f_index", "f_middle", "f_ring"),
    "mitten_thumb_t": ("thumb", "f_middle"),
}
FINGERS = ("thumb", "f_index", "f_middle", "f_ring")


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
    return build_from({**VARIANTS, **FINGER_VARIANTS}[variant])


def _rot(v, axis, ang):
    """로드리게스 회전."""
    from math import cos, sin
    c, s = cos(ang), sin(ang)
    k = axis
    dot = sum(v[i] * k[i] for i in range(3))
    cr = _cross(k, v)
    return tuple(v[i] * c + cr[i] * s + k[i] * dot * (1 - c) for i in range(3))


def hand_parts(wrist, direction, side_sign, style):
    """손바닥 + 엄지 + 손가락 3개 박스. (parts, gt). style: straight | claw."""
    from math import radians as rad
    front = (0.0, -1.0, 0.0)
    n = _norm(tuple(c * side_sign for c in _cross(direction, front)))  # 손바닥 쪽(T-포즈에서 아래)
    across = _norm(tuple(c * side_sign for c in _cross(n, direction)))  # 정면(-Y) 쪽이 검지·엄지
    add = lambda a, b, s=1.0: tuple(a[i] + b[i] * s for i in range(3))  # noqa: E731
    parts, gt = [], {}
    knuckle = add(wrist, direction, 0.08)
    # 손 섬이 손목 고리를 포함하도록 팔뚝 쪽으로 6cm 늘린다 (실제 메시처럼 손목에서 측지 거리 출발)
    parts.append(_segment_box(add(wrist, direction, -0.06), add(wrist, direction, 0.005), 0.07, 0.07))
    parts.append(_segment_box(add(wrist, direction, -0.005), knuckle, 0.075, 0.026))
    bends = {"straight": (0.0, 0.0, 0.0), "claw": (rad(20), rad(35), rad(30)), "mitten": (0.0, 0.0, 0.0)}[style]
    lengths = (0.035, 0.026, 0.02)
    offsets = {"f_index": 0.024, "f_middle": 0.0, "f_ring": -0.024}
    if style == "mitten":
        # 손가락 4개가 붙은 덩어리: 손바닥보다 약간 좁고 얇다
        tip = add(knuckle, direction, 0.075)
        parts.append(_segment_box(add(knuckle, direction, -0.01), tip, 0.068, 0.02))
        gt["f_middle_base"], gt["f_middle_tip"] = knuckle, tip
        offsets = {}
    for name, off in offsets.items():
        p = add(knuckle, across, off)
        gt[f"{name}_base"] = p
        d = direction
        axis = _norm(_cross(d, n))
        for seg, (ln, bend) in enumerate(zip(lengths, bends)):
            d = _norm(_rot(d, axis, bend))
            q = add(p, d, ln)
            parts.append(_segment_box(p, q, 0.017, 0.015))
            p = q
        gt[f"{name}_tip"] = p
    tb = add(add(wrist, direction, 0.025), across, 0.04)
    td = _norm(add(_mul3(direction, 0.6), across, 0.8))
    gt["thumb_base"] = tb
    # 엄지 뿌리를 손바닥 안까지 묻어 리메시 후에도 손과 이어지게 한다
    parts.append(_segment_box(add(tb, td, -0.025), tb, 0.019, 0.016))
    p = tb
    # 엄지는 덜 굽혀 끝이 손바닥에 닿지 않게 한다 (닿으면 리메시로 붙어 손가락 끝이 사라진다)
    for ln, bend in zip((0.028, 0.022, 0.018), tuple(b * 0.4 for b in bends)):
        td = _norm(_rot(td, _norm(_cross(td, n)), bend))
        q = add(p, td, ln)
        parts.append(_segment_box(p, q, 0.019, 0.016))
        p = q
    gt["thumb_tip"] = p
    return parts, gt


def _mul3(v, s):
    return tuple(c * s for c in v)


def build_from(cfg: dict, split_hands: bool = False):
    """split_hands=True 이면 (몸 정점, 몸 삼각형, 정답, 손 정점, 손 삼각형) 을 돌려준다."""
    leg_len = 0.82 * cfg["leg"]
    hip_z = leg_len + 0.08
    torso_top = hip_z + 0.65
    head_h = 0.22 * cfg["head"]
    head_hw = 0.1 * cfg["head"]
    fat = cfg.get("fat", False)
    # 비만형은 다리가 굵어 가랑이 틈을 남기려고 다리 간격을 벌린다
    leg_x, thigh_w, shin_w = (0.17, 0.22, 0.2) if fat else (0.1, 0.12, 0.1)
    torso_hw, torso_hd = (0.3, 0.25) if fat else (0.17, 0.1)

    gt = {}
    parts = []
    hand_boxes = []
    for name, s in (("L", 1.0), ("R", -1.0)):
        hip = (s * leg_x, 0.0, hip_z)
        knee = (s * leg_x, 0.0, 0.08 + 0.5 * leg_len)
        ankle = (s * leg_x, 0.0, 0.08)
        parts.append(_segment_box(hip, knee, thigh_w))
        parts.append(_segment_box(knee, ankle, shin_w))
        parts.append(_box((s * leg_x, -0.06, 0.04), (0.07 if fat else 0.05, 0.13 if fat else 0.12, 0.04)))
        shoulder = (s * (torso_hw if fat else 0.19), 0.0, torso_top - 0.08)
        ang = radians(cfg["arm_angle"])
        direction = (s * cos(ang), 0.0, -sin(ang))
        arm_len = 0.7 * cfg["arm"]
        elbow = tuple(shoulder[i] + direction[i] * 0.42 * arm_len for i in range(3))
        wrist = tuple(shoulder[i] + direction[i] * 0.78 * arm_len for i in range(3))
        tip = tuple(shoulder[i] + direction[i] * arm_len for i in range(3))
        parts.append(_segment_box(shoulder, elbow, 0.09))
        if cfg.get("fingers"):
            # 손목을 조금 지나 손 섬과 겹치게 한다
            parts.append(_segment_box(elbow, tuple(wrist[i] + direction[i] * 0.01 for i in range(3)), 0.08))
            hp, hgt = hand_parts(wrist, direction, s, cfg["fingers"])
            hand_boxes.extend(hp)
            gt.update({f"{k}_{name}": v for k, v in hgt.items()})
            tip = hgt["f_middle_tip"]
        else:
            parts.append(_segment_box(elbow, wrist, 0.08))
            parts.append(_segment_box(wrist, tip, 0.07, 0.03))
        gt.update({
            f"hip_{name}": hip, f"knee_{name}": knee, f"ankle_{name}": ankle,
            f"shoulder_{name}": shoulder, f"elbow_{name}": elbow, f"wrist_{name}": wrist,
            f"hand_tip_{name}": tip,
        })
    # 골반이 다리 상단을 덮도록 몸통을 hip 아래까지 내린다
    parts.append(_box((0.0, 0.0, 0.5 * (hip_z - 0.06 + torso_top)), (torso_hw, torso_hd, 0.5 * (torso_top - hip_z + 0.06))))
    if fat:
        # 목 없이 어깨 살이 머리 아랫부분을 감싸며 좁아지고, 정수리는 머리보다 좁다
        head_base = torso_top + 0.02
        parts.append(_box((0.0, 0.05, torso_top + 0.025), (0.24, 0.2, 0.025)))
        parts.append(_box((0.0, 0.05, torso_top + 0.075), (0.16, 0.16, 0.025)))
        body_h = head_h - 0.05
        parts.append(_box((0.0, 0.0, head_base + body_h / 2), (head_hw, 0.11 * cfg["head"], body_h / 2)))
        parts.append(_box((0.0, 0.0, head_base + body_h + 0.025), (0.07, 0.08, 0.025)))
    else:
        parts.append(_box((0.0, 0.0, torso_top + 0.04), (0.05, 0.05, 0.04)))
        head_base = torso_top + 0.08
        parts.append(_box((0.0, 0.0, head_base + head_h / 2), (head_hw, 0.11 * cfg["head"], head_h / 2)))
    gt["head_base"] = (0.0, 0.0, head_base)
    gt["head_top"] = (0.0, 0.0, head_base + head_h)

    def mesh(boxes):
        verts, tris = [], []
        for p in boxes:
            base = len(verts)
            verts.extend(p)
            tris.extend((base + a, base + b, base + c) for a, b, c in _BOX_TRIS)
        return verts, tris

    if split_hands:
        return (*mesh(parts), gt, *mesh(hand_boxes))
    return (*mesh(parts + hand_boxes), gt)


def build_face_variant(cfg: dict | None = None):
    """입을 벌린 머리 + 별도 조각 눈동자. (몸 정점, 몸 삼각형, 정답, 머리 정점, 머리 삼각형, 눈 정점, 눈 삼각형).

    머리는 입 틈(2cm)이 리메시로 메워지지 않도록 별도 섬으로 촘촘히 리메시하고, 눈동자는 리메시하지 않는 별도 조각이다.
    """
    cfg = dict(cfg or VARIANTS["realistic_t"])
    bv, bt, gt = build_from(cfg)
    # build_from 의 머리 상자를 빼고 다시 만든다 (몸 메시는 상자 8정점 단위)
    head_base = gt["head_base"]
    hb, hh = head_base[2], gt["head_top"][2] - head_base[2]
    hx, hy = 0.1, 0.11
    nverts = len(bv) - 8
    bv, bt = bv[:nverts], [t for t in bt if max(t) < nverts]
    lip = hb + 0.3 * hh
    boxes = [
        _box((0.0, hy / 2, hb + hh / 2), (hx, hy / 2, hh / 2)),                       # 뒤통수
        _box((0.0, -hy / 2, (lip + 0.01 + hb + hh) / 2), (hx, hy / 2, (hb + hh - lip - 0.01) / 2)),  # 윗얼굴
        _box((0.0, -0.1 / 2, (hb + lip - 0.01) / 2), (hx * 0.9, 0.1 / 2, (lip - 0.01 - hb) / 2)),  # 아래턱
    ]
    eyes = []
    for s in (1.0, -1.0):
        c = (s * 0.045, -hy + 0.005, lip + 0.09)
        eyes.append(_box(c, (0.015, 0.015, 0.015)))
        gt[f"eye_{'L' if s > 0 else 'R'}"] = c
    gt["lip_z"] = lip
    gt["chin_bottom_z"] = hb

    def mesh(bx):
        verts, tris = [], []
        for p in bx:
            base = len(verts)
            verts.extend(p)
            tris.extend((base + a, base + b, base + c) for a, b, c in _BOX_TRIS)
        return verts, tris

    hv, ht = mesh(boxes)
    ev, et = mesh(eyes)
    return bv, bt, gt, hv, ht, ev, et
