"""메시 표면 균일 샘플링 (bpy 비의존).

로우폴리 메시는 정점만으로 단면을 만들 수 없으므로 삼각형 면적 가중으로 표면 점을 뽑는다.
"""

from __future__ import annotations

import random
from bisect import bisect_left
from math import sqrt
from typing import Sequence

Point = tuple[float, float, float]


def _tri_area(a, b, c) -> float:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    return 0.5 * sqrt(cx * cx + cy * cy + cz * cz)


def sample_surface(
    vertices: Sequence[Sequence[float]],
    triangles: Sequence[Sequence[int]],
    count: int,
    seed: int = 0,
) -> list[Point]:
    """면적 가중 표면 샘플 count개 + 원본 정점(count 이하일 때)을 반환한다. seed 고정으로 결과 재현."""
    cumulative: list[float] = []
    total = 0.0
    for t in triangles:
        total += _tri_area(vertices[t[0]], vertices[t[1]], vertices[t[2]])
        cumulative.append(total)
    if total <= 0.0:
        raise ValueError("면적이 있는 삼각형이 없습니다.")

    rng = random.Random(seed)
    out: list[Point] = []
    for _ in range(count):
        i = min(bisect_left(cumulative, rng.random() * total), len(triangles) - 1)
        a, b, c = (vertices[j] for j in triangles[i])
        r1 = sqrt(rng.random())
        r2 = rng.random()
        wa, wb, wc = 1.0 - r1, r1 * (1.0 - r2), r1 * r2
        out.append(
            (
                wa * a[0] + wb * b[0] + wc * c[0],
                wa * a[1] + wb * b[1] + wc * c[1],
                wa * a[2] + wb * b[2] + wc * c[2],
            )
        )
    if len(vertices) <= count:
        out.extend((v[0], v[1], v[2]) for v in vertices)
    return out
