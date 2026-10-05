"""Landmark Agent 순수 로직 단위 테스트: 광선 교차, 병합, 굽힘 보정, 스키마 검증."""

import json
import pathlib
import sys
import unittest
from math import dist

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from agents import landmark_schema  # noqa: E402
from core import landmark_merge  # noqa: E402
from core.triangulate import OrthoView, intersect_rays  # noqa: E402

FRONT = OrthoView("front", (0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0), 2.0)
SIDE = OrthoView("side", (0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (-1.0, 0.0, 0.0), 2.0)


def fake_response(points, kind="BIPED", conf=0.9):
    out = {"body_type": kind, "notes": ""}
    for view in (FRONT, SIDE):
        entries = {}
        for name in landmark_schema.joint_names(kind):
            p = points.get(name, (0.0, 0.0, 1.0))
            u, v = view.project(p)
            entries[name] = {"u": u, "v": v, "visible": name in points, "confidence": conf}
        out[view.name] = entries
    return out


class TriangulateTest(unittest.TestCase):
    def test_project_ray_roundtrip(self):
        p = (0.3, -0.2, 1.4)
        rays = [v.ray(*v.project(p)) for v in (FRONT, SIDE)]
        self.assertLess(dist(intersect_rays(rays), p), 1e-9)

    def test_parallel_rays_rejected(self):
        with self.assertRaises(ValueError):
            intersect_rays([FRONT.ray(0.5, 0.5), FRONT.ray(0.6, 0.5)])


class MergeTest(unittest.TestCase):
    def test_merge_weights_and_outlier(self):
        truth = {"knee_L": (0.1, -0.05, 0.5), "elbow_L": (0.4, 0.05, 1.4), "hip_L": (0.1, 0.0, 0.9)}
        heur = {"knee_L": (0.1, -0.05, 0.56), "elbow_L": (0.4, 0.05, 1.4), "hip_L": (0.1, 0.0, 0.9)}
        ai = fake_response({**truth, "hip_L": (0.1, 0.0, 1.5)}, conf=1.0)  # hip 는 오인식(0.6 이탈)
        ai3d = landmark_merge.triangulate_joints(ai, {"front": FRONT, "side": SIDE})
        merged, used = landmark_merge.merge(heur, ai3d, size=1.8)
        self.assertIn("knee_L", used)
        self.assertNotIn("hip_L", used)
        self.assertLess(dist(merged["knee_L"], truth["knee_L"]), dist(heur["knee_L"], truth["knee_L"]))
        self.assertEqual(merged["hip_L"], heur["hip_L"])

    def test_low_confidence_ignored(self):
        heur = {"knee_L": (0.1, 0.0, 0.5)}
        ai3d = landmark_merge.triangulate_joints(fake_response({"knee_L": (0.1, 0.0, 0.45)}, conf=0.3),
                                                 {"front": FRONT, "side": SIDE})
        merged, used = landmark_merge.merge(heur, ai3d, 1.8)
        self.assertEqual(used, [])

    def test_enforce_bends(self):
        j = {"hip_L": (0.1, 0.0, 0.9), "knee_L": (0.1, 0.05, 0.5), "ankle_L": (0.1, 0.0, 0.1),
             "shoulder_L": (0.2, 0.0, 1.4), "elbow_L": (0.45, -0.05, 1.4), "wrist_L": (0.7, 0.0, 1.4)}
        out = landmark_merge.enforce_bends(j, "BIPED", "-Y")
        self.assertLess(out["knee_L"][1], 0.0)   # 정면(-Y) 쪽으로
        self.assertGreater(out["elbow_L"][1], 0.0)  # 뒤(+Y) 쪽으로
        out = landmark_merge.enforce_bends(j, "BIPED", "+Y")
        self.assertGreater(out["knee_L"][1], 0.0)


class SchemaTest(unittest.TestCase):
    def test_schema_strict_and_complete(self):
        for kind in ("BIPED", "QUADRUPED"):
            s = landmark_schema.response_schema(kind)
            self.assertFalse(s["additionalProperties"])
            self.assertEqual(set(s["properties"]["front"]["required"]), set(landmark_schema.joint_names(kind)))
            for name in landmark_schema.joint_names(kind):
                base = name[:-2] if name.endswith(("_L", "_R")) else name
                self.assertIn(base, landmark_schema.JOINT_DESCRIPTIONS)

    def test_parse_clamps_and_validates(self):
        data = fake_response({"knee_L": (0.1, 0.0, 0.5)})
        data["front"]["knee_L"]["u"] = 1.7
        parsed = landmark_schema.parse_response(json.dumps(data), "BIPED")
        self.assertEqual(parsed["front"]["knee_L"]["u"], 1.0)
        del data["side"]["knee_R"]
        with self.assertRaises(landmark_schema.LandmarkResponseError):
            landmark_schema.parse_response(json.dumps(data), "BIPED")
        with self.assertRaises(landmark_schema.LandmarkResponseError):
            landmark_schema.parse_response("not json", "BIPED")


if __name__ == "__main__":
    unittest.main()
