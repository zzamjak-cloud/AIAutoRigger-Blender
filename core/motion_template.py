"""모션 템플릿: 손으로 다듬은 액션을 타입(체형)별로 등록하고 다른 캐릭터에 다시 쓰는 저장소 (bpy 비의존).

동작 사전(poseclip)은 극점 포즈 12개로 줄인 포즈 언어지만, 템플릿은 F-커브를 거의 그대로 담는다.
키 타이밍·보간·추가로 키를 넣은 본(턱, 팔 IK 회전 등)이 모두 남는다. 캐릭터마다 다른 값은 bridge/template 이
캐릭터 기준 값으로 바꿔 넣는다 (위치는 다리·팔 길이 비율, 회전은 캐릭터 축 기준 레스트 대비 회전).

파일 구조:
    <폴더>/<타입>/<동작>.json            현재 버전
    <폴더>/<타입>/_history/<동작>.v<N>.json  덮어쓰기 전 버전 (등록할 때마다 하나씩 쌓인다)

템플릿 형식:
    {"format": 1, "type": "Zombie_Thin", "name": "walk", "loop": true, "frames": 59, "version": 3,
     "description": "", "saved": "2026-10-16T12:00:00", "source": {"file": ..., "rig": ..., "action": ...},
     "body": {"leg": m, "arm": m, "height": m, "width": m, "depth": m},
     "channels": [{"path": 'pose.bones["torso"].location', "bone": "torso", "prop": "location", "space": "leg",
                   "size": 3, "cyclic": true, "offset": false,
                   "keys": [{"t": 0.0, "v": [..], "ip": "BEZIER" | [성분별], "hl": [왼쪽, 오른쪽] | [[..] 성분별],
                             "m": [키가 있던 성분] (일부 성분에만 키가 있을 때), "hd": [[dt 성분별, dv], [dt, dv]]}, ...]}]}
    space: "leg"/"arm"(캐릭터 축 위치 / 길이), "hand"(어깨 기준 손 위치 / 팔 길이), "rot"(캐릭터 축 레스트 대비 회전 사원수),
           "hand_rot"(캐릭터 축 절대 방향 사원수), "raw"(로컬 값 그대로 — "index" 성분 하나: 오일러 굴림·스케일·사용자 속성)
    t: 0~1 (루프는 한 주기, 단발은 전체 길이). hd 는 핸들을 직접 고친 키만 둔다 (자동 핸들은 다시 계산한다).
    cyclic: 루프에서 Cycles 모디파이어가 있던 커브인지 (손으로 뺀 커브는 적용할 때도 넣지 않는다).
"""

from __future__ import annotations

import datetime
import json
import pathlib
import re

FORMAT = 1
AUTO_TYPE = "AUTO"
BUILTIN_DIR = pathlib.Path(__file__).with_name("motion_templates")
HISTORY = "_history"
AUTO_HANDLES = ("AUTO", "AUTO_CLAMPED")
# 체형 비교에 쓰는 비율 (모두 키 대비)
BODY_RATIOS = ("leg", "arm", "width", "depth")


def safe_name(text: str, default: str = "motion") -> str:
    """파일·타입 이름: 영문·숫자·_·- 만 남긴다 (대소문자는 유지)."""
    out = re.sub(r"[^A-Za-z0-9_\-]+", "_", str(text or "")).strip("_-")
    return out[:48] or default


def motion_name(action_name: str, prefixes=()) -> str:
    """액션 이름 → 동작 이름. 'Zombie_Thin_Attack_R' 에서 리그·메시 이름 접두사를 떼 'Attack_R' 로 만든다."""
    name = action_name
    for p in sorted((p for p in prefixes if p), key=len, reverse=True):
        if name.lower().startswith(p.lower() + "_") and len(name) > len(p) + 1:
            name = name[len(p) + 1:]
            break
    return safe_name(name)


def body_ratios(body: dict) -> dict:
    h = body.get("height") or 0.0
    if h <= 0.0:
        return {}
    return {k: body[k] / h for k in BODY_RATIOS if isinstance(body.get(k), (int, float))}


def body_distance(a: dict, b: dict) -> float:
    """두 체형의 비율 차이 (작을수록 비슷하다). 폭·두께는 다리·팔보다 덜 본다."""
    ra, rb = body_ratios(a), body_ratios(b)
    weights = {"leg": 2.0, "arm": 1.5, "width": 1.0, "depth": 1.0}
    common = [k for k in ra if k in rb]
    if not common:
        return float("inf")
    return sum(weights[k] * (ra[k] - rb[k]) ** 2 for k in common) ** 0.5


