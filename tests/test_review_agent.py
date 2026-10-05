"""Rig Review Agent 세션 루프 단위 테스트 (모의 클라이언트, bpy·SDK 비의존)."""

import pathlib
import sys
import types
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from agents import claude_client  # noqa: E402
from agents.review_agent import ReviewSession  # noqa: E402

claude_client._sdk = lambda: types.SimpleNamespace(**{n: type(n, (Exception,), {}) for n in (
    "AuthenticationError", "PermissionDeniedError", "NotFoundError", "RateLimitError",
    "BadRequestError", "APIStatusError", "APIConnectionError")})


def tool_use(i, name, inp):
    return types.SimpleNamespace(type="tool_use", id=f"toolu_{i}", name=name, input=inp)


def text(t):
    return types.SimpleNamespace(type="text", text=t)


class ScriptedClient:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=self._stream))

    def _stream(self, **params):
        self.calls.append(params)
        stop, content = self.turns.pop(0)
        msg = types.SimpleNamespace(stop_reason=stop, content=content)

        class S:
            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False

            def get_final_message(s):
                return msg

        return S()


def session(turns, max_turns=6):
    client = ScriptedClient(turns)
    s = ReviewSession(client, claude_client.AgentSettings(), ["knee_L", "knee_R"], ["DEF-shin.L"], ["rest", "squat"], max_turns)
    s.start([("Pose 'rest':", b"\x89PNG fake")], "metrics", "BIPED")
    return s, client


class ReviewSessionTest(unittest.TestCase):
    def run_loop(self, s):
        renders = []
        while not s.done:
            calls = s.step()
            if calls:
                s.submit([s.handle(c, lambda p, v: renders.append((p, v)) or b"png") for c in calls])
        return renders

    def test_full_loop(self):
        s, client = session([
            ("tool_use", [tool_use(1, "render_pose", {"pose": "squat", "view": "side"})]),
            ("tool_use", [
                tool_use(2, "propose_joint_move", {"joint": "knee_L", "dx": 0.0, "dy": -0.02, "dz": 0.01, "reason": "knee too high"}),
                tool_use(3, "propose_weight_smooth", {"bone": "DEF-shin.L", "iterations": 3, "reason": "crease"}),
                tool_use(4, "propose_joint_move", {"joint": "knee_L", "dx": 0.5, "dy": 0.0, "dz": 0.0, "reason": "bad"}),
            ]),
            ("end_turn", [text("Knee slightly high; shin weights creased.")]),
        ])
        renders = self.run_loop(s)
        self.assertEqual(renders, [("squat", "side")])
        self.assertEqual([p.kind for p in s.proposals], ["move_joint", "smooth_weights"])
        self.assertIn("Knee", s.summary)
        # 도구 결과는 한 user 메시지에, 범위 밖 입력은 is_error 로 돌려준다
        last_results = s.messages[4]["content"]
        self.assertEqual(len(last_results), 3)
        self.assertTrue(last_results[2]["is_error"])
        p = client.calls[0]
        self.assertTrue(all(t["strict"] and t["eager_input_streaming"] for t in p["tools"]))
        self.assertEqual(p["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("tool_choice", p)

    def test_turn_limit(self):
        s, _ = session([("tool_use", [tool_use(i, "render_pose", {"pose": "rest", "view": "front"})]) for i in range(3)], max_turns=2)
        self.run_loop(s)
        self.assertTrue(s.done)
        self.assertIn("한도", s.summary)

    def test_truncated_turn_not_executed(self):
        s, _ = session([("max_tokens", [tool_use(1, "propose_joint_move", {"joint": "knee_L"})])])
        self.run_loop(s)
        self.assertEqual(s.proposals, [])


if __name__ == "__main__":
    unittest.main()
