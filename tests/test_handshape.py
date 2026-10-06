"""손 모양(손가락 굽힘) 정의·동작별 손가락 채널·포즈 클립 손 모양 단위 테스트 (bpy 비의존)."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from core import handshape as H  # noqa: E402
from core import locomotion as L  # noqa: E402
from core import poseclip as P  # noqa: E402

LEG, ARM = 0.85, 0.6
BODY = P.Body.approx(LEG, ARM)


def fingers(m, side):
    return next(c for c in m.channels if c.bone == f"fingers.{side}" and c.kind == "curl").keys


def shape_at(keys, t):
    return H.nearest(L.sample(keys, t))


class HandShapeTest(unittest.TestCase):
    def test_shapes_in_range(self):
        for name, values in H.SHAPES.items():
            self.assertEqual(len(values), len(H.FINGERS), name)
            self.assertTrue(all(0.0 <= v <= 1.0 for v in values), name)
            self.assertEqual(H.nearest(values), name, "손 모양 → 이름 왕복")

    def test_normalize(self):
        self.assertEqual(H.normalize(" fist "), "FIST")
        self.assertIsNone(H.normalize("karate"))
        self.assertIsNone(H.normalize(3))
        self.assertEqual(H.curls("bogus"), H.SHAPES[H.DEFAULT])


class MotionFingersTest(unittest.TestCase):
    def test_every_motion_has_both_hands(self):
        for motion in L.MOTIONS:
            for style in ("NORMAL", "ZOMBIE"):
                m = L.generate(L.preset(motion, style), LEG, ARM)
                for side in ("L", "R"):
                    keys = fingers(m, side)
                    self.assertGreaterEqual(len(keys), 2, f"{motion}/{style} {side}")
                    if m.loop:
                        self.assertEqual(keys[0].value, keys[-1].value, f"{motion}/{style}: 루프가 닫힘")
                    else:
                        self.assertEqual(keys[-1].t, 1.0, f"{motion}/{style}: 단발은 끝까지 유지")

    def test_defaults_per_motion(self):
        self.assertEqual(shape_at(fingers(L.generate(L.preset("WALK"), LEG, ARM), "L"), 0.3), "RELAXED")
        self.assertEqual(shape_at(fingers(L.generate(L.preset("RUN"), LEG, ARM), "L"), 0.3), "LOOSE_FIST")
        self.assertEqual(shape_at(fingers(L.generate(L.preset("HAPPY"), LEG, ARM), "R"), 0.3), "OPEN")
        self.assertEqual(shape_at(fingers(L.generate(L.preset("WALK", "ZOMBIE"), LEG, ARM), "R"), 0.3), "CLAW")

    def test_attack_fist_and_weapon_grip(self):
        p = L.preset("ATTACK", attack_kind="SWING")
        m = L.generate(p, LEG, ARM)
        strike = min(0.8, p.anticipation + 0.15)
        self.assertEqual(shape_at(fingers(m, "R"), strike), "FIST", "맨손 휘두르기는 주먹")
        self.assertEqual(shape_at(fingers(m, "R"), 1.0), "RELAXED", "복귀하며 손을 푼다")
        self.assertEqual(shape_at(fingers(m, "L"), strike), "LOOSE_FIST", "반대 손은 가볍게 쥐고 방어")
        for kind in ("THRUST", "SLASH_H", "SLASH_V", "OVERHEAD"):
            m = L.generate(L.preset("ATTACK", attack_kind=kind, two_handed=kind == "OVERHEAD"), LEG, ARM)
            keys = fingers(m, "R")
            self.assertTrue(all(H.nearest(k.value) == "GRIP" for k in keys), f"{kind}: 무기는 끝까지 쥔다")
            if kind == "OVERHEAD":
                self.assertTrue(all(H.nearest(k.value) == "GRIP" for k in fingers(m, "L")), "양손 무기는 두 손 모두 쥔다")

    def test_hand_shape_override_and_clamp(self):
        m = L.generate(L.preset("JUMP", hand_shape="FIST"), LEG, ARM)
        self.assertTrue(all(H.nearest(k.value) == "FIST" for k in fingers(m, "L")))
        self.assertEqual(L.clamp({"motion": "WALK", "hand_shape": "karate"}).hand_shape, "AUTO")
        self.assertEqual(L.clamp({"motion": "WALK", "hand_shape": "point"}).hand_shape, "POINT")


class ClipFingersTest(unittest.TestCase):
    def test_clamp_keeps_valid_shapes(self):
        clip = P.clamp({"name": "x", "loop": False, "frames": 24, "keys": [
            {"t": 0.0, "rest": True}, {"t": 0.5, "fingers_R": "fist", "fingers_L": "karate"}]})
        self.assertEqual(clip["keys"][1]["fingers_R"], "FIST")
        self.assertIsNone(clip["keys"][1]["fingers_L"])

    def test_default_relaxed_and_rest(self):
        clip = P.clamp({"name": "x", "loop": False, "frames": 24, "keys": [
            {"t": 0.0, "rest": True}, {"t": 0.4, "fingers_R": "FIST"}, {"t": 1.0, "rest": True}]})
        m = P.to_motion(P.ClipParams(clip), BODY)
        self.assertEqual(shape_at(fingers(m, "L"), 0.5), "RELAXED", "손 모양 키가 없는 손은 RELAXED")
        self.assertEqual(shape_at(fingers(m, "R"), 0.0), "RELAXED", "rest 키는 RELAXED")
        self.assertEqual(shape_at(fingers(m, "R"), 0.4), "FIST")
        self.assertEqual(shape_at(fingers(m, "R"), 1.0), "RELAXED")

    def test_library_shapes(self):
        lib = {e.name: e for e in P.load_library()}
        punch = P.to_motion(P.ClipParams(lib["punch"].clip), BODY)
        self.assertEqual(shape_at(fingers(punch, "R"), 0.45), "FIST")
        axe = P.to_motion(P.ClipParams(lib["axe_overhead_2h"].clip), BODY)
        self.assertTrue(all(H.nearest(k.value) == "GRIP" for k in fingers(axe, "L")), "도끼는 처음부터 끝까지 쥔다")
        point = P.to_motion(P.ClipParams(lib["point"].clip), BODY)
        self.assertEqual(shape_at(fingers(point, "R"), 0.5), "POINT")

    def test_round_trip_and_compact(self):
        lib = {e.name: e for e in P.load_library()}
        clip = lib["sword_slash"].clip
        back = P.from_motion(P.to_motion(P.ClipParams(clip), BODY), BODY, "copy")
        self.assertTrue(all(k["fingers_R"] == "GRIP" for k in back["keys"]), "저장해도 손 모양 유지")
        self.assertIn('"fingers_R":"GRIP"', P.compact(clip))


if __name__ == "__main__":
    unittest.main()
