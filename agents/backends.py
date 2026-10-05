"""AI 백엔드: 로컬 Claude Code CLI / Codex CLI / Anthropic API 를 같은 인터페이스로 감싼다 (bpy 비의존).

모든 백엔드는 "이미지 몇 장 + 프롬프트 → JSON 스키마에 맞는 dict" 한 가지 호출만 제공한다.
CLI 백엔드는 사용자가 이미 로그인해 둔 계정(구독)을 쓰므로 API 키가 필요 없다.
실행은 백그라운드 스레드에서 하며, cancel() 로 진행 중인 하위 프로세스를 종료할 수 있다.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from functools import lru_cache

CLAUDE_CODE = "CLAUDE_CODE"
CODEX = "CODEX"
API = "API"

# GUI 로 띄운 Blender 는 셸 PATH 를 물려받지 않으므로 흔한 설치 위치를 함께 찾는다
_EXTRA_DIRS = [
    "~/.local/bin", "~/.npm-global/bin", "~/.claude/local", "~/.bun/bin",
    "/opt/homebrew/bin", "/usr/local/bin", "~/AppData/Roaming/npm",
]


class BackendError(RuntimeError):
    """사용자에게 그대로 보여 줄 수 있는 백엔드 오류."""


def _search_path() -> str:
    dirs = [os.path.expanduser(d) for d in _EXTRA_DIRS]
    return os.pathsep.join([os.environ.get("PATH", "")] + dirs)


def find_executable(name: str, override: str = "") -> str | None:
    return _find_cached(name, override, os.environ.get("PATH", ""))


def clear_cache():
    _find_cached.cache_clear()


@lru_cache(maxsize=32)
def _find_cached(name: str, override: str, _path_key: str) -> str | None:
    # Preferences draw() 가 매 다시 그리기마다 부르므로 PATH 가 바뀌지 않는 한 캐시한다
    if override:
        path = os.path.expanduser(override)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
        # 지정 경로가 사라졌으면(재설치·이동) 자동 탐색으로 되돌아간다
    # Windows 는 배치 셔틀(.cmd)보다 네이티브 실행 파일을 우선한다 (인자 인용 문제 회피)
    names = [name + ".exe", name + ".cmd", name] if sys.platform == "win32" else [name]
    for n in names:
        found = shutil.which(n, path=_search_path())
        if found:
            return found
    return None


@dataclass
class BackendSettings:
    kind: str = "AUTO"
    claude_path: str = ""
    codex_path: str = ""
    model: str = ""  # 비우면 각 CLI 기본 모델
    effort: str = "medium"
    timeout: float = 600.0
    # repr 에 키가 찍히지 않게 한다
    api_key: str = field(default="", repr=False)
    api_model: str = "claude-opus-5-5"


def _kill_tree(proc):
    """CLI 가 띄운 자식(node 등)까지 함께 종료한다. 남겨 두면 구독 사용량을 계속 쓰고 임시 폴더를 잡고 있다."""
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=10)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        proc.kill()


class _Subprocess:
    """취소 가능한 하위 프로세스 실행 공통부."""

    # 자식이 하위 프로세스에 넘기지 않을 환경 변수 (로그인된 계정 대신 키 과금으로 바뀌는 것을 막는다)
    strip_env: tuple[str, ...] = ()

    def __init__(self):
        self._proc = None
        self._lock = threading.Lock()
        self.cancelled = False

    def cancel(self):
        with self._lock:
            self.cancelled = True
            if self._proc is not None:
                _kill_tree(self._proc)

    def _run(self, cmd, cwd, stdin_text, timeout):
        env = {k: v for k, v in os.environ.items() if k not in self.strip_env}
        env["PATH"] = _search_path()
        group = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32"
            else {"start_new_session": True}
        )
        with self._lock:
            if self.cancelled:
                raise BackendError("취소되었습니다.")
            try:
                self._proc = subprocess.Popen(
                    cmd, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace", **group,
                )
            except OSError as exc:
                raise BackendError(f"{os.path.basename(cmd[0])} 실행 실패: {exc}") from exc
        proc = self._proc
        try:
            out, err = proc.communicate(stdin_text, timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            self._reap(proc)
            raise BackendError(f"{os.path.basename(cmd[0])} 응답 시간 초과 ({int(timeout)}초)")
        if self.cancelled:
            self._reap(proc)
            raise BackendError("취소되었습니다.")
        return proc.returncode, out, err

    @staticmethod
    def _reap(proc):
        try:
            proc.communicate(timeout=5)
        except (subprocess.TimeoutExpired, ValueError, OSError):
            pass


def _write_images(tmp: str, images: list[tuple[str, bytes]]) -> list[str]:
    paths = []
    for name, png in images:
        p = os.path.join(tmp, f"{name}.png")
        with open(p, "wb") as f:
            f.write(png)
        paths.append(p)
    return paths


class ClaudeCodeBackend(_Subprocess):
    label = "Claude Code CLI"
    strip_env = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

    def __init__(self, exe: str, settings: BackendSettings):
        super().__init__()
        self.exe = exe
        self.settings = settings

    def run_json(self, system: str, prompt: str, images: list[tuple[str, bytes]], schema: dict) -> dict:
        with tempfile.TemporaryDirectory(prefix="airig_cc_", ignore_cleanup_errors=True) as tmp:
            paths = _write_images(tmp, images)
            listing = "\n".join(f"- {os.path.basename(p)}" for p in paths)
            text = (
                f"{system}\n\nFirst use the Read tool to view each image file in the working directory, in order:\n"
                f"{listing}\n\n{prompt}"
            )
            # 읽기 도구 하나만 허용하고 사용자 설정·MCP·슬래시 명령을 끈다 (--bare 는 API 키 전용이라 쓰지 않는다)
            cmd = [
                self.exe, "-p", "--output-format", "json", "--json-schema", json.dumps(schema, separators=(",", ":")),
                "--tools", "Read", "--allowedTools", "Read", "--add-dir", tmp,
                "--setting-sources", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--disable-slash-commands", "--no-session-persistence", "--effort", self.settings.effort,
            ]
            if self.settings.model:
                cmd += ["--model", self.settings.model]
            code, out, err = self._run(cmd, tmp, text, self.settings.timeout)
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            raise BackendError(f"Claude Code CLI 출력 해석 실패 (종료 코드 {code}): {(err or out)[-300:]}")
        if not isinstance(data, dict):
            raise BackendError("Claude Code CLI 출력이 JSON 객체가 아닙니다.")
        if code != 0 or data.get("is_error") or data.get("subtype") != "success":
            raise BackendError(f"Claude Code CLI 실패: {str(data.get('result') or err)[-300:]}")
        result = data.get("structured_output")
        if not isinstance(result, dict):
            raise BackendError("Claude Code CLI 가 구조화 출력을 반환하지 않았습니다.")
        return result


class CodexBackend(_Subprocess):
    label = "Codex CLI"
    strip_env = ("OPENAI_API_KEY", "CODEX_API_KEY")

    def __init__(self, exe: str, settings: BackendSettings):
        super().__init__()
        self.exe = exe
        self.settings = settings

    def run_json(self, system: str, prompt: str, images: list[tuple[str, bytes]], schema: dict) -> dict:
        with tempfile.TemporaryDirectory(prefix="airig_codex_", ignore_cleanup_errors=True) as tmp:
            paths = _write_images(tmp, images)
            schema_path = os.path.join(tmp, "schema.json")
            out_path = os.path.join(tmp, "result.json")
            with open(schema_path, "w", encoding="utf-8") as f:
                json.dump(schema, f)
            names = ", ".join(os.path.basename(p) for p in paths)
            text = f"{system}\n\nAttached images, in order: {names}.\n\n{prompt}"
            cmd = [self.exe, "exec"]
            for p in paths:
                # codex 는 -i 값을 쉼표로 나누므로 작업 폴더 기준 파일 이름만 넘긴다
                cmd += ["-i", os.path.basename(p)]
            cmd += [
                "--output-schema", schema_path, "-o", out_path, "--skip-git-repo-check", "--ephemeral",
                "-s", "read-only", "-C", tmp, "-c", f"model_reasoning_effort={self.settings.effort}",
            ]
            if self.settings.model:
                cmd += ["-m", self.settings.model]
            cmd.append("-")
            code, out, err = self._run(cmd, tmp, text, self.settings.timeout)
            if code != 0 or not os.path.isfile(out_path):
                raise BackendError(f"Codex CLI 실패 (종료 코드 {code}): {err[-300:]}")
            with open(out_path, encoding="utf-8") as f:
                raw = f.read()
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            raise BackendError(f"Codex CLI 출력 해석 실패: {raw[-300:]}")
        if not isinstance(result, dict):
            raise BackendError("Codex CLI 가 JSON 객체를 반환하지 않았습니다.")
        return result


class ApiBackend:
    label = "Anthropic API"

    def __init__(self, settings: BackendSettings):
        from . import claude_client

        self._cc = claude_client
        self.settings = settings
        self.agent_settings = claude_client.AgentSettings(
            api_key=settings.api_key, model=settings.api_model, effort=settings.effort, timeout=settings.timeout
        )
        self.client = claude_client.make_client(self.agent_settings)

    def cancel(self):
        # SDK 스트림은 강제 중단 수단이 없으므로 결과를 버리는 것으로 대신한다
        pass

    def run_json(self, system: str, prompt: str, images: list[tuple[str, bytes]], schema: dict) -> dict:
        content = []
        for name, png in images:
            content.append({"type": "text", "text": f"Image {name}:"})
            content.append(self._cc.image_block(png))
        content.append({"type": "text", "text": prompt})
        try:
            text, _message = self._cc.request_json(self.client, self.agent_settings, system, content, schema)
        except self._cc.AgentError as exc:
            raise BackendError(str(exc)) from exc
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise BackendError(f"API 응답 JSON 해석 실패: {exc}") from exc


LABELS = {CLAUDE_CODE: ClaudeCodeBackend.label, CODEX: CodexBackend.label, API: "Anthropic API"}


def resolve(settings: BackendSettings) -> tuple[str, str | None]:
    """(실제 백엔드 종류, 실행 파일). 클라이언트를 만들지 않으므로 UI 에서 자주 불러도 가볍다."""
    kind = settings.kind
    claude = find_executable("claude", settings.claude_path)
    codex = find_executable("codex", settings.codex_path)
    if kind == "AUTO":
        if claude:
            return CLAUDE_CODE, claude
        if codex:
            return CODEX, codex
        if settings.api_key or os.environ.get("ANTHROPIC_API_KEY"):
            return API, None
        raise BackendError("Claude Code CLI·Codex CLI 를 찾지 못했고 API 키도 없습니다. Preferences 에서 설정하세요.")
    if kind == CLAUDE_CODE:
        if not claude:
            raise BackendError("Claude Code CLI(claude) 를 찾지 못했습니다. Preferences 에 경로를 지정하세요.")
        return kind, claude
    if kind == CODEX:
        if not codex:
            raise BackendError("Codex CLI(codex) 를 찾지 못했습니다. Preferences 에 경로를 지정하세요.")
        return kind, codex
    if kind == API:
        return kind, None
    raise BackendError(f"알 수 없는 백엔드: {kind}")


def create(settings: BackendSettings):
    """설정에 맞는 백엔드. AUTO 는 Claude Code CLI → Codex CLI → API(키가 있을 때) 순으로 고른다."""
    kind, exe = resolve(settings)
    if kind == CLAUDE_CODE:
        return ClaudeCodeBackend(exe, settings)
    if kind == CODEX:
        return CodexBackend(exe, settings)
    if kind == API:
        try:
            return ApiBackend(settings)
        except RuntimeError as exc:
            raise BackendError(str(exc)) from exc
    raise BackendError(f"알 수 없는 백엔드: {kind}")
