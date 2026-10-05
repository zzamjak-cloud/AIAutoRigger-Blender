"""2족 애니메이션 키 포즈 생성 (bpy 비의존): 루프(걷기·달리기·대기·기쁨)와 단발 동작(점프·공격·피격·사망).

매 프레임 키를 찍지 않고 동작의 극점 포즈(접지·낮은 자세·교차·높은 자세 등)에만 키를 둔다.
사이는 베지어(Auto-Clamped)로 보간하고, 발이 땅을 딛는 구간만 선형으로 두어 미끄러짐을 막는다.
루프 동작은 각 채널의 마지막 키를 첫 키의 한 주기 뒤 복제로 닫아 Cycles 모디파이어가 끊김 없이 반복하게 한다.
단발 동작은 t=0 에서 시작해 t=1 에서 끝나며(점프·공격·피격은 레스트로 복귀, 사망은 쓰러진 자세 유지) 반복하지 않는다.

좌표는 캐릭터 기준: 오프셋 (side, forward, up) — side 는 캐릭터 왼쪽, forward 는 정면, up 은 위.
회전 (pitch, roll, yaw) 도(degree): pitch>0 앞으로 숙임(발은 발끝 내림), roll>0 오른쪽으로 기울임, yaw>0 왼쪽으로 돎.
거리 파라미터는 다리 길이(leg) 또는 팔 길이(arm) 대비 비율이다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from math import cos, pi

MOTIONS = ("WALK", "RUN", "IDLE", "HAPPY", "JUMP", "ATTACK", "HIT", "DEATH")
LOOPING = frozenset({"WALK", "RUN", "IDLE", "HAPPY"})  # 나머지는 단발 동작
ROOT_MOTION_OK = frozenset({"WALK", "RUN", "JUMP"})  # 전진이 의미 있는 동작
STYLES = ("NORMAL", "ZOMBIE")
LINEAR = "LINEAR"
BEZIER = "BEZIER"


def is_loop(motion: str) -> bool:
    return motion in LOOPING


@dataclass
class GaitParams:
    motion: str = "WALK"
    cycle_frames: int = 32  # 루프 한 주기 또는 단발 동작 전체 길이 (프레임)
    duty: float = 0.6  # 한 발이 땅에 닿아 있는 주기 비율 (걷기 0.6, 달리기 0.35)
    stride: float = 0.55  # 딛는 동안 발이 몸 기준으로 지나가는 거리 / 다리 길이. 점프·공격·피격은 전진(돌진·밀림) 거리
    step_height: float = 0.12  # 발 들어 올림 / 다리 길이. 기쁨은 깡충 뛰는 높이
    bounce: float = 0.03
    sway: float = 0.03
    crouch: float = 0.02  # 몸통을 낮춰 무릎을 굽힌 정도. 점프·공격·사망은 준비 자세 깊이
    lean_deg: float = 4.0  # 몸통 앞 숙임 (피격은 음수 = 뒤로 젖힘)
    hip_yaw_deg: float = 6.0  # 골반 비틀기. 공격은 몸통 비틀기 각도
    chest_counter_deg: float = 5.0  # 가슴 반대 비틀기. 공격은 가슴 추가 비틀기
    toe_roll_deg: float = 20.0
    arm_swing: float = 0.25  # 팔 흔들기 폭. 기쁨은 팔 펌핑 폭, 피격은 팔 벌림
    arm_forward: float = 0.0  # 손 앞으로 내밀기. 공격은 휘두르는 손이 닿는 거리
    arm_raise: float = 0.0  # 손 들어 올림. 점프·공격(준비)·기쁨·피격·사망의 팔 높이
    arm_inward: float = 0.0  # 손을 몸 중앙 쪽으로 모음 (A-포즈로 벌린 팔을 앞으로 모을 때)
    head_pitch_deg: float = 0.0
    head_roll_deg: float = 0.0
    head_bob_deg: float = 2.0
    limp_side: str = "NONE"  # "L" | "R" | "NONE"
    limp: float = 0.0  # 0~1: 해당 다리를 끌며 덜 들어 올린다
    jump_height: float = 0.35  # 점프 높이 / 다리 길이
    anticipation: float = 0.25  # 단발 동작에서 준비 동작(웅크림·팔 뒤로 빼기·무릎 꺾임)에 쓰는 길이 비율
    attack_side: str = "R"  # 공격하는 손
    fall_dir: str = "BACK"  # 사망 시 쓰러지는 방향 "BACK" | "FRONT"
    root_motion: bool = False

    def to_dict(self):
        return asdict(self)


# 파라미터 허용 범위 (AI 응답 검증·클램프)
RANGES = {
    "cycle_frames": (12, 240), "duty": (0.2, 0.8), "stride": (0.0, 1.2), "step_height": (0.0, 0.4),
    "bounce": (0.0, 0.15), "sway": (0.0, 0.15), "crouch": (0.0, 0.3), "lean_deg": (-45.0, 45.0),
    "hip_yaw_deg": (0.0, 40.0), "chest_counter_deg": (0.0, 40.0), "toe_roll_deg": (0.0, 45.0),
    "arm_swing": (0.0, 0.6), "arm_forward": (0.0, 0.9), "arm_raise": (-0.3, 0.9), "arm_inward": (0.0, 0.6),
    "head_pitch_deg": (-30.0, 45.0), "head_roll_deg": (-30.0, 30.0), "head_bob_deg": (0.0, 15.0),
    "limp": (0.0, 1.0), "jump_height": (0.05, 1.0), "anticipation": (0.05, 0.5),
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
    # 기쁨: 두 팔을 머리 위로 들고 흔들며 두 번 깡충 뛰는 루프
    ("HAPPY", "NORMAL"): dict(cycle_frames=40, stride=0.0, step_height=0.1, bounce=0.05, sway=0.02, crouch=0.04,
                              lean_deg=0.0, hip_yaw_deg=4.0, chest_counter_deg=3.0, arm_swing=0.15, arm_forward=0.2,
                              arm_raise=0.85, arm_inward=0.15, head_pitch_deg=-8.0, head_bob_deg=6.0),
    ("HAPPY", "ZOMBIE"): dict(cycle_frames=56, stride=0.0, step_height=0.04, bounce=0.04, sway=0.05, crouch=0.06,
                              lean_deg=8.0, hip_yaw_deg=5.0, chest_counter_deg=3.0, arm_swing=0.1, arm_forward=0.35,
                              arm_raise=0.6, arm_inward=0.2, head_pitch_deg=4.0, head_roll_deg=12.0, head_bob_deg=8.0),
    # 점프: 웅크림 → 도약 → 체공(무릎 접음) → 착지 주저앉음 → 복귀
    ("JUMP", "NORMAL"): dict(cycle_frames=36, stride=0.6, crouch=0.18, jump_height=0.35, anticipation=0.25, lean_deg=8.0,
                             toe_roll_deg=25.0, arm_swing=0.3, arm_raise=0.6, arm_inward=0.1, head_bob_deg=5.0),
    ("JUMP", "ZOMBIE"): dict(cycle_frames=44, stride=0.4, crouch=0.12, jump_height=0.2, anticipation=0.35, lean_deg=18.0,
                             toe_roll_deg=15.0, arm_swing=0.1, arm_forward=0.5, arm_raise=0.3, arm_inward=0.2,
                             head_pitch_deg=12.0, head_roll_deg=10.0, head_bob_deg=4.0),
    # 공격: 한 손을 뒤로 빼며 몸을 비틀고(준비) 앞으로 돌진하며 휘두른 뒤 복귀
    ("ATTACK", "NORMAL"): dict(cycle_frames=28, stride=0.25, crouch=0.06, anticipation=0.35, lean_deg=12.0, hip_yaw_deg=15.0,
                               chest_counter_deg=20.0, arm_forward=0.8, arm_raise=0.4, arm_inward=0.2, head_bob_deg=4.0),
    ("ATTACK", "ZOMBIE"): dict(cycle_frames=40, stride=0.2, crouch=0.08, anticipation=0.45, lean_deg=20.0, hip_yaw_deg=10.0,
                               chest_counter_deg=12.0, arm_forward=0.7, arm_raise=0.5, arm_inward=0.25, head_pitch_deg=10.0,
                               head_roll_deg=10.0, head_bob_deg=4.0),
    # 피격: 몸통이 뒤로 젖혀지고 밀리며 팔이 벌어졌다가 복귀
    ("HIT", "NORMAL"): dict(cycle_frames=24, stride=0.12, crouch=0.05, anticipation=0.15, lean_deg=-18.0, chest_counter_deg=10.0,
                            arm_swing=0.3, arm_raise=0.35, head_pitch_deg=-20.0, head_bob_deg=0.0),
    ("HIT", "ZOMBIE"): dict(cycle_frames=32, stride=0.15, crouch=0.08, anticipation=0.2, lean_deg=-25.0, chest_counter_deg=8.0,
                            arm_swing=0.2, arm_raise=0.3, arm_forward=0.3, head_pitch_deg=-15.0, head_roll_deg=15.0, head_bob_deg=0.0),
    # 사망: 무릎이 꺾이며 뒤(또는 앞)로 쓰러져 바닥에 눕는다. 끝 자세를 유지
    ("DEATH", "NORMAL"): dict(cycle_frames=48, crouch=0.2, anticipation=0.2, fall_dir="BACK", arm_raise=0.3, arm_swing=0.2,
                              head_pitch_deg=-15.0, head_roll_deg=10.0, head_bob_deg=0.0),
    ("DEATH", "ZOMBIE"): dict(cycle_frames=60, crouch=0.15, anticipation=0.3, fall_dir="FRONT", arm_raise=0.2, arm_swing=0.1,
                              arm_forward=0.4, head_pitch_deg=10.0, head_roll_deg=15.0, head_bob_deg=0.0),
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
        elif f.name == "attack_side":
            out[f.name] = v if v in ("L", "R") else "R"
        elif f.name == "fall_dir":
            out[f.name] = v if v in ("BACK", "FRONT") else "BACK"
        elif f.name == "root_motion":
            out[f.name] = bool(v)
        elif f.name in RANGES and isinstance(v, (int, float)) and not isinstance(v, bool):
            lo, hi = RANGES[f.name]
            v = min(hi, max(lo, v))
            out[f.name] = int(round(v)) if f.name == "cycle_frames" else float(v)
    p = GaitParams(**out)
    if p.motion not in ROOT_MOTION_OK:
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
    root_distance: float  # 전진 거리 (root_motion 일 때, m): 루프는 한 주기, 점프는 한 번

    @property
    def loop(self) -> bool:
        return is_loop(self.params.motion)

    def key_count(self) -> int:
        return sum(len(c.keys) for c in self.channels)


def _close(keys: list[Key]) -> list[Key]:
    """시작 키를 한 주기 뒤에 복제해 루프를 닫는다."""
    keys = sorted(keys, key=lambda k: k.t)
    return keys + [Key(keys[0].t + 1.0, keys[0].value, keys[0].interp)]


def _hold(keys: list[Key]) -> list[Key]:
    """단발 동작: 정렬만 하고 마지막 키(t=1)를 그대로 둔다. 끝 키가 없으면 마지막 값을 t=1 에 복제한다."""
    keys = sorted(keys, key=lambda k: k.t)
    if keys[-1].t < 1.0:
        keys.append(Key(1.0, keys[-1].value, keys[-1].interp))
    return keys


def sample(keys: list[Key], t: float) -> tuple:
    """키 사이 선형 근사 값 (손 위치에 몸통 이동을 더할 때 사용). 키 범위 밖의 t 는 한 주기로 접는다."""
    t0 = keys[0].t
    if not (t0 <= t <= keys[-1].t):
        t = t0 + ((t - t0) % 1.0)
    for a, b in zip(keys, keys[1:]):
        if a.t <= t <= b.t:
            u = 0.0 if b.t == a.t else (t - a.t) / (b.t - a.t)
            return tuple(x + (y - x) * u for x, y in zip(a.value, b.value))
    return keys[-1].value


def _follow(keys: list[Key], torso: list[Key]) -> list[Key]:
    """손 IK 는 Root 를 따르므로 몸통 이동을 더해 몸과 함께 움직이게 한다."""
    return [Key(k.t, tuple(x + y for x, y in zip(k.value, sample(torso, k.t))), k.interp) for k in keys]


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
    builder = _BUILDERS.get(p.motion, _gait)
    return builder(p, leg, arm)


def _idle(p: GaitParams, leg: float, arm: float) -> Motion:
    base_down = -p.crouch * leg
    b = p.bounce * leg
    sw = p.sway * leg
    torso_loc = _close([Key(0.0, (sw, 0.0, base_down)), Key(0.25, (0.0, 0.0, base_down - b)),
                        Key(0.5, (-sw, 0.0, base_down)), Key(0.75, (0.0, 0.0, base_down - b))])
    torso_rot = _close([Key(0.0, (p.lean_deg, -0.5 * p.head_bob_deg, 0.0)),
                        Key(0.5, (p.lean_deg + 0.5 * p.head_bob_deg, 0.5 * p.head_bob_deg, 0.0))])
    hips = _close([Key(0.0, (0.0, 0.0, p.hip_yaw_deg)), Key(0.5, (0.0, 0.0, -p.hip_yaw_deg))])
    chest = _close([Key(0.0, (0.0, 0.0, -p.chest_counter_deg)), Key(0.5, (1.5, 0.0, p.chest_counter_deg))])
    head = _close([Key(0.0, (p.head_pitch_deg, p.head_roll_deg, 0.0)),
                   Key(0.35, (p.head_pitch_deg + p.head_bob_deg, p.head_roll_deg - p.head_bob_deg, 0.5 * p.head_bob_deg)),
                   Key(0.7, (p.head_pitch_deg - 0.5 * p.head_bob_deg, p.head_roll_deg + 0.5 * p.head_bob_deg, -p.head_bob_deg))])
    ch = [Channel("torso", "loc", torso_loc), Channel("torso", "rot", torso_rot), Channel("hips", "rot", hips),
          Channel("chest", "rot", chest), Channel("head", "rot", head)]
    for side, ph in (("L", 0.0), ("R", 0.15)):
        ch.append(Channel(f"hand_ik.{side}", "loc", _hand_keys(p, arm, ph, torso_loc, -0.5, side)))
    return Motion(p, ch, 0.0)


def _gait(p: GaitParams, leg: float, arm: float) -> Motion:
    """걷기·달리기."""
    ch: list[Channel] = []
    limp_l = p.limp if p.limp_side == "L" else 0.0
    limp_r = p.limp if p.limp_side == "R" else 0.0
    base_down = -p.crouch * leg
    b = p.bounce * leg
    sw = p.sway * leg
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


def _inward(p: GaitParams, arm: float, side: str) -> float:
    """손을 몸 중앙 쪽으로 모으는 side 오프셋 (왼손은 -side 로)."""
    return p.arm_inward * arm * (-1.0 if side == "L" else 1.0)


def _happy(p: GaitParams, leg: float, arm: float) -> Motion:
    """기쁨 루프: 두 팔을 들고 흔들며 두 번 깡충 뛴다. 손은 몸통을 따라간다."""
    hop = p.step_height * leg
    b, sw, c = p.bounce * leg, p.sway * leg, p.crouch * leg
    torso_loc = _close([Key(0.0, (0.0, 0.0, -c)), Key(0.15, (sw, 0.0, -c - b)), Key(0.3, (0.0, 0.0, hop)),
                        Key(0.5, (0.0, 0.0, -c)), Key(0.65, (-sw, 0.0, -c - b)), Key(0.8, (0.0, 0.0, hop))])
    torso_rot = _close([Key(0.0, (p.lean_deg, 0.0, 0.0)), Key(0.3, (p.lean_deg - 3.0, 0.0, 0.0)),
                        Key(0.5, (p.lean_deg, 0.0, 0.0)), Key(0.8, (p.lean_deg - 3.0, 0.0, 0.0))])
    hips = _close([Key(0.0, (0.0, 0.0, p.hip_yaw_deg)), Key(0.5, (0.0, 0.0, -p.hip_yaw_deg))])
    chest = _close([Key(0.0, (0.0, 0.5 * p.chest_counter_deg, -p.chest_counter_deg)),
                    Key(0.5, (0.0, -0.5 * p.chest_counter_deg, p.chest_counter_deg))])
    hb = p.head_bob_deg
    head = _close([Key(0.0, (p.head_pitch_deg, p.head_roll_deg + hb, 0.5 * hb)),
                   Key(0.3, (p.head_pitch_deg - 0.5 * hb, p.head_roll_deg, 0.0)),
                   Key(0.5, (p.head_pitch_deg, p.head_roll_deg - hb, -0.5 * hb)),
                   Key(0.8, (p.head_pitch_deg - 0.5 * hb, p.head_roll_deg, 0.0))])
    ch = [Channel("torso", "loc", torso_loc), Channel("torso", "rot", torso_rot), Channel("hips", "rot", hips),
          Channel("chest", "rot", chest), Channel("head", "rot", head)]
    # 발은 깡충 뛸 때만 잠깐(주기의 16%) 땅을 떠나 몸통보다 조금 더 올라간다(무릎을 접음). 나머지는 고정
    if hop > 0.0:
        feet = _close([Key(0.0, (0.0, 0.0, 0.0)), Key(0.22, (0.0, 0.0, 0.0)), Key(0.3, (0.0, 0.0, 1.3 * hop)),
                       Key(0.38, (0.0, 0.0, 0.0)), Key(0.72, (0.0, 0.0, 0.0)), Key(0.8, (0.0, 0.0, 1.3 * hop)),
                       Key(0.88, (0.0, 0.0, 0.0))])
        for side in ("L", "R"):
            ch.append(Channel(f"foot_ik.{side}", "loc", list(feet)))
    # 두 손을 들고 펌핑: 뛰어오를 때 가장 높다
    a = p.arm_swing * arm
    for side in ("L", "R"):
        keys = []
        for t in (0.0, 0.15, 0.3, 0.5, 0.65, 0.8):
            pump = cos(2.0 * pi * (t - 0.3) * 2.0)  # 주기당 두 번
            keys.append(Key(t, (_inward(p, arm, side), p.arm_forward * arm + 0.3 * a * pump, p.arm_raise * arm + a * pump)))
        ch.append(Channel(f"hand_ik.{side}", "loc", _close(_follow(keys, torso_loc))))
    return Motion(p, ch, 0.0)


def _jump(p: GaitParams, leg: float, arm: float) -> Motion:
    """제자리(또는 전진) 점프 단발 동작."""
    a = p.anticipation
    launch = a + 0.06
    land = min(0.85, launch + 0.32)
    apex = 0.5 * (launch + land)
    settle = min(0.95, land + 0.1)
    jh, c = p.jump_height * leg, p.crouch * leg
    tuck = 0.6 * jh  # 체공 중 무릎을 접어 발이 몸통보다 더 올라감
    roll = p.toe_roll_deg
    torso_loc = _hold([Key(0.0, (0.0, 0.0, 0.0)), Key(a, (0.0, 0.0, -c)), Key(launch, (0.0, 0.0, 0.05 * leg)),
                       Key(apex, (0.0, 0.0, jh)), Key(land, (0.0, 0.0, -0.02 * leg)), Key(settle, (0.0, 0.0, -0.8 * c)),
                       Key(1.0, (0.0, 0.0, 0.0))])
    lean = p.lean_deg
    torso_rot = _hold([Key(0.0, (0.0, 0.0, 0.0)), Key(a, (lean, 0.0, 0.0)), Key(launch, (0.5 * lean, 0.0, 0.0)),
                       Key(apex, (-0.3 * lean, 0.0, 0.0)), Key(land, (lean, 0.0, 0.0)), Key(settle, (lean, 0.0, 0.0)),
                       Key(1.0, (0.0, 0.0, 0.0))])
    hb = p.head_bob_deg
    head = _hold([Key(0.0, (p.head_pitch_deg, p.head_roll_deg, 0.0)), Key(a, (p.head_pitch_deg + hb, p.head_roll_deg, 0.0)),
                  Key(apex, (p.head_pitch_deg - hb, p.head_roll_deg, 0.0)), Key(land, (p.head_pitch_deg + hb, p.head_roll_deg, 0.0)),
                  Key(1.0, (p.head_pitch_deg, p.head_roll_deg, 0.0))])
    ch = [Channel("torso", "loc", torso_loc), Channel("torso", "rot", torso_rot), Channel("head", "rot", head)]
    feet = _hold([Key(0.0, (0.0, 0.0, 0.0)), Key(launch, (0.0, 0.0, 0.0)), Key(apex, (0.0, 0.05 * leg, jh + tuck)),
                  Key(land, (0.0, 0.0, 0.0)), Key(1.0, (0.0, 0.0, 0.0))])
    heel = _hold([Key(0.0, (0.0,)), Key(a, (0.0,)), Key(launch, (roll,)), Key(apex, (0.3 * roll,)),
                  Key(land, (0.5 * roll,)), Key(settle, (0.0,)), Key(1.0, (0.0,))])
    for side in ("L", "R"):
        ch += [Channel(f"foot_ik.{side}", "loc", list(feet)), Channel(f"foot_heel_ik.{side}", "roll", list(heel))]
    # 팔: 웅크릴 때 뒤로 뺐다가 도약하며 위로 올리고 착지 때 내린다
    sw, up = p.arm_swing * arm, p.arm_raise * arm
    for side in ("L", "R"):
        inw = _inward(p, arm, side)
        keys = [Key(0.0, (0.0, 0.0, 0.0)), Key(a, (0.0, -sw, -0.1 * arm)), Key(launch, (inw, 0.3 * sw, 0.5 * up)),
                Key(apex, (inw, 0.3 * sw, up)), Key(land, (inw, 0.2 * sw, 0.2 * up)), Key(settle, (0.0, 0.1 * sw, -0.05 * arm)),
                Key(1.0, (0.0, 0.0, 0.0))]
        ch.append(Channel(f"hand_ik.{side}", "loc", _hold(_follow(keys, torso_loc))))
    distance = p.stride * leg if p.root_motion else 0.0
    if p.root_motion:
        ch.append(Channel("root", "loc", [Key(0.0, (0.0, 0.0, 0.0), LINEAR), Key(launch, (0.0, 0.0, 0.0), LINEAR),
                                          Key(land, (0.0, distance, 0.0), LINEAR), Key(1.0, (0.0, distance, 0.0), LINEAR)]))
    return Motion(p, ch, distance)


def _attack(p: GaitParams, leg: float, arm: float) -> Motion:
    """한 손 휘두르기 단발 동작. 준비(손 뒤로·몸 비틀기) → 타격(돌진·반대로 비틀기) → 후속 → 복귀."""
    a = p.anticipation
    strike = min(0.8, a + 0.15)
    follow = min(0.9, strike + 0.12)
    sgn = 1.0 if p.attack_side == "L" else -1.0  # 휘두르는 손이 있는 쪽 (side 축 부호)
    reach, up = p.arm_forward * arm, p.arm_raise * arm
    lunge, c = p.stride * leg, p.crouch * leg
    twist, chest_twist = p.hip_yaw_deg, p.chest_counter_deg
    torso_loc = _hold([Key(0.0, (0.0, 0.0, 0.0)), Key(a, (0.0, -0.08 * leg, -0.5 * c)), Key(strike, (0.0, lunge, -c)),
                       Key(follow, (0.0, lunge, -c)), Key(1.0, (0.0, 0.0, 0.0))])
    # 준비 때 휘두르는 쪽 어깨를 뒤로(그쪽으로 돎), 타격 때 반대로 돈다
    torso_rot = _hold([Key(0.0, (0.0, 0.0, 0.0)), Key(a, (0.3 * p.lean_deg, 0.0, sgn * twist)),
                       Key(strike, (p.lean_deg, 0.0, -sgn * twist)), Key(follow, (p.lean_deg, 0.0, -sgn * 1.2 * twist)),
                       Key(1.0, (0.0, 0.0, 0.0))])
    chest = _hold([Key(0.0, (0.0, 0.0, 0.0)), Key(a, (0.0, 0.0, sgn * chest_twist)), Key(strike, (0.0, 0.0, -sgn * chest_twist)),
                   Key(follow, (0.0, 0.0, -sgn * chest_twist)), Key(1.0, (0.0, 0.0, 0.0))])
    # 머리는 목표를 계속 본다 (몸통 비틀기를 일부 상쇄)
    hb = p.head_bob_deg
    head = _hold([Key(0.0, (p.head_pitch_deg, p.head_roll_deg, 0.0)),
                  Key(a, (p.head_pitch_deg, p.head_roll_deg, -sgn * 0.6 * (twist + chest_twist))),
                  Key(strike, (p.head_pitch_deg + hb, p.head_roll_deg, sgn * 0.6 * (twist + chest_twist))),
                  Key(follow, (p.head_pitch_deg + hb, p.head_roll_deg, sgn * 0.6 * (twist + chest_twist))),
                  Key(1.0, (p.head_pitch_deg, p.head_roll_deg, 0.0))])
    ch = [Channel("torso", "loc", torso_loc), Channel("torso", "rot", torso_rot), Channel("chest", "rot", chest),
          Channel("head", "rot", head)]
    hand = p.attack_side
    other = "L" if hand == "R" else "R"
    inw = _inward(p, arm, hand)
    swing = [Key(0.0, (0.0, 0.0, 0.0)), Key(a, (sgn * 0.15 * arm, -0.35 * arm, up)),
             Key(strike, (inw - sgn * 0.1 * arm, reach, 0.15 * arm)), Key(follow, (inw - sgn * 0.4 * arm, 0.6 * reach, -0.05 * arm)),
             Key(min(0.95, follow + 0.2), (0.0, 0.15 * arm, 0.05 * arm)), Key(1.0, (0.0, 0.0, 0.0))]
    ch.append(Channel(f"hand_ik.{hand}", "loc", _hold(_follow(swing, torso_loc))))
    # 반대 손은 가슴 앞에서 방어 자세
    oin = _inward(p, arm, other)
    guard = [Key(0.0, (0.0, 0.0, 0.0)), Key(a, (oin, 0.35 * arm, 0.3 * arm)), Key(strike, (oin, 0.3 * arm, 0.3 * arm)),
             Key(follow, (oin, 0.3 * arm, 0.3 * arm)), Key(1.0, (0.0, 0.0, 0.0))]
    ch.append(Channel(f"hand_ik.{other}", "loc", _hold(_follow(guard, torso_loc))))
    return Motion(p, ch, 0.0)


def _hit(p: GaitParams, leg: float, arm: float) -> Motion:
    """피격 단발 동작: 충격에 몸통이 뒤로 젖혀지고 밀리며 팔이 벌어졌다가 복귀."""
    impact = p.anticipation
    peak = min(0.6, impact + 0.1)
    recover = min(0.8, peak + 0.25)
    kb, c = p.stride * leg, p.crouch * leg
    lean = p.lean_deg
    torso_loc = _hold([Key(0.0, (0.0, 0.0, 0.0)), Key(impact, (0.0, -0.5 * kb, -0.3 * c)), Key(peak, (0.0, -kb, -c)),
                       Key(recover, (0.0, -0.6 * kb, -0.5 * c)), Key(1.0, (0.0, 0.0, 0.0))])
    torso_rot = _hold([Key(0.0, (0.0, 0.0, 0.0)), Key(impact, (lean, 0.0, 0.0)), Key(peak, (1.2 * lean, 0.0, 0.0)),
                       Key(recover, (0.4 * lean, 0.0, 0.0)), Key(1.0, (0.0, 0.0, 0.0))])
    cc = p.chest_counter_deg
    chest = _hold([Key(0.0, (0.0, 0.0, 0.0)), Key(impact, (-cc, 0.0, 0.0)), Key(peak, (-0.6 * cc, 0.0, 0.0)),
                   Key(1.0, (0.0, 0.0, 0.0))])
    hp, hr = p.head_pitch_deg, p.head_roll_deg
    head = _hold([Key(0.0, (0.0, 0.0, 0.0)), Key(impact, (hp, hr, 0.0)), Key(peak, (0.6 * hp, 0.6 * hr, 0.0)),
                  Key(recover, (0.2 * hp, 0.2 * hr, 0.0)), Key(1.0, (0.0, 0.0, 0.0))])
    ch = [Channel("torso", "loc", torso_loc), Channel("torso", "rot", torso_rot), Channel("chest", "rot", chest),
          Channel("head", "rot", head)]
    # 팔: 충격에 바깥·위로 벌어진다
    out, up, fwd = p.arm_swing * arm, p.arm_raise * arm, p.arm_forward * arm
    for side in ("L", "R"):
        o = 1.0 if side == "L" else -1.0
        keys = [Key(0.0, (0.0, 0.0, 0.0)), Key(impact, (o * out, fwd + 0.2 * arm, up)), Key(peak, (o * 0.8 * out, fwd + 0.1 * arm, 0.6 * up)),
                Key(recover, (o * 0.3 * out, 0.5 * fwd, 0.2 * up)), Key(1.0, (0.0, 0.0, 0.0))]
        ch.append(Channel(f"hand_ik.{side}", "loc", _hold(_follow(keys, torso_loc))))
    return Motion(p, ch, 0.0)


def _death(p: GaitParams, leg: float, arm: float) -> Motion:
    """사망 단발 동작: 무릎이 꺾이며 뒤(BACK) 또는 앞(FRONT)으로 쓰러져 눕고 끝 자세를 유지한다."""
    buckle = p.anticipation
    tip = min(0.6, buckle + 0.25)
    impact = min(0.75, tip + 0.17)
    rebound = min(0.85, impact + 0.08)
    settle = min(0.95, rebound + 0.12)
    d = -1.0 if p.fall_dir == "BACK" else 1.0  # 몸통이 이동·회전하는 forward 부호
    c = p.crouch * leg
    ground = 0.18 * leg  # 누웠을 때 골반 높이 (몸 두께)
    lie = -(1.1 * leg - ground)  # 몸통 레스트 높이(≈ 다리 + 발목)에서 바닥까지
    shift = d * 0.45 * leg  # 쓰러지며 골반이 이동하는 거리
    torso_loc = _hold([Key(0.0, (0.0, 0.0, 0.0)), Key(buckle, (0.0, d * 0.05 * leg, -c)), Key(tip, (0.0, 0.45 * shift, -0.35 * leg)),
                       Key(impact, (0.0, shift, lie + 0.02 * leg)), Key(rebound, (0.0, shift, lie + 0.05 * leg)),
                       Key(settle, (0.0, shift, lie)), Key(1.0, (0.0, shift, lie))])
    torso_rot = _hold([Key(0.0, (0.0, 0.0, 0.0)), Key(buckle, (d * 5.0, 0.0, 0.0)), Key(tip, (d * 45.0, 0.0, 0.0)),
                       Key(impact, (d * 88.0, 0.0, 0.0)), Key(rebound, (d * 84.0, 0.0, 0.0)), Key(settle, (d * 88.0, 0.0, 0.0)),
                       Key(1.0, (d * 88.0, 0.0, 0.0))])
    hp, hr = p.head_pitch_deg, p.head_roll_deg
    if p.fall_dir == "BACK":
        # 뒤로 넘어가며 머리가 먼저 젖혀지고(hp<0), 바닥에 닿은 뒤 옆으로 기운다
        head = _hold([Key(0.0, (0.0, 0.0, 0.0)), Key(tip, (hp, 0.0, 0.0)), Key(impact, (0.4 * abs(hp), 0.0, 0.0)),
                      Key(settle, (0.2 * hp, hr, 0.5 * hr)), Key(1.0, (0.2 * hp, hr, 0.5 * hr))])
    else:
        # 앞으로 엎어지며 얼굴이 바닥에 박히지 않게 고개를 옆으로 돌린다
        head = _hold([Key(0.0, (0.0, 0.0, 0.0)), Key(tip, (hp, 0.0, 0.0)), Key(impact, (-0.5 * abs(hp), 0.3 * hr, 40.0)),
                      Key(settle, (-0.3 * abs(hp), hr, 70.0)), Key(1.0, (-0.3 * abs(hp), hr, 70.0))])
    ch = [Channel("torso", "loc", torso_loc), Channel("torso", "rot", torso_rot), Channel("head", "rot", head)]
    # 발: 누우면 다리가 펴지도록 골반 반대쪽으로 밀리고, 발끝이 위(BACK)/아래(FRONT)를 향한다.
    # 엎어질 때는 IK 무릎이 바닥 쪽으로 꺾이므로 다리가 완전히 펴지는 거리까지 밀어 무릎 관통을 막는다
    reach, lift, toe = (0.4 * leg, 0.06 * leg, 65.0) if d < 0 else (0.55 * leg, 0.1 * leg, 50.0)
    feet = _hold([Key(0.0, (0.0, 0.0, 0.0)), Key(buckle, (0.0, 0.0, 0.0)), Key(tip, (0.0, -d * 0.15 * leg, 0.02 * leg)),
                  Key(impact, (0.0, -d * reach, lift + 0.02 * leg)), Key(settle, (0.0, -d * reach, lift)),
                  Key(1.0, (0.0, -d * reach, lift))])
    foot_rot = _hold([Key(0.0, (0.0, 0.0, 0.0)), Key(buckle, (0.0, 0.0, 0.0)), Key(tip, (d * 20.0, 0.0, 0.0)),
                      Key(impact, (d * toe, 0.0, 0.0)), Key(1.0, (d * toe, 0.0, 0.0))])
    for side in ("L", "R"):
        ch += [Channel(f"foot_ik.{side}", "loc", list(feet)), Channel(f"foot_ik.{side}", "rot", list(foot_rot))]
    # 손: 쓰러지며 허우적대다가 어깨 옆 바닥에 떨어진다 (몸통 이동을 따르지 않고 절대 위치로 둔다)
    up, out, fwd = p.arm_raise * arm, p.arm_swing * arm, p.arm_forward * arm
    hand_down = -(1.0 * leg - 0.06 * leg)  # 손 레스트 높이(≈ 골반)에서 바닥까지
    for side in ("L", "R"):
        o = 1.0 if side == "L" else -1.0
        rest_side = o * 0.35 * arm
        final = (rest_side, d * 0.95 * leg if d > 0 else d * 0.8 * leg, hand_down)
        flail = (o * 0.1 * arm, 0.4 * arm + fwd, up) if d < 0 else (o * 0.1 * arm, 0.5 * arm + fwd, 0.2 * arm)
        keys = [Key(0.0, (0.0, 0.0, 0.0)), Key(buckle, (0.0, 0.1 * arm, 0.1 * arm)), Key(tip, flail),
                Key(impact, (final[0], final[1], final[2] + 0.04 * leg)), Key(settle, final), Key(1.0, final)]
        ch.append(Channel(f"hand_ik.{side}", "loc", _hold(keys)))
    return Motion(p, ch, 0.0)


_BUILDERS = {"WALK": _gait, "RUN": _gait, "IDLE": _idle, "HAPPY": _happy, "JUMP": _jump, "ATTACK": _attack,
             "HIT": _hit, "DEATH": _death}


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
    _ul, raise_l = span("hand_ik.L", "loc", 2)
    _ur, raise_r = span("hand_ik.R", "loc", 2)
    p = m.params
    kind = "cycle" if m.loop else "clip"
    return (f"{kind} {p.cycle_frames / fps:.2f}s ({p.cycle_frames} frames at {fps} fps, {'looping' if m.loop else 'one-shot'}); "
            f"foot travel L {100 * (fl_hi - fl_lo):.1f} cm, R {100 * (fr_hi - fr_lo):.1f} cm; "
            f"foot lift L {100 * lift_l:.1f} cm, R {100 * lift_r:.1f} cm; body vertical range {100 * (t_hi - t_lo):.1f} cm "
            f"(lowest {100 * t_lo:.1f} cm from rest); hands reach forward L {100 * reach_l:.1f} cm, R {100 * reach_r:.1f} cm; "
            f"hands raised L {100 * raise_l:.1f} cm, R {100 * raise_r:.1f} cm")
