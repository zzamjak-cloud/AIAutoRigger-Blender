"""2족 관절 휴리스틱 단위 테스트 (bpy 비의존)."""

import importlib.util
import pathlib
import sys
import unittest
from math import dist

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sampling = _load("sampling", ROOT / "core" / "sampling.py")
biped = _load("biped_landmarks", ROOT / "core" / "biped_landmarks.py")
humanoid = _load("humanoid_fixture", ROOT / "tests" / "fixtures" / "humanoid.py")

# 높이 대비 허용 오차
TOLERANCE = 0.06
CHECKED = ("hip", "knee", "ankle", "shoulder", "elbow", "wrist", "hand_tip")


class BipedLandmarkTest(unittest.TestCase):
    def _run(self, variant, flip=False):
        verts, tris, gt = humanoid.build(variant)
        if flip:
            verts = [(-v[0], -v[1], v[2]) for v in verts]
            gt = {k: (-v[0], -v[1], v[2]) for k, v in gt.items()}
        pts = sampling.sample_surface(verts, tris, 30000, seed=1)
        result = biped.estimate_biped(pts)
        H = result.height
        for joint in CHECKED:
            for side in ("L", "R"):
                key = f"{joint}_{side}"
                err = dist(result.joints[key], gt[key]) / H
                self.assertLess(err, TOLERANCE, f"{variant} {key} 오차 {err:.3f} est={result.joints[key]} gt={gt[key]}")
        err = abs(result.joints["head_base"][2] - gt["head_base"][2]) / H
        self.assertLess(err, TOLERANCE, f"{variant} head_base 높이 오차 {err:.3f}")
        return result

    def test_realistic_t_pose(self):
        r = self._run("realistic_t")
        self.assertEqual(r.facing, "-Y")

    def test_realistic_a_pose(self):
        self._run("realistic_a")

    def test_stylized_proportions(self):
        self._run("stylized_t")

    def test_facing_plus_y(self):
        r = self._run("realistic_t", flip=True)
        self.assertEqual(r.facing, "+Y")

    def test_ik_bend_direction(self):
        verts, tris, _ = humanoid.build("realistic_t")
        r = biped.estimate_biped(sampling.sample_surface(verts, tris, 30000, seed=2))
        j = r.joints
        # 무릎은 앞(-Y), 팔꿈치는 뒤(+Y)로 굽어 있어야 Rigify IK 극 방향이 정해진다
        self.assertLess(j["knee_L"][1], 0.5 * (j["hip_L"][1] + j["ankle_L"][1]))
        self.assertGreater(j["elbow_L"][1], 0.5 * (j["shoulder_L"][1] + j["wrist_L"][1]))

    def test_sampling_deterministic(self):
        verts, tris, _ = humanoid.build("realistic_t")
        self.assertEqual(sampling.sample_surface(verts, tris, 100, seed=5), sampling.sample_surface(verts, tris, 100, seed=5))


if __name__ == "__main__":
    unittest.main()
