"""월별 취준기록 리포트. 지원일 기준으로 지원 기록을 달마다 묶는다. (시트·네트워크와 무관한 순수 함수)"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from .records import STAGE_KEYS, Application, StageStatus
from .stats import DEFAULT_STAGE_TITLES

INTERVIEW_KEYS = ("interview1", "interview2")
_KIND = {
    StageStatus.PASS: "pass",
    StageStatus.FAIL: "fail",
    StageStatus.PENDING: "pending",
    StageStatus.DROPPED: "dropped",
}
_WORD = {StageStatus.PASS: "합격", StageStatus.FAIL: "불합격", StageStatus.PENDING: "대기", StageStatus.DROPPED: "포기"}


def month_label(year: int, month: int) -> str:
    """(2026, 11) → '26년 11월'"""
    return f"{year % 100:02d}년 {month}월"


def current_stage(app: Application, titles: dict[str, str] | None = None) -> tuple[str, str]:
    """지원 한 건이 지금 어느 전형에 있는지. ('1차면접 대기', 'pending') 처럼 (문구, 종류)를 돌려준다.

    기록이 있는 마지막 전형을 본다. 최종 결과까지 합격이면 '최종 합격'.
    """
    titles = {**DEFAULT_STAGE_TITLES, **(titles or {})}
    last_key, last_status = None, None
    for key in STAGE_KEYS:
        status = app.stages.get(key)
        if status in _KIND:
            last_key, last_status = key, status
    if last_key is None:
        return f"{titles['document']} 대기", "pending"
    if last_key == "final" and last_status == StageStatus.PASS:
        return "최종 합격", "pass"
    return f"{titles[last_key]} {_WORD[last_status]}", _KIND[last_status]


@dataclass
class MonthReport:
    year: int
    month: int
    apps: list[Application] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    def to_dict(self, titles: dict[str, str], overall_rate: float | None) -> dict:
        apps = sorted(self.apps, key=lambda a: (a.applied, a.row), reverse=True)  # 최근 지원이 위로
        decided = sum(1 for a in apps if a.document_decided)
        passed = sum(1 for a in apps if a.document_passed)
        rate = passed / decided if decided else None
        interviews = sum(1 for a in apps for k in INTERVIEW_KEYS if a.stages.get(k) in (StageStatus.PASS, StageStatus.FAIL, StageStatus.PENDING))
        final_passed = sum(1 for a in apps if a.stages.get("final") == StageStatus.PASS)
        rows = []
        for app in apps:
            label, kind = current_stage(app, titles)
            rows.append(
                {
                    "channel": app.channel,
                    "company": app.company,
                    "role": app.role,
                    "applied": app.applied_raw or app.applied.isoformat(),
                    "stage": label,
                    "kind": kind,
                }
            )
        return {
            "key": self.key,
            "label": month_label(self.year, self.month),
            "applied": len(apps),
            "document": {"decided": decided, "passed": passed, "waiting": len(apps) - decided, "rate": rate},
            "interviews": interviews,
            "final_passed": final_passed,
            "apps": rows,
            "insights": _insights(apps, decided, passed, rate, overall_rate),
            "notes": [{"company": a.company, "note": a.note} for a in apps if a.note],
        }


def _pct(rate: float) -> str:
    return f"{rate * 100:.1f}%"


def _insights(apps: list[Application], decided: int, passed: int, rate: float | None, overall: float | None) -> list[str]:
    """그 달 기록에서 바로 읽을 수 있는 사실만 짧게. (추측·AI 없음)"""
    lines = []
    if rate is not None:
        line = f"서류 결과가 나온 {decided}건 중 {passed}건 합격했어요 ({_pct(rate)})."
        if overall is not None and decided >= 3:
            if abs(rate - overall) < 0.005:
                line += f" 전체 평균({_pct(overall)})과 같아요."
            else:
                line += f" 전체 평균({_pct(overall)})보다 {'높아요' if rate > overall else '낮아요'}."
        lines.append(line)
    waiting = len(apps) - decided
    if waiting:
        lines.append(f"서류 결과를 기다리는 곳이 {waiting}곳 있어요.")
    reached = [a.company for a in apps if any(a.stages.get(k) in _KIND for k in INTERVIEW_KEYS)]
    if reached:
        names = ", ".join(reached[:5]) + (f" 외 {len(reached) - 5}곳" if len(reached) > 5 else "")
        lines.append(f"면접까지 간 곳: {names}")
    channels = Counter(a.channel for a in apps if a.channel)
    top = channels.most_common(2)
    if len(top) == 2 and top[0][1] > top[1][1]:  # 동점이면 '가장 많았다'고 하지 않음
        name, count = top[0]
        lines.append(f"'{name}' 지원이 {count}건으로 가장 많았어요.")
    dropped = sum(1 for a in apps if any(s == StageStatus.DROPPED for s in a.stages.values()))
    if dropped:
        lines.append(f"전형을 포기한 곳이 {dropped}곳 있어요.")
    return lines


def monthly_reports(
    apps: Iterable[Application], columns: dict[str, str] | None = None, overall_rate: float | None = None
) -> dict:
    """{'months': [최신 달부터 리포트...], 'undated': 지원일이 없거나 읽을 수 없는 건수}. 기록 없는 달은 없다."""
    titles = {k: v for k, v in (columns or {}).items() if k in STAGE_KEYS}
    months: dict[tuple[int, int], MonthReport] = {}
    undated = 0
    for app in apps:
        if app.applied is None:
            undated += 1
            continue
        ym = (app.applied.year, app.applied.month)
        months.setdefault(ym, MonthReport(*ym)).apps.append(app)
    ordered = sorted(months.values(), key=lambda m: (m.year, m.month), reverse=True)
    return {"months": [m.to_dict(titles, overall_rate) for m in ordered], "undated": undated}
