"""애니메이션(루프·단발) 키 생성·Motion Agent 파라미터 검증 단위 테스트 (bpy 비의존)."""

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
                self.assertEqual(m.loop, motion in L.LOOPING)
                for c in m.channels:
                    self.assertLessEqual(len(c.keys), 9, f"{motion} {c.bone} {c.kind}: 키가 너무 많음")
                    self.assertEqual([k.t for k in c.keys], sorted(k.t for k in c.keys), f"{motion} {c.bone}: 키 순서")
                    if c.bone == "root":  # 전진은 선형 키
                        continue
                    if m.loop:
                        self.assertAlmostEqual(c.keys[-1].t - c.keys[0].t, 1.0)
                        self.assertEqual(c.keys[-1].value, c.keys[0].value, f"{motion} {c.bone} 루프가 닫히지 않음")
                    else:
                        # 단발 동작은 0 에서 시작해 1 에서 끝나고, 사망을 뺀 나머지는 레스트로 돌아온다
                        self.assertEqual((c.keys[0].t, c.keys[-1].t), (0.0, 1.0), f"{motion} {c.bone}: 단발 구간")
                        if c.kind == "loc":
                            self.assertEqual(c.keys[0].value, (0.0, 0.0, 0.0), f"{motion} {c.bone}: 레스트 위치에서 시작")
                        if motion != "DEATH":
                            self.assertEqual(c.keys[-1].value, c.keys[0].value, f"{motion} {c.bone}: 시작 자세로 복귀")
                per_frame = len(m.channels) * m.params.cycle_frames
                self.assertLess(m.key_count(), per_frame / 3, f"{motion}: 매 프레임 방식 대비 키 절감 부족")

    def test_jump_flight_and_root_motion(self):
        p = L.preset("JUMP", root_motion=True)
        m = L.generate(p, LEG, ARM)
        feet = channel(m, "foot_ik.L", "loc").keys
        torso = channel(m, "torso", "loc").keys
        apex = max(feet, key=lambda k: k.value[2])
        self.assertGreater(apex.value[2], p.jump_height * LEG, "체공 중 발은 몸통보다 더 올라간다(무릎 접음)")
        self.assertAlmostEqual(max(k.value[2] for k in torso), p.jump_height * LEG)
        self.assertLess(min(k.value[2] for k in torso), 0.0, "도약 전 웅크림")
        root = channel(m, "root", "loc").keys
        self.assertEqual([k.interp for k in root], [L.LINEAR] * 4)
        self.assertAlmostEqual(root[-1].value[1], p.stride * LEG)
        self.assertAlmostEqual(m.root_distance, p.stride * LEG)
        self.assertEqual(root[1].value[1], 0.0, "도약 전에는 전진하지 않는다")

    def test_attack_swings_chosen_hand(self):
        for side, sgn in (("R", -1.0), ("L", 1.0)):
            p = L.preset("ATTACK", attack_side=side)
            m = L.generate(p, LEG, ARM)
            other = "L" if side == "R" else "R"
            swing = channel(m, f"hand_ik.{side}", "loc").keys
            guard = channel(m, f"hand_ik.{other}", "loc").keys
            reach = max(k.value[1] for k in swing)
            self.assertGreater(reach, 0.7 * p.arm_forward * ARM, f"{side}: 휘두르는 손이 앞으로 뻗음")
            self.assertGreater(reach, max(k.value[1] for k in guard), f"{side}: 방어 손은 덜 뻗음")
            windup = min(swing, key=lambda k: k.value[1])
            self.assertLess(windup.value[1], 0.0, f"{side}: 준비 때 손을 뒤로 뺌")
            yaw = [k.value[2] for k in channel(m, "torso", "rot").keys]
            self.assertEqual((yaw[1] > 0) if sgn > 0 else (yaw[1] < 0), True, f"{side}: 준비 때 그쪽으로 몸을 돎")
            self.assertEqual((yaw[2] < 0) if sgn > 0 else (yaw[2] > 0), True, f"{side}: 타격 때 반대로 돎")
        self.assertEqual(L.clamp({"motion": "ATTACK", "attack_side": "X"}).attack_side, "R")

    def test_hit_recoils_and_death_lies_down(self):
        hit = L.generate(L.preset("HIT"), LEG, ARM)
        self.assertLess(min(k.value[1] for k in channel(hit, "torso", "loc").keys), 0.0, "피격: 뒤로 밀림")
        self.assertLess(min(k.value[0] for k in channel(hit, "torso", "rot").keys), 0.0, "피격: 뒤로 젖혀짐")
        for fall_dir, sign in (("BACK", -1.0), ("FRONT", 1.0)):
            m = L.generate(L.preset("DEATH", fall_dir=fall_dir), LEG, ARM)
            torso = channel(m, "torso", "loc").keys
            self.assertLess(torso[-1].value[2], -0.8 * LEG, f"{fall_dir}: 골반이 바닥 근처까지 내려감")
            self.assertGreater(torso[-1].value[2], -1.1 * LEG, f"{fall_dir}: 바닥을 뚫지 않음")
            self.assertEqual(torso[-1].value[1] > 0, sign > 0, f"{fall_dir}: 쓰러지는 방향")
            pitch = channel(m, "torso", "rot").keys[-1].value[0]
            self.assertAlmostEqual(pitch, sign * 88.0)
            feet = channel(m, "foot_ik.L", "loc").keys
            self.assertEqual(feet[-1].value[1] > 0, sign < 0, f"{fall_dir}: 발은 골반 반대쪽으로 펴짐")
            self.assertEqual(feet[-1].value, feet[-2].value, f"{fall_dir}: 끝 자세 유지")
        self.assertEqual(L.clamp({"motion": "DEATH", "fall_dir": "SIDE"}).fall_dir, "BACK")

    def test_happy_hops_with_arms_up(self):
        p = L.preset("HAPPY")
        m = L.generate(p, LEG, ARM)
        self.assertTrue(m.loop)
        feet = channel(m, "foot_ik.L", "loc").keys
        self.assertEqual(sum(1 for k in feet if k.value[2] > 0), 2, "주기당 두 번 깡충")
        self.assertEqual(feet[0].value, (0.0, 0.0, 0.0))
        hands = channel(m, "hand_ik.L", "loc").keys
        self.assertGreater(min(k.value[2] for k in hands), 0.5 * p.arm_raise * ARM, "팔을 계속 들고 있음")
        self.assertFalse(any(c.bone.startswith("foot_ik") for c in L.generate(L.preset("HAPPY", step_height=0.0), LEG, ARM).channels))
        self.assertFalse(L.clamp({"motion": "HAPPY", "root_motion": True}).root_motion)

    def test_sample_holds_clip_end(self):
        keys = [L.Key(0.0, (0.0,)), L.Key(0.5, (1.0,)), L.Key(1.0, (2.0,))]
        self.assertEqual(L.sample(keys, 1.0), (2.0,))
        self.assertEqual(L.sample(keys, 0.25), (0.5,))
        self.assertEqual(L.sample(keys, 1.25), (0.5,), "범위 밖은 한 주기로 접음")

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
        self.assertFalse(L.clamp({"motion": "ATTACK", "root_motion": True}).root_motion)
        self.assertTrue(L.clamp({"motion": "JUMP", "root_motion": True}).root_motion)


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
        self.assertIn("DEATH", txt)
        self.assertIn("fall_dir", txt)
        rev = motion_agent.review_prompt("좀비 걷기", L.preset("WALK"), ["side_t000", "front_t000"])
        self.assertIn("side_t000, front_t000", rev)


if __name__ == "__main__":
    unittest.main()