def validate(data: dict) -> dict:
    """읽은 템플릿 검증. 형식이 다르거나 채널이 없으면 ValueError."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("모션 템플릿 형식이 아닙니다.")
    if not isinstance(data.get("channels"), list) or not data["channels"]:
        raise ValueError("템플릿에 채널이 없습니다.")
    frames = data.get("frames")
    if not isinstance(frames, (int, float)) or frames < 1:
        raise ValueError("템플릿 길이(frames)가 잘못되었습니다.")
    for ch in data["channels"]:
        if not isinstance(ch, dict) or not ch.get("keys") or "prop" not in ch:
            raise ValueError("템플릿 채널 형식이 잘못되었습니다.")
    data["type"] = safe_name(data.get("type"), "Default")
    data["name"] = safe_name(data.get("name"))
    data["loop"] = bool(data.get("loop"))
    data["frames"] = int(round(frames))
    return data


def _read(path: pathlib.Path, source: str) -> dict | None:
    try:
        data = validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, KeyError):
        return None
    # 타입·이름은 폴더·파일 이름이 기준이다 (폴더를 복사해 새 타입을 만들어도 겹치지 않게)
    data["type"], data["name"] = path.parent.name, path.stem
    data["_source"] = source
    data["_path"] = str(path)
    return data


def _scan(root: pathlib.Path, source: str) -> dict:
    out = {}
    if not root or not root.is_dir():
        return out
    for type_dir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")):
        if safe_name(type_dir.name, "") != type_dir.name:
            continue
        for path in sorted(type_dir.glob("*.json")):
            if safe_name(path.stem, "") != path.stem:
                continue
            data = _read(path, source)
            if data is not None:
                out[(data["type"], data["name"])] = data
    return out


def load(user_dir=None) -> dict:
    """{(타입, 동작): 템플릿}. 내장 템플릿 위에 사용자 폴더 템플릿을 덮는다 (같은 타입·동작은 사용자 것이 우선)."""
    out = _scan(BUILTIN_DIR, "builtin")
    if user_dir:
        out.update(_scan(pathlib.Path(user_dir), "user"))
    return out


def types(templates: dict) -> list[str]:
    return sorted({t for t, _ in templates})


def motions(templates: dict, type_name: str) -> list[str]:
    if type_name == AUTO_TYPE:
        return sorted({n for _, n in templates})
    return sorted(n for t, n in templates if t == type_name)


def nearest_type(templates: dict, body: dict, name: str | None = None) -> str | None:
    """체형이 가장 비슷한 타입. name 을 주면 그 동작이 있는 타입 중에서 고른다."""
    best, best_d = None, float("inf")
    for (t, n), data in sorted(templates.items()):
        if name is not None and n != name:
            continue
        d = body_distance(body, data.get("body") or {})
        if best is None or d < best_d:  # 체형 정보가 없으면 이름순 첫 타입
            best, best_d = t, d
    return best


def resolve(templates: dict, type_name: str, name: str, body: dict | None = None) -> dict:
    """(타입 또는 AUTO, 동작) → 템플릿. AUTO 는 체형이 가장 비슷한 타입을 고른다."""
    if type_name == AUTO_TYPE:
        type_name = nearest_type(templates, body or {}, name)
    data = templates.get((type_name, name))
    if data is None:
        raise KeyError(f"템플릿 '{type_name}/{name}' 이 없습니다.")
    return data


def save(user_dir, data: dict, now: datetime.datetime | None = None) -> pathlib.Path:
    """사용자 폴더에 등록한다. 같은 타입·동작이 있으면 이전 파일을 _history/<동작>.v<N>.json 으로 옮기고 버전을 올린다."""
    data = validate(dict(data))
    root = pathlib.Path(user_dir) / data["type"]
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{data['name']}.json"

    def version_of(p):
        try:
            return int(json.loads(p.read_text(encoding="utf-8")).get("version") or 1)
        except (OSError, ValueError, TypeError, AttributeError):
            return 0

    # 새 버전 = 현재·히스토리·내장 중 가장 높은 버전 + 1 (히스토리에서 복원한 뒤 다시 등록해도 겹치지 않게)
    builtin = BUILTIN_DIR / data["type"] / f"{data['name']}.json"
    known = [version_of(p) for p in (path, builtin) if p.exists()]
    known += [int(m.group(1)) for p in history(user_dir, data["type"], data["name"])
              if (m := re.search(r"\.v(\d+)", p.name))]
    version = max(known, default=0) + 1
    data["version"] = version
    data["saved"] = (now or datetime.datetime.now()).isoformat(timespec="seconds")
    clean = {k: v for k, v in data.items() if not k.startswith("_")}
    # 새 파일을 먼저 다 쓴 뒤 옮긴다 (쓰기 실패로 현재 버전이 사라지지 않게)
    tmp = root / f".{data['name']}.json.tmp"
    tmp.write_text(json.dumps(clean, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if path.exists():
        hist = root / HISTORY
        hist.mkdir(exist_ok=True)
        old = version_of(path) or version - 1
        target = hist / f"{data['name']}.v{old}.json"
        n = 1
        while target.exists():  # 손으로 버전을 맞추지 않은 파일이 겹치면 번호를 붙인다
            target = hist / f"{data['name']}.v{old}_{n}.json"
            n += 1
        path.replace(target)
    tmp.replace(path)
    return path


def history(user_dir, type_name: str, name: str) -> list[pathlib.Path]:
    hist = pathlib.Path(user_dir) / safe_name(type_name, "Default") / HISTORY
    if not hist.is_dir():
        return []

    def version(p):
        m = re.search(r"\.v(\d+)", p.name)
        return int(m.group(1)) if m else 0

    return sorted(hist.glob(f"{safe_name(name)}.v*.json"), key=version)
