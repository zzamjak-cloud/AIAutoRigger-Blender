"""평가 하네스 본 이름 매핑·집계 단위 테스트 (bpy 비의존)."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from core import evaluation  # noqa: E402

H, T = (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)


def joints(names, kind="BIPED"):
    return set(evaluation.map_bones([(n, H, T) for n in names], kind))


class BoneNameTest(unittest.TestCase):
    def test_mixamo(self):
        names = ["mixamorig:Hips", "mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot",
                 "mixamorig:LeftToeBase", "mixamorig:LeftShoulder", "mixamorig:LeftArm", "mixamorig:LeftForeArm",
                 "mixamorig:LeftHand", "mixamorig:LeftHandIndex1", "mixamorig:Head"]
        self.assertEqual(joints(names), {"hip_L", "knee_L", "ankle_L", "shoulder_L", "elbow_L", "wrist_L", "head_base"})

    def test_blender_rigify_unity_bip(self):
        self.assertEqual(joints(["thigh.L", "shin.L", "foot.L", "upper_arm.L", "forearm.L", "hand.L"]),
                         {"hip_L", "knee_L", "ankle_L", "shoulder_L", "elbow_L", "wrist_L"})
        self.assertEqual(joints(["DEF-thigh.R", "DEF-thigh.R.001", "DEF-forearm.R"]), {"hip_R", "elbow_R"})
        self.assertEqual(joints(["RightUpperLeg", "RightLowerLeg", "RightUpperArm", "RightLowerArm"]),
                         {"hip_R", "knee_R", "shoulder_R", "elbow_R"})
        self.assertEqual(joints(["Bip01 L Thigh", "Bip01 L Calf", "Bip01 L UpperArm", "Bip01 L Forearm"]),
                         {"hip_L", "knee_L", "shoulder_L", "elbow_L"})

    def test_quadruped(self):
        self.assertEqual(
            joints(["front_thigh.L", "front_shin.L", "front_foot.L", "thigh.L", "shin.L", "foot.L", "tail.001"], "QUADRUPED"),
            {"f_shoulder_L", "f_elbow_L", "f_wrist_L", "r_hip_L", "r_knee_L", "r_hock_L"},
        )
        self.assertEqual(joints(["UpperArm.R", "LowerArm.R", "Hand.R", "BackThigh.R"], "QUADRUPED"),
                         {"f_shoulder_R", "f_elbow_R", "f_wrist_R", "r_hip_R"})

    def test_summary_and_markdown(self):
        ok = evaluation.CaseResult("a", "cat", "BIPED", True, joint_errors={"hip_L": 0.02, "knee_L": 0.04})
        bad = evaluation.CaseResult("b", "cat", "BIPED", False, error="x")
        s = evaluation.summarize([ok, bad])
        self.assertEqual(s["cat"]["success"], 1)
        self.assertAlmostEqual(s["cat"]["mean_joint_error"], 0.03)
        md = evaluation.to_markdown([ok, bad], s)
        self.assertIn("| cat | 2 | 1 |", md)
        self.assertIn("실패: x", md)


if __name__ == "__main__":
    unittest.main()
