"""2족 캐릭터 관절 위치 휴리스틱 추정 (bpy 비의존).

전제: Z-up, T/A-포즈, 좌우 대칭에 가까운 형상. .L 은 해부학적 왼쪽(정면 -Y 일 때 +X).
정면은 -Y가 기본이며 발 방향으로 +Y 정면도 자동 감지한다(내부는 Z축 180° 회전 좌표로 계산).

고정 신체 비율 대신 단면(높이별 X 구간)과 팔 영역 연결 성분으로 실제 형상을 측정하므로
머리가 크거나 다리가 짧은 과장 비율에도 적용된다. 비율 상수는 측정된 구간 내부 분할에만 쓴다.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import floor, sqrt
from statistics import median
from typing import Sequence

Point = tuple[float, float, float]

SLICE_COUNT = 120
# 단면 X 구간 분리 간격 (높이 대비)
GAP_RATIO = 0.02
# 팔 연결 성분 탐색 복셀 크기 (높이 대비)
ARM_VOXEL_RATIO = 0.02
# IK 극(pole) 방향을 확정하기 위한 무릎·팔꿈치 굽힘 오프셋 (분절 길이 대비)
BEND_RATIO = 0.03
# 목 판정: 위쪽 머리 단면이 목 단면보다 이 배수 이상 넓어야 한다
NECK_BULGE = 1.08
# 목이 묻힌 체형에서 머리 높이 = 머리 폭 × 이 비율
HEAD_HEIGHT_RATIO = 1.0
# 발등 높이 판정: 발끝 돌출이 이 비율 이상 정강이 쪽으로 물러난 첫 단면
FOOT_TOP_RETREAT = 0.7
SIDES = (("L", 1.0), ("R", -1.0))


@dataclass
class BipedLandmarks:
    joints: dict[str, Point]
    facing: str  # "-Y" 또는 "+Y"
    height: float
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Interval:
    xmin: float
    xmax: float
    points: list[Point]

    @property
    def center(self) -> float:
        return 0.5 * (self.xmin + self.xmax)

    @property
    def width(self) -> float:
        return self.xmax - self.xmin


def _centroid(pts: Sequence[Point]) -> Point:
    n = len(pts)
    return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n, sum(p[2] for p in pts) / n)


def _intervals(pts: list[Point], gap: float) -> list[_Interval]:
    if not pts:
        return []
    s = sorted(pts, key=lambda p: p[0])
    groups = [[s[0]]]
    for p in s[1:]:
        if p[0] - groups[-1][-1][0] > gap:
            groups.append([p])
        else:
            groups[-1].append(p)
    return [_Interval(g[0][0], g[-1][0], g) for g in groups]


def _central(intervals: list[_Interval], cx: float) -> _Interval | None:
    if not intervals:
        return None
    for iv in intervals:
        if iv.xmin <= cx <= iv.xmax:
            return iv
    return min(intervals, key=lambda iv: abs(iv.center - cx))


def _is_leg_slice(intervals: list[_Interval], cx: float) -> bool:
    has_left = any(iv.xmin > cx for iv in intervals)
    has_right = any(iv.xmax < cx for iv in intervals)
    spans = any(iv.xmin <= cx <= iv.xmax for iv in intervals)
    return has_left and has_right and not spans


def _leg_interval(intervals: list[_Interval], cx: float, sign: float) -> _Interval | None:
    side = [iv for iv in intervals if (iv.xmin > cx if sign > 0 else iv.xmax < cx)]
    if not side:
        return None
    return min(side, key=lambda iv: abs(iv.center - cx))


def _lerp(a: Point, b: Point, t: float) -> Point:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def _arm_component(points: list[Point], cx: float, sign: float, threshold: float, voxel: float, zmin_allowed: float):
    """손끝(가장 바깥 점)에서 시작해 몸통 바깥 반공간 안에서 복셀 연결 성분을 확장한다."""
    cand = [p for p in points if sign * (p[0] - cx) > threshold and p[2] > zmin_allowed]
    if not cand:
        return [], None
    tip = max(cand, key=lambda p: sign * (p[0] - cx))
    grid: dict[tuple[int, int, int], list[Point]] = {}
    for p in cand:
        grid.setdefault((floor(p[0] / voxel), floor(p[1] / voxel), floor(p[2] / voxel)), []).append(p)
    start = (floor(tip[0] / voxel), floor(tip[1] / voxel), floor(tip[2] / voxel))
    seen = {start}
    queue = deque([start])
    while queue:
        kx, ky, kz = queue.popleft()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    k = (kx + dx, ky + dy, kz + dz)
                    if k in grid and k not in seen:
                        seen.add(k)
                        queue.append(k)
    arm = [p for k in seen for p in grid[k]]
    return arm, tip


def _band_centroid(pts: list[Point], origin: Point, axis: Point, length: float, t0: float, t1: float) -> Point | None:
    sel = []
    for p in pts:
        t = ((p[0] - origin[0]) * axis[0] + (p[1] - origin[1]) * axis[1] + (p[2] - origin[2]) * axis[2]) / length
        if t0 <= t <= t1:
            sel.append(p)
    return _centroid(sel) if sel else None


def _foot_top_z(leg_slices: list[tuple[int, _Interval]], z_of, zmin: float, leg_len: float) -> float | None:
    """발끝(-Y) 돌출이 정강이 앞면 쪽으로 대부분 물러나는 첫 높이. 발 돌출이 뚜렷하지 않으면 None."""
    fronts = [(z_of(k), min(p[1] for p in iv.points)) for k, iv in leg_slices]
    toe = [f for z, f in fronts if z - zmin < 0.1 * leg_len]
    shin = [f for z, f in fronts if 0.1 * leg_len <= z - zmin <= 0.35 * leg_len]
    if not toe or not shin:
        return None
    toe_front = min(toe)
    protrusion = max(shin) - toe_front
    if protrusion < 0.05 * leg_len:
        return None
    for z, f in fronts:
        if z - zmin > 0.02 * leg_len and f >= toe_front + FOOT_TOP_RETREAT * protrusion:
            return z
    return None


def _buried_head(slices: list[list[_Interval]], neck_ks: list[int], w: dict[int, float], cx: float, zmax: float, z_of):
    """목이 보이지 않을 때 (머리 시작 높이, 머리 중심 y).

    어깨에서 머리로 가파르게 좁아지다 머리 폭에서 완만해지는 꺾임점 위를 머리로 보고,
    머리 폭에 비례한 머리 높이로 시작 높이를 정한다. 머리 아랫부분은 어깨 살 단면에 묻혀 있다.
    """
    m = 3
    scored = [k for k in neck_ks if k - m in w and k + m in w]
    if scored:
        k_e = max(scored, key=lambda k: (w[k - m] - w[k]) - (w[k] - w[k + m]))
    else:
        k_e = neck_ks[0]
    above = [k for k in neck_ks if k > k_e] or [neck_ks[-1]]
    head_w = median(w[k] for k in above)
    head_base_z = min(max(zmax - HEAD_HEIGHT_RATIO * head_w, z_of(neck_ks[0])), z_of(k_e))
    centers = []
    for k in above:
        ys = [p[1] for p in _central(slices[k], cx).points if abs(p[0] - cx) <= 0.5 * head_w]
        if ys:
            centers.append(0.5 * (max(ys) + min(ys)))
    return head_base_z, (median(centers) if centers else None)


def estimate_biped(points: Sequence[Sequence[float]], symmetric: bool = True) -> BipedLandmarks:
    pts: list[Point] = [(p[0], p[1], p[2]) for p in points]
    if len(pts) < 500:
        raise ValueError("관절 추정에 필요한 표면 샘플이 부족합니다.")
    warnings: list[str] = []

    zmin = min(p[2] for p in pts)
    zmax = max(p[2] for p in pts)
    H = zmax - zmin
    if H <= 0.0:
        raise ValueError("높이가 0인 메시입니다.")
    cx = median(p[0] for p in pts)

    # 정면 감지: 발끝은 정강이보다 앞쪽으로 튀어나온다
    foot_pts = [p for p in pts if p[2] < zmin + 0.04 * H]
    shin_pts = [p for p in pts if zmin + 0.12 * H < p[2] < zmin + 0.2 * H]
    facing = "-Y"
    if foot_pts and shin_pts and _centroid(foot_pts)[1] > _centroid(shin_pts)[1]:
        facing = "+Y"
        # Z축 180° 회전으로 정면 -Y 기준 좌표에 맞춘다 (거울 반전이 아니므로 .L 은 해부학적 왼쪽을 유지)
        pts = [(2.0 * cx - p[0], -p[1], p[2]) for p in pts]

    n = SLICE_COUNT
    dz = H / n
    buckets: list[list[Point]] = [[] for _ in range(n)]
    for p in pts:
        buckets[min(n - 1, int((p[2] - zmin) / dz))].append(p)
    gap = GAP_RATIO * H
    slices = [_intervals(b, gap) for b in buckets]

    def z_of(k: int) -> float:
        return zmin + (k + 0.5) * dz

    def k_of(z: float) -> int:
        return max(0, min(n - 1, int((z - zmin) / dz)))

    # 가랑이: 바닥부터 이어지는 '좌우 분리 + 중앙 비어 있음' 단면 구간의 끝
    k_c = -1
    started = False
    for k in range(n):
        if _is_leg_slice(slices[k], cx):
            started = True
            k_c = k
        elif started:
            break
        elif k > 0.15 * n:
            break
    if k_c < 5:
        warnings.append("다리 분리를 찾지 못해 가랑이 높이를 비율로 가정했습니다.")
        k_c = int(0.45 * n)
    crotch_z = zmin + (k_c + 1) * dz
    leg_len = crotch_z - zmin

    joints: dict[str, Point] = {}
    leg_outer: dict[str, float] = {}
    for name, sign in SIDES:
        leg_slices: list[tuple[int, _Interval]] = []
        for k in range(min(k_c + 1, n)):
            iv = _leg_interval(slices[k], cx, sign)
            if iv is not None:
                leg_slices.append((k, iv))
        if not leg_slices:
            # 다리 분리 실패 시 몸통 절반을 다리로 본다
            for k in range(min(k_c + 1, n)):
                sel = [p for p in buckets[k] if sign * (p[0] - cx) > 0]
                if sel:
                    xs = [p[0] for p in sel]
                    leg_slices.append((k, _Interval(min(xs), max(xs), sel)))
        leg_outer[name] = max(sign * (iv.xmax if sign > 0 else iv.xmin) - sign * cx for _, iv in leg_slices)

        def leg_at(z: float) -> Point:
            k_target = k_of(z)
            k, iv = min(leg_slices, key=lambda e: abs(e[0] - k_target))
            c = _centroid(iv.points)
            return (c[0], c[1], z)

        def depth(iv: _Interval) -> float:
            ys = [p[1] for p in iv.points]
            return max(ys) - min(ys)

        mid = [depth(iv) for k, iv in leg_slices if 0.3 * leg_len < z_of(k) - zmin < 0.6 * leg_len]
        mid_depth = median(mid) if mid else depth(leg_slices[len(leg_slices) // 2][1])
        ankle_z = zmin + 0.25 * leg_len
        for k, iv in leg_slices:
            if z_of(k) - zmin > 0.02 * leg_len and depth(iv) <= 1.4 * mid_depth:
                ankle_z = min(max(z_of(k), zmin + 0.04 * leg_len), zmin + 0.25 * leg_len)
                break
        # 굵은 다리는 발보다 깊어 깊이 기준이 바닥 근처에서 멈춘다. 발끝 돌출이 끝나는 높이(발등 위)로 보정한다
        foot_top = _foot_top_z(leg_slices, z_of, zmin, leg_len)
        if foot_top is not None:
            ankle_z = min(max(ankle_z, foot_top), zmin + 0.25 * leg_len)

        hip_z = crotch_z + 0.1 * leg_len
        top = [iv for k, iv in leg_slices if k >= k_c - 2] or [leg_slices[-1][1]]
        hip_c = _centroid([p for iv in top for p in iv.points])
        hip = (hip_c[0], hip_c[1], hip_z)
        ankle = leg_at(ankle_z)
        knee_z = 0.5 * (hip_z + ankle_z)
        knee = leg_at(knee_z)
        knee = (knee[0], knee[1] - BEND_RATIO * leg_len, knee[2])

        foot = [p for k, iv in leg_slices if z_of(k) < ankle_z for p in iv.points] or leg_slices[0][1].points
        toe_y = min(p[1] for p in foot)
        heel_y = max(p[1] for p in foot)
        fxs = [p[0] for p in foot]
        foot_w = max(fxs) - min(fxs)
        floor_z = zmin
        toe_tip = (ankle[0], toe_y, floor_z + 0.02 * leg_len)
        toe_base = (ankle[0], ankle[1] + 0.65 * (toe_y - ankle[1]), floor_z + 0.02 * leg_len)
        joints[f"hip_{name}"] = hip
        joints[f"knee_{name}"] = knee
        joints[f"ankle_{name}"] = ankle
        joints[f"toe_base_{name}"] = toe_base
        joints[f"toe_tip_{name}"] = toe_tip
        joints[f"heel_in_{name}"] = (ankle[0] - sign * 0.4 * foot_w, heel_y, floor_z)
        joints[f"heel_out_{name}"] = (ankle[0] + sign * 0.4 * foot_w, heel_y, floor_z)

    # 몸통 하단 반폭
    torso_ks = range(k_c + 1, min(n, k_c + 1 + max(3, int(0.2 * (n - k_c)))))
    widths = [_central(slices[k], cx).width for k in torso_ks if slices[k]]
    torso_hw = 0.5 * median(widths) if widths else 0.1 * H

    def torso_center(z: float) -> tuple[float, float]:
        """해당 높이 몸통 단면의 (중심 y, 깊이)."""
        k = k_of(z)
        for dk in range(n):
            for kk in (k - dk, k + dk):
                if 0 <= kk < n and slices[kk]:
                    iv = _central(slices[kk], cx)
                    sel = [p for p in iv.points if abs(p[0] - cx) <= torso_hw] or iv.points
                    ys = [p[1] for p in sel]
                    return 0.5 * (max(ys) + min(ys)), max(ys) - min(ys)
        return 0.0, 0.0

    # 팔
    voxel = ARM_VOXEL_RATIO * H
    shoulder_zs = []
    arm_tops = []
    for name, sign in SIDES:
        threshold = max(1.2 * torso_hw, 0.0)
        cand_pts = [
            p
            for p in pts
            if (p[2] > crotch_z and sign * (p[0] - cx) > threshold)
            or (crotch_z - 0.3 * leg_len < p[2] <= crotch_z and sign * (p[0] - cx) > leg_outer[name] + 0.02 * H)
        ]
        arm, tip = _arm_component(cand_pts, cx, sign, 0.0, voxel, crotch_z - 0.3 * leg_len)
        if not arm:
            raise ValueError("팔을 찾지 못했습니다. T/A-포즈인지 확인하세요.")
        reach = sign * (tip[0] - cx)
        root_band = [p for p in arm if sign * (p[0] - cx) < threshold + 0.08 * (reach - threshold)] or arm
        root = _centroid(root_band)
        shoulder = (cx + sign * torso_hw, root[1], root[2])
        tip_c = _centroid([p for p in arm if sign * (p[0] - cx) > reach - 0.03 * H])
        axis = (tip_c[0] - shoulder[0], tip_c[1] - shoulder[1], tip_c[2] - shoulder[2])
        length = sqrt(sum(a * a for a in axis))
        u = (axis[0] / length, axis[1] / length, axis[2] / length)
        elbow = _band_centroid(arm, shoulder, u, length, 0.37, 0.43) or _lerp(shoulder, tip_c, 0.4)
        wrist = _band_centroid(arm, shoulder, u, length, 0.72, 0.78) or _lerp(shoulder, tip_c, 0.75)
        elbow = (elbow[0], elbow[1] + BEND_RATIO * length, elbow[2])
        joints[f"shoulder_{name}"] = shoulder
        joints[f"elbow_{name}"] = elbow
        joints[f"wrist_{name}"] = wrist
        joints[f"hand_tip_{name}"] = tip_c
        shoulder_zs.append(shoulder[2])
        arm_tops.append(max(p[2] for p in root_band))

    shoulder_z = max(shoulder_zs)

    # 목: 팔 상단 위 ~ 머리 꼭대기 사이에서 몸통 단면이 가장 좁은 곳
    k_lo = k_of(max(arm_tops) + dz)
    k_hi = k_of(zmax - 0.05 * (zmax - shoulder_z))
    neck_ks = [k for k in range(k_lo, k_hi) if slices[k]]
    head_y = None
    if neck_ks:
        raw = {k: _central(slices[k], cx).width for k in range(max(0, k_lo - 1), min(n, k_hi + 1)) if slices[k]}
        # 표본이 성긴 단면은 폭이 작게 재지므로 이웃 단면과의 최댓값으로 잡음을 누른다
        w = {k: max(raw.get(j, 0.0) for j in (k - 1, k, k + 1)) for k in neck_ks}
        # 위쪽에 머리가 다시 넓어지는 잘록한 단면만 목으로 본다 (정수리의 좁은 단면 배제)
        necked = [k for k in neck_ks if max((w[j] for j in neck_ks if j > k), default=0.0) >= NECK_BULGE * w[k]]
        if necked:
            head_base_z = z_of(min(necked, key=lambda k: w[k]))
        else:
            # 목이 어깨 살에 묻혀 단면이 정수리까지 줄기만 하는 체형(비만 등)
            head_base_z, head_y = _buried_head(slices, neck_ks, w, cx, zmax, z_of)
            warnings.append("목의 잘록한 부분이 없어 머리 크기로 머리 시작 높이를 추정했습니다.")
    else:
        warnings.append("목 위치를 찾지 못해 비율로 가정했습니다.")
        head_base_z = shoulder_z + 0.3 * (zmax - shoulder_z)
    neck_base_z = shoulder_z + 0.3 * (head_base_z - shoulder_z)

    spine_base_z = crotch_z + 0.05 * leg_len
    spine_fracs = (0.0, 0.227, 0.438, 0.705, 1.0)
    spine_names = ("spine_base", "spine_1", "spine_2", "spine_3", "neck_base")
    for nm, f in zip(spine_names, spine_fracs):
        z = spine_base_z + f * (neck_base_z - spine_base_z)
        yc, d = torso_center(z)
        # 척추는 몸통 중심보다 등 쪽(+Y)에 위치한다
        joints[nm] = (cx, yc + 0.15 * d, z)
    for nm, z in (("neck_mid", 0.5 * (neck_base_z + head_base_z)), ("head_base", head_base_z)):
        yc, _ = torso_center(z)
        joints[nm] = (cx, yc, z)
    if head_y is not None:
        # 묻힌 목 높이의 단면은 등 살까지 포함하므로 머리 중심 깊이를 쓴다
        joints["head_base"] = (cx, head_y, head_base_z)
        joints["neck_mid"] = (cx, 0.5 * (joints["neck_base"][1] + head_y), joints["neck_mid"][2])
    yc, _ = torso_center(zmax - 0.1 * (zmax - head_base_z))
    joints["head_top"] = (cx, yc, zmax)

    chest_y, chest_d = torso_center(neck_base_z)
    for name, sign in SIDES:
        s = joints[f"shoulder_{name}"]
        joints[f"clavicle_{name}"] = (cx + sign * 0.1 * torso_hw, chest_y - 0.3 * chest_d, s[2] + 0.02 * H)
        hy, hd = torso_center(spine_base_z)
        joints[f"pelvis_tip_{name}"] = (cx + sign * 0.65 * torso_hw, hy - 0.4 * hd, spine_base_z + 0.1 * leg_len)

    if symmetric:
        _symmetrize(joints, cx)
    if facing == "+Y":
        joints = {k: (2.0 * cx - v[0], -v[1], v[2]) for k, v in joints.items()}
    return BipedLandmarks(joints=joints, facing=facing, height=H, warnings=warnings)


def _symmetrize(joints: dict[str, Point], cx: float) -> None:
    for key in [k for k in joints if k.endswith("_L")]:
        base = key[:-2]
        lp, rp = joints[key], joints.get(f"{base}_R")
        if rp is None:
            continue
        off = 0.5 * ((lp[0] - cx) - (rp[0] - cx))
        y = 0.5 * (lp[1] + rp[1])
        z = 0.5 * (lp[2] + rp[2])
        joints[key] = (cx + off, y, z)
        joints[f"{base}_R"] = (cx - off, y, z)
