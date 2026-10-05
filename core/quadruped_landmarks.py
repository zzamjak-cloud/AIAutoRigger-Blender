"""4족 캐릭터 관절 위치 휴리스틱 추정 (bpy 비의존).

전제: Z-up, 네 발로 선 자세, 몸통 길이 방향이 Y축. 머리 방향(-Y/+Y)은 자동 감지하며
내부 계산은 머리가 -Y 인 기준 좌표(Z축 180° 회전)로 수행한다. .L 은 해부학적 왼쪽.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Sequence

from .body_type import clusters_xy, leg_clusters

Point = tuple[float, float, float]

SLICE_COUNT = 80
# IK 극 방향 확정용 굽힘 오프셋 (다리 높이 대비)
BEND_RATIO = 0.04
# 이보다 짧은 꼬리는 없는 것으로 본다 (몸길이 대비)
MIN_TAIL_RATIO = 0.06


@dataclass
class QuadrupedLandmarks:
    joints: dict[str, Point]
    facing: str  # 머리 방향 "-Y" 또는 "+Y"
    size: float
    has_tail: bool
    warnings: list[str] = field(default_factory=list)


def _centroid(pts: Sequence[Point]) -> Point:
    n = len(pts)
    return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n, sum(p[2] for p in pts) / n)


def _lerp(a: Point, b: Point, t: float) -> Point:
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def estimate_quadruped(points: Sequence[Sequence[float]], symmetric: bool = True) -> QuadrupedLandmarks:
    pts: list[Point] = [(p[0], p[1], p[2]) for p in points]
    if len(pts) < 500:
        raise ValueError("관절 추정에 필요한 표면 샘플이 부족합니다.")
    warnings: list[str] = []
    zs = [p[2] for p in pts]
    zmin, zmax = min(zs), max(zs)
    H = zmax - zmin
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    size = max(H, max(xs) - min(xs), max(ys) - min(ys))
    cx = median(xs)

    legs = leg_clusters(pts, zmin, H, size)
    if len(legs) < 4:
        raise ValueError(f"4족 다리 4개를 찾지 못했습니다 (감지 {len(legs)}개).")
    legs = legs[:4]
    feet = [_centroid(c) for c in legs]

    # 머리 방향: 다리 영역 바깥으로 튀어나온 부분 중 더 높은 쪽이 머리
    y_lo = min(f[1] for f in feet)
    y_hi = max(f[1] for f in feet)
    front_part = [p for p in pts if p[1] < y_lo]
    back_part = [p for p in pts if p[1] > y_hi]
    front_top = max((p[2] for p in front_part), default=zmin)
    back_top = max((p[2] for p in back_part), default=zmin)
    facing = "-Y"
    if back_top > front_top:
        facing = "+Y"
        # Z축 180° 회전 (거울 반전이 아니므로 .L 은 해부학적 왼쪽을 유지)
        pts = [(2.0 * cx - p[0], -p[1], p[2]) for p in pts]
        legs = [[(2.0 * cx - p[0], -p[1], p[2]) for p in c] for c in legs]
        feet = [_centroid(c) for c in legs]

    order = sorted(range(4), key=lambda i: feet[i][1])
    front, rear = order[:2], order[2:]
    named = {}
    for group, prefix in ((front, "front"), (rear, "rear")):
        a, b = group
        left, right = (a, b) if feet[a][0] > feet[b][0] else (b, a)
        named[f"{prefix}_L"] = left
        named[f"{prefix}_R"] = right

    n = SLICE_COUNT
    dz = H / n
    buckets: list[list[Point]] = [[] for _ in range(n)]
    for p in pts:
        buckets[min(n - 1, int((p[2] - zmin) / dz))].append(p)
    cell = 0.02 * size

    # 각 다리 기둥: 다리 발자국과 이어진 단면 군집을 위로 추적하다가 몸통과 합쳐지면 멈춘다
    columns: dict[str, list[tuple[float, Point]]] = {}
    merge_z: dict[str, float] = {}
    foot_span = {key: max(p[1] for p in legs[i]) - min(p[1] for p in legs[i]) for key, i in named.items()}
    for key, i in named.items():
        fx, fy = feet[i][0], feet[i][1]
        col = []
        top = zmin + 0.5 * H
        for k in range(n):
            if not buckets[k]:
                continue
            comps = clusters_xy(buckets[k], cell)
            comp = min(
                comps,
                key=lambda c: min((p[0] - fx) ** 2 + (p[1] - fy) ** 2 for p in c),
            )
            span_y = max(p[1] for p in comp) - min(p[1] for p in comp)
            if k > 2 and span_y > 3.0 * max(foot_span[key], cell):
                top = zmin + k * dz
                break
            c = _centroid(comp)
            col.append((zmin + (k + 0.5) * dz, c))
            fx, fy = c[0], c[1]
        if len(col) < 3:
            raise ValueError("다리 기둥을 추적하지 못했습니다.")
        columns[key] = col
        merge_z[key] = top

    def col_at(key: str, z: float) -> Point:
        zz, c = min(columns[key], key=lambda e: abs(e[0] - z))
        return (c[0], c[1], z)

    belly_z = median(merge_z.values())
    front_y = 0.5 * (col_at("front_L", belly_z)[1] + col_at("front_R", belly_z)[1])
    rear_y = 0.5 * (col_at("rear_L", belly_z)[1] + col_at("rear_R", belly_z)[1])
    body_len = rear_y - front_y
    if body_len <= 0:
        raise ValueError("앞다리와 뒷다리를 구분하지 못했습니다.")

    def back_z_at(y: float) -> float:
        band = [p for p in pts if abs(p[1] - y) < 0.03 * size and abs(p[0] - cx) < 0.5 * size]
        return max((p[2] for p in band), default=zmax)

    joints: dict[str, Point] = {}
    # 다리
    for side, sign in (("L", 1.0), ("R", -1.0)):
        rk = f"rear_{side}"
        top_z = merge_z[rk]
        hip_y = col_at(rk, belly_z)[1]
        back = back_z_at(hip_y)
        leg_h = top_z - zmin
        hip = (col_at(rk, top_z)[0], hip_y, top_z + 0.55 * (back - top_z))
        knee = col_at(rk, zmin + 0.64 * (hip[2] - zmin))
        hock = col_at(rk, zmin + 0.33 * (hip[2] - zmin))
        paw = col_at(rk, zmin + 0.055 * (hip[2] - zmin))
        toe_y = min(p[1] for p in legs[named[rk]])
        joints[f"r_hip_{side}"] = hip
        # 뒷무릎(stifle)은 앞으로, 비절(hock)은 뒤로 굽는다
        joints[f"r_knee_{side}"] = (knee[0], knee[1] - BEND_RATIO * leg_h, knee[2])
        joints[f"r_hock_{side}"] = (hock[0], hock[1] + BEND_RATIO * leg_h, hock[2])
        joints[f"r_paw_{side}"] = paw
        joints[f"r_toe_{side}"] = (paw[0], min(toe_y, paw[1] - 0.05 * leg_h), zmin)
        joints[f"pelvis_tip_{side}"] = (cx + sign * 0.6 * abs(hip[0] - cx), hip_y - 0.15 * body_len, back)

        fk = f"front_{side}"
        top_z = merge_z[fk]
        sh_y = col_at(fk, belly_z)[1]
        back = back_z_at(sh_y)
        leg_h = top_z - zmin
        shoulder = (col_at(fk, top_z)[0], sh_y, top_z + 0.45 * (back - top_z))
        elbow = col_at(fk, top_z)
        wrist = col_at(fk, zmin + 0.19 * (shoulder[2] - zmin))
        paw = col_at(fk, zmin + 0.05 * (shoulder[2] - zmin))
        toe_y = min(p[1] for p in legs[named[fk]])
        joints[f"scapula_{side}"] = (cx + sign * 0.5 * abs(shoulder[0] - cx), sh_y + 0.1 * body_len, back)
        joints[f"f_shoulder_{side}"] = shoulder
        # 앞다리 팔꿈치는 뒤로, 손목은 앞으로 굽는다
        joints[f"f_elbow_{side}"] = (elbow[0], elbow[1] + BEND_RATIO * leg_h, elbow[2])
        joints[f"f_wrist_{side}"] = (wrist[0], wrist[1] - 0.5 * BEND_RATIO * leg_h, wrist[2])
        joints[f"f_paw_{side}"] = paw
        joints[f"f_toe_{side}"] = (paw[0], min(toe_y, paw[1] - 0.05 * leg_h), zmin)

    # 몸통 척추: 엉덩이 뒤쪽에서 어깨 앞쪽까지, 등선과 배선 사이 등 쪽 1/3 지점
    def spine_point(y: float) -> Point:
        band = [p for p in pts if abs(p[1] - y) < 0.03 * size and p[2] > belly_z - 0.05 * H]
        if not band:
            return (cx, y, belly_z)
        top = max(p[2] for p in band)
        bottom = min(p[2] for p in band)
        return (cx, y, bottom + 0.7 * (top - bottom))

    root_y = rear_y + 0.1 * body_len
    chest_y = front_y - 0.1 * body_len
    torso_names = ("spine_root", "spine_1", "spine_2", "spine_3", "spine_4", "neck_base")
    for i, nm in enumerate(torso_names):
        joints[nm] = spine_point(root_y + (chest_y - root_y) * i / (len(torso_names) - 1))

    # 목·머리: 어깨 앞쪽 영역을 Y 단면으로 따라가 코끝까지
    head_pts = [p for p in pts if p[1] < chest_y and p[2] > belly_z]
    if not head_pts:
        raise ValueError("머리를 찾지 못했습니다.")
    nose = min(head_pts, key=lambda p: p[1])
    path = []
    steps = 12
    for i in range(steps + 1):
        y = chest_y + (nose[1] - chest_y) * i / steps
        band = [p for p in head_pts if abs(p[1] - y) < 0.5 * abs(nose[1] - chest_y) / steps + 1e-6]
        if band:
            zz = [p[2] for p in band]
            path.append((y, 0.5 * (max(zz) + min(zz)), max(zz) - min(zz)))
    if len(path) < 4:
        raise ValueError("목·머리 경로를 추적하지 못했습니다.")
    inner = path[2:-2] or path
    neck_i = path.index(min(inner, key=lambda e: e[2]))
    head_base = (cx, path[neck_i][0], path[neck_i][1])
    joints["neck_mid"] = _lerp(joints["neck_base"], head_base, 0.5)
    joints["head_base"] = head_base
    joints["head_tip"] = (cx, nose[1], path[-1][1])

    # 꼬리
    tail_pts = [p for p in pts if p[1] > root_y and p[2] > belly_z]
    has_tail = False
    if tail_pts:
        tip = max(tail_pts, key=lambda p: p[1])
        if tip[1] - root_y > MIN_TAIL_RATIO * body_len + 0.02 * size:
            has_tail = True
            prev = joints["spine_root"]
            for i in range(1, 5):
                y = root_y + (tip[1] - root_y) * i / 4
                band = [p for p in tail_pts if abs(p[1] - y) < 0.03 * size]
                c = _centroid(band) if band else (cx, y, prev[2])
                joints[f"tail_{i}"] = (cx, y if i < 4 else tip[1], c[2] if i < 4 else tip[2])
                prev = joints[f"tail_{i}"]
    if not has_tail:
        warnings.append("꼬리가 없어 꼬리 본을 생략했습니다.")

    if symmetric:
        for key in [k for k in joints if k.endswith("_L")]:
            base = key[:-2]
            lp, rp = joints[key], joints[f"{base}_R"]
            off = 0.5 * ((lp[0] - cx) - (rp[0] - cx))
            y, z = 0.5 * (lp[1] + rp[1]), 0.5 * (lp[2] + rp[2])
            joints[key] = (cx + off, y, z)
            joints[f"{base}_R"] = (cx - off, y, z)
    if facing == "+Y":
        joints = {k: (2.0 * cx - v[0], -v[1], v[2]) for k, v in joints.items()}
    return QuadrupedLandmarks(joints=joints, facing=facing, size=size, has_tail=has_tail, warnings=warnings)
