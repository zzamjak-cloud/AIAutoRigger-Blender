"""직교 뷰 이미지 좌표 → 3D 광선, 다중 뷰 광선 교차 (bpy 비의존)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

Vec = tuple[float, float, float]


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


@dataclass(frozen=True)
class OrthoView:
    """직교 카메라. center 는 이미지 중앙에 해당하는 월드 좌표, scale 은 이미지 한 변의 월드 길이."""

    name: str
    center: Vec
    right: Vec
    up: Vec
    forward: Vec
    scale: float

    def ray(self, u: float, v: float) -> tuple[Vec, Vec]:
        """정규화 이미지 좌표(u: 왼→오, v: 위→아래, 0~1)의 광선 (원점, 방향)."""
        p = _add(self.center, _add(_mul(self.right, (u - 0.5) * self.scale), _mul(self.up, (0.5 - v) * self.scale)))
        return p, self.forward

    def project(self, point: Vec) -> tuple[float, float]:
        d = _sub(point, self.center)
        return 0.5 + _dot(d, self.right) / self.scale, 0.5 - _dot(d, self.up) / self.scale

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("name", "center", "right", "up", "forward", "scale")}


def intersect_rays(rays: Sequence[tuple[Vec, Vec]]) -> Vec:
    """여러 광선에 대한 최소제곱 최근접점. 방향 벡터는 단위 길이여야 한다."""
    # sum (I - d d^T) x = sum (I - d d^T) p 를 3x3 로 푼다
    A = [[0.0] * 3 for _ in range(3)]
    b = [0.0, 0.0, 0.0]
    for p, d in rays:
        for i in range(3):
            for j in range(3):
                m = (1.0 if i == j else 0.0) - d[i] * d[j]
                A[i][j] += m
                b[i] += m * p[j]
    return _solve3(A, b)


def _solve3(A, b) -> Vec:
    m = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(3):
        piv = max(range(c, 3), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-12:
            raise ValueError("광선이 평행해 교차점을 계산할 수 없습니다.")
        m[c], m[piv] = m[piv], m[c]
        for r in range(3):
            if r != c:
                f = m[r][c] / m[c][c]
                for k in range(c, 4):
                    m[r][k] -= f * m[c][k]
    return (m[0][3] / m[0][0], m[1][3] / m[1][1], m[2][3] / m[2][2])
