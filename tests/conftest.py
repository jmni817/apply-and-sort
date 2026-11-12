from __future__ import annotations

import copy

import pytest

from apply_and_sort.config import default_config

HEADER = ["지원형태", "회사", "직무", "지원일", "고용형태", "서류", "1차면접", "비고"]


class FakeSheets:
    """메모리 위에서 동작하는 SheetsClient 대역."""

    def __init__(self, sheets: dict[str, list[list[str]]], title: str = "취준 기록"):
        self.sheets = copy.deepcopy(sheets)
        self._title = title
        self.appended: list[list[str]] = []

    def title(self) -> str:
        return self._title

    def sheet_names(self) -> list[str]:
        return list(self.sheets)

    def ensure_sheet(self, name: str, header: list[str]) -> None:
        self.sheets.setdefault(name, [list(header)])

    def header_rows(self, sheets: list[str]) -> dict[str, list[str]]:
        return {name: list(self.sheets[name][0]) if self.sheets[name] else [] for name in sheets}

    def read_values(self, sheet: str) -> list[list[str]]:
        return copy.deepcopy(self.sheets[sheet])

    def update_cells(self, sheet: str, cells: list[tuple[int, int, str]]) -> None:
        rows = self.sheets[sheet]
        for row, col, value in cells:
            while len(rows) < row:
                rows.append([])
            target = rows[row - 1]
            while len(target) <= col:
                target.append("")
            target[col] = value

    def append_rows(self, sheet: str, rows: list[list[str]]) -> None:
        self.sheets[sheet].extend(copy.deepcopy(rows))
        self.appended.extend(rows)


@pytest.fixture
def config():
    return default_config()


@pytest.fixture
def sample_values():
    return [
        HEADER,
        ["간편", "가나다랩", "콘텐츠 마케터", "26-11-01", "전환형인턴", "합격", "", ""],
        ["일반", "라마바전자", "브랜드마케팅", "26-10-20", "정규직", "불합격", "", ""],
        ["일반", "사아자커머스", "그로스 마케팅", "26-10-15", "체험형인턴", "불합격", "", ""],
        ["간편", "가나다랩", "퍼포먼스 마케터", "26-10-10", "체험형인턴", "", "", "결과 대기"],
        ["", "", "", "", "", "", "", ""],
    ]
