"""손가락 검출 (bpy 비의존): 손 영역 메시 그래프의 측지 거리로 손가락 끝·마디를 찾는다.

1. 손목 단면에서 시작하는 측지 거리 g 의 국소 최대점 = 손가락 끝 (굽은 갈고리 손가락도 표면을 따라가므로 성립)
2. 각 끝에서의 측지 거리 h 등고선 단면을 따라 중심점을 이어 손가락 중심선을 만든다 (부피 안쪽)
3. 등고선 단면에 다른 손가락 영역(가장 가까운 끝이 다른 정점)이 섞이기 시작하는 곳 = 손가락 뿌리
4. 뿌리가 손목에 가장 가까운 손가락을 엄지로 보고, 나머지는 정면 쪽부터 검지·중지·약지·소지 순으로 이름 붙인다
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from math import sqrt
from statistics import median
from typing import Sequence

Vec = tuple[float, float, float]

FINGER_NAMES = ("f_index", "f_middle", "f_ring", "f_pinky")
# 뿌리 → 끝 마디 비율 (근위·중위·원위 지골)
PHALANX_SPLITS = (0.45, 0.75)
MAX_FINGERS = 5
# 마지막 검출의 끝 후보 진단 (테스트·튜닝용)
DEBUG: list = []
# 손가락 끝 판정 돌출도 하한, 손가락 최소 길이 (손 길이 대비)
PROTRUSION_MIN = 0.35
# 돌출도 측정 측지 반경 (손 길이 대비)
PROTRUSION_RADIUS = 0.35
MIN_FINGER_RATIO = 0.18


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _len(a):
    return sqrt(_dot(a, a))


def _norm(a):
    n = _len(a)
    return _mul(a, 1.0 / n) if n > 1e-12 else (0.0, 0.0, 0.0)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _centroid(pts):
    n = len(pts)
    return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n, sum(p[2] for p in pts) / n)


@dataclass
class Finger:
    name: str
    points: list[Vec]  # 뿌리, 마디1, 마디2, 끝

    @property
    def base(self) -> Vec:
        return self.points[0]


@dataclass
class HandFingers:
    fingers: list[Finger]
    wrist: Vec
    dorsal: Vec  # 손등 방향 단위 벡터 (손가락 본 roll 기준)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"wrist": list(self.wrist), "dorsal": list(self.dorsal),
                "fingers": [{"name": f.name, "points": [list(p) for p in f.points]} for f in self.fingers]}

    @staticmethod
    def from_dict(d: dict) -> "HandFingers":
        return HandFingers([Finger(f["name"], [tuple(p) for p in f["points"]]) for f in d["fingers"]],
                           tuple(d["wrist"]), tuple(d["dorsal"]))


def _dijkstra(adj, coords, sources, max_dist=float("inf")):
    dist = {s: 0.0 for s in sources}
    prev = {}
    heap = [(0.0, s) for s in sources]
    heapq.heapify(heap)
    while heap:
        d, v = heapq.heappop(heap)
        if d > dist.get(v, float("inf")):
            continue
        for n in adj[v]:
            nd = d + _len(_sub(coords[v], coords[n]))
            if nd > max_dist:
                continue
            if nd < dist.get(n, float("inf")):
                dist[n] = nd
                prev[n] = v
                heapq.heappush(heap, (nd, n))
    return dist, prev


def _component(adj, members, start):
    seen = {start}
    stack = [start]
    while stack:
        v = stack.pop()
        for n in adj[v]:
            if n in members and n not in seen:
                seen.add(n)
                stack.append(n)
    return seen


def _protrusion(adj, coords, v, radius):
    """측지 반경 radius 테두리 중심이 v 에서 얼마나 떨어졌나 (반경 대비).

    손가락 끝은 관 끝이라 테두리가 손가락 단면으로 모여 0.5 이상, 주름·평면의 국소 최대는 원판처럼 퍼져 작다.
    """
    dist, _ = _dijkstra(adj, coords, [v], max_dist=radius)
    ring = [coords[k] for k, dv in dist.items() if dv > 0.75 * radius]
    if len(ring) < 3:
        return 0.0
    return _len(_sub(coords[v], _centroid(ring))) / radius


def detect_fingers(
    verts: Sequence[Sequence[float]],
    edges: Sequence[Sequence[int]],
    wrist: Vec,
    hand_tip: Vec,
    front: Vec = (0.0, -1.0, 0.0),
) -> HandFingers | None:
    """손 하나의 손가락. 손가락이 2개 미만으로 보이면(벙어리장갑형) None."""
    coords = [(v[0], v[1], v[2]) for v in verts]
    axis = _sub(hand_tip, wrist)
    hand_len = _len(axis)
    if hand_len < 1e-6:
        return None
    d = _norm(axis)
    radius = 2.2 * hand_len

    region = {i for i, p in enumerate(coords)
              if _dot(_sub(p, wrist), d) > -0.05 * hand_len and _len(_sub(p, wrist)) < radius}
    if len(region) < 20:
        return None
    adj = {i: [] for i in region}
    for a, b in edges:
        if a in region and b in region:
            adj[a].append(b)
            adj[b].append(a)
    start = min(region, key=lambda i: _len(_sub(coords[i], hand_tip)))
    comp = _component(adj, region, start)
    adj = {i: [n for n in adj[i] if n in comp] for i in comp}

    # 손목 단면 정점을 출발점으로 둔다
    # 손목 단면 근처만 출발점으로 둔다 (허리·허벅지처럼 같은 반경 안의 다른 부위 제외)
    seeds = [i for i in comp if _dot(_sub(coords[i], wrist), d) < 0.08 * hand_len
             and _len(_sub(coords[i], wrist)) < 0.8 * hand_len]
    if not seeds:
        seeds = [min(comp, key=lambda i: _len(_sub(coords[i], wrist)))]
    g, prev = _dijkstra(adj, coords, seeds)
    if not g:
        return None
    gmax = max(g.values())

    # 손가락 끝: g 의 국소 최대 + 이미 고른 끝과 측지적으로 충분히 떨어짐
    edge_lens = [_len(_sub(coords[a], coords[b])) for a in comp for b in adj[a] if a < b]
    step = max(0.035 * hand_len, 1.2 * median(edge_lens)) if edge_lens else 0.035 * hand_len
    DEBUG.clear()
    tips: list[int] = []
    tip_dist: dict[int, float] = {}
    cap = PROTRUSION_RADIUS * hand_len
    for v in sorted(comp, key=lambda i: -g.get(i, 0.0)):
        # 엄지는 다른 손가락보다 측지 거리가 짧으므로 문턱을 낮게 둔다
        if g.get(v, 0.0) < 0.15 * gmax or len(tips) >= MAX_FINGERS:
            break
        if any(g.get(n, 0.0) > g[v] + 1e-9 for n in adj[v]):
            continue
        if tips and tip_dist.get(v, float("inf")) < 0.3 * hand_len:
            continue
        prot = _protrusion(adj, coords, v, cap)
        DEBUG.append({"tip": coords[v], "g": g[v], "protrusion": prot})
        if prot < PROTRUSION_MIN:
            continue
        tips.append(v)
        dist_new, _ = _dijkstra(adj, coords, [v])
        for k, val in dist_new.items():
            tip_dist[k] = min(tip_dist.get(k, float("inf")), val)
    if len(tips) < 2:
        return None

    h = [_dijkstra(adj, coords, [t])[0] for t in tips]
    label = {v: min(range(len(tips)), key=lambda i: h[i].get(v, float("inf"))) for v in comp}

    raw = []
    for i, t in enumerate(tips):
        # 손목 → 끝 최단 경로 (끝에서 거슬러 올라감)
        path = [t]
        while path[-1] in prev:
            path.append(prev[path[-1]])
        centers = []
        base_s = None
        s = step
        widths = []
        while s < g[t]:
            ring = {v for v in comp if abs(h[i].get(v, 1e9) - s) < 0.75 * step}
            anchor = min(path, key=lambda v: abs(h[i].get(v, 1e9) - s))
            if anchor not in ring:
                ring.add(anchor)
            piece = _component(adj, ring, anchor)
            pts = [coords[v] for v in piece]
            c = _centroid(pts)
            width = max(_len(_sub(p, c)) for p in pts)
            foreign = sum(1 for v in piece if label[v] != i) / len(piece)
            if centers and (foreign > 0.3 or (len(widths) >= 2 and width > 2.2 * median(widths))):
                base_s = s
                break
            centers.append(c)
            widths.append(width)
            s += step
        if len(centers) < 2:
            continue
        length = sum(_len(_sub(centers[k + 1], centers[k])) for k in range(len(centers) - 1)) + _len(_sub(coords[t], centers[0]))
        if length < MIN_FINGER_RATIO * hand_len:
            continue
        # 끝에서 뿌리 방향 중심점 목록 → 뿌리에서 끝으로 뒤집는다
        chain = list(reversed(centers))
        tip_point = coords[t]
        chain.append(_add(chain[-1], _mul(_sub(tip_point, chain[-1]), 0.7)))
        raw.append((chain, base_s if base_s is not None else g[t]))

    if len(raw) < 2:
        return None

    def resample(chain):
        seg = [_len(_sub(chain[k + 1], chain[k])) for k in range(len(chain) - 1)]
        total = sum(seg)
        out = [chain[0]]
        for frac in PHALANX_SPLITS:
            target, acc = frac * total, 0.0
            for k, sl in enumerate(seg):
                if acc + sl >= target:
                    t = (target - acc) / sl if sl > 0 else 0.0
                    out.append(_add(chain[k], _mul(_sub(chain[k + 1], chain[k]), t)))
                    break
                acc += sl
        out.append(chain[-1])
        return out

    fingers = [resample(c) for c, _ in raw]
    warnings = []

    # 엄지: 뿌리가 손목에 가장 가까운 손가락이 나머지보다 확실히 가까울 때
    thumb_idx = None
    if len(fingers) >= 3:
        order = sorted(range(len(fingers)), key=lambda k: _len(_sub(fingers[k][0], wrist)))
        near, rest = order[0], order[1:]
        if _len(_sub(fingers[near][0], wrist)) < 0.8 * median(_len(_sub(fingers[k][0], wrist)) for k in rest):
            thumb_idx = near
    elif len(fingers) == 2:
        warnings.append("손가락이 2개뿐이라 엄지 판별 없이 검지·중지로 이름 붙였습니다.")

    others = [k for k in range(len(fingers)) if k != thumb_idx]
    # 손바닥을 가로지르는 순서로 정렬한다. 뿌리끼리는 거의 붙어 있을 수 있어 손가락 전체 중심을 쓴다
    mids = [_centroid(f) for f in fingers]
    if thumb_idx is not None:
        ref = mids[thumb_idx]
        across = _norm(_sub(_centroid([mids[k] for k in others]), ref))
        others.sort(key=lambda k: _dot(_sub(mids[k], ref), across))
    else:
        others.sort(key=lambda k: -_dot(mids[k], front))
    named = []
    if thumb_idx is not None:
        named.append(Finger("thumb", fingers[thumb_idx]))
    for name, k in zip(FINGER_NAMES, others):
        named.append(Finger(name, fingers[k]))

    # 손등 방향: 손가락이 굽은 반대쪽. 거의 곧으면 손 축에 수직인 세계 위쪽(없으면 바깥쪽)
    bend = (0.0, 0.0, 0.0)
    for f in named:
        straight = _norm(_sub(f.points[1], f.points[0]))
        tipdir = _sub(f.points[-1], f.points[0])
        bend = _add(bend, _sub(tipdir, _mul(straight, _dot(tipdir, straight))))
    bend = _sub(bend, _mul(d, _dot(bend, d)))
    if _len(bend) > 0.05 * hand_len:
        dorsal = _norm(_mul(bend, -1.0))
    else:
        up = _sub((0.0, 0.0, 1.0), _mul(d, d[2]))
        dorsal = _norm(up) if _len(up) > 0.3 else _norm(_cross(d, front))
    return HandFingers(named, wrist, dorsal, warnings)


def mirror(hand: HandFingers, cx: float) -> HandFingers:
    """X = cx 평면 거울상 (반대쪽 손 대칭화용)."""
    m = lambda p: (2.0 * cx - p[0], p[1], p[2])  # noqa: E731
    return HandFingers([Finger(f.name, [m(p) for p in f.points]) for f in hand.fingers], m(hand.wrist),
                       (-hand.dorsal[0], hand.dorsal[1], hand.dorsal[2]), list(hand.warnings))


def symmetrize(left: HandFingers, right: HandFingers, cx: float) -> tuple[HandFingers, HandFingers]:
    """좌우 손가락 이름·수가 같으면 거울 평균, 다르면 손가락이 더 많이 잡힌 쪽을 거울로 쓴다."""
    if [f.name for f in left.fingers] != [f.name for f in right.fingers]:
        src = left if len(left.fingers) >= len(right.fingers) else right
        other = mirror(src, cx)
        return (src, other) if src is left else (other, src)
    mr = mirror(right, cx)
    avg = lambda a, b: _mul(_add(a, b), 0.5)  # noqa: E731
    fingers = [Finger(a.name, [avg(p, q) for p, q in zip(a.points, b.points)]) for a, b in zip(left.fingers, mr.fingers)]
    new_left = HandFingers(fingers, avg(left.wrist, mr.wrist), _norm(_add(left.dorsal, mr.dorsal)), left.warnings)
    return new_left, mirror(new_left, cx)
