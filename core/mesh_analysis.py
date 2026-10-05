"""메시 정점 분석 (bpy 비의존 순수 Python).

리깅 파이프라인의 첫 단계로, 이후 랜드마크 추정·스켈레톤 배치가 기준으로 삼는
경계 상자, 높이 축, 좌우(X) 대칭도를 계산한다. Blender 밖에서도 단위 테스트가
가능하도록 좌표 튜플 시퀀스만 입력으로 받는다.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from math import floor, sqrt
from typing import Iterable, Sequence

Point = Sequence[float]

# 대칭 판정 허용 오차 = 경계 상자 대각선 × 이 비율
SYMMETRY_TOLERANCE_RATIO = 0.01
# 대칭도 계산에 사용할 최대 표본 수 (대형 메시 성능 보호)
MAX_SYMMETRY_SAMPLES = 20000


@dataclass(frozen=True)
class MeshAnalysis:
    vertex_count: int
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    dimensions: tuple[float, float, float]
    up_axis: str
    center_x: float
    symmetry_x: float

    def to_dict(self) -> dict:
        return asdict(self)


def _bounds(points: Sequence[Point]):
    xs, ys, zs = zip(*((p[0], p[1], p[2]) for p in points))
    lo = (min(xs), min(ys), min(zs))
    hi = (max(xs), max(ys), max(zs))
    return lo, hi


def _sample(points: Sequence[Point], limit: int) -> Sequence[Point]:
    if len(points) <= limit:
        return points
    step = len(points) / limit
    return [points[int(i * step)] for i in range(limit)]


def symmetry_score_x(points: Sequence[Point], center_x: float, tolerance: float) -> float:
    """x = center_x 평면 기준 거울상 정점이 tolerance 내에 존재하는 비율(0~1)."""
    if not points:
        return 0.0
    if tolerance <= 0.0:
        tolerance = 1e-6
    cell = tolerance
    grid: dict[tuple[int, int, int], list[Point]] = {}
    for p in points:
        key = (floor(p[0] / cell), floor(p[1] / cell), floor(p[2] / cell))
        grid.setdefault(key, []).append(p)

    tol_sq = tolerance * tolerance
    samples = _sample(points, MAX_SYMMETRY_SAMPLES)
    matched = 0
    for p in samples:
        mx = 2.0 * center_x - p[0]
        kx, ky, kz = floor(mx / cell), floor(p[1] / cell), floor(p[2] / cell)
        found = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for q in grid.get((kx + dx, ky + dy, kz + dz), ()):
                        if (q[0] - mx) ** 2 + (q[1] - p[1]) ** 2 + (q[2] - p[2]) ** 2 <= tol_sq:
                            found = True
                            break
                    if found:
                        break
                if found:
                    break
            if found:
                break
        matched += found
    return matched / len(samples)


def analyze_points(points: Iterable[Point]) -> MeshAnalysis:
    pts = list(points)
    if not pts:
        raise ValueError("정점이 없는 메시는 분석할 수 없습니다.")
    lo, hi = _bounds(pts)
    dims = (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])
    # Blender 좌표계는 Z-up이 관례이지만, 잘못 임포트된(Y-up) 모델을 감지하기 위해 Y/Z 중 큰 쪽을 높이 축으로 본다
    up_axis = "Z" if dims[2] >= dims[1] else "Y"
    center_x = (lo[0] + hi[0]) * 0.5
    diag = sqrt(sum(d * d for d in dims))
    score = symmetry_score_x(pts, center_x, diag * SYMMETRY_TOLERANCE_RATIO)
    return MeshAnalysis(
        vertex_count=len(pts),
        bbox_min=lo,
        bbox_max=hi,
        dimensions=dims,
        up_axis=up_axis,
        center_x=center_x,
        symmetry_x=score,
    )
