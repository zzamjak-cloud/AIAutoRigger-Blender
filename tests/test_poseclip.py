"""포즈 클립 변환·클램프·동작 사전·Motion Agent 클립 응답 단위 테스트 (bpy 비의존)."""

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from agents import motion_agent  # noqa: E402
from core import locomotion as L  # noqa: E402
from core import poseclip as P  # noqa: E402

LEG, ARM = 0.85, 0.6
BODY = P.Body.approx(LEG, ARM)


def channel(m, bone, kind):
    return next(c for c in m.channels if c.bone == bone and c.kind == kind)


class ClampTest(unittest.TestCase):
    def test_clamp_ranges_and_order(self):
        clip = P.clamp({"name": "My Clip!", "loop": False, "frames": 999, "keys": [
            {"t": 0.8, "foot_L": {"up": -1.0, "fwd": 5.0}, "bogus": 1},
            {"t": 0.2, "hand_R": {"up": 9.0}, "torso": {"up": -3.0}, "ease": "LINEAR"},
            {"t": 0.0, "rest": True},
        ]})
        self.assertEqual(clip["name"], "my_clip")
        self.assertEqual(clip["frames"], 240)
        self.assertEqual([k["t"] for k in clip["keys"]], [0.0, 0.2, 0.8])
        self.assertEqual(clip["keys"][2]["foot_L"]["up"], 0.0, "발은 바닥 아래로 못 간다")
        self.assertEqual(clip["keys"][2]["foot_L"]["fwd"], 0.8)
        self.assertEqual(clip["keys"][1]["hand_R"]["up"], 1.2)
        self.assertEqual(clip["keys"][1]["ease"], L.LINEAR)
        self.assertIsNone(clip["keys"][1]["hips"])
        self.assertTrue(clip["keys"][0]["rest"])

    def test_loop_drops_end_key_and_limits_count(self):
        keys = [{"t": i / 20.0, "torso": {"up": 0.01 * i}} for i in range(21)]
        clip = P.clamp({"name": "x", "loop": True, "frames": 24, "keys": keys})
        self.assertEqual(len(clip["keys"]), P.MAX_KEYS)
        self.assertLess(clip["keys"][-1]["t"], 1.0)
        with self.assertRaises(ValueError):
            P.clamp({"name": "x", "loop": True, "keys": [{"t": 1.0, "torso": {}}]})
        with self.assertRaises(ValueError):
            P.clamp({"keys": "nope"})


