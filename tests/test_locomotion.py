"""이동 루프 키 생성·Motion Agent 파라미터 검증 단위 테스트 (bpy 비의존)."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from agents import motion_agent  # noqa: E402
from core import locomotion as L  # noqa: E402

LEG, ARM = 0.85, 0.6


def channel(m, bone, kind):
    return next(c for c in m.channels if c.bone == bone and c.kind == kind)


class LocomotionTest(unittest.TestCase):
    def test_sparse_keys_and_closed_loops(self):
        for motion in L.MOTIONS:
            for style in L.STYLES:
                m = L.generate(L.preset(motion, style), LEG, ARM)
                for c in m.channels:
                    self.assertLessEqual(len(c.keys), 9, f"{motion} {c.bone} {c.kind}: 키가 너무 많음")
                    if c.bone != "root":  # 전진은 선형 두 키
                        self.assertAlmostEqual(c.keys[-1].t - c.keys[0].t, 1.0)
                        self.assertEqual(c.keys[-1].value, c.keys[0].value, f"{motion} {c.bone} 루프가 닫히지 않음")
                per_frame = len(m.channels) * m.params.cycle_frames
                self.assertLess(m.key_count(), per_frame / 3, f"{motion}: 매 프레임 방식 대비 키 절감 부족")

    def test_planted_foot_is_linear_and_on_ground(self):
        p = L.preset("WALK")
        foot = channel(L.generate(p, LEG, ARM), "foot_ik.L", "loc").keys
        contact, flat, toe_off = foot[0], foot[1], foot[2]
        self.assertEqual((contact.interp, flat.interp, toe_off.interp), (L.LINEAR, L.LINEAR, L.BEZIER))
        self.assertTrue(all(k.value[2] == 0.0 for k in (contact, flat, toe_off)))
        s = p.stride * LEG
        self.assertAlmostEqual(contact.value[1], s / 2)
        self.assertAlmostEqual(toe_off.value[1], -s / 2)
        # 딛는 동안 일정 속도로 뒤로 (제자리 걷기의 러닝머신 이동)
        v1 = (flat.value[1] - contact.value[1]) / (flat.t - contact.t)
        v2 = (toe_off.value[1] - flat.value[1]) / (toe_off.t - flat.t)
        self.assertAlmostEqual(v1, v2)
        self.assertAlmostEqual(foot[3].value[2], p.step_height * LEG)

    def test_feet_alternate_and_arms_oppose(self):
        m = L.generate(L.preset("WALK"), LEG, ARM)
        self.assertAlmostEqual(channel(m, "foot_ik.R", "loc").keys[0].t - channel(m, "foot_ik.L", "loc").keys[0].t, 0.5)
        # 왼발이 앞(0)일 때 오른손이 앞
        r = L.sample(channel(m, "hand_ik.R", "loc").keys, 0.0)[1]
        l = L.sample(channel(m, "hand_ik.L", "loc").keys, 0.0)[1]
        self.assertGreater(r, l)

    def test_limp_and_root_motion(self):
        p = L.preset("WALK", "ZOMBIE", root_motion=True)
        m = L.generate(p, LEG, ARM)
        hl = max(k.value[2] for k in channel(m, "foot_ik.L", "loc").keys)
        hr = max(k.value[2] for k in channel(m, "foot_ik.R", "loc").keys)
        self.assertLess(hr, 0.6 * hl, "끄는 오른발은 덜 들어야 함")
        root = channel(m, "root", "loc").keys
        self.assertEqual([k.interp for k in root], [L.LINEAR, L.LINEAR])
        self.assertAlmostEqual(root[1].value[1], m.root_distance)
        self.assertAlmostEqual(m.root_distance, p.stride * LEG / p.duty)

    def test_run_has_flight_and_idle_keeps_feet(self):
        run = L.generate(L.preset("RUN"), LEG, ARM)
        torso = channel(run, "torso", "loc").keys
        high = max(torso, key=lambda k: k.value[2])
        # 체공 중간에는 두 발 모두 땅에 없다 (딛는 비율 < 0.5)
        self.assertGreater(run.params.duty, 0.0)
        self.assertLess(run.params.duty, 0.5)
        self.assertTrue(run.params.duty < (high.t % 0.5) < 0.5 or run.params.duty < ((high.t + 0.5) % 1.0))
        idle = L.generate(L.preset("IDLE", "ZOMBIE"), LEG, ARM)
        self.assertFalse(any(c.bone.startswith("foot_ik") for c in idle.channels))
        self.assertFalse(idle.params.root_motion)

    def test_clamp(self):
        p = L.clamp({"motion": "RUN", "cycle_frames": 999, "stride": -3, "limp_side": "X", "lean_deg": True, "bogus": 1})
        self.assertEqual(p.cycle_frames, 240)
        self.assertEqual(p.stride, 0.0)
        self.assertEqual(p.limp_side, "NONE")
        self.assertEqual(p.lean_deg, L.PRESETS[("RUN", "NORMAL")]["lean_deg"])
        self.assertEqual(L.clamp({"motion": "DANCE"}).motion, "WALK")


class MotionAgentTest(unittest.TestCase):
    def test_schema_strict(self):
        s = motion_agent.schema()
        params = s["properties"]["params"]
        self.assertFalse(s["additionalProperties"] or params["additionalProperties"])
        self.assertEqual(set(params["required"]), set(params["properties"]))
        self.assertEqual(set(params["properties"]), set(L.GaitParams.__dataclass_fields__))
        self.assertEqual(set(motion_agent.DESCRIPTIONS), set(L.GaitParams.__dataclass_fields__))

    def test_parse(self):
        p, done, summary = motion_agent.parse({"params": {"motion": "WALK", "limp": 5}, "done": True, "summary": "ok"})
        self.assertEqual((p.limp, done, summary), (1.0, True, "ok"))
        with self.assertRaises(ValueError):
            motion_agent.parse({"done": True})

    def test_prompts_mention_request_and_images(self):
        txt = motion_agent.request_prompt("좀비 걷기", "WALK", LEG, ARM, L.preset("WALK"))
        self.assertIn("좀비 걷기", txt)
        self.assertIn("stride", txt)
        rev = motion_agent.review_prompt("좀비 걷기", L.preset("WALK"), ["side_t000", "front_t000"])
        self.assertIn("side_t000, front_t000", rev)


if __name__ == "__main__":
    unittest.main()
