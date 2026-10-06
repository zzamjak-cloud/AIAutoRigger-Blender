"""손 모양(손가락 굽힘) 정의 (bpy 비의존).

손 모양은 손가락별 굽힘 정도(0 = 쭉 편 손, 1 = 주먹)로 나타낸다. 브리지가 Rigify 손가락 마디 컨트롤 세 개를
각각 손바닥 쪽으로 굽힘 × 최대 각도만큼 돌린다(관절마다 같은 각도, 부모를 따라 누적되어 말린다).
손가락이 없는 리그(벙어리장갑·상자형 손)는 무시되고, 감지된 손가락만 쓴다.
"""

from __future__ import annotations

# 손 모양을 정의하는 손가락 순서 (Rigify 손가락 이름)
FINGERS = ("thumb", "f_index", "f_middle", "f_ring", "f_pinky")
# 굽힘 1.0 의 관절당 회전 각도(도). 엄지는 손바닥을 가로질러 덮으므로 작게 둔다
MAX_CURL_DEG = {"thumb": 55.0, "f_index": 80.0, "f_middle": 80.0, "f_ring": 80.0, "f_pinky": 80.0}

SHAPES = {
    "OPEN": (0.0, 0.0, 0.0, 0.0, 0.0),  # 쭉 편 손 (손 흔들기·박수·놀람)
    "RELAXED": (0.15, 0.2, 0.27, 0.34, 0.42),  # 힘을 뺀 손: 새끼손가락 쪽으로 갈수록 더 굽는다
    "LOOSE_FIST": (0.35, 0.55, 0.62, 0.68, 0.74),  # 가볍게 쥔 손 (달리기·준비 자세)
    "FIST": (0.6, 1.0, 1.0, 1.0, 1.0),  # 주먹 (펀치·방어)
    "GRIP": (0.5, 0.78, 0.82, 0.86, 0.9),  # 손잡이를 쥔 손 (칼·도끼·단검)
    "POINT": (0.55, 0.0, 1.0, 1.0, 1.0),  # 검지로 가리키기
    "CLAW": (0.25, 0.5, 0.5, 0.5, 0.5),  # 좀비 갈퀴 손: 손가락 마디를 반쯤 굽혀 벌림
}
DEFAULT = "RELAXED"


def curls(shape: str) -> tuple:
    """손 모양 이름 → 손가락별 굽힘. 모르는 이름은 RELAXED."""
    return SHAPES.get(shape, SHAPES[DEFAULT])


def nearest(values: tuple) -> str:
    """손가락별 굽힘 → 가장 가까운 손 모양 이름 (애니메이션을 클립으로 저장할 때)."""
    return min(SHAPES, key=lambda s: sum((a - b) ** 2 for a, b in zip(SHAPES[s], values)))


def normalize(name) -> str | None:
    """AI 응답·사전 값 → 손 모양 이름. 모르는 값은 None."""
    if not isinstance(name, str):
        return None
    name = name.strip().upper()
    return name if name in SHAPES else None
