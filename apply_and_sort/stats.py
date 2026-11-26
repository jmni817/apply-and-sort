"""서류·전형별 합격률 집계. 시트·네트워크와 무관한 순수 함수만 둔다."""

from __future__ import annotations

import unicodedata
from dataclasses import asdict, dataclass
from typing import Callable, Iterable

from .records import STAGE_KEYS, Application, StageStatus

SIZE_ORDER = ["대기업", "중견기업", "중소기업", "알수없음"]
DEFAULT_STAGE_TITLES = {
    "document": "서류",
    "aptitude": "인적성/AI/과제",
    "interview1": "1차면접",
    "interview2": "2차면접",
    "final": "최종 결과",
}


@dataclass
class StageStat:
    key: str  # columns 의 키 (document, aptitude, ...)
    title: str  # 시트 헤더 이름
    passed: int = 0
    failed: int = 0
    pending: int = 0  # 결과 대기·진행중
    dropped: int = 0  # 전형 포기
    skipped: int = 0  # 해당없음 (그 공고에 없는 단계)
    not_reached: int = 0  # 미진행 (아직 도달하지 않음)
    column_missing: bool = False  # 시트에 이 전형 열이 없음

    @property
    def decided(self) -> int:
        return self.passed + self.failed

    @property
    def reached(self) -> int:
        """이 전형에 실제로 들어선 건수 (합격·불합격·대기·포기)."""
        return self.decided + self.pending + self.dropped

    @property
    def base(self) -> int:
        """합격률 분모. 서류는 전체 지원, 그 뒤 전형은 합격+불합격+진행중(대기)."""
        if self.key == "document":
            return self.passed + self.failed + self.pending + self.dropped + self.skipped + self.not_reached
        return self.decided + self.pending

    @property
    def rate(self) -> float | None:
        return self.passed / self.base if self.base else None

    def to_dict(self) -> dict:
        return {**asdict(self), "decided": self.decided, "reached": self.reached, "base": self.base, "rate": self.rate}


_STAGE_FIELD = {
    StageStatus.PASS: "passed",
    StageStatus.FAIL: "failed",
    StageStatus.PENDING: "pending",
    StageStatus.DROPPED: "dropped",
    StageStatus.SKIPPED: "skipped",
    StageStatus.NOT_REACHED: "not_reached",
}


def stage_stats(apps: Iterable[Application], columns: dict[str, str] | None = None) -> list[StageStat]:
    """전형별 합격/불합격/대기/포기/해당없음/미진행 수와 합격률 (서류: 합격 ÷ 전체 지원, 그 뒤: 합격 ÷ (합격+불합격+진행중))."""
    apps = list(apps)
    titles = {**DEFAULT_STAGE_TITLES, **{k: v for k, v in (columns or {}).items() if k in STAGE_KEYS}}
    result = []
    for key in STAGE_KEYS:
        stat = StageStat(key, titles[key])
        present = [app.stages[key] for app in apps if key in app.stages]
        stat.column_missing = bool(apps) and not present
        for status in present:
            setattr(stat, _STAGE_FIELD[status], getattr(stat, _STAGE_FIELD[status]) + 1)
        result.append(stat)
    return result


@dataclass
class GroupStat:
    name: str
    applied: int = 0  # 지원 건수
    decided: int = 0  # 서류 결과가 나온 건수
    passed: int = 0  # 서류 합격
    waiting: int = 0  # 결과 대기 (빈칸 포함)

    @property
    def rate(self) -> float | None:
        """서류 합격률 = 서류 합격 ÷ 전체 지원 (결과 대기도 분모에 들어감)."""
        return self.passed / self.applied if self.applied else None

    def to_dict(self) -> dict:
        return {**asdict(self), "rate": self.rate}


