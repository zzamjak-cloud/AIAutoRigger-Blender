"""배포 구성 정적 회귀 검사: 매니페스트·wheel 목록·워크플로·README."""

import pathlib
import re
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = tomllib.loads((ROOT / "blender_manifest.toml").read_text(encoding="utf-8"))
WORKFLOWS = ROOT / ".github" / "workflows"
REPO_URL = "https://zzamjak-cloud.github.io/AIAutoRigger-Blender/index.json"


class DistributionTest(unittest.TestCase):
    def test_manifest(self):
        self.assertEqual(MANIFEST["id"], "ai_auto_rigger")
        self.assertRegex(MANIFEST["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(set(MANIFEST["platforms"]), {"macos-arm64", "macos-x64", "windows-x64", "linux-x64"})
        self.assertIn("network", MANIFEST["permissions"])
        self.assertIn("files", MANIFEST["permissions"])
        excluded = MANIFEST["build"]["paths_exclude_pattern"]
        for p in ("/tests/", "/scripts/", "/docs/", "/.github/", "/dist/"):
            self.assertIn(p, excluded)
        self.assertNotIn("/wheels/", excluded)

    def test_wheels_cover_sdk_for_each_platform_and_python(self):
        wheels = [pathlib.Path(w).name for w in MANIFEST["wheels"]]
        self.assertTrue(any(w.startswith("anthropic-") for w in wheels))
        for native in ("pydantic_core", "jiter"):
            for py in ("cp311", "cp313"):
                for tag in ("macosx_11_0_arm64", "x86_64.whl", "win_amd64", "manylinux"):
                    self.assertTrue(any(w.startswith(native) and py in w and tag in w for w in wheels),
                                    f"{native} {py} {tag} wheel 누락")

    def test_manifest_version_matches_changelog(self):
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## [{MANIFEST['version']}]", changelog)

    def test_workflows(self):
        check = (WORKFLOWS / "check.yml").read_text(encoding="utf-8")
        release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
        pages = (WORKFLOWS / "pages.yml").read_text(encoding="utf-8")
        self.assertIn("unittest discover", check)
        self.assertIn("blender_rig_test.py", check)
        self.assertIn("--split-platforms", release)
        self.assertIn('tags: ["v*"]', release)
        self.assertIn("server-generate", pages)
        self.assertIn("workflows: [release]", pages)
        # 같은 플랫폼 다중 버전은 업데이트를 막으므로 최신 릴리스만 수집해야 한다
        self.assertIn("gh release view", pages)
        self.assertNotIn("gh release list", pages)
        # CI 가 내려받은 Blender 가 패키지에 섞이지 않도록 저장소 밖에 설치해야 한다
        for wf in (check, release, pages):
            self.assertNotIn("mkdir blender ", wf)
            self.assertIn('$RUNNER_TEMP/blender', wf)
        self.assertIn("52428800", release)

    def test_readme_separates_dev_and_user_install(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(REPO_URL, readme)
        self.assertIn("Check for Updates on Startup", readme)
        self.assertIn("scripts/dev_run.sh", readme)
        self.assertIn("scripts\\dev_run.ps1", readme)
        self.assertNotRegex(readme, r"자동\s*설치")


if __name__ == "__main__":
    unittest.main()
