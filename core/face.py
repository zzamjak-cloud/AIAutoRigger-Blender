"""턱·눈 검출 (bpy 비의존).

턱: 얼굴 정면 중앙 띠의 앞쪽 윤곽 f(z)(높이별 가장 앞의 y)를 아래에서 위로 훑는다.
    목 → 턱 아래면(윤곽이 급히 앞으로 나옴) → 턱 끝(첫 전방 극점) → 입(뒤로 들어간 극점) → 윗입술.
    입 오목이 없는 머리(상자형 등)는 턱을 만들지 않는다.
눈: 머리 앞 위쪽에 좌우 대칭으로 놓인 작은 메시 조각(눈동자)이 있을 때만 만든다.
    눈이 머리와 한 덩어리로 조각된 모델은 눈 본을 돌리면 눈두덩이가 찌그러지므로 만들지 않는다.
정면 +Y 캐릭터는 Z축 180° 회전 좌표로 계산한 뒤 되돌린다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import median
from typing import Sequence

Vec = tuple[float, float, float]

PROFILE_BINS = 80
STRIP_RATIO = 0.08  # 정면 중앙 띠 반폭 (머리 폭 대비)
# 턱을 만들 최소 입 오목 깊이 (머리 앞뒤 깊이 대비)
MIN_MOUTH_DEPTH = 0.04


@dataclass
class Jaw:
    pivot: Vec
    chin: Vec
    lip_z: float
    chin_bottom_z: float
    depth: float  # 입술 선 높이의 머리 앞뒤 깊이
    open_depth: float  # 입 오목 깊이 (머리 깊이 대비)
    front_sign: float  # 정면 방향 Y 부호 (-1: 정면 -Y)
    head_width: float = 0.0  # 좌우 범위 제한용 (0 이면 제한 없음: 이전 버전 데이터)

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        return Jaw(tuple(d["pivot"]), tuple(d["chin"]), d["lip_z"], d["chin_bottom_z"], d["depth"], d["open_depth"],
                   d["front_sign"], d.get("head_width", 0.0))


@dataclass
class Eye:
    side: str
    center: Vec
    radius: float
    island: int  # 섬 번호 (bridge 가 웨이트 지정에 사용)


@dataclass
class Face:
    jaw: Jaw | None
    eyes: list[Eye] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self):
        return {"jaw": self.jaw.to_dict() if self.jaw else None,
                "eyes": [asdict(e) for e in self.eyes]}

    @staticmethod
    def from_dict(d):
        return Face(Jaw.from_dict(d["jaw"]) if d.get("jaw") else None,
                    [Eye(e["side"], tuple(e["center"]), e["radius"], e["island"]) for e in d.get("eyes", [])])


def detect_jaw(points: Sequence[Sequence[float]], neck_base: Vec, head_top: Vec, cx: float, facing: str = "-Y") -> tuple[Jaw | None, str]:
    """(턱 또는 None, 사유)."""
    rot = facing == "+Y"
    pts = [((2 * cx - p[0], -p[1], p[2]) if rot else (p[0], p[1], p[2])) for p in points]
    z0, z1 = neck_base[2], head_top[2]
    if z1 - z0 <= 0:
        return None, "머리 높이를 알 수 없습니다."
    head = [p for p in pts if z0 <= p[2] <= z1]
    upper = [p[0] for p in head if p[2] > z0 + 0.5 * (z1 - z0)]
    if len(head) < 200 or not upper:
        return None, "머리 표면 샘플이 부족합니다."
    hw = max(upper) - min(upper)
    strip = STRIP_RATIO * hw
    n = PROFILE_BINS
    dz = (z1 - z0) / n
    front, back = [None] * n, [None] * n
    zs = [z0 + (k + 0.5) * dz for k in range(n)]
    for p in head:
        k = min(n - 1, int((p[2] - z0) / dz))
        if back[k] is None or p[1] > back[k]:
            back[k] = p[1]
        if abs(p[0] - cx) < strip and (front[k] is None or p[1] < front[k]):
            front[k] = p[1]
    # 띠 안에 앞면 샘플이 없으면 뒷면 점이 '가장 앞'으로 잡혀 가짜 입 오목이 된다. 머리 중심보다 뒤면 결측으로 본다
    head_ys = sorted(p[1] for p in head)
    y_mid = head_ys[len(head_ys) // 2]
    y_cut = y_mid + 0.3 * (head_ys[-1] - y_mid)  # 입 안 깊은 벽은 남기고 뒷면 점만 버린다
    for k in range(n):
        if front[k] is not None and front[k] > y_cut:
            front[k] = None
    valid = [k for k in range(n) if front[k] is not None and back[k] is not None]
    if len(valid) < n // 2:
        return None, "얼굴 정면 윤곽을 만들지 못했습니다."
    depth_ref = median(back[k] - front[k] for k in valid)
    # 빈 칸은 이웃 값으로 채운다
    for k in range(n):
        if front[k] is None:
            near = min(valid, key=lambda j: abs(j - k))
            front[k], back[k] = front[near], back[near]

    # 턱 아래면: 얼굴 중간에서 아래로 내려가다 윤곽이 뒤로 크게 물러난 뒤 다시 앞으로 나오지 않는 첫 지점.
    # 금방 다시 앞으로 나오면 입 틈이다. 아래에서 위로 훑으면 가슴·목 경계를 턱으로 오인한다
    k_start = int(0.6 * n)
    window = max(2, int(0.12 * n))
    k_bottom = None
    for k in range(k_start, 0, -1):
        drop = front[k - 1] - front[k]
        if drop <= 0.15 * depth_ref:
            continue
        below = range(k - 1, max(-1, k - 1 - window), -1)
        if any(front[kk] < front[k] + 0.5 * drop for kk in below):
            continue
        k_bottom = k
        break
    if k_bottom is None:
        return None, "턱 아래 윤곽을 찾지 못했습니다."
    face_h = z1 - zs[k_bottom]
    span = lambda frac: max(1, int(frac * face_h / dz))  # noqa: E731
    # 턱 끝: 아래면 위 첫 전방 극점
    rng = range(k_bottom, min(k_start, k_bottom + span(0.3)) + 1)
    k_chin = min(rng, key=lambda k: front[k])
    # 입: 턱 끝 위 뒤로 들어간 극점, 그 위 윗입술(다시 앞으로 나온 극점)
    rng = range(k_chin + 1, min(k_start, k_chin + span(0.3)) + 1)
    if not rng:
        return None, "입 위치를 찾지 못했습니다."
    k_mouth = max(rng, key=lambda k: front[k])
    rng_up = range(k_mouth + 1, min(n, k_mouth + span(0.2)) + 1)
    if not rng_up or k_mouth + 1 >= n:
        return None, "윗입술을 찾지 못했습니다."
    k_upper = min(rng_up, key=lambda k: front[min(k, n - 1)])
    open_depth = (front[k_mouth] - max(front[k_chin], front[k_upper])) / depth_ref
    if open_depth < MIN_MOUTH_DEPTH:
        return None, "입 오목(입술 선)이 보이지 않아 턱 본을 만들지 않았습니다."

    lip_z = zs[k_mouth]
    chin_bottom = zs[k_bottom] - 0.5 * dz
    pivot_z = lip_z + 0.3 * (lip_z - chin_bottom)
    kp = min(n - 1, int((pivot_z - z0) / dz))
    depth_p = back[kp] - front[kp]
    pivot = (cx, 0.5 * (front[kp] + back[kp]) + 0.1 * depth_p, pivot_z)
    chin_z = zs[k_chin]
    chin = (cx, front[k_chin] + 0.2 * (back[k_chin] - front[k_chin]), chin_z - 0.3 * (chin_z - chin_bottom))
    depth_lip = back[k_mouth] - front[k_mouth]
    if rot:
        pivot = (2 * cx - pivot[0], -pivot[1], pivot[2])
        chin = (2 * cx - chin[0], -chin[1], chin[2])
    return Jaw(pivot, chin, lip_z, chin_bottom, depth_lip if depth_lip > 0 else depth_ref, open_depth,
               1.0 if rot else -1.0, hw), ""


def jaw_weight(v: Vec, jaw: Jaw) -> float:
    """아래턱 웨이트 0~1: 입술 선 아래 + 회전축 앞 + 목보다 위."""
    def clamp(x):
        return 0.0 if x < 0 else (1.0 if x > 1 else x)

    jaw_h = max(1e-6, jaw.lip_z - jaw.chin_bottom_z)
    s = clamp((jaw.lip_z - v[2]) / (0.25 * jaw_h))
    forward = (v[1] - jaw.pivot[1]) * jaw.front_sign  # 양수 = 회전축보다 앞
    f = clamp((forward + 0.05 * jaw.depth) / (0.25 * jaw.depth))
    g = clamp((v[2] - (jaw.chin_bottom_z - 0.35 * jaw_h)) / (0.3 * jaw_h))
    # 머리 폭 밖(어깨·늘어진 머리카락·얼굴 근처 손 등)은 턱에 끌려가지 않게 한다
    lat = 1.0
    if jaw.head_width > 0:
        half = 0.5 * jaw.head_width
        lat = clamp((1.25 * half - abs(v[0] - jaw.pivot[0])) / (0.25 * half))
    return s * f * g * lat


def pick_eyes(islands: Sequence[tuple[Vec, float, int]], head_center: Vec, head_width: float, head_top_z: float,
              lip_z: float | None, facing: str = "-Y") -> list[Eye]:
    """(중심, 반지름, 섬 번호) 목록에서 눈동자 한 쌍을 고른다. 없으면 빈 목록."""
    cx = head_center[0]
    front = -1.0 if facing == "-Y" else 1.0
    zmin = lip_z if lip_z is not None else head_center[2] - 0.25 * (head_top_z - head_center[2])
    cand = [(c, r, i) for c, r, i in islands
            if r < 0.2 * head_width and zmin < c[2] < head_top_z
            and (c[1] - head_center[1]) * front > 0 and abs(c[0] - cx) > 0.08 * head_width
            and abs(c[0] - cx) < 0.5 * head_width]
    best = None
    for a in cand:
        for b in cand:
            if not (a[0][0] > cx > b[0][0]):
                continue
            # 좌우 대칭·같은 높이·비슷한 크기일수록 좋다
            score = (abs((a[0][0] - cx) + (b[0][0] - cx)) + abs(a[0][2] - b[0][2]) + abs(a[0][1] - b[0][1])
                     + abs(a[1] - b[1]))
            if best is None or score < best[0]:
                best = (score, a, b)
    if best is None or best[0] > 0.15 * head_width:
        return []
    _, a, b = best
    left, right = (a, b) if facing == "-Y" else (b, a)
    return [Eye("L", left[0], left[1], left[2]), Eye("R", right[0], right[1], right[2])]
