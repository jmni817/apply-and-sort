"""서류 합격률 집계. 시트·네트워크와 무관한 순수 함수만 둔다."""

from __future__ import annotations

import unicodedata
from dataclasses import asdict, dataclass
from typing import Callable, Iterable

from .records import Application

SIZE_ORDER = ["대기업", "중견기업", "중소기업", "알수없음"]


@dataclass
class GroupStat:
    name: str
    applied: int = 0  # 지원 건수
    decided: int = 0  # 서류 결과가 나온 건수
    passed: int = 0  # 서류 합격
    waiting: int = 0  # 결과 대기 (빈칸 포함)

    @property
    def rate(self) -> float | None:
        return self.passed / self.decided if self.decided else None

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


def summarize(apps: list[Application]) -> dict:
    """대시보드에 보여줄 묶음별 합격률."""
    overall = group_stats(apps, lambda a: "전체")
    return {
        "overall": overall[0].to_dict() if overall else GroupStat("전체").to_dict(),
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
    for group in summary["groups"]:
        lines.append(f"[{group['title']}]")
        width = max([_width(r["name"]) for r in group["rows"]] + [4])
        for r in group["rows"]:
            name = r["name"] + " " * (width - _width(r["name"]))
            lines.append(
                f"  {name}  {r['passed']:>3}/{r['decided']:<3}  {pct(r['rate']):>6}"
                + (f"  (대기 {r['waiting']})" if r["waiting"] else "")
            )
        lines.append("")
    if summary["unclassified"]:
        lines.append(f"기업규모가 비어 있는 행이 {summary['unclassified']}개 있어요. `apply-and-sort classify` 로 채울 수 있어요.")
    return "\n".join(lines).rstrip()