class ToMotionTest(unittest.TestCase):
    def clip(self, loop=False, **extra):
        return P.clamp({"name": "t", "loop": loop, "frames": 24, "keys": [
            {"t": 0.0, "rest": True},
            {"t": 0.3, "torso": {"fwd": 0.2, "up": -0.1, "pitch": 10}, "hand_R": {"fwd": 0.5, "up": 0.4}},
            {"t": 0.6, "hand_R": {"fwd": 0.9, "up": 0.5}, "foot_R": {"fwd": 0.3, "up": 0.0}},
            {"t": 0.8, "foot_R": {"fwd": 0.5, "up": 0.0}},
            {"t": 0.95, "torso": {"up": -0.05}, "hand_R": {"fwd": 0.1, "up": 0.1}},
        ] + ([] if loop else [{"t": 1.0, "rest": True}]), **extra})

    def test_units_follow_and_hold(self):
        m = P.to_motion(P.ClipParams(self.clip()), BODY)
        self.assertFalse(m.loop)
        torso = channel(m, "torso", "loc").keys
        self.assertEqual((torso[0].t, torso[-1].t), (0.0, 1.0))
        self.assertAlmostEqual(torso[1].value[1], 0.2 * LEG)
        hand = channel(m, "hand_ik.R", "loc").keys
        at = {round(k.t, 4): k for k in hand}
        self.assertIn(0.3, at)
        # 손은 어깨 기준 팔 길이 비율: (어깨 오프셋 + 값×팔 길이)를 몸통 피벗 중심으로 몸통 회전(pitch 10)만큼 돌리고 몸통 이동을 더한다
        sh, pv = BODY.shoulder["R"], BODY.pivot["R"]
        u = (sh[0], sh[1] + 0.5 * ARM, sh[2] + 0.4 * ARM)
        want = P._hand_offset(u, (0.0, 0.2 * LEG, -0.1 * LEG), (10.0, 0.0, 0.0), pv)
        for a, b in zip(at[0.3].value, want):
            self.assertAlmostEqual(a, b)
        # 앞으로 숙이면(pitch>0) 어깨 위 손은 더 앞으로 간다
        self.assertGreater(want[1], sh[1] + 0.5 * ARM + 0.2 * LEG)
        plain = P._hand_offset(u, (0.0, 0.2 * LEG, -0.1 * LEG), (0.0, 0.0, 0.0), pv)
        self.assertAlmostEqual(plain[1], sh[1] + 0.5 * ARM + 0.2 * LEG)

        self.assertEqual(hand[-1].value, (0.0, 0.0, 0.0), "단발은 레스트로 끝남")
        # 접지 키 사이는 선형, 키가 없던 발은 레스트에서 시작
        foot = channel(m, "foot_ik.R", "loc").keys
        self.assertEqual(foot[0].value, (0.0, 0.0, 0.0))
        planted = next(k for k in foot if round(k.t, 4) == 0.6)
        self.assertEqual(planted.interp, L.LINEAR)
        self.assertFalse(any(c.bone == "foot_ik.L" and c.kind == "loc" and len(c.keys) > 2 for c in m.channels))
        self.assertLessEqual(max(len(c.keys) for c in m.channels), P.MAX_KEYS + 2)

    def test_rotate_axes(self):
        up, fwd = (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)
        x, y, z = P.rotate(up, 90.0, 0.0, 0.0)
        self.assertAlmostEqual(y, 1.0, msg="pitch>0: 위가 앞으로 숙음")
        x, y, z = P.rotate(up, 0.0, 90.0, 0.0)
        self.assertAlmostEqual(x, -1.0, msg="roll>0: 위가 오른쪽(-side)으로 기움")
        x, y, z = P.rotate(fwd, 0.0, 0.0, 90.0)
        self.assertAlmostEqual(x, 1.0, msg="yaw>0: 앞이 왼쪽(+side)으로 돎")
        v = (0.3, -0.2, 0.5)
        back = P.rotate(P.rotate(v, 25.0, -10.0, 40.0), 25.0, -10.0, 40.0, inverse=True)
        for a, b in zip(v, back):
            self.assertAlmostEqual(a, b)
    def test_loop_closes_and_root(self):
        p = P.ClipParams(self.clip(loop=True, root_distance=0.5), root_motion=True)
        m = P.to_motion(p, BODY)
        self.assertTrue(m.loop)
        for c in m.channels:
            if c.bone == "root":
                self.assertAlmostEqual(c.keys[-1].value[1], 0.5 * LEG)
                continue
            self.assertAlmostEqual(c.keys[-1].t - c.keys[0].t, 1.0)
            self.assertEqual(c.keys[-1].value, c.keys[0].value, f"{c.bone} {c.kind} 루프가 닫히지 않음")
        self.assertAlmostEqual(m.root_distance, 0.5 * LEG)
        self.assertEqual(P.to_motion(P.ClipParams(self.clip(loop=True, root_distance=0.5)), BODY).root_distance, 0.0)

    def test_floor_guard(self):
        clip = P.clamp({"name": "f", "loop": False, "frames": 12, "keys": [
            {"t": 0.5, "torso": {"up": -0.95}, "hand_L": {"up": -1.3}}]})
        m = P.to_motion(P.ClipParams(clip), BODY)
        self.assertGreaterEqual(channel(m, "torso", "loc").keys[1].value[2], P.TORSO_FLOOR * LEG - 1e-9)
        hand = channel(m, "hand_ik.L", "loc").keys[1].value[2]
        # 손은 최종 위치가 바닥 여유(HAND_CLEARANCE)까지만 내려간다
        self.assertGreaterEqual(hand, P.HAND_CLEARANCE - BODY.hand_height["L"] - 1e-9)
        self.assertEqual(P.ClipParams(clip).to_dict()["motion"], "CLIP")
        self.assertEqual(P.ClipParams(clip).name, "f")


class RoundTripTest(unittest.TestCase):
    def test_gait_to_clip_and_back(self):
        for motion in ("WALK", "JUMP", "HIT"):
            m = L.generate(L.preset(motion), LEG, ARM)
            clip = P.from_motion(m, BODY, "copy")
            self.assertEqual(clip["loop"], m.loop)
            self.assertLessEqual(len(clip["keys"]), P.MAX_KEYS)
            m2 = P.to_motion(P.ClipParams(clip), BODY)
            # 몸통 높이 범위가 비슷하게 보존된다
            z1 = [k.value[2] for k in channel(m, "torso", "loc").keys]
            z2 = [k.value[2] for k in channel(m2, "torso", "loc").keys]
            self.assertAlmostEqual(min(z1), min(z2), places=2, msg=motion)
            # 손은 몸통을 뺐다가 다시 더하므로 같은 시점 값이 보존된다
            wrap = (lambda t: t % 1.0) if m.loop else (lambda t: t)
            h1 = {round(wrap(k.t), 3): k.value for k in channel(m, "hand_ik.R", "loc").keys[:-1]}
            h2 = {round(wrap(k.t), 3): k.value for k in channel(m2, "hand_ik.R", "loc").keys}
            common = set(h1) & set(h2)
            self.assertTrue(common, motion)
            for t in common:
                for a, b in zip(h1[t], h2[t]):
                    self.assertAlmostEqual(a, b, places=4, msg=f"{motion} hand @{t}")

    def test_compact_is_parseable(self):
        clip = P.from_motion(L.generate(L.preset("RUN"), LEG, ARM), BODY, "run_copy")
        again = P.clamp(json.loads(P.compact(clip)))
        self.assertEqual([k["t"] for k in again["keys"]], [k["t"] for k in clip["keys"]])
        for a, b in zip(again["keys"], clip["keys"]):
            for c in P.CONTROLS:
                self.assertEqual(a[c] is None, b[c] is None)
                if a[c] is not None:
                    for f in P.FIELDS[c]:
                        self.assertAlmostEqual(a[c][f], b[c][f], places=2)


