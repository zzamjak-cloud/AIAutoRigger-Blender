"""AI 백엔드 하위 프로세스 경로 단위 테스트 (가짜 claude/codex 실행 파일 사용, 네트워크·비용 없음)."""

import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agents import backends  # noqa: E402
from agents.review_agent import ReviewSession  # noqa: E402

FAKE = ROOT / "tests" / "fixtures" / "fake_ai_cli.py"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
SCHEMA = {"type": "object", "properties": {"u": {"type": "number"}}, "required": ["u"], "additionalProperties": False}


class FakeCliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name in ("claude", "codex"):
            shutil.copy(FAKE, self.bin / name)
            os.chmod(self.bin / name, 0o755)
        self.responses = self.tmp / "responses.json"
        self.log = self.tmp / "log.jsonl"
        os.environ["AIRIG_FAKE_RESPONSES"] = str(self.responses)
        os.environ["AIRIG_FAKE_LOG"] = str(self.log)
        os.environ.pop("AIRIG_FAKE_SLEEP", None)
        # 실제 설치된 claude/codex 를 찾지 않도록 탐색 경로를 격리한다 (가짜 CLI 의 python3 는 /usr/bin)
        self._env_path, self._extra = os.environ.get("PATH", ""), backends._EXTRA_DIRS
        os.environ["PATH"] = "/usr/bin:/bin"
        backends._EXTRA_DIRS = []
        backends.clear_cache()

    def tearDown(self):
        os.environ["PATH"] = self._env_path
        backends._EXTRA_DIRS = self._extra
        backends.clear_cache()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def respond(self, *items):
        self.responses.write_text(json.dumps(list(items)))

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def settings(self, kind, **kw):
        return backends.BackendSettings(kind=kind, claude_path=str(self.bin / "claude"), codex_path=str(self.bin / "codex"), **kw)


class BackendTest(FakeCliCase):
    def test_claude_code(self):
        self.respond({"u": 0.25})
        b = backends.create(self.settings(backends.CLAUDE_CODE, effort="high", model="opus"))
        self.assertIsInstance(b, backends.ClaudeCodeBackend)
        self.assertEqual(b.run_json("SYS", "PROMPT", [("front", PNG), ("side", PNG)], SCHEMA), {"u": 0.25})
        call = self.calls()[0]
        self.assertEqual(call["images"], ["front.png", "side.png"])
        self.assertIn("SYS", call["prompt"])
        args = call["args"]
        for flag in ("--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands"):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index("--effort") + 1], "high")
        self.assertEqual(args[args.index("--model") + 1], "opus")
        self.assertEqual(args[args.index("--setting-sources") + 1], "")

    def test_codex(self):
        self.respond({"u": 0.75})
        b = backends.create(self.settings(backends.CODEX))
        self.assertEqual(b.run_json("SYS", "PROMPT", [("front", PNG)], SCHEMA), {"u": 0.75})
        call = self.calls()[0]
        self.assertEqual(call["images"], ["front.png"])
        self.assertIn("--ephemeral", call["args"])
        self.assertIn("model_reasoning_effort=medium", call["args"])

    def test_auto_prefers_claude_then_codex(self):
        self.assertIsInstance(backends.create(self.settings("AUTO")), backends.ClaudeCodeBackend)
        s = self.settings("AUTO")
        s.claude_path = str(self.tmp / "missing")
        self.assertIsInstance(backends.create(s), backends.CodexBackend)

    def test_stale_override_falls_back_to_search(self):
        s = self.settings(backends.CODEX)
        s.codex_path = str(self.tmp / "moved" / "codex")
        backends._EXTRA_DIRS = [str(self.bin)]
        backends.clear_cache()
        self.assertEqual(backends.resolve(s), (backends.CODEX, str(self.bin / "codex")))

    def test_resolve_without_creating_client(self):
        self.assertEqual(backends.resolve(self.settings("AUTO"))[0], backends.CLAUDE_CODE)

    def test_missing_executable(self):
        s = self.settings(backends.CODEX)
        s.codex_path = str(self.tmp / "missing")
        with self.assertRaises(backends.BackendError):
            backends.create(s)

    def test_api_keys_not_passed_to_cli(self):
        self.respond({"u": 0.5})
        os.environ["ANTHROPIC_API_KEY"] = "sk-should-not-leak"
        try:
            b = backends.create(self.settings(backends.CLAUDE_CODE))
            b.run_json("S", "P", [("front", PNG)], SCHEMA)
        finally:
            del os.environ["ANTHROPIC_API_KEY"]
        self.assertNotIn("ANTHROPIC_API_KEY", self.calls()[0]["env_keys"])

    def test_cli_failure_reported(self):
        self.responses.write_text("not json")  # 가짜 CLI 가 예외로 종료
        b = backends.create(self.settings(backends.CLAUDE_CODE))
        with self.assertRaises(backends.BackendError):
            b.run_json("S", "P", [("front", PNG)], SCHEMA)

    def test_timeout_and_cancel(self):
        self.respond({"u": 1})
        os.environ["AIRIG_FAKE_SLEEP"] = "5"
        b = backends.create(self.settings(backends.CODEX, timeout=0.5))
        before = set(pathlib.Path(tempfile.gettempdir()).glob("airig_codex_*"))
        t0 = time.time()
        with self.assertRaisesRegex(backends.BackendError, "시간 초과"):
            b.run_json("S", "P", [("front", PNG)], SCHEMA)
        self.assertLess(time.time() - t0, 3)
        self.assertEqual(set(pathlib.Path(tempfile.gettempdir()).glob("airig_codex_*")), before, "임시 폴더가 남음")
        self.assertIsNotNone(b._proc.poll(), "시간 초과 후 프로세스가 회수되지 않음")
        b = backends.create(self.settings(backends.CLAUDE_CODE))
        err = {}

        def run():
            try:
                b.run_json("S", "P", [("front", PNG)], SCHEMA)
            except backends.BackendError as exc:
                err["e"] = str(exc)

        t = threading.Thread(target=run)
        t0 = time.time()
        t.start()
        time.sleep(0.5)
        b.cancel()
        t.join(3)
        self.assertFalse(t.is_alive())
        self.assertLess(time.time() - t0, 3)
        self.assertIn("취소", err.get("e", ""))


