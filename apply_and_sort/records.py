"""시트의 행을 지원 기록(Application)으로 바꾸기."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PASS, FAIL = "합격", "불합격"


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


def parse_applications(values: list[list[str]], columns: dict[str, str]) -> list[Application]:
    """시트 값(1행 = 헤더)을 지원 기록 목록으로. 회사가 빈 행은 건너뛴다."""
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
        apps.append(
            Application(
                row=offset,
                company=company,
                role=cell(row, "role"),
                channel=cell(row, "channel"),
                employment=cell(row, "employment"),
                document=cell(row, "document"),
                size=cell(row, "size"),
            )
        )
    return apps


def normalize_company(name: Any) -> str:
    """같은 회사를 같은 키로: 대소문자·공백 무시."""
    return "".join(str(name).lower().split())
