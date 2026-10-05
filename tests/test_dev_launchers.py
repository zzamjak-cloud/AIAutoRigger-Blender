"""macOS/Windows 개발 실행기 정적 회귀 검사 (Windows 런타임은 이 검사로만 보증)."""

import pathlib
import re
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def manifest_id():
    text = (ROOT / "blender_manifest.toml").read_text(encoding="utf-8")
    return re.search(r'^id\s*=\s*"([A-Za-z0-9_]+)"', text, re.M).group(1)


class DevLauncherTest(unittest.TestCase):
    def test_all_launchers_exist(self):
        for name in ("dev_run.sh", "dev_run.ps1", "dev_run.bat", "dev_bootstrap.py"):
            self.assertTrue((SCRIPTS / name).is_file(), name)

    def test_manifest_id_matches_bootstrap_default(self):
        bootstrap = (SCRIPTS / "dev_bootstrap.py").read_text(encoding="utf-8")
        self.assertIn(f'"AIRIG_ADDON_ID", "{manifest_id()}"', bootstrap)
        self.assertIn('f"bl_ext.user_default.{ADDON_ID}"', bootstrap)

    def test_sh_syntax_and_safety(self):
        sh = SCRIPTS / "dev_run.sh"
        subprocess.run(["bash", "-n", str(sh)], check=True)
        text = sh.read_text(encoding="utf-8")
        self.assertIn("--python-exit-code 1", text)
        self.assertIn("BLENDER_USER_RESOURCES", text)
        self.assertIn("AIAutoRiggerDev", text)
        self.assertIn("extensions/user_default", text)
        self.assertIn('"$@"', text)
        # 실제 폴더를 지우지 않는 안전 처리
        self.assertNotIn("rm -rf", text)

    def test_ps1_encoding_and_logic(self):
        raw = (SCRIPTS / "dev_run.ps1").read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "PowerShell 5.1 한국어 출력을 위해 UTF-8 BOM 필요")
        text = raw.decode("utf-8-sig")
        for needle in (
            "portable\\extensions\\user_default",
            "-ItemType Junction",
            "'--python-exit-code', '1'",
            "ValueFromRemainingArguments",
            "exit $LASTEXITCODE",
            "[System.IO.Directory]::Delete($Link)",
            "dev_bootstrap.py",
        ):
            self.assertIn(needle, text)
        self.assertNotIn("Remove-Item", text)
        self.assertNotIn("-Recurse", text)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh 미설치: PowerShell 파서 검사 생략")
    def test_ps1_parses(self):
        cmd = (
            "$e=$null;[System.Management.Automation.Language.Parser]::ParseFile("
            f"'{SCRIPTS / 'dev_run.ps1'}',[ref]$null,[ref]$e)|Out-Null;"
            "if($e.Count){$e;exit 1}"
        )
        subprocess.run(["pwsh", "-NoProfile", "-Command", cmd], check=True)

    def test_bat_ascii_crlf_and_forwarding(self):
        raw = (SCRIPTS / "dev_run.bat").read_bytes()
        raw.decode("ascii")
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""), "CRLF 줄바꿈 필요")
        text = raw.decode("ascii")
        self.assertIn("dev_run.ps1", text)
        self.assertIn("%*", text)
        self.assertIn("exit /b %ERRORLEVEL%", text)


if __name__ == "__main__":
    unittest.main()