def group_stats(
    apps: Iterable[Application],
    key: Callable[[Application], str | None],
    *,
    order: list[str] | None = None,
) -> list[GroupStat]:
    """key 값이 같은 기록끼리 묶어 합격률을 센다. key 가 None 이면 제외."""
    groups: dict[str, GroupStat] = {}
    for app in apps:
        name = key(app)
        if name is None:
            continue
        stat = groups.setdefault(name, GroupStat(name))
        stat.applied += 1
        if app.document_decided:
            stat.decided += 1
            stat.passed += app.document_passed
        else:
            stat.waiting += 1
    rank = {name: i for i, name in enumerate(order or [])}
    return sorted(groups.values(), key=lambda s: (rank.get(s.name, len(rank)), -s.applied, s.name))


def _or(value: str, empty: str) -> str:
    return value or empty


def summarize(apps: list[Application], columns: dict[str, str] | None = None) -> dict:
    """대시보드에 보여줄 묶음별 서류 합격률과 전형별 합격률."""
    overall = group_stats(apps, lambda a: "전체")
    return {
        "overall": overall[0].to_dict() if overall else GroupStat("전체").to_dict(),
        "stages": [s.to_dict() for s in stage_stats(apps, columns)],
        "groups": [
            {"title": "지원형태별", "rows": [s.to_dict() for s in group_stats(apps, lambda a: _or(a.channel, "(빈칸)"))]},
            {
                "title": "기업규모별",
                "rows": [s.to_dict() for s in group_stats(apps, lambda a: _or(a.size, "(미분류)"), order=SIZE_ORDER)],
            },
            {
                "title": "기업규모별 · 인턴만",
                "rows": [
                    s.to_dict()
                    for s in group_stats(
                        apps, lambda a: _or(a.size, "(미분류)") if a.is_intern else None, order=SIZE_ORDER
                    )
                ],
            },
            {"title": "고용형태별", "rows": [s.to_dict() for s in group_stats(apps, lambda a: _or(a.employment, "(빈칸)"))]},
        ],
        "unclassified": sum(1 for a in apps if not a.size),
    }


def _width(text: str) -> int:
    """터미널에서 차지하는 칸 수. 한글처럼 넓은 글자는 2칸."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def format_summary(summary: dict) -> str:
    """터미널 출력용 표."""

    def pct(rate: float | None) -> str:
        return "-" if rate is None else f"{rate * 100:.1f}%"

    o = summary["overall"]
    lines = [f"전체: 지원 {o['applied']}건 · 결과 {o['decided']}건 · 서류 합격 {o['passed']}건 ({pct(o['rate'])})", ""]
    if summary.get("stages"):
        lines.append("[전형별 합격률]  합격/지원  합격률  (대기·포기·해당없음·미진행)")
        width = max(_width(s["title"]) for s in summary["stages"])
        for s in summary["stages"]:
            title = s["title"] + " " * (width - _width(s["title"]))
            if s["column_missing"]:
                lines.append(f"  {title}  (시트에 열 없음)")
                continue
            extra = [f"{label} {s[k]}" for k, label in
                     (("pending", "대기"), ("dropped", "포기"), ("skipped", "해당없음"), ("not_reached", "미진행")) if s[k]]
            lines.append(
                f"  {title}  {s['passed']:>3}/{s['base']:<3}  {pct(s['rate']):>6}"
                + (f"  ({' · '.join(extra)})" if extra else "")
            )
        lines.append("")
        lines.append("[서류 합격률 · 기준별]")
    for group in summary["groups"]:
        lines.append(f"[{group['title']}]")
        width = max([_width(r["name"]) for r in group["rows"]] + [4])
        for r in group["rows"]:
            name = r["name"] + " " * (width - _width(r["name"]))
            lines.append(
                f"  {name}  {r['passed']:>3}/{r['applied']:<3}  {pct(r['rate']):>6}"
                + (f"  (대기 {r['waiting']})" if r["waiting"] else "")
            )
        lines.append("")
    if summary["unclassified"]:
        lines.append(f"기업규모가 비어 있는 행이 {summary['unclassified']}개 있어요. `apply-and-sort classify` 로 채울 수 있어요.")
    return "\n".join(lines).rstrip()
