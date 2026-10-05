"""체형 분류와 수평 단면 2D 군집화 (bpy 비의존)."""

from __future__ import annotations

from collections import deque
from math import floor
from typing import Sequence

Point = tuple[float, float, float]

BIPED = "BIPED"
QUADRUPED = "QUADRUPED"
# 다리 판정 높이 대역 (높이 대비)
LEG_BAND = (0.03, 0.15)
# 이 비율보다 점이 적은 군집은 잡음으로 버린다
MIN_CLUSTER_RATIO = 0.03


def clusters_xy(points: Sequence[Point], cell: float) -> list[list[Point]]:
    """XY 평면 점유 격자의 8-이웃 연결 성분. 점 수 내림차순."""
    grid: dict[tuple[int, int], list[Point]] = {}
    for p in points:
        grid.setdefault((floor(p[0] / cell), floor(p[1] / cell)), []).append(p)
    seen: set[tuple[int, int]] = set()
    out: list[list[Point]] = []
    for start in grid:
        if start in seen:
            continue
        seen.add(start)
        queue = deque([start])
        comp: list[Point] = []
        while queue:
            kx, ky = queue.popleft()
            comp.extend(grid[(kx, ky)])
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    k = (kx + dx, ky + dy)
                    if k in grid and k not in seen:
                        seen.add(k)
                        queue.append(k)
        out.append(comp)
    out.sort(key=len, reverse=True)
    return out


def leg_clusters(points: Sequence[Point], zmin: float, height: float, size: float) -> list[list[Point]]:
    lo, hi = zmin + LEG_BAND[0] * height, zmin + LEG_BAND[1] * height
    band = [p for p in points if lo <= p[2] <= hi]
    if not band:
        return []
    comps = clusters_xy(band, 0.02 * size)
    return [c for c in comps if len(c) >= MIN_CLUSTER_RATIO * len(band)]


def classify(points: Sequence[Point]) -> tuple[str, int]:
    """(체형, 감지된 다리 수). 다리 4개 이상이면 4족, 그 외 2족으로 본다."""
    zs = [p[2] for p in points]
    zmin, zmax = min(zs), max(zs)
    height = zmax - zmin
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    size = max(height, max(xs) - min(xs), max(ys) - min(ys))
    legs = leg_clusters(points, zmin, height, size)
    return (QUADRUPED if len(legs) >= 4 else BIPED), len(legs)
