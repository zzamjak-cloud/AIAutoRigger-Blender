"""손가락 데이터 구조 단위 테스트 (거울·대칭화·직렬화)."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from core import fingers  # noqa: E402


def hand(x_sign=1.0, n=("thumb", "f_index", "f_middle")):
    fs = [fingers.Finger(name, [(x_sign * (0.8 + 0.02 * k + 0.01 * j), -0.02 * k, 1.4 - 0.01 * j) for j in range(4)])
          for k, name in enumerate(n)]
    return fingers.HandFingers(fs, (x_sign * 0.7, 0.0, 1.45), (0.0, 0.0, 1.0))


class FingersTest(unittest.TestCase):
    def test_roundtrip(self):
        h = hand()
        back = fingers.HandFingers.from_dict(h.to_dict())
        self.assertEqual([f.name for f in back.fingers], ["thumb", "f_index", "f_middle"])
        self.assertEqual(back.fingers[1].points, h.fingers[1].points)

    def test_mirror(self):
        m = fingers.mirror(hand(), 0.0)
        self.assertAlmostEqual(m.fingers[0].points[0][0], -0.8)
        self.assertAlmostEqual(m.wrist[0], -0.7)

    def test_symmetrize_average_and_mismatch(self):
        left, right = hand(1.0), hand(-1.0)
        right.fingers[0].points[0] = (-0.82, 0.0, 1.4)
        l2, r2 = fingers.symmetrize(left, right, 0.0)
        self.assertAlmostEqual(l2.fingers[0].points[0][0], 0.81)
        self.assertAlmostEqual(r2.fingers[0].points[0][0], -0.81)
        # 한쪽이 덜 잡히면 많이 잡힌 쪽을 거울로 쓴다
        l3, r3 = fingers.symmetrize(hand(1.0), hand(-1.0, ("thumb", "f_index")), 0.0)
        self.assertEqual(len(r3.fingers), 3)

    def test_too_small_input(self):
        self.assertIsNone(fingers.detect_fingers([(0, 0, 0)] * 5, [], (0, 0, 0), (0.1, 0, 0)))


if __name__ == "__main__":
    unittest.main()
