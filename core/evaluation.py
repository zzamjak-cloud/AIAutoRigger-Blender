"""평가 하네스 공용 로직 (bpy 비의존): 정답 리그 본 이름 → 표준 관절 매핑, 오차 집계.

정답 리그는 출처마다 본 이름 규칙이 다르므로(Mixamo, Unity, Blender, Rigify, Quaternius 등)
이름을 정규화한 뒤 좌우·부위 키워드로 표준 관절명에 매핑한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from math import dist
from statistics import mean, median
from typing import Iterable

# (관절명, 부위 키워드 정규식, 본의 head/tail 중 관절 위치) — 위에서부터 먼저 일치한 규칙 사용
BIPED_RULES = (
    ("hip", r"(thigh|upleg|upperleg|hip(?!s))", "head"),
    ("knee", r"(calf|shin|lowerleg|knee|(?<!up)leg$)", "head"),
    ("ankle", r"(foot|ankle)", "head"),
    ("elbow", r"(forearm|lowerarm|elbow)", "head"),
    ("shoulder", r"(upperarm|uparm|(?<!fore)arm$)", "head"),
    ("wrist", r"(hand|wrist)", "head"),
)
QUADRUPED_RULES = (
    # 앞다리는 front/fore 접두가 붙은 다리 이름이거나 팔 계열 이름
    ("f_elbow", r"((front|fore)\w*(shin|calf|lowerleg)|forearm|lowerarm)", "head"),
    ("f_shoulder", r"((front|fore)\w*(thigh|upperleg|upleg)|upperarm|uparm|(?<!fore)arm$)", "head"),
    ("f_wrist", r"((front|fore)\w*foot|hand|wrist)", "head"),
    ("r_hip", r"(back|hind|rear)?\w*(thigh|upperleg|upleg)", "head"),
    ("r_knee", r"(back|hind|rear)?\w*(shin|calf|lowerleg)", "head"),
    ("r_hock", r"(back|hind|rear)?\w*(foot|ankle)", "head"),
)
CENTER_RULES = (("head_base", r"^head$", "head"),)

_PREFIX = re.compile(r"^(mixamorig\d*:|def-|org-|bip0?1[ _]?|b_|bn_|j_|jnt_)")
_SIDE_PATTERNS = (
    (re.compile(r"([._ -]l$|^l[._ -]|left)"), "L"),
    (re.compile(r"([._ -]r$|^r[._ -]|right)"), "R"),
)
# 꼬리, 손가락, 발가락, 얼굴, 보조 본은 제외
_IGNORE = re.compile(r"(tail|finger|thumb|index|middle|ring|pinky|toe|eye|jaw|(?<!for)ear|twist|roll|ik|pole|ctrl|target|end$|nub$|\.0\d\d$)")


def normalize(name: str) -> tuple[str, str | None]:
    """(부위 문자열, 좌우 'L'/'R'/None)."""
    n = name.strip().lower()
    n = _PREFIX.sub("", n)
    side = None
    for pattern, s in _SIDE_PATTERNS:
        if pattern.search(n):
            side = s
            n = pattern.sub("", n)
            break
    n = re.sub(r"[^a-z0-9]", "", n)
    return n, side


def map_bones(bones: Iterable[tuple[str, tuple, tuple]], kind: str) -> dict[str, tuple]:
    """(본 이름, head, tail) 목록 → {표준 관절명: 좌표}. 같은 관절에 여러 본이 맞으면 첫 본을 쓴다."""
    rules = (QUADRUPED_RULES if kind == "QUADRUPED" else BIPED_RULES)
    out: dict[str, tuple] = {}
    for name, head, tail in bones:
        if _IGNORE.search(name.lower()):
            continue
        part, side = normalize(name)
        if side is None:
            for joint, pattern, end in CENTER_RULES:
                if joint not in out and re.search(pattern, part):
                    out[joint] = tuple(head if end == "head" else tail)
            continue
        for joint, pattern, end in rules:
            if re.search(pattern, part):
                key = f"{joint}_{side}"
                if key not in out:
                    out[key] = tuple(head if end == "head" else tail)
                break
    return out


@dataclass
class CaseResult:
    name: str
    category: str
    kind: str = ""
    ok: bool = False
    error: str = ""
    joint_errors: dict[str, float] = field(default_factory=dict)
    unweighted_ratio: float = 0.0
    rest_displacement: float = 0.0
    seconds: float = 0.0

    @property
    def mean_error(self) -> float | None:
        return mean(self.joint_errors.values()) if self.joint_errors else None


def joint_errors(estimated: dict[str, tuple], truth: dict[str, tuple], size: float) -> dict[str, float]:
    """정답에 있는 관절만 크기 대비 거리 오차로 비교한다."""
    return {k: dist(estimated[k], v) / size for k, v in truth.items() if k in estimated}


def summarize(results: list[CaseResult]) -> dict:
    by_cat: dict[str, list[CaseResult]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r)
    summary = {}
    for cat, rs in sorted(by_cat.items()):
        errs = [r.mean_error for r in rs if r.ok and r.mean_error is not None]
        summary[cat] = {
            "cases": len(rs),
            "success": sum(r.ok for r in rs),
            "mean_joint_error": mean(errs) if errs else None,
            "median_joint_error": median(errs) if errs else None,
            "max_joint_error": max((max(r.joint_errors.values()) for r in rs if r.ok and r.joint_errors), default=None),
            "mean_unweighted_ratio": mean(r.unweighted_ratio for r in rs if r.ok) if any(r.ok for r in rs) else None,
        }
    return summary


def to_markdown(results: list[CaseResult], summary: dict) -> str:
    def f(v):
        return "-" if v is None else f"{v:.3f}"

    lines = [
        "# 자동 리깅 평가 리포트",
        "",
        "오차는 모델 크기(높이·길이 중 최대) 대비 관절 거리.",
        "",
        "| 범주 | 케이스 | 성공 | 평균 오차 | 중앙값 | 최대 | 무가중 정점 비율 |",
        "|---|---|---|---|---|---|---|",
    ]
    for cat, s in summary.items():
        lines.append(
            f"| {cat} | {s['cases']} | {s['success']} | {f(s['mean_joint_error'])} | "
            f"{f(s['median_joint_error'])} | {f(s['max_joint_error'])} | {f(s['mean_unweighted_ratio'])} |"
        )
    lines += ["", "## 케이스", "", "| 범주 | 이름 | 체형 | 결과 | 평균 오차 | 최악 관절 | 초 |", "|---|---|---|---|---|---|---|"]
    for r in results:
        worst = max(r.joint_errors.items(), key=lambda e: e[1]) if r.joint_errors else None
        worst_s = f"{worst[0]} {worst[1]:.3f}" if worst else "-"
        status = "OK" if r.ok else f"실패: {r.error}"
        lines.append(f"| {r.category} | {r.name} | {r.kind} | {status} | {f(r.mean_error)} | {worst_s} | {r.seconds:.1f} |")
    return "\n".join(lines) + "\n"
