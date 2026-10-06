"""포즈 시퀀스(클립) → 키 채널 변환과 동작 사전 (bpy 비의존).

AI 나 사전(라이브러리)이 극점 포즈를 직접 쓰는 제한된 포즈 언어다. 컨트롤은 몸통·골반·가슴·머리·양손·양발뿐이고,
값은 캐릭터 기준 오프셋(side, fwd, up: 몸통·발은 다리 길이, 손은 팔 길이 비율)과 회전(pitch, roll, yaw, 도)이다.
발 접지 구간 선형 보간, 바닥 관통 방지, 루프 닫기, 키 수 제한, 범위 클램프는 여기서 보장하므로
AI 가 값을 잘못 써도 캐릭터가 바닥을 뚫거나 루프가 끊기지는 않는다.

클립 형식:
    {"name": "punch", "loop": false, "frames": 24, "root_distance": 0.0,
     "keys": [{"t": 0.0, "ease": "BEZIER", "rest": true, "torso": null, "hips": null, "chest": null, "head": null,
               "hand_L": null, "hand_R": null, "foot_L": null, "foot_R": null},
              {"t": 0.4, "ease": "BEZIER", "rest": false,
               "torso": {"side": 0, "fwd": 0.1, "up": -0.05, "pitch": 10, "roll": 0, "yaw": -15},
               "hand_R": {"side": 0.1, "fwd": 0.9, "up": 0.3, "pitch": 0, "roll": 0, "yaw": 0}, ...}]}
- 키에서 null 인 컨트롤은 그 시점에 키를 두지 않는다 (다른 키 사이를 베지어로 지나간다).
- "rest": true 는 모든 컨트롤을 그 시점에 레스트(0)로 둔다.
- 손 위치는 어깨 기준 팔 길이 비율이다 (|벡터| ≤ 1 이면 닿는다). 레스트 손 위치가 캐릭터마다 달라도(A-포즈, 팔 내림)
  "fwd 0.9, up 0" 은 언제나 어깨 높이로 뻗은 손이 된다. 몸통이 움직이면 어깨도 함께 움직이므로 몸통 이동이 더해진다.
- 발은 up == 0 이면 땅에 닿은 것이고, 접지 키 사이는 선형이라 미끄러지지 않는다. 키가 없는 발은 제자리에 고정된다.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field

from . import locomotion as L

CONTROLS = ("torso", "hips", "chest", "head", "hand_L", "hand_R", "foot_L", "foot_R")
LOC_FIELDS = ("side", "fwd", "up")
ROT_FIELDS = ("pitch", "roll", "yaw")
FIELDS = {
    "torso": LOC_FIELDS + ROT_FIELDS,
    "hips": ROT_FIELDS, "chest": ROT_FIELDS, "head": ROT_FIELDS,
    "hand_L": LOC_FIELDS + ROT_FIELDS, "hand_R": LOC_FIELDS + ROT_FIELDS,
    "foot_L": LOC_FIELDS + ROT_FIELDS + ("heel",), "foot_R": LOC_FIELDS + ROT_FIELDS + ("heel",),
}
BONES = {"torso": "torso", "hips": "hips", "chest": "chest", "head": "head", "hand_L": "hand_ik.L", "hand_R": "hand_ik.R",
         "foot_L": "foot_ik.L", "foot_R": "foot_ik.R"}
HEEL_BONES = {"foot_L": "foot_heel_ik.L", "foot_R": "foot_heel_ik.R"}
MAX_KEYS = 12
FRAME_RANGE = (8, 240)
# 값 범위 (AI 응답 클램프). 거리는 비율, 각도는 도
RANGES = {
    "torso": {"side": (-0.8, 0.8), "fwd": (-0.8, 0.8), "up": (-0.95, 1.0), "pitch": (-90.0, 90.0), "roll": (-60.0, 60.0), "yaw": (-90.0, 90.0)},
    "hips": {"pitch": (-45.0, 45.0), "roll": (-45.0, 45.0), "yaw": (-45.0, 45.0)},
    "chest": {"pitch": (-45.0, 45.0), "roll": (-45.0, 45.0), "yaw": (-45.0, 45.0)},
    "head": {"pitch": (-40.0, 60.0), "roll": (-45.0, 45.0), "yaw": (-80.0, 80.0)},
    "hand": {"side": (-1.0, 1.0), "fwd": (-1.0, 1.0), "up": (-1.3, 1.2), "pitch": (-90.0, 90.0), "roll": (-90.0, 90.0), "yaw": (-90.0, 90.0)},
    "foot": {"side": (-0.5, 0.5), "fwd": (-0.8, 0.8), "up": (0.0, 1.0), "pitch": (-70.0, 70.0), "roll": (-30.0, 30.0), "yaw": (-45.0, 45.0), "heel": (-45.0, 45.0)},
}
# 바닥 관통 방지 (다리 길이 비율): 몸통 레스트 높이 ≈ 1.1×다리
TORSO_FLOOR = -0.92
HAND_CLEARANCE = 0.04  # 손이 바닥 위로 남기는 여유 (m)


@dataclass
class Body:
    """리그 실측 (m). shoulder 는 손 IK 레스트 위치에서 어깨까지의 캐릭터 기준 (side, fwd, up) 오프셋,
    hand_height 는 손 IK 레스트의 바닥 높이."""

    leg: float
    arm: float
    shoulder: dict  # {"L": (side, fwd, up), "R": (...)}
    hand_height: dict  # {"L": m, "R": m}
    pivot: dict | None = None  # 손 IK 레스트 → 몸통(torso) 피벗 오프셋. 없으면 어깨 바로 아래 손 높이로 본다

    def __post_init__(self):
        if self.pivot is None:
            self.pivot = {s: (sh[0], 0.0, 0.0) for s, sh in self.shoulder.items()}

    @classmethod
    def approx(cls, leg: float, arm: float) -> "Body":
        """실측이 없을 때(단위 테스트·변환 전용) A-포즈 근사: 손은 어깨에서 바깥 0.5·아래 0.85 팔 길이."""
        return cls(leg, arm, {"L": (-0.5 * arm, 0.0, 0.85 * arm), "R": (0.5 * arm, 0.0, 0.85 * arm)},
                   {"L": 1.05 * leg, "R": 1.05 * leg})


def rotate(v: tuple, pitch: float, roll: float, yaw: float, inverse: bool = False) -> tuple:
    """캐릭터 기준 (side, fwd, up) 벡터를 몸통 회전(도)으로 돌린다. 브리지 char_rotation 과 같은 순서(roll → pitch → yaw).

    (side, fwd, up) 은 왼손 좌표계라 (right, fwd, up) 으로 바꿔 계산한다. pitch>0 앞으로 숙임, roll>0 오른쪽, yaw>0 왼쪽.
    """
    from math import cos, radians, sin

    def rx(a, x, y, z):
        c, s = cos(a), sin(a)
        return x, y * c - z * s, y * s + z * c

    def ry(a, x, y, z):
        c, s = cos(a), sin(a)
        return x * c + z * s, y, -x * s + z * c

    def rz(a, x, y, z):
        c, s = cos(a), sin(a)
        return x * c - y * s, x * s + y * c, z

    x, y, z = -v[0], v[1], v[2]
    p, r, w = radians(pitch), radians(roll), radians(yaw)
    if inverse:
        x, y, z = rz(-w, x, y, z)
        x, y, z = rx(p, x, y, z)
        x, y, z = ry(-r, x, y, z)
    else:
        x, y, z = ry(r, x, y, z)
        x, y, z = rx(-p, x, y, z)
        x, y, z = rz(w, x, y, z)
    return (-x, y, z)


def _hand_offset(u: tuple, torso_t: tuple, torso_r: tuple, pivot: tuple) -> tuple:
    """손 레스트 기준 오프셋(몸통 레스트 자세, m) u → 몸통이 이동·회전한 뒤의 레스트 기준 오프셋.

    손 IK 는 Root 를 따르므로 어깨가 몸통과 함께 돌도록 몸통 피벗을 중심으로 돌리고 몸통 이동을 더한다.
    """
    rel = tuple(a - b for a, b in zip(u, pivot))
    rot = rotate(rel, *torso_r)
    return tuple(t + r + pv for t, r, pv in zip(torso_t, rot, pivot))


def _hand_offset_inverse(off: tuple, torso_t: tuple, torso_r: tuple, pivot: tuple) -> tuple:
    rel = tuple(o - t - pv for o, t, pv in zip(off, torso_t, pivot))
    rot = rotate(rel, *torso_r, inverse=True)
    return tuple(r + pv for r, pv in zip(rot, pivot))


def _ranges(control: str) -> dict:
    if control.startswith("hand"):
        return RANGES["hand"]
    if control.startswith("foot"):
        return RANGES["foot"]
    return RANGES[control]


def empty_key(t: float = 0.0, rest: bool = False, ease: str = L.BEZIER) -> dict:
    return {"t": t, "ease": ease, "rest": rest, **{c: None for c in CONTROLS}}


def _num(v, lo, hi, default=0.0) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    return float(min(hi, max(lo, v)))


def clamp(data: dict) -> dict:
    """dict(AI 응답·사전) → 범위가 보장된 클립. 모르는 키는 버리고, 키는 시간순 정렬 후 최대 MAX_KEYS 개."""
    if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
        raise ValueError("클립에 keys 가 없습니다.")
    name = re.sub(r"[^A-Za-z0-9_]+", "_", str(data.get("name") or "clip")).strip("_").lower() or "clip"
    loop = bool(data.get("loop", False))
    frames = int(round(_num(data.get("frames"), *FRAME_RANGE, default=24.0)))
    out = {"name": name[:32], "loop": loop, "frames": frames,
           "root_distance": _num(data.get("root_distance"), 0.0, 3.0), "keys": []}
    for raw in data["keys"]:
        if not isinstance(raw, dict):
            continue
        t = _num(raw.get("t"), 0.0, 1.0)
        if loop and t >= 1.0:
            continue  # 루프는 생성기가 닫으므로 t=1 키는 버린다
        key = empty_key(round(t, 4), raw.get("rest") is True, L.LINEAR if raw.get("ease") == L.LINEAR else L.BEZIER)
        for c in CONTROLS:
            v = raw.get(c)
            if isinstance(v, dict):
                rng = _ranges(c)
                key[c] = {f: _num(v.get(f), *rng[f]) for f in FIELDS[c]}
        out["keys"].append(key)
    out["keys"].sort(key=lambda k: k["t"])
    # 같은 시점 키는 뒤의 것으로 합친다
    merged = []
    for key in out["keys"]:
        if merged and merged[-1]["t"] == key["t"]:
            prev = merged[-1]
            prev["rest"] = prev["rest"] or key["rest"]
            for c in CONTROLS:
                if key[c] is not None:
                    prev[c] = key[c]
            continue
        merged.append(key)
    out["keys"] = merged[:MAX_KEYS]
    if not out["keys"]:
        raise ValueError("클립에 유효한 키가 없습니다.")
    return out


@dataclass
class ClipParams:
    """포즈 시퀀스 기반 동작의 파라미터 (GaitParams 와 같은 자리에 들어간다)."""

    clip: dict
    root_motion: bool = False
    motion: str = field(default="CLIP", init=False)

    @property
    def name(self) -> str:
        return self.clip["name"]

    @property
    def cycle_frames(self) -> int:
        return self.clip["frames"]

    @property
    def loop(self) -> bool:
        return self.clip["loop"]

    def to_dict(self):
        return {"motion": "CLIP", "cycle_frames": self.cycle_frames, "root_motion": self.root_motion, "clip": self.clip}


def _values(control: str, v: dict, body: Body, rest: bool) -> tuple[tuple, tuple, float | None]:
    """(위치 m — 레스트 기준 오프셋, 회전 도, 발 굴림 도). 손은 어깨 기준 값을 레스트 기준으로 바꾼다."""
    if control.startswith("hand"):
        # 어깨 기준 값 → 몸통이 레스트일 때의 손 레스트 기준 오프셋 (몸통 이동·회전은 to_motion 이 나중에 더한다)
        if rest:
            loc = (0.0, 0.0, 0.0)
        else:
            sh = body.shoulder[control[-1]]
            loc = tuple(s + v[f] * body.arm for s, f in zip(sh, LOC_FIELDS))
    elif "side" in FIELDS[control]:
        loc = tuple(v[f] * body.leg for f in LOC_FIELDS)
    else:
        loc = ()
    rot = tuple(v[f] for f in ROT_FIELDS)
    heel = v.get("heel") if control.startswith("foot") else None
    return loc, rot, heel


def _finish(keys: list[L.Key], loop: bool) -> list[L.Key]:
    """루프는 첫 키를 한 주기 뒤에 복제해 닫고, 단발은 레스트에서 시작해 끝 값을 유지한다."""
    keys = sorted(keys, key=lambda k: k.t)
    if loop:
        return L._close(keys)
    if keys[0].t > 0.0:
        keys.insert(0, L.Key(0.0, tuple(0.0 for _ in keys[0].value), L.BEZIER))
    return L._hold(keys)


def to_motion(p: ClipParams, body: Body) -> L.Motion:
    """클립 → 키 채널. 손은 어깨 기준 값을 레스트 기준으로 바꾼 뒤 몸통 이동을 따르고, 발 접지 키 사이는 선형이다."""
    clip = p.clip
    loop = clip["loop"]
    leg = body.leg
    per: dict[tuple[str, str], list[L.Key]] = {}
    for key in clip["keys"]:
        t = key["t"]
        for c in CONTROLS:
            v = key[c]
            rest = v is None and key["rest"]
            if rest:
                v = {f: 0.0 for f in FIELDS[c]}
            if v is None:
                continue
            loc, rot, heel = _values(c, v, body, rest)
            if loc:
                if c == "torso":
                    loc = (loc[0], loc[1], max(loc[2], TORSO_FLOOR * leg))
                per.setdefault((c, "loc"), []).append(L.Key(t, loc, key["ease"]))
            per.setdefault((c, "rot"), []).append(L.Key(t, rot, key["ease"]))
            if heel is not None:
                per.setdefault((c, "roll"), []).append(L.Key(t, (heel,), key["ease"]))
    # 발: 접지(up == 0) 키에서 다음 접지 키까지는 선형이라 미끄러지지 않는다
    for c in ("foot_L", "foot_R"):
        keys = sorted(per.get((c, "loc"), []), key=lambda k: k.t)
        for a, b in zip(keys, keys[1:]):
            if a.value[2] == 0.0 and b.value[2] == 0.0:
                a.interp = L.LINEAR
    torso_loc = _finish(per[("torso", "loc")], loop) if ("torso", "loc") in per else None
    torso_rot = _finish(per[("torso", "rot")], loop) if ("torso", "rot") in per else None
    zero3 = (0.0, 0.0, 0.0)

    def torso_at(t):
        return (L.sample(torso_loc, t) if torso_loc else zero3, L.sample(torso_rot, t) if torso_rot else zero3)

    channels: list[L.Channel] = []
    for (c, kind), keys in per.items():
        if c.startswith("hand") and kind == "loc":
            # 손: 몸통 피벗을 중심으로 몸통 회전을 따라 돌리고 몸통 이동을 더한다. 몸통 키 시점에도 손 키를 둬야
            # 몸이 움직일 때 손이 뒤처지지 않는다
            raw = _finish(list(keys), loop)
            ease = {round(k.t, 6): k.interp for k in keys}
            times = {round(k.t, 6) for k in keys}
            for src in (torso_loc, torso_rot):
                for tk in (src[:-1] if loop else src) if src else ():
                    if 0.0 <= tk.t <= 1.0:
                        times.add(round(tk.t, 6))
            side = c[-1]
            out = []
            for t in sorted(times):
                tl, tr = torso_at(t)
                off = _hand_offset(L.sample(raw, t), tl, tr, body.pivot[side])
                off = (off[0], off[1], max(off[2], HAND_CLEARANCE - body.hand_height[side]))
                out.append(L.Key(t, off, ease.get(t, L.BEZIER)))
            keys = out
        bone = HEEL_BONES[c] if kind == "roll" else BONES[c]
        if c == "torso" and kind == "loc":
            finished = torso_loc
        elif c == "torso" and kind == "rot":
            finished = torso_rot
        else:
            finished = _finish(keys, loop)
        channels.append(L.Channel(bone, kind, finished))
    distance = clip["root_distance"] * leg if p.root_motion else 0.0
    if distance > 0.0:
        channels.append(L.Channel("root", "loc", [L.Key(0.0, (0.0, 0.0, 0.0), L.LINEAR), L.Key(1.0, (0.0, distance, 0.0), L.LINEAR)]))
    return L.Motion(p, channels, distance)


def from_motion(m: L.Motion, body: Body, name: str) -> dict:
    """키 채널 → 클립 (사전 저장용). 손은 몸통 이동을 빼고 어깨 기준 팔 길이 비율로 되돌린다."""
    loop = m.loop
    leg, arm = body.leg, body.arm
    torso_loc = next((c.keys for c in m.channels if c.bone == "torso" and c.kind == "loc"), None)
    torso_rot = next((c.keys for c in m.channels if c.bone == "torso" and c.kind == "rot"), None)
    zero3 = (0.0, 0.0, 0.0)
    by_time: dict[float, dict] = {}
    by_bone = {v: k for k, v in BONES.items()}
    by_heel = {v: k for k, v in HEEL_BONES.items()}
    for ch in m.channels:
        if ch.bone == "root":
            continue
        control = by_bone.get(ch.bone) or by_heel.get(ch.bone)
        if control is None:
            continue
        keys = ch.keys[:-1] if loop else ch.keys
        for k in keys:
            t = round(k.t % 1.0, 4) if loop else round(min(k.t, 1.0), 4)
            key = by_time.setdefault(t, empty_key(t))
            if k.interp == L.LINEAR:
                key["ease"] = L.LINEAR
            v = key[control] or {f: 0.0 for f in FIELDS[control]}
            if ch.kind == "roll":
                v["heel"] = k.value[0]
            elif ch.kind == "rot":
                v.update(zip(ROT_FIELDS, k.value))
            else:
                val = k.value
                if control.startswith("hand"):
                    tl = L.sample(torso_loc, k.t) if torso_loc else zero3
                    tr = L.sample(torso_rot, k.t) if torso_rot else zero3
                    val = _hand_offset_inverse(val, tl, tr, body.pivot[control[-1]])
                    val = tuple(x - s for x, s in zip(val, body.shoulder[control[-1]]))
                scale = arm if control.startswith("hand") else leg
                v.update(zip(LOC_FIELDS, (x / scale for x in val)))
            key[control] = v
    clip = {"name": name, "loop": loop, "frames": m.params.cycle_frames,
            "root_distance": (m.root_distance / leg) if leg else 0.0, "keys": sorted(by_time.values(), key=lambda k: k["t"])}
    # 키가 너무 많으면(걷기 등) 극점만 남기도록 간격이 좁은 키부터 버린다
    while len(clip["keys"]) > MAX_KEYS:
        gaps = [(clip["keys"][i + 1]["t"] - clip["keys"][i - 1]["t"], i) for i in range(1, len(clip["keys"]) - 1)]
        del clip["keys"][min(gaps)[1]]
    return clamp(clip)


# ---- 동작 사전 ---------------------------------------------------------------

BUILTIN_PATH = pathlib.Path(__file__).with_name("motion_library.json")


@dataclass
class Entry:
    name: str
    description: str
    clip: dict
    source: str = "builtin"  # "builtin" | 파일 경로


def load_library(user_dir: str | pathlib.Path | None = None) -> list[Entry]:
    """내장 사전 + 사용자 사전(JSON 파일당 항목 하나 또는 목록). 같은 이름은 사용자 항목이 우선한다."""
    entries: dict[str, Entry] = {}
    for raw in json.loads(BUILTIN_PATH.read_text(encoding="utf-8")):
        e = _entry(raw, "builtin")
        entries[e.name] = e
    if user_dir:
        for path in sorted(pathlib.Path(user_dir).glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for raw in (data if isinstance(data, list) else [data]):
                try:
                    e = _entry(raw, str(path))
                except (ValueError, TypeError, KeyError):
                    continue
                entries[e.name] = e
    return sorted(entries.values(), key=lambda e: e.name)


def _entry(raw: dict, source: str) -> Entry:
    clip = clamp(raw["clip"])
    return Entry(clip["name"], str(raw.get("description") or ""), clip, source)


def save_entry(user_dir: str | pathlib.Path, entry: Entry) -> pathlib.Path:
    d = pathlib.Path(user_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{entry.name}.json"
    path.write_text(json.dumps({"description": entry.description, "clip": entry.clip}, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def compact(clip: dict) -> str:
    """프롬프트용 짧은 JSON: null 컨트롤과 rest=false 는 생략한다."""
    keys = []
    for k in clip["keys"]:
        item = {"t": k["t"]}
        if k["ease"] == L.LINEAR:
            item["ease"] = L.LINEAR
        if k["rest"]:
            item["rest"] = True
        for c in CONTROLS:
            if k[c] is not None:
                item[c] = {f: round(v, 3) if isinstance(v, float) else v for f, v in k[c].items() if v != 0.0}
        keys.append(item)
    data = {"name": clip["name"], "loop": clip["loop"], "frames": clip["frames"], "keys": keys}
    if clip["root_distance"]:
        data["root_distance"] = clip["root_distance"]
    return json.dumps(data, separators=(",", ":"))
