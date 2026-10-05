"""4족 관절 휴리스틱·체형 분류 단위 테스트 (bpy 비의존)."""

import pathlib
import sys
import unittest
from math import dist

ROOT = pathlib.Path(__file__).resolve().parents[1]
# 저장소 루트 __init__.py 는 bpy 를 import 하므로 core 를 최상위 패키지로 불러온다
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))

from core import body_type, quadruped_landmarks, sampling  # noqa: E402
import humanoid  # noqa: E402
import quadruped  # noqa: E402

TOLERANCE = 0.06
CHECKED = ("r_hip", "r_knee", "r_hock", "f_shoulder", "f_elbow", "f_wrist")


def _points(module, variant, flip=False, seed=1):
    verts, tris, gt = module.build(variant)
    if flip:
        verts = [(-v[0], -v[1], v[2]) for v in verts]
        gt = {k: (-v[0], -v[1], v[2]) for k, v in gt.items()}
    return sampling.sample_surface(verts, tris, 30000, seed=seed), gt


class QuadrupedTest(unittest.TestCase):
    def _run(self, variant, flip=False):
        pts, gt = _points(quadruped, variant, flip)
        r = quadruped_landmarks.estimate_quadruped(pts)
        for joint in CHECKED:
            for side in ("L", "R"):
                key = f"{joint}_{side}"
                err = dist(r.joints[key], gt[key]) / r.size
                self.assertLess(err, TOLERANCE, f"{variant} {key} 오차 {err:.3f} est={r.joints[key]} gt={gt[key]}")
        err = dist(r.joints["head_base"], gt["head_base"]) / r.size
        self.assertLess(err, 0.1, f"{variant} head_base 오차 {err:.3f}")
        self.assertTrue(r.has_tail)
        self.assertLess(dist(r.joints["tail_4"], gt["tail_tip"]) / r.size, 0.06)
        return r

    def test_dog(self):
        self.assertEqual(self._run("dog").facing, "-Y")

    def test_stylized(self):
        self._run("stylized_quad")

    def test_facing_plus_y(self):
        self.assertEqual(self._run("dog", flip=True).facing, "+Y")

    def test_ik_bends(self):
        pts, _ = _points(quadruped, "dog")
        j = quadruped_landmarks.estimate_quadruped(pts).joints
        mid = lambda a, b: 0.5 * (j[a][1] + j[b][1])  # noqa: E731
        self.assertLess(j["r_knee_L"][1], mid("r_hip_L", "r_hock_L"))
        self.assertGreater(j["f_elbow_L"][1], mid("f_shoulder_L", "f_wrist_L"))

    def test_classify(self):
        for module, variants, expected in (
            (quadruped, quadruped.VARIANTS, body_type.QUADRUPED),
            (humanoid, humanoid.VARIANTS, body_type.BIPED),
        ):
            for v in variants:
                pts, _ = _points(module, v)
                kind, legs = body_type.classify(pts)
                self.assertEqual(kind, expected, f"{v}: 다리 {legs}개")


if __name__ == "__main__":
    unittest.main()
