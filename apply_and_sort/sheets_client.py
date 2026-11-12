"""Google Sheets API 얇은 wrapper: 인증, 시트 읽기, 셀 쓰기, 행 추가.

이 프로그램은 시트의 행을 지우지 않는다. 쓰는 곳은 데이터 시트의 '기업규모' 열과
기업정보 시트(행 추가)뿐이다.
"""

from __future__ import annotations

import json
import logging
import os
import random
import socket
import time
from pathlib import Path
from typing import Any, Callable

from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

log = logging.getLogger(__name__)

# 내 구글 시트 읽기/쓰기. (드라이브의 다른 파일에는 접근하지 않음)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class AuthError(Exception):
    """OAuth 인증 실패 / 자격증명 파일 문제."""


class SheetsApiError(Exception):
    """재시도 후에도 실패한 Sheets API 호출."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- 인증


def validate_client_secrets(data: Any) -> None:
    """credentials.json 내용이 OAuth '데스크톱 앱' 클라이언트 형식인지 검사."""
    if not isinstance(data, dict):
        raise AuthError("credentials.json 형식이 올바르지 않습니다 (JSON 객체가 아님).")
    if "web" in data and "installed" not in data:
        raise AuthError(
            "'웹 애플리케이션' 유형의 OAuth 클라이언트입니다. "
            "Google Cloud Console에서 '데스크톱 앱' 유형으로 다시 만들어 주세요."
        )
    installed = data.get("installed")
    if not isinstance(installed, dict):
        raise AuthError("credentials.json 에 'installed' 항목이 없습니다 (데스크톱 앱 클라이언트 필요).")
    for key in ("client_id", "client_secret"):
        value = installed.get(key)
        if not value or str(value).startswith("YOUR_"):
            raise AuthError(f"credentials.json 의 {key} 값이 비어 있거나 예시 값입니다.")


def save_private_file(path: Path, content: str) -> None:
    """토큰/키 파일은 소유자만 읽을 수 있게 저장 (POSIX에서 0600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:  # Windows 등
        pass


def load_credentials(
    credentials_path: str | Path,
    token_path: str | Path,
    *,
    interactive: bool = True,
    open_browser: bool = True,
    browser: str | None = None,
    timeout_seconds: int | None = None,
):
    """token.json 이 있으면 재사용(필요 시 refresh), 없으면 브라우저 OAuth 로그인.

    browser: webbrowser 에 등록된 이름. 대시보드는 이를 이용해 로그인 주소를 받아 화면에 보여준다.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    credentials_path, token_path = Path(credentials_path), Path(token_path)
    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except (ValueError, json.JSONDecodeError) as exc:
            log.warning("token.json 을 읽을 수 없어 재인증합니다: %s", exc)

    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_private_file(token_path, creds.to_json())
            return creds
        except RefreshError as exc:
            log.warning("토큰 갱신 실패 (만료/폐기됨): %s", exc)
            creds = None

    if not interactive:
        raise AuthError(f"유효한 토큰({token_path})이 없습니다. 대시보드에서 구글 계정을 먼저 연결해 주세요.")
    if not credentials_path.exists():
        raise AuthError(
            f"OAuth 클라이언트 파일({credentials_path})이 없습니다. 대시보드에서 본인의 credentials.json 을 등록해 주세요."
        )
    try:
        validate_client_secrets(json.loads(credentials_path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise AuthError(f"credentials.json JSON 파싱 실패: {exc}") from exc

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(
        host="localhost",
        port=0,
        open_browser=open_browser,
        browser=browser,
        timeout_seconds=timeout_seconds,
        authorization_prompt_message="브라우저에서 아래 주소로 Google 로그인을 진행하세요:\n{url}",
        success_message="인증이 완료되었습니다. 이 창을 닫고 apply-and-sort 로 돌아가세요.",
    )
    save_private_file(token_path, creds.to_json())
    return creds


def build_service(creds):
    from googleapiclient.discovery import build

    return build("sheets", "v4", credentials=creds, cache_discovery=False)


# --------------------------------------------------------------------------- 재시도


def _api_disabled(error: HttpError) -> bool:
    content = error.content.decode("utf-8", "replace") if isinstance(error.content, bytes) else str(error.content)
    return "SERVICE_DISABLED" in content or "accessNotConfigured" in content


def execute_with_retry(
    request,
    *,
    max_retries: int = 5,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
):
    """Sheets API 요청 실행. 레이트리밋(429)·5xx·네트워크 오류는 지수 백오프로 재시도."""
    for attempt in range(max_retries + 1):
        try:
            return request.execute()
        except RefreshError as exc:  # 토큰 만료/권한 해제 → 재시도해도 소용없음
            raise AuthError(f"구글 로그인이 만료되었거나 권한이 해제되었습니다. 다시 연결해 주세요. ({exc})") from exc
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if status not in RETRYABLE_STATUS or attempt == max_retries:
                if status == 400 and "Unable to parse range" in str(exc):
                    raise SheetsApiError("시트(탭) 이름을 찾지 못했습니다. 3단계의 탭 이름을 확인해 주세요.", status) from exc
                if status == 404:
                    raise SheetsApiError("시트를 찾지 못했습니다. 주소와 시트(탭) 이름을 확인해 주세요.", status) from exc
                if status == 403 and _api_disabled(exc):
                    raise SheetsApiError(
                        "Google Cloud 프로젝트에서 Google Sheets API 가 꺼져 있습니다. "
                        "API 및 서비스 → 라이브러리에서 'Google Sheets API'를 사용으로 바꿔 주세요.",
                        status,
                    ) from exc
                if status == 403:
                    raise SheetsApiError("이 시트에 접근할 권한이 없습니다. 연결한 구글 계정을 확인해 주세요.", status) from exc
                raise SheetsApiError(f"Sheets API 오류 (HTTP {status}): {exc}", status) from exc
            log.debug("Sheets API HTTP %s, 재시도 %d/%d", status, attempt + 1, max_retries)
        except (socket.timeout, TimeoutError, ConnectionError) as exc:
            if attempt == max_retries:
                raise SheetsApiError(f"네트워크 오류: {exc}") from exc
            log.debug("네트워크 오류, 재시도 %d/%d: %s", attempt + 1, max_retries, exc)
        sleep(min(base_delay * (2**attempt), 60.0) + random.uniform(0, 0.5))
    raise AssertionError("unreachable")


# --------------------------------------------------------------------------- 클라이언트


def column_letter(index: int) -> str:
    """0부터 시작하는 열 번호를 A1 표기의 열 이름으로. (0 → A, 26 → AA)"""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def quote_sheet(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


class SheetsClient:
    """스프레드시트 하나를 다루는 wrapper."""

    def __init__(self, service, spreadsheet_id: str, *, max_retries: int = 5, sleep=time.sleep):
        self._service = service
        self.spreadsheet_id = spreadsheet_id
        self._max_retries = max_retries
        self._sleep = sleep

    @classmethod
    def from_files(cls, credentials_path, token_path, spreadsheet_id: str, *, interactive=True):
        creds = load_credentials(credentials_path, token_path, interactive=interactive)
        return cls(build_service(creds), spreadsheet_id)

    def _call(self, request):
        return execute_with_retry(request, max_retries=self._max_retries, sleep=self._sleep)

    @property
    def _sheets(self):
        return self._service.spreadsheets()

    def title(self) -> str:
        data = self._call(self._sheets.get(spreadsheetId=self.spreadsheet_id, fields="properties.title"))
        return data["properties"]["title"]

    def sheet_names(self) -> list[str]:
        data = self._call(self._sheets.get(spreadsheetId=self.spreadsheet_id, fields="sheets.properties.title"))
        return [s["properties"]["title"] for s in data.get("sheets", [])]

    def ensure_sheet(self, name: str, header: list[str]) -> None:
        """시트(탭)가 없으면 만들고 1행에 헤더를 쓴다."""
        if name in self.sheet_names():
            return
        self._call(
            self._sheets.batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": name}}}]},
            )
        )
        self.update_cells(name, [(1, i, value) for i, value in enumerate(header)])

    def header_rows(self, sheets: list[str]) -> dict[str, list[str]]:
        """탭마다 1행(헤더)만 한 번의 요청으로 읽는다."""
        if not sheets:
            return {}
        data = self._call(
            self._sheets.values().batchGet(
                spreadsheetId=self.spreadsheet_id,
                ranges=[f"{quote_sheet(name)}!1:1" for name in sheets],
            )
        )
        rows = {}
        for name, value_range in zip(sheets, data.get("valueRanges", [])):
            values = value_range.get("values") or [[]]
            rows[name] = [str(cell).strip() for cell in values[0]]
        return rows

    def read_values(self, sheet: str) -> list[list[str]]:
        """시트 전체 값 (행마다 길이가 다를 수 있음)."""
        data = self._call(
            self._sheets.values().get(
                spreadsheetId=self.spreadsheet_id,
                range=quote_sheet(sheet),
                valueRenderOption="FORMATTED_VALUE",
            )
        )
        return [[str(cell) for cell in row] for row in data.get("values", [])]

    def update_cells(self, sheet: str, cells: list[tuple[int, int, str]]) -> None:
        """[(행 번호(1부터), 열 번호(0부터), 값), ...] 을 한 번에 쓴다."""
        if not cells:
            return
        data = [
            {"range": f"{quote_sheet(sheet)}!{column_letter(col)}{row}", "values": [[value]]}
            for row, col, value in cells
        ]
        self._call(
            self._sheets.values().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data},
            )
        )

    def append_rows(self, sheet: str, rows: list[list[str]]) -> None:
        if not rows:
            return
        self._call(
            self._sheets.values().append(
                spreadsheetId=self.spreadsheet_id,
                range=f"{quote_sheet(sheet)}!A1",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": rows},
            )
        )
