"""anthropic SDK 와 의존성 wheel 을 플랫폼·Python 버전별로 내려받고 매니페스트 wheels 목록을 갱신한다.

    python3 scripts/fetch_wheels.py

Blender 는 설치 시 현재 플랫폼·Python 에 맞는 wheel 만 골라 설치하므로 Python 3.11(Blender 4.2~4.x)과
3.13(Blender 5.x) wheel 을 함께 둔다. wheels/ 는 커밋하지 않고 빌드·CI 에서 이 스크립트로 채운다.
"""

import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
WHEELS = ROOT / "wheels"
MANIFEST = ROOT / "blender_manifest.toml"
REQUIREMENT = "anthropic==1.11.0"
PYTHONS = ("3.11", "3.13")
# Blender 플랫폼 이름 → pip 플랫폼 태그
PLATFORMS = {
    "macos-arm64": ["macosx_11_0_arm64"],
    "macos-x64": ["macosx_10_12_x86_64", "macosx_10_13_x86_64", "macosx_11_0_x86_64"],
    "windows-x64": ["win_amd64"],
    "linux-x64": ["manylinux_2_17_x86_64", "manylinux2014_x86_64", "manylinux_2_28_x86_64"],
}


def download(py, tags):
    cmd = [sys.executable, "-m", "pip", "download", REQUIREMENT, "--quiet", "--disable-pip-version-check",
           "--only-binary=:all:", "--implementation", "cp", "--python-version", py,
           "--abi", "cp" + py.replace(".", ""), "--abi", "abi3", "--abi", "none", "-d", str(WHEELS)]
    for t in tags:
        cmd += ["--platform", t]
    cmd += ["--platform", "any"]
    subprocess.run(cmd, check=True)


def update_manifest(names):
    text = MANIFEST.read_text(encoding="utf-8")
    block = "wheels = [\n" + "".join(f'  "./wheels/{n}",\n' for n in names) + "]\n"
    platforms = "platforms = [" + ", ".join(f'"{p}"' for p in PLATFORMS) + "]\n"
    text = re.sub(r"(?ms)^wheels = \[.*?^\]\n\n?", "", text)
    text = re.sub(r"(?m)^platforms = \[.*\]\n\n?", "", text)
    # [build] 같은 테이블보다 앞(최상위 키 영역)에 둔다
    idx = text.index("\n[")
    text = text[:idx + 1] + platforms + "\n" + block + "\n" + text[idx + 1:]
    MANIFEST.write_text(text, encoding="utf-8")


def main():
    if WHEELS.exists():
        shutil.rmtree(WHEELS)
    WHEELS.mkdir()
    for py in PYTHONS:
        for tags in PLATFORMS.values():
            download(py, tags)
    names = sorted(p.name for p in WHEELS.glob("*.whl"))
    update_manifest(names)
    print(f"[fetch_wheels] {len(names)} wheels → {WHEELS}")


if __name__ == "__main__":
    main()
