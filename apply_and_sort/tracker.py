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

    # ---- 읽기

    def check_data_sheet(self) -> None:
        """데이터 탭이 실제로 있는지 확인. 시트 제목을 탭 이름으로 잘못 넣는 경우가 많아 탭 목록을 알려 준다."""
        name = self.config["data_sheet"]
        names = self.sheets.sheet_names()
        if name not in names:
            raise SheetFormatError(
                f"'{name}' 탭이 없어요. 시트 제목이 아니라 아래쪽 탭 이름을 넣어 주세요. "
                f"(이 시트에 있는 탭: {', '.join(names)})"
            )

    def load(self) -> list[Application]:
        self.check_data_sheet()
        return parse_applications(self.sheets.read_values(self.config["data_sheet"]), self.columns)

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
        sheet = self.config["data_sheet"]
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

        self.sheets.update_cells(self.config["data_sheet"], cells)
        return report