class ReviewValidateTest(unittest.TestCase):
    def test_boundaries(self):
        s = ReviewSession(None, ["knee_L"], ["DEF-shin.L"], ["rest"])
        ok = {"kind": "smooth_weights", "target": "DEF-shin.L", "iterations": 3, "reason": "r"}
        self.assertIsNone(s.validate(ok))
        for bad in (
            {**ok, "iterations": 0}, {**ok, "iterations": 11}, {**ok, "iterations": True},
            {**ok, "target": "DEF-nope"}, {**ok, "reason": None}, {**ok, "kind": "delete_bone"},
            {"kind": "move_joint", "target": "knee_L", "dx": True, "dy": 0, "dz": 0, "reason": "r"},
            {"kind": "move_joint", "target": "knee_L", "dx": 0.2, "dy": 0, "dz": 0, "reason": "r"},
            {"kind": "move_joint", "target": "hip_L", "dx": 0, "dy": 0, "dz": 0, "reason": "r"},
        ):
            self.assertIsNotNone(s.validate(bad), bad)


class ReviewRoundTest(FakeCliCase):
    def test_rounds_with_codex(self):
        self.respond(
            {"render_requests": [{"pose": "squat", "view": "side"}],
             "proposals": [{"kind": "move_joint", "target": "knee_L", "dx": 0, "dy": -0.02, "dz": 0.01, "iterations": 0, "reason": "high"},
                           {"kind": "move_joint", "target": "knee_L", "dx": 0.5, "dy": 0, "dz": 0, "iterations": 0, "reason": "bad"}],
             "done": False, "summary": ""},
            {"render_requests": [],
             "proposals": [{"kind": "smooth_weights", "target": "DEF-shin.L", "dx": 0, "dy": 0, "dz": 0, "iterations": 3, "reason": "crease"},
                           {"kind": "move_joint", "target": "knee_L", "dx": 0, "dy": -0.03, "dz": 0, "iterations": 0, "reason": "refined"}],
             "done": True, "summary": "Knee slightly high."},
        )
        s = ReviewSession(backends.create(self.settings(backends.CODEX)), ["knee_L", "knee_R"], ["DEF-shin.L"], ["rest", "squat"], max_rounds=4)
        s.start([("rest_front", PNG), ("squat_front", PNG)], "metrics", "BIPED")
        req = s.step()
        self.assertEqual(req, [("squat", "side")])
        self.assertEqual(len(s.rejected), 1)
        s.add_renders([("r1_squat_side", PNG)])
        self.assertEqual(s.step(), [])
        self.assertTrue(s.done)
        self.assertEqual(sorted(p.kind for p in s.proposals), ["move_joint", "smooth_weights"])
        self.assertEqual(next(p for p in s.proposals if p.kind == "move_joint").delta, (0.0, -0.03, 0.0))
        self.assertIn("Knee", s.summary)
        calls = self.calls()
        self.assertEqual(calls[1]["images"], ["rest_front.png", "squat_front.png", "r1_squat_side.png"])
        self.assertIn("Rejected last round", calls[1]["prompt"])
        self.assertIn("already queued", calls[1]["prompt"])

    def test_rejected_gets_retry_round_and_requests_deduped(self):
        self.respond(
            {"render_requests": [], "proposals": [
                {"kind": "move_joint", "target": "knee_L", "dx": 0.5, "dy": 0, "dz": 0, "iterations": 0, "reason": "bad"}],
             "done": False, "summary": ""},
            {"render_requests": [{"pose": "rest", "view": "side"}, {"pose": "rest", "view": "side"}],
             "proposals": [{"kind": "move_joint", "target": "knee_L", "dx": 0.05, "dy": 0, "dz": 0, "iterations": 0, "reason": "fixed"}],
             "done": False, "summary": ""},
            {"render_requests": [], "proposals": [], "done": True, "summary": "ok"},
        )
        s = ReviewSession(backends.create(self.settings(backends.CODEX)), ["knee_L"], [], ["rest"], max_rounds=4)
        s.start([("rest_front", PNG)], "m", "BIPED")
        self.assertEqual(s.step(), [])
        self.assertFalse(s.done, "거부된 제안이 있으면 재전송 라운드를 줘야 함")
        self.assertEqual(s.step(), [("rest", "side")])
        self.assertEqual([p.delta for p in s.proposals], [(0.05, 0.0, 0.0)])

    def test_round_limit(self):
        self.respond({"render_requests": [{"pose": "rest", "view": "side"}], "proposals": [], "done": False, "summary": ""})
        s = ReviewSession(backends.create(self.settings(backends.CLAUDE_CODE)), ["knee_L"], [], ["rest"], max_rounds=2)
        s.start([("rest_front", PNG)], "m", "BIPED")
        while not s.done:
            for pose, view in s.step():
                s.add_renders([(f"r{s.rounds}_{pose}_{view}", PNG)])
        self.assertEqual(s.rounds, 2)
        self.assertIn("final round", self.calls()[1]["prompt"])


if __name__ == "__main__":
    unittest.main()