class LibraryTest(unittest.TestCase):
    def test_builtin_entries_convert(self):
        lib = P.load_library()
        names = {e.name for e in lib}
        for want in ("punch", "sword_slash", "axe_overhead_2h", "wave", "bow", "clap", "sit_down", "dance", "kick"):
            self.assertIn(want, names)
        for e in lib:
            self.assertTrue(e.description)
            m = P.to_motion(P.ClipParams(e.clip), BODY)
            self.assertEqual(m.loop, e.clip["loop"], e.name)
            self.assertLessEqual(max(len(c.keys) for c in m.channels), P.MAX_KEYS + 2, e.name)
            for c in m.channels:
                if c.bone.startswith("foot_ik") and c.kind == "loc":
                    self.assertTrue(all(k.value[2] >= 0.0 for k in c.keys), f"{e.name}: 발이 바닥 아래")
                if m.loop:
                    self.assertEqual(c.keys[-1].value, c.keys[0].value, f"{e.name} {c.bone}")
        self.assertGreater(max(k.value[1] for k in channel(P.to_motion(P.ClipParams(next(e.clip for e in lib if e.name == "punch")), BODY), "hand_ik.R", "loc").keys), 0.4)

    def test_user_entries_override_and_save(self):
        with tempfile.TemporaryDirectory() as d:
            punch = next(e for e in P.load_library() if e.name == "punch")
            mine = P.Entry("punch", "my punch", dict(punch.clip, frames=40))
            path = P.save_entry(d, mine)
            self.assertTrue(path.exists())
            (pathlib.Path(d) / "broken.json").write_text("{nope", encoding="utf-8")
            (pathlib.Path(d) / "extra.json").write_text(json.dumps([{"description": "two", "clip": dict(punch.clip, name="punch2")}]), encoding="utf-8")
            lib = {e.name: e for e in P.load_library(d)}
            self.assertEqual(lib["punch"].clip["frames"], 40)
            self.assertEqual(lib["punch"].description, "my punch")
            self.assertEqual(lib["punch2"].source, str(pathlib.Path(d) / "extra.json"))


class AgentClipTest(unittest.TestCase):
    def test_schema_has_both_modes(self):
        s = motion_agent.schema()
        self.assertEqual(set(s["required"]), {"mode", "params", "clip", "done", "summary"})
        params = s["properties"]["params"]
        self.assertEqual(set(params["required"]), set(L.GaitParams.__dataclass_fields__))
        self.assertIn("null", params["type"])
        key = s["properties"]["clip"]["properties"]["keys"]["items"]
        self.assertEqual(set(key["required"]), {"t", "ease", "rest", *P.CONTROLS})
        self.assertEqual(set(key["properties"]["foot_L"]["required"]), set(P.FIELDS["foot_L"]))
        self.assertFalse(key["additionalProperties"])
        self.assertEqual(set(motion_agent.DESCRIPTIONS), set(L.GaitParams.__dataclass_fields__))

    def test_parse_modes(self):
        clip = {"name": "x", "loop": False, "frames": 20, "root_distance": 0, "keys": [{"t": 0, "rest": True, "ease": "BEZIER",
                **{c: None for c in P.CONTROLS}}]}
        p, done, _ = motion_agent.parse({"mode": "CLIP", "params": None, "clip": clip, "done": True, "summary": "s"})
        self.assertIsInstance(p, P.ClipParams)
        self.assertTrue(done)
        p, _, _ = motion_agent.parse({"mode": "PARAMS", "params": {"motion": "RUN"}, "clip": None, "done": False, "summary": ""})
        self.assertIsInstance(p, L.GaitParams)
        self.assertEqual(p.motion, "RUN")
        p, _, _ = motion_agent.parse({"clip": clip, "done": False, "summary": ""})
        self.assertIsInstance(p, P.ClipParams, "mode 가 없으면 채워진 쪽")
        with self.assertRaises(ValueError):
            motion_agent.parse({"mode": "CLIP", "params": {"motion": "WALK"}, "clip": None, "done": False, "summary": ""})

    def test_prompts_include_library_and_spec(self):
        lib = P.load_library()
        txt = motion_agent.request_prompt("양손 도끼 내려찍기", "ATTACK", LEG, ARM, L.preset("ATTACK"), 24, lib)
        self.assertIn("axe_overhead_2h", txt)
        self.assertIn("CLIP format", txt)
        self.assertIn("attack_kind", txt)
        rev = motion_agent.review_prompt("x", P.ClipParams(lib[0].clip), ["side_t000"], "cm", lib)
        self.assertIn("Current clip", rev)
        self.assertIn(lib[0].name, rev)


if __name__ == "__main__":
    unittest.main()
