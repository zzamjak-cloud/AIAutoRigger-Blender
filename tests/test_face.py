"""턱·눈 검출 단위 테스트 (bpy 비의존): 입 벌린 상자 머리 픽스처."""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
from core import face, sampling  # noqa: E402
import humanoid  # noqa: E402


def points(rotate=False):
    bv, bt, gt, hv, ht, ev, et = humanoid.build_face_variant()
    verts = bv + hv
    tris = bt + [(a + len(bv), b + len(bv), c + len(bv)) for a, b, c in ht]
    if rotate:
        verts = [(-v[0], -v[1], v[2]) for v in verts]
    return head_samples(verts, tris, gt), gt


def head_samples(verts, tris, gt):
    # 애드온과 같이 목 위 삼각형만 샘플링한다
    z0 = gt["head_base"][2] - 0.08
    return sampling.sample_surface(verts, [t for t in tris if max(verts[i][2] for i in t) > z0], 60000, seed=3)


class JawTest(unittest.TestCase):
    def test_open_mouth(self):
        pts, gt = points()
        neck = (0.0, 0.0, gt["head_base"][2] - 0.08)
        jaw, why = face.detect_jaw(pts, neck, gt["head_top"], 0.0, "-Y")
        self.assertIsNotNone(jaw, why)
        self.assertAlmostEqual(jaw.lip_z, gt["lip_z"], delta=0.01)
        self.assertAlmostEqual(jaw.chin_bottom_z, gt["chin_bottom_z"], delta=0.01)
        self.assertGreater(jaw.pivot[2], jaw.lip_z)
        self.assertLess(jaw.chin[2], jaw.lip_z)
        # 아래턱 앞은 1, 이마·목은 0
        self.assertEqual(face.jaw_weight((0.0, -0.1, gt["chin_bottom_z"] + 0.01), jaw), 1.0)
        self.assertEqual(face.jaw_weight((0.0, -0.1, gt["lip_z"] + 0.1), jaw), 0.0)
        self.assertEqual(face.jaw_weight((0.0, -0.05, gt["chin_bottom_z"] - 0.08), jaw), 0.0)
        # 머리 폭 밖(어깨·손 등)은 같은 높이·앞쪽이어도 턱에 끌려가지 않는다
        self.assertEqual(face.jaw_weight((0.2, -0.1, gt["chin_bottom_z"] + 0.01), jaw), 0.0)
        self.assertEqual(face.jaw_weight((0.09, -0.1, gt["chin_bottom_z"] + 0.01), jaw), 1.0)

    def test_facing_plus_y(self):
        pts, gt = points(rotate=True)
        jaw, why = face.detect_jaw(pts, (0.0, 0.0, gt["head_base"][2] - 0.08), gt["head_top"], 0.0, "+Y")
        self.assertIsNotNone(jaw, why)
        self.assertAlmostEqual(jaw.lip_z, gt["lip_z"], delta=0.01)
        self.assertGreater(jaw.chin[1], jaw.pivot[1])  # 턱 끝이 정면(+Y) 쪽

    def test_box_head_has_no_jaw(self):
        verts, tris, gt = humanoid.build("realistic_t")
        pts = head_samples(verts, tris, gt)
        jaw, why = face.detect_jaw(pts, (0.0, 0.0, gt["head_base"][2] - 0.08), gt["head_top"], 0.0, "-Y")
        self.assertIsNone(jaw)
        self.assertTrue(why)


class EyeTest(unittest.TestCase):
    def test_pick_symmetric_pair(self):
        center, width = (0.0, 0.0, 1.75), 0.2
        islands = [((0.045, -0.105, 1.79), 0.015, 1), ((-0.045, -0.105, 1.79), 0.015, 2),
                   ((0.0, 0.05, 1.2), 0.3, 3), ((0.03, -0.09, 1.68), 0.01, 4)]
        eyes = face.pick_eyes(islands, center, width, 1.85, 1.7, "-Y")
        self.assertEqual([(e.side, e.island) for e in eyes], [("L", 1), ("R", 2)])
        eyes = face.pick_eyes([(( -c[0], -c[1], c[2]), r, i) for c, r, i in islands], (0.0, 0.0, 1.75), width, 1.85, 1.7, "+Y")
        self.assertEqual([(e.side, e.island) for e in eyes], [("L", 1), ("R", 2)])

    def test_no_pair(self):
        self.assertEqual(face.pick_eyes([((0.045, -0.105, 1.79), 0.015, 1)], (0.0, 0.0, 1.75), 0.2, 1.85, 1.7), [])

    def test_roundtrip(self):
        f = face.Face(face.Jaw((0, 0, 1), (0, -0.1, 0.9), 0.95, 0.88, 0.2, 0.3, -1.0), [face.Eye("L", (0.04, -0.1, 1.0), 0.01, 3)])
        self.assertEqual(face.Face.from_dict(f.to_dict()).to_dict(), f.to_dict())


if __name__ == "__main__":
    unittest.main()
