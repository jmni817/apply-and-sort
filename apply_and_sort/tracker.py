"""시트 읽기 → 기업규모 채우기 → 합격률 집계를 묶는 흐름."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from .company import AIError, CompanyClassifier, CompanyInfo
from .records import Application, SheetFormatError, header_index, normalize_company, parse_applications
from .sheets_client import SheetsClient
from .stats import summarize

log = logging.getLogger(__name__)

CACHE_HEADER = ["회사", "기업규모", "업종", "근거", "확인일"]


@dataclass
class FillReport:
    filled: int = 0  # 기업규모를 채운 행 수
    searched: int = 0  # AI 로 새로 찾은 회사 수
    skipped: int = 0  # 시간 제한·오류로 못 채운 행 수
    errors: list[str] = field(default_factory=list)

    def message(self) -> str:
        text = f"{self.filled}행을 채웠어요 (AI가 새로 찾은 회사 {self.searched}곳)."
        if self.skipped:
            text += f" {self.skipped}행은 못 채웠어요."
        return text


class Tracker:
    def __init__(self, sheets: SheetsClient, config: dict[str, Any]):
        self.sheets = sheets
        self.config = config
        self.columns: dict[str, str] = config["columns"]
        self._data_sheet: str | None = None

    # ---- 읽기

    def data_sheet(self) -> str:
        """지원 기록이 있는 탭을 찾는다: 1행에 '회사'와 '서류' 열이 있는 첫 번째 탭.

        사용자가 탭 이름을 고를 필요가 없도록 헤더를 보고 자동으로 정한다.
        (config.yaml 의 data_sheet 에 조건에 맞는 탭 이름이 있으면 그 탭을 먼저 쓴다)
        """
        if self._data_sheet is None:
            names = self.sheets.sheet_names()
            headers = self.sheets.header_rows(names)
            required = {self.columns["company"], self.columns["document"]}
            candidates = [n for n in names if n != self.config["cache_sheet"] and required <= set(headers.get(n, []))]
            if not candidates:
                raise SheetFormatError(
                    f"1행에 '{self.columns['company']}'와 '{self.columns['document']}' 열이 있는 탭을 찾지 못했어요. "
                    f"(이 시트에 있는 탭: {', '.join(names)})"
                )
            preferred = self.config.get("data_sheet") or ""
            self._data_sheet = preferred if preferred in candidates else candidates[0]
        return self._data_sheet

    def load(self) -> list[Application]:
        return parse_applications(self.sheets.read_values(self.data_sheet()), self.columns)

    def summary(self) -> dict:
        return summarize(self.load())

    def read_cache(self) -> dict[str, CompanyInfo]:
        """기업정보 시트의 {정규화한 회사명: 정보}. 같은 회사가 여러 번 있으면 아래 행이 우선."""
        name = self.config["cache_sheet"]
        if name not in self.sheets.sheet_names():
            return {}
        cache = {}
        for row in self.sheets.read_values(name)[1:]:
            row = row + [""] * (3 - len(row))
            if row[0].strip() and row[1].strip():
                cache[normalize_company(row[0])] = CompanyInfo(row[1].strip(), row[2].strip())
        return cache

    # ---- 기업규모 채우기

    def _size_column(self) -> int:
        """'기업규모' 열 번호. 없으면 헤더 맨 끝에 만든다."""
        sheet = self.data_sheet()
        header = (self.sheets.read_values(sheet) or [[]])[0]
        index = header_index(header, self.columns)
        if "size" in index:
            return index["size"]
        col = len(header)
        self.sheets.update_cells(sheet, [(1, col, self.columns["size"])])
        return col

    def fill_sizes(
        self,
        classifier: CompanyClassifier | None,
        *,
        time_limit: float | None = None,
        progress: Callable[[str], None] = lambda message: None,
        clock: Callable[[], float] = time.monotonic,
    ) -> FillReport:
        """기업규모가 빈 행을 채운다. 기업정보 시트에 있는 회사는 AI 에게 묻지 않는다."""
        report = FillReport()
        size_col = self._size_column()
        apps = [a for a in self.load() if not a.size]
        if not apps:
            return report
        self.sheets.ensure_sheet(self.config["cache_sheet"], CACHE_HEADER)
        cache = self.read_cache()
        start = clock()
        cells: list[tuple[int, int, str]] = []

        for app in apps:
            key = normalize_company(app.company)
            info = cache.get(key)
            if info is None:
                if classifier is None:
                    report.skipped += 1
                    continue
                if time_limit is not None and clock() - start > time_limit:
                    report.skipped += 1
                    continue
                progress(f"{app.company} 확인 중...")
                try:
                    info = classifier.classify(app.company, app.role)
                except AIError as exc:
                    # 키·주소·네트워크 문제는 다음 회사에서도 똑같이 실패하므로 AI 호출을 멈춘다
                    report.errors.append(f"{app.company}: {exc}")
                    report.skipped += 1
                    classifier = None
                    continue
                cache[key] = info
                report.searched += 1
                # 바로 저장해 두면 중간에 멈춰도 다음 실행에서 다시 묻지 않는다
                self.sheets.append_rows(
                    self.config["cache_sheet"],
                    [[app.company, info.size, info.industry, info.reason, date.today().isoformat()]],
                )
            cells.append((app.row, size_col, info.size))
            report.filled += 1

        self.sheets.update_cells(self.data_sheet(), cells)
        return report
