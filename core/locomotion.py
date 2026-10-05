"""2족 이동 루프(걷기·달리기·대기) 키 포즈 생성 (bpy 비의존).

매 프레임 키를 찍지 않고 동작의 극점 포즈(접지·낮은 자세·교차·높은 자세 등)에만 키를 둔다.
사이는 베지어(Auto-Clamped)로 보간하고, 발이 땅을 딛는 구간만 선형으로 두어 미끄러짐을 막는다.
각 채널의 마지막 키는 첫 키를 한 주기 뒤에 복제해 Cycles 모디파이어가 끊김 없이 반복하게 한다.

좌표는 캐릭터 기준: 오프셋 (side, forward, up) — side 는 캐릭터 왼쪽, forward 는 정면, up 은 위.
회전 (pitch, roll, yaw) 도(degree): pitch>0 앞으로 숙임(발은 발끝 내림), roll>0 오른쪽으로 기울임, yaw>0 왼쪽으로 돎.
거리 파라미터는 다리 길이(leg) 또는 팔 길이(arm) 대비 비율이다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from math import cos, pi

MOTIONS = ("WALK", "RUN", "IDLE")
STYLES = ("NORMAL", "ZOMBIE")
LINEAR = "LINEAR"
BEZIER = "BEZIER"


@dataclass
class GaitParams:
    motion: str = "WALK"
    cycle_frames: int = 32
    duty: float = 0.6  # 한 발이 땅에 닿아 있는 주기 비율 (걷기 0.6, 달리기 0.35)
    stride: float = 0.55  # 딛는 동안 발이 몸 기준으로 지나가는 거리 / 다리 길이
    step_height: float = 0.12
    bounce: float = 0.03
    sway: float = 0.03
    crouch: float = 0.02  # 몸통을 낮춰 무릎을 굽힌 정도
    lean_deg: float = 4.0
    hip_yaw_deg: float = 6.0
    chest_counter_deg: float = 5.0
    toe_roll_deg: float = 20.0
    arm_swing: float = 0.25
    arm_forward: float = 0.0
    arm_raise: float = 0.0
    arm_inward: float = 0.0  # 손을 몸 중앙 쪽으로 모음 (A-포즈로 벌린 팔을 앞으로 모을 때)
    head_pitch_deg: float = 0.0
    head_roll_deg: float = 0.0
    head_bob_deg: float = 2.0
    limp_side: str = "NONE"  # "L" | "R" | "NONE"
    limp: float = 0.0  # 0~1: 해당 다리를 끌며 덜 들어 올린다
    root_motion: bool = False

    def to_dict(self):
        return asdict(self)


# 파라미터 허용 범위 (AI 응답 검증·클램프)
RANGES = {
    "cycle_frames": (12, 240), "duty": (0.2, 0.8), "stride": (0.0, 1.2), "step_height": (0.0, 0.4),
    "bounce": (0.0, 0.15), "sway": (0.0, 0.15), "crouch": (0.0, 0.3), "lean_deg": (-20.0, 45.0),
    "hip_yaw_deg": (0.0, 25.0), "chest_counter_deg": (0.0, 25.0), "toe_roll_deg": (0.0, 45.0),
    "arm_swing": (0.0, 0.6), "arm_forward": (0.0, 0.9), "arm_raise": (-0.3, 0.9), "arm_inward": (0.0, 0.6),
    "head_pitch_deg": (-30.0, 45.0), "head_roll_deg": (-30.0, 30.0), "head_bob_deg": (0.0, 15.0),
    "limp": (0.0, 1.0),
}

PRESETS = {
    ("WALK", "NORMAL"): {},
    ("WALK", "ZOMBIE"): dict(cycle_frames=44, stride=0.38, step_height=0.07, bounce=0.04, sway=0.07, crouch=0.06,
                             lean_deg=14.0, hip_yaw_deg=8.0, chest_counter_deg=3.0, toe_roll_deg=10.0, arm_swing=0.06,
                             arm_forward=0.65, arm_raise=0.45, arm_inward=0.25, head_pitch_deg=12.0, head_roll_deg=14.0,
                             head_bob_deg=6.0, limp_side="R", limp=0.6),
    ("RUN", "NORMAL"): dict(cycle_frames=18, duty=0.35, stride=0.75, step_height=0.3, bounce=0.06, sway=0.02,
                            crouch=0.05, lean_deg=10.0, hip_yaw_deg=8.0, chest_counter_deg=8.0, toe_roll_deg=30.0,
                            arm_swing=0.4, arm_raise=0.25, head_bob_deg=3.0),
    ("RUN", "ZOMBIE"): dict(cycle_frames=24, duty=0.4, stride=0.6, step_height=0.18, bounce=0.07, sway=0.06,
                            crouch=0.08, lean_deg=22.0, hip_yaw_deg=10.0, chest_counter_deg=4.0, toe_roll_deg=15.0,
                            arm_swing=0.12, arm_forward=0.7, arm_raise=0.5, arm_inward=0.25, head_pitch_deg=15.0, head_roll_deg=10.0,
                            head_bob_deg=8.0, limp_side="R", limp=0.35),
    ("IDLE", "NORMAL"): dict(cycle_frames=96, stride=0.0, step_height=0.0, bounce=0.012, sway=0.015, crouch=0.01,
                             lean_deg=1.0, hip_yaw_deg=1.5, chest_counter_deg=1.0, arm_swing=0.03, head_bob_deg=2.0),
    ("IDLE", "ZOMBIE"): dict(cycle_frames=84, stride=0.0, step_height=0.0, bounce=0.025, sway=0.06, crouch=0.05,
                             lean_deg=12.0, hip_yaw_deg=4.0, chest_counter_deg=3.0, arm_swing=0.06, arm_forward=0.45, arm_inward=0.15,
                             arm_raise=0.2, head_pitch_deg=14.0, head_roll_deg=18.0, head_bob_deg=8.0),
}


def preset(motion: str, style: str = "NORMAL", **overrides) -> GaitParams:
    values = {"motion": motion, **PRESETS.get((motion, style), {}), **overrides}
    return clamp(values)


def clamp(values: dict) -> GaitParams:
    """dict(AI 응답 등) → 범위가 보장된 GaitParams. 모르는 키는 무시한다."""
    base = GaitParams(motion=values.get("motion", "WALK") if values.get("motion") in MOTIONS else "WALK")
    if base.motion != "WALK":
        base = GaitParams(**{**base.to_dict(), **PRESETS.get((base.motion, "NORMAL"), {}), "motion": base.motion})
    out = base.to_dict()
    for f in fields(GaitParams):
        if f.name not in values or f.name == "motion":
            continue
        v = values[f.name]
        if f.name == "limp_side":
            out[f.name] = v if v in ("L", "R", "NONE") else "NONE"
        elif f.name == "root_motion":
            out[f.name] = bool(v)
        elif f.name in RANGES and isinstance(v, (int, float)) and not isinstance(v, bool):
            lo, hi = RANGES[f.name]
            v = min(hi, max(lo, v))
            out[f.name] = int(round(v)) if f.name == "cycle_frames" else float(v)
    p = GaitParams(**out)
    if p.motion == "IDLE":
        p.root_motion = False
    return p


@dataclass
class Key:
    t: float  # 주기 비율 (0 = 시작 프레임). 1 이상이면 다음 주기
    value: tuple
    interp: str = BEZIER  # 이 키에서 다음 키까지의 보간


@dataclass
class Channel:
    bone: str
    kind: str  # "loc" | "rot" | "roll" (로컬 X 회전 하나, 도)
    keys: list[Key] = field(default_factory=list)


@dataclass
class Motion:
    params: GaitParams
    channels: list[Channel]
    root_distance: float  # 한 주기에 전진하는 거리 (root_motion 일 때, m)

    def key_count(self) -> int:
        return sum(len(c.keys) for c in self.channels)


def _close(keys: list[Key]) -> list[Key]:
    """시작 키를 한 주기 뒤에 복제해 루프를 닫는다."""
    keys = sorted(keys, key=lambda k: k.t)
    return keys + [Key(keys[0].t + 1.0, keys[0].value, keys[0].interp)]


def sample(keys: list[Key], t: float) -> tuple:
    """키 사이 선형 근사 값 (손 위치에 몸통 이동을 더할 때 사용). 키는 _close 된 상태여야 한다."""
    t0 = keys[0].t
    t = t0 + ((t - t0) % 1.0)
    for a, b in zip(keys, keys[1:]):
        if a.t <= t <= b.t:
            u = 0.0 if b.t == a.t else (t - a.t) / (b.t - a.t)
            return tuple(x + (y - x) * u for x, y in zip(a.value, b.value))
    return keys[-1].value


def _foot_keys(p: GaitParams, leg: float, phase: float, limp: float) -> tuple[list[Key], list[Key]]:
    """한 발의 (위치, 회전) 키. phase 는 이 발이 앞에서 땅에 닿는 시점."""
    # 딛는 구간 이동 거리는 두 발이 같아야 몸 속도와 맞아 미끄러지지 않는다. 절뚝임은 높이·굴림에만 반영한다
    s = p.stride * leg
    h = p.step_height * leg * (1.0 - 0.7 * limp)
    d = p.duty
    swing = 1.0 - d
    roll = p.toe_roll_deg * (1.0 - 0.6 * limp)
    flat = min(0.12, 0.3 * d)
    loc = [
        Key(phase, (0.0, s / 2, 0.0), LINEAR),  # 접지: 앞에서 뒤꿈치로 닿음
        Key(phase + flat, (0.0, s / 2 - s * flat / d, 0.0), LINEAR),  # 발바닥 전체가 닿음
        Key(phase + d, (0.0, -s / 2, 0.0), BEZIER),  # 발끝으로 밀며 떨어짐
        Key(phase + d + 0.45 * swing, (0.0, -0.05 * s, h), BEZIER),  # 발을 가장 높이 듦
        Key(phase + d + 0.85 * swing, (0.0, 0.45 * s, 0.2 * h), BEZIER),  # 다음 접지 준비
    ]
    # 발 굴림 (Rigify foot_heel_ik): +는 발끝을 축으로 뒤꿈치를 들고, -는 뒤꿈치를 축으로 발끝을 든다.
    # 발목을 직접 돌리면 발끝이 바닥을 뚫으므로 굴림 컨트롤을 쓴다
    drag = 0.5 * roll * limp
    rot = [
        Key(phase, (-0.6 * roll,), BEZIER),  # 뒤꿈치로 접지
        Key(phase + flat, (0.0,), BEZIER),
        Key(phase + d, (roll,), BEZIER),  # 발끝으로 밀기
        Key(phase + d + 0.45 * swing, (0.3 * roll + drag,), BEZIER),  # 끄는 다리는 발끝이 처짐
        Key(phase + d + 0.85 * swing, (-0.4 * roll,), BEZIER),
    ]
    return _close(loc), _close(rot)


def generate(p: GaitParams, leg: float, arm: float) -> Motion:
    """키 포즈 채널. 반환 위치 오프셋은 m, 회전은 도."""
    ch: list[Channel] = []
    limp_l = p.limp if p.limp_side == "L" else 0.0
    limp_r = p.limp if p.limp_side == "R" else 0.0
    base_down = -p.crouch * leg
    b = p.bounce * leg
    sw = p.sway * leg

    if p.motion == "IDLE":
        torso_loc = _close([Key(0.0, (sw, 0.0, base_down)), Key(0.25, (0.0, 0.0, base_down - b)),
                            Key(0.5, (-sw, 0.0, base_down)), Key(0.75, (0.0, 0.0, base_down - b))])
        torso_rot = _close([Key(0.0, (p.lean_deg, -0.5 * p.head_bob_deg, 0.0)),
                            Key(0.5, (p.lean_deg + 0.5 * p.head_bob_deg, 0.5 * p.head_bob_deg, 0.0))])
        hips = _close([Key(0.0, (0.0, 0.0, p.hip_yaw_deg)), Key(0.5, (0.0, 0.0, -p.hip_yaw_deg))])
        chest = _close([Key(0.0, (0.0, 0.0, -p.chest_counter_deg)), Key(0.5, (1.5, 0.0, p.chest_counter_deg))])
        head = _close([Key(0.0, (p.head_pitch_deg, p.head_roll_deg, 0.0)),
                       Key(0.35, (p.head_pitch_deg + p.head_bob_deg, p.head_roll_deg - p.head_bob_deg, 0.5 * p.head_bob_deg)),
                       Key(0.7, (p.head_pitch_deg - 0.5 * p.head_bob_deg, p.head_roll_deg + 0.5 * p.head_bob_deg, -p.head_bob_deg))])
        ch += [Channel("torso", "loc", torso_loc), Channel("torso", "rot", torso_rot), Channel("hips", "rot", hips),
               Channel("chest", "rot", chest), Channel("head", "rot", head)]
        for side, ph in (("L", 0.0), ("R", 0.15)):
            ch.append(Channel(f"hand_ik.{side}", "loc", _hand_keys(p, arm, ph, torso_loc, -0.5, side)))
        return Motion(p, ch, 0.0)

    d = p.duty
    run = p.motion == "RUN"
    # 몸통 높이: 걷기는 접지 직후 가장 낮고 다리 교차 후 가장 높다. 달리기는 딛는 중간이 낮고 체공 중간이 높다
    low1, high1 = (0.5 * d, 0.5 * d + 0.25) if run else (0.1, 0.35)
    dip_l, dip_r = 1.0 + 1.5 * limp_l, 1.0 + 1.5 * limp_r  # 끄는 다리로 딛을 때 더 주저앉는다
    torso_loc = _close([
        Key(low1, (0.5 * sw, 0.0, base_down - b * dip_l)),
        Key(high1, (sw, 0.0, base_down + (b if run else 0.4 * b))),
        Key(low1 + 0.5, (-0.5 * sw, 0.0, base_down - b * dip_r)),
        Key(high1 + 0.5, (-sw, 0.0, base_down + (b if run else 0.4 * b))),
    ])
    torso_rot = _close([Key(low1, (p.lean_deg, 0.0, 0.0)), Key(high1, (p.lean_deg + 0.3 * p.head_bob_deg, 0.0, 0.0)),
                        Key(low1 + 0.5, (p.lean_deg, 0.0, 0.0)), Key(high1 + 0.5, (p.lean_deg + 0.3 * p.head_bob_deg, 0.0, 0.0))])
    # 왼발이 앞으로 나올 때(0) 골반 왼쪽이 앞으로 → 오른쪽으로 돎(yaw<0). 가슴은 반대로 비튼다
    hips = _close([Key(0.0, (0.0, 0.0, -p.hip_yaw_deg)), Key(0.5, (0.0, 0.0, p.hip_yaw_deg))])
    chest = _close([Key(0.0, (0.0, 0.0, p.chest_counter_deg)), Key(0.5, (0.0, 0.0, -p.chest_counter_deg))])
    hb = p.head_bob_deg
    head = _close([Key(low1, (p.head_pitch_deg + hb, p.head_roll_deg, 0.0)),
                   Key(high1, (p.head_pitch_deg - 0.5 * hb, p.head_roll_deg + 0.5 * hb, 0.0)),
                   Key(low1 + 0.5, (p.head_pitch_deg + hb, p.head_roll_deg, 0.0)),
                   Key(high1 + 0.5, (p.head_pitch_deg - 0.5 * hb, p.head_roll_deg - 0.5 * hb, 0.0))])
    ch += [Channel("torso", "loc", torso_loc), Channel("torso", "rot", torso_rot), Channel("hips", "rot", hips),
           Channel("chest", "rot", chest), Channel("head", "rot", head)]

    for side, ph, limp in (("L", 0.0, limp_l), ("R", 0.5, limp_r)):
        loc, rot = _foot_keys(p, leg, ph, limp)
        ch += [Channel(f"foot_ik.{side}", "loc", loc), Channel(f"foot_heel_ik.{side}", "roll", rot)]

    # 팔은 반대쪽 다리와 함께 앞으로 나온다 (왼발 앞 = 오른팔 앞)
    for side, ph in (("L", 0.5), ("R", 0.0)):
        ch.append(Channel(f"hand_ik.{side}", "loc", _hand_keys(p, arm, ph, torso_loc, 0.35, side)))

    distance = p.stride * leg / d if p.root_motion else 0.0
    if p.root_motion:
        ch.append(Channel("root", "loc", [Key(0.0, (0.0, 0.0, 0.0), LINEAR), Key(1.0, (0.0, distance, 0.0), LINEAR)]))
    return Motion(p, ch, distance)


def _hand_keys(p: GaitParams, arm: float, ph: float, torso: list[Key], lift: float, side: str) -> list[Key]:
    """팔 흔들기 극점(ph, ph+0.5)과 몸통 키 시점에만 키를 둔다.

    손 IK 는 Root 를 따르므로 몸통 이동을 더해 몸과 함께 움직이게 하고, 같은 시점에 키를 둬야 몸이 들썩일 때
    손이 뒤처지지 않는다. 흔들기는 코사인(ph 에서 가장 앞)이며 앞으로 나올 때 lift 비율만큼 들린다.
    """
    a = p.arm_swing * arm
    fwd, up = p.arm_forward * arm, p.arm_raise * arm
    inward = p.arm_inward * arm * (-1.0 if side == "L" else 1.0)
    times = sorted({round(ph, 6), round(ph + 0.5, 6)} | {round(ph + ((k.t - ph) % 1.0), 6) for k in torso[:-1]})
    keys = []
    for t in times:
        c = cos(2.0 * pi * (t - ph))
        off = (inward, fwd + a * c, up + lift * a * max(c, 0.0))
        keys.append(Key(t, tuple(x + y for x, y in zip(off, sample(torso, t)))))
    return _close(keys)


def facts(m: Motion, fps: int = 24) -> str:
    """검토 AI 에게 줄 실측 요약 (cm·초). 렌더만으로는 작은 동작이 잘 안 보이므로 수치를 함께 준다."""
    def span(bone, kind, axis):
        ch = next((c for c in m.channels if c.bone == bone and c.kind == kind), None)
        if ch is None:
            return 0.0, 0.0
        vals = [k.value[axis] for k in ch.keys]
        return min(vals), max(vals)

    fl_lo, fl_hi = span("foot_ik.L", "loc", 1)
    fr_lo, fr_hi = span("foot_ik.R", "loc", 1)
    _l0, lift_l = span("foot_ik.L", "loc", 2)
    _r0, lift_r = span("foot_ik.R", "loc", 2)
    t_lo, t_hi = span("torso", "loc", 2)
    _hl, reach_l = span("hand_ik.L", "loc", 1)
    _hr, reach_r = span("hand_ik.R", "loc", 1)
    p = m.params
    return (f"cycle {p.cycle_frames / fps:.2f}s ({p.cycle_frames} frames at {fps} fps); "
            f"foot travel L {100 * (fl_hi - fl_lo):.1f} cm, R {100 * (fr_hi - fr_lo):.1f} cm; "
            f"foot lift L {100 * lift_l:.1f} cm, R {100 * lift_r:.1f} cm; body bob {100 * (t_hi - t_lo):.1f} cm; "
            f"hands reach forward L {100 * reach_l:.1f} cm, R {100 * reach_r:.1f} cm")
