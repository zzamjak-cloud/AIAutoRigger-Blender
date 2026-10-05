#!/usr/bin/env python3
"""claude / codex CLI 흉내 (테스트 전용). 실제 CLI 와 같은 인자 규약을 검사하고 준비된 응답을 차례로 돌려준다.

환경 변수
  AIRIG_FAKE_RESPONSES  응답 dict 목록 JSON 파일 (호출마다 하나씩 소비)
  AIRIG_FAKE_LOG        호출 기록(JSON lines) 파일
  AIRIG_FAKE_SLEEP      응답 전 대기 초 (취소·시간 초과 테스트)
"""

import json
import os
import pathlib
import sys
import time


def next_response():
    path = pathlib.Path(os.environ["AIRIG_FAKE_RESPONSES"])
    items = json.loads(path.read_text())
    item = items.pop(0) if len(items) > 1 else items[0]
    path.write_text(json.dumps(items))
    return item


def log(entry):
    with open(os.environ["AIRIG_FAKE_LOG"], "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def png_ok(p):
    with open(p, "rb") as f:
        return f.read(8) == b"\x89PNG\r\n\x1a\n"


def main():
    args = sys.argv[1:]
    prompt = sys.stdin.read()
    time.sleep(float(os.environ.get("AIRIG_FAKE_SLEEP", "0")))
    if args and args[0] == "exec":
        images = [args[i + 1] for i, a in enumerate(args) if a == "-i"]
        assert all(os.sep not in p for p in images), "codex -i 는 작업 폴더 기준 파일 이름이어야 함"
        schema = json.loads(pathlib.Path(args[args.index("--output-schema") + 1]).read_text())
        out = args[args.index("-o") + 1]
        assert args[-1] == "-" and "-s" in args and args[args.index("-s") + 1] == "read-only"
        assert all(png_ok(p) for p in images), "이미지가 PNG 가 아님"
        log({"cli": "codex", "images": [os.path.basename(p) for p in images], "schema_keys": sorted(schema["properties"]),
             "prompt": prompt, "args": args})
        pathlib.Path(out).write_text(json.dumps(next_response()))
        return 0
    assert "-p" in args and args[args.index("--output-format") + 1] == "json"
    schema = json.loads(args[args.index("--json-schema") + 1])
    assert args[args.index("--tools") + 1] == "Read" and args[args.index("--allowedTools") + 1] == "Read"
    assert "--strict-mcp-config" in args and os.path.samefile(args[args.index("--add-dir") + 1], os.getcwd())
    images = sorted(p for p in os.listdir(os.getcwd()) if p.endswith(".png"))
    assert images and all(png_ok(p) for p in images) and all(p in prompt for p in images), "프롬프트·작업 폴더 이미지 불일치"
    log({"cli": "claude", "images": images, "schema_keys": sorted(schema["properties"]), "prompt": prompt, "args": args, "env_keys": sorted(os.environ)})
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                      "structured_output": next_response(), "session_id": "fake"}))
    return 0


sys.exit(main())
