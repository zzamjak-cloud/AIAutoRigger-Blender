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

    def test_fat_buried_neck(self):
        # 목이 어깨 살에 묻혀도 정수리를 목으로 오인하지 않고, 굵은 다리에서도 발목이 발등 위에 온다
        r = self._run("fat_a")
        self.assertGreater(r.joints["head_top"][2] - r.joints["head_base"][2], 0.5 * 0.22)

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

    def test_bend_measured_from_limb_line(self):
        # 모든 체형에서 무릎은 엉덩이→발목 선보다 앞, 팔꿈치는 어깨→손목 선보다 뒤 (선 기준, 단면 중심 기준이 아님)
        def offset(a, m, b):
            ab = [b[i] - a[i] for i in range(3)]
            u = sum((m[i] - a[i]) * ab[i] for i in range(3)) / sum(x * x for x in ab)
            return m[1] - (a[1] + ab[1] * u)
        for variant in humanoid.VARIANTS:
            verts, tris, _ = humanoid.build(variant)
            j = biped.estimate_biped(sampling.sample_surface(verts, tris, 30000, seed=3)).joints
            for s in ("L", "R"):
                self.assertLess(offset(j[f"hip_{s}"], j[f"knee_{s}"], j[f"ankle_{s}"]), -0.01, f"{variant} 무릎 {s}")
                self.assertGreater(offset(j[f"shoulder_{s}"], j[f"elbow_{s}"], j[f"wrist_{s}"]), 0.01, f"{variant} 팔꿈치 {s}")

    def test_bend_off_line_fixes_forward_ankle(self):
        # Zombie_Big 실측: 발목이 엉덩이보다 앞(-Y)이라 단면 중심 무릎이 선보다 4.6cm 뒤에 있던 경우
        hip, knee, ankle = (0.19, -0.004, 0.639), (0.218, 0.001, 0.392), (0.202, -0.087, 0.146)
        fixed = biped.bend_off_line(hip, knee, ankle, -1.0, 0.015)
        ab = [ankle[i] - hip[i] for i in range(3)]
        u = sum((knee[i] - hip[i]) * ab[i] for i in range(3)) / sum(x * x for x in ab)
        line_y = hip[1] + ab[1] * u
        self.assertLess(fixed[1], line_y - 0.014)
        self.assertEqual((fixed[0], fixed[2]), (knee[0], knee[2]), "앞뒤(Y)만 바꾼다")
        already = (0.2, -0.2, 0.39)
        self.assertEqual(biped.bend_off_line(hip, already, ankle, -1.0, 0.015), already, "이미 앞이면 그대로")
        elbow = biped.bend_off_line((0.5, 0.0, 1.6), (0.9, -0.05, 1.3), (1.2, 0.0, 1.0), 1.0, 0.02)
        self.assertGreaterEqual(elbow[1], 0.02 - 1e-9)

    def test_sampling_deterministic(self):
        verts, tris, _ = humanoid.build("realistic_t")
        self.assertEqual(sampling.sample_surface(verts, tris, 100, seed=5), sampling.sample_surface(verts, tris, 100, seed=5))


if __name__ == "__main__":
    unittest.main()
