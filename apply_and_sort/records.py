"""시트의 행을 지원 기록(Application)으로 바꾸기."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any

PASS, FAIL = "합격", "불합격"

# 전형 순서 (columns 의 키). 서류 → 인적성/AI/과제 → 1차면접 → 2차면접 → 최종 결과
STAGE_KEYS = ["document", "aptitude", "interview1", "interview2", "final"]

# 전형 칸 값 판정 키워드 (공백 제거·소문자 후 '포함'으로 비교, 위에서부터 먼저 맞는 것)
DEFAULT_STAGE_VALUES: dict[str, list[str]] = {
    "not_applicable": ["-", "해당없음", "해당 없음", "없음", "n/a", "na", "x"],  # 이 칸과 정확히 같을 때만
    "fail": ["불합격", "탈락"],
    "dropped": ["포기", "불참", "미응시"],
    "pending": ["예비", "대기", "진행", "보류"],
    "pass": ["합격", "통과"],
}


class StageStatus(str, Enum):
    PASS = "합격"
    FAIL = "불합격"
    PENDING = "대기"  # 결과가 아직 확정되지 않음 (진행중·결과 대기중·예비합격 등)
    DROPPED = "포기"  # 지원자가 전형을 포기 (합격률 계산에서 제외)
    SKIPPED = "해당없음"  # 그 공고에 없는 단계 ('-' 같은 표시, 또는 빈칸인데 뒤 전형 기록이 있음)
    NOT_REACHED = "미진행"  # 빈칸이고 뒤 전형 기록도 없음 (아직 도달하지 않음)

    @property
    def decided(self) -> bool:
        return self in (StageStatus.PASS, StageStatus.FAIL)


def _norm(value: str) -> str:
    return "".join(value.split()).lower()


def classify_stage_value(value: str, stage_values: dict[str, list[str]] | None = None) -> StageStatus | None:
    """전형 칸 값 하나를 해석한다. 빈칸이면 None (앞뒤 전형을 보고 resolve_stages 가 정한다)."""
    rules = {**DEFAULT_STAGE_VALUES, **(stage_values or {})}
    text = _norm(value)
    if not text:
        return None
    if text in {_norm(v) for v in rules["not_applicable"]}:
        return StageStatus.SKIPPED
    for key, status in (
        ("fail", StageStatus.FAIL),
        ("dropped", StageStatus.DROPPED),
        ("pending", StageStatus.PENDING),
        ("pass", StageStatus.PASS),
    ):
        if any(_norm(word) in text for word in rules[key]):
            return status
    return StageStatus.PENDING  # 모르는 표기는 '아직 확정 안 됨'으로 본다


def resolve_stages(raw: list[StageStatus | None]) -> list[StageStatus]:
    """빈칸(None)을 앞뒤 맥락으로 정한다.

    - 뒤 전형에 기록이 있으면 → 해당없음 (예: 인적성 없이 바로 1차면접을 본 공고)
    - 뒤 전형에도 기록이 없으면 → 미진행 (아직 그 단계에 도달하지 않음)
    """
    resolved = []
    for i, status in enumerate(raw):
        if status is None:
            later = any(s is not None and s != StageStatus.SKIPPED for s in raw[i + 1 :])
            status = StageStatus.SKIPPED if later else StageStatus.NOT_REACHED
        resolved.append(status)
    return resolved


_DATE_RE = re.compile(r"^\s*(\d{4}|\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})")


def parse_date(value: str) -> date | None:
    """지원일 칸을 날짜로. 26-11-01, 2026-11-01, 2026.11.01, 2026. 11. 1., 26년 11월 1일 등을 읽고, 아니면 None."""
    match = _DATE_RE.match(str(value or ""))
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:  # 2026-13-40 같은 잘못된 날짜
        return None


class SheetFormatError(Exception):
    """데이터 시트에 꼭 필요한 열이 없음."""


@dataclass
class Application:
    row: int  # 시트의 실제 행 번호 (헤더가 1행)
    company: str
    role: str = ""
    channel: str = ""  # 지원형태 (간편/일반 등)
    employment: str = ""  # 고용형태
    document: str = ""  # 서류 결과
    size: str = ""  # 기업규모
    stages: dict[str, StageStatus] = field(default_factory=dict)  # 전형별 상태 (STAGE_KEYS 순서)
    applied_raw: str = ""  # 지원일 칸에 적힌 그대로
    applied: date | None = None  # 읽을 수 있는 날짜일 때만
    note: str = ""  # 비고

    @property
    def is_intern(self) -> bool:
        return "인턴" in self.employment

    @property
    def document_decided(self) -> bool:
        return self.document in (PASS, FAIL)

    @property
    def document_passed(self) -> bool:
        return self.document == PASS


def header_index(header: list[str], columns: dict[str, str]) -> dict[str, int]:
    """{필드 이름: 열 번호}. 회사·서류 열은 반드시 있어야 한다."""
    positions = {name.strip(): i for i, name in enumerate(header) if name.strip()}
    index = {field: positions[title] for field, title in columns.items() if title in positions}
    missing = [columns[field] for field in ("company", "document") if field not in index]
    if missing:
        raise SheetFormatError(f"시트 1행에 {', '.join(repr(m) for m in missing)} 열이 없습니다.")
    return index


def parse_applications(
    values: list[list[str]],
    columns: dict[str, str],
    stage_values: dict[str, list[str]] | None = None,
) -> list[Application]:
    """시트 값(1행 = 헤더)을 지원 기록 목록으로. 회사가 빈 행은 건너뛴다. (시트는 읽기만 한다)"""
    if not values:
        raise SheetFormatError("데이터 시트가 비어 있습니다.")
    index = header_index(values[0], columns)

    def cell(row: list[str], field: str) -> str:
        col = index.get(field)
        return row[col].strip() if col is not None and col < len(row) else ""

    apps = []
    for offset, row in enumerate(values[1:], start=2):
        company = cell(row, "company")
        if not company:
            continue
        stage_keys = [key for key in STAGE_KEYS if key in index]  # 시트에 실제로 있는 전형 열만
        raw = [classify_stage_value(cell(row, key), stage_values) for key in stage_keys]
        apps.append(
            Application(
                row=offset,
                company=company,
                role=cell(row, "role"),
                channel=cell(row, "channel"),
                employment=cell(row, "employment"),
                document=cell(row, "document"),
                size=cell(row, "size"),
                stages=dict(zip(stage_keys, resolve_stages(raw))),
                applied_raw=cell(row, "applied_at"),
                applied=parse_date(cell(row, "applied_at")),
                note=cell(row, "note"),
            )
        )
    return apps


def normalize_company(name: Any) -> str:
    """같은 회사를 같은 키로: 대소문자·공백 무시."""
    return "".join(str(name).lower().split())
