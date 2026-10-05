"""bpy 없이 실행되는 순수 Python 단위 테스트: python3 -m unittest discover -s tests"""

import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 패키지 루트 __init__.py 가 bpy 를 import 하므로 core 모듈만 직접 로드한다
_spec = importlib.util.spec_from_file_location("mesh_analysis", ROOT / "core" / "mesh_analysis.py")
mesh_analysis = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mesh_analysis
_spec.loader.exec_module(mesh_analysis)


def _box(sx, sy, sz, ox=0.0):
    return [
        (ox + x * sx, y * sy, z * sz)
        for x in (-0.5, 0.5)
        for y in (-0.5, 0.5)
        for z in (0.0, 1.0)
    ]


class MeshAnalysisTest(unittest.TestCase):
    def test_symmetric_box(self):
        r = mesh_analysis.analyze_points(_box(0.5, 0.3, 1.8))
        self.assertEqual(r.vertex_count, 8)
        self.assertEqual(r.up_axis, "Z")
        self.assertAlmostEqual(r.dimensions[2], 1.8)
        self.assertAlmostEqual(r.center_x, 0.0)
        self.assertAlmostEqual(r.symmetry_x, 1.0)

    def test_y_up_detection(self):
        r = mesh_analysis.analyze_points(_box(0.5, 1.8, 0.3))
        self.assertEqual(r.up_axis, "Y")

    def test_asymmetric_points(self):
        pts = _box(1.0, 1.0, 1.0) + [(0.4, 0.1, 0.3), (0.45, -0.2, 0.7)]
        r = mesh_analysis.analyze_points(pts)
        self.assertLess(r.symmetry_x, 1.0)
        self.assertGreater(r.symmetry_x, 0.7)

    def test_offset_center(self):
        r = mesh_analysis.analyze_points(_box(1.0, 1.0, 1.0, ox=3.0))
        self.assertAlmostEqual(r.center_x, 3.0)
        self.assertAlmostEqual(r.symmetry_x, 1.0)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            mesh_analysis.analyze_points([])


if __name__ == "__main__":
    unittest.main()
