"""로컬 대시보드 서버.

- 이 PC(127.0.0.1)에서만 열리고, 실행할 때마다 새로 만든 접속 토큰이 있어야 API 를 쓸 수 있다.
- 키·토큰은 설정 파일 옆의 파일에만 저장하고, 화면에는 등록 여부만 보여준다.
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import __version__
from .company import key_path, load_classifier, read_api_key
from .config import ConfigError, default_config, extract_spreadsheet_id, load_config, resolve_path, save_config
from .records import SheetFormatError
from .sheets_client import AuthError, SheetsApiError, SheetsClient, load_credentials, save_private_file, validate_client_secrets
from .tracker import Tracker

log = logging.getLogger(__name__)

COOKIE_NAME = "aas_session"
MAX_BODY = 64 * 1024
CLASSIFY_TIME_LIMIT = 30 * 60  # 한 번 누를 때 최대 30분까지 검색


class _LinkCaptureBrowser(webbrowser.BaseBrowser):
    """Google 로그인 주소를 브라우저로 직접 열지 않고 받아 두는 가짜 브라우저.

    백그라운드 스레드에서 브라우저를 여는 동작은 환경에 따라 조용히 실패하는 경우가 있어,
    주소를 대시보드에 넘겨 페이지(사용자 클릭)에서 새 탭으로 연다.
    """

    def __init__(self, name: str, on_url):
        super().__init__(name)
        self._on_url = on_url

    def open(self, url, new=0, autoraise=True):
        self._on_url(url)
        return True


class DashboardState:
    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)
        self._lock = threading.Lock()
        self.oauth = {"running": False, "error": "", "auth_url": ""}
        self._browser_name = f"apply-and-sort-login-{id(self)}"
        webbrowser.register(self._browser_name, None, _LinkCaptureBrowser(self._browser_name, self._set_auth_url))
        self.job: dict[str, Any] = {"running": False, "log": [], "result": "", "errors": []}

    # ---- 설정

    def config(self) -> dict[str, Any]:
        try:
            return load_config(self.config_path)
        except ConfigError:
            return default_config()

    def _save(self, config: dict[str, Any]) -> None:
        with self._lock:
            save_config(self.config_path, config)

    def credentials_path(self, config=None) -> Path:
        return resolve_path(self.config_path, (config or self.config())["credentials_path"])

    def token_path(self, config=None) -> Path:
        return resolve_path(self.config_path, (config or self.config())["token_path"])

    def status(self) -> dict[str, Any]:
        config = self.config()
        return {
            "version": __version__,
            "credentials": self.credentials_path(config).exists(),
            "connected": self.token_path(config).exists(),
            "spreadsheet_url": config.get("spreadsheet_url", ""),
            "data_sheet": config.get("data_sheet", ""),
            "claude_key": bool(read_api_key(config, self.config_path)),
            "oauth": dict(self.oauth),
        }

    def save_credentials(self, text: str) -> None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("JSON 파일이 아니에요. Google Cloud 에서 받은 credentials.json 을 그대로 넣어 주세요.") from exc
        validate_client_secrets(data)
        save_private_file(self.credentials_path(), json.dumps(data, ensure_ascii=False, indent=2))
        if not self.config_path.exists():
            self._save(self.config())

    def save_settings(self, payload: dict[str, Any]) -> None:
        config = self.config()
        url = str(payload.get("spreadsheet_url") or "").strip()
        extract_spreadsheet_id(url)  # 형식 확인
        config["spreadsheet_url"] = url
        sheet = str(payload.get("data_sheet") or "").strip()
        if sheet:
            config["data_sheet"] = sheet
        self._save(config)

    def save_claude_key(self, key: str) -> None:
        config = self.config()
        path = key_path(config, self.config_path)
        key = key.strip()
        if not key:
            path.unlink(missing_ok=True)
            return
        if not key.startswith("sk-ant-"):
            raise ValueError("Claude API 키는 sk-ant- 로 시작해요. console.anthropic.com 에서 만든 키를 넣어 주세요.")
        save_private_file(path, key)
        if not self.config_path.exists():
            self._save(config)

    # ---- 구글 로그인

    def _set_auth_url(self, url: str) -> None:
        self.oauth = {"running": True, "error": "", "auth_url": url}

    def start_oauth(self) -> None:
        if self.oauth["running"]:
            return  # 이미 대기 중: 화면에 있는 로그인 링크를 그대로 쓰면 된다
        if not self.credentials_path().exists():
            raise ValueError("먼저 1단계에서 credentials.json 을 등록해 주세요.")
        self.oauth = {"running": True, "error": "", "auth_url": ""}
        threading.Thread(target=self._oauth_worker, daemon=True).start()

    def _oauth_worker(self) -> None:
        config = self.config()
        try:
            load_credentials(
                self.credentials_path(config),
                self.token_path(config),
                browser=self._browser_name,
                timeout_seconds=300,
            )
            self.oauth = {"running": False, "error": "", "auth_url": ""}
        except BaseException as exc:  # 로그인 창을 닫거나 5분이 지나는 경우 포함. '대기 중'으로 멈춰 있지 않게 한다
            log.warning("OAuth 실패: %s", exc)
            message = str(exc) or "5분 안에 로그인이 끝나지 않았어요. [구글 계정 연결]을 다시 눌러 주세요."
            self.oauth = {"running": False, "error": message, "auth_url": ""}

    def disconnect(self) -> None:
        self.token_path().unlink(missing_ok=True)

    # ---- 시트

    def tracker(self) -> Tracker:
        config = self.config()
        if not config.get("spreadsheet_url"):
            raise ConfigError("구글 시트 주소를 먼저 저장해 주세요.")
        sheets = SheetsClient.from_files(
            self.credentials_path(config),
            self.token_path(config),
            extract_spreadsheet_id(config["spreadsheet_url"]),
            interactive=False,
        )
        return Tracker(sheets, config)

    def summary(self) -> dict[str, Any]:
        tracker = self.tracker()
        return {"title": tracker.sheets.title(), **tracker.summary()}

    def start_classify(self) -> None:
        with self._lock:
            if self.job["running"]:
                return
            self.job = {"running": True, "log": [], "result": "", "errors": []}
        threading.Thread(target=self._classify_worker, daemon=True).start()

    def _classify_worker(self) -> None:
        def progress(message: str) -> None:
            self.job["log"] = (self.job["log"] + [message])[-50:]

        try:
            config = self.config()
            classifier = load_classifier(config, self.config_path)
            report = self.tracker().fill_sizes(classifier, time_limit=CLASSIFY_TIME_LIMIT, progress=progress)
            result = report.message()
            if classifier is None and report.skipped:
                result += " Claude API 키를 등록하면 처음 보는 회사도 자동으로 검색해요."
            self.job.update(result=result, errors=report.errors)
        except (ConfigError, AuthError, SheetsApiError, SheetFormatError) as exc:
            self.job.update(result="", errors=[str(exc)])
        except Exception as exc:
            log.exception("기업규모 채우기 실패")
            self.job.update(result="", errors=[f"예상하지 못한 오류: {exc}"])
        finally:
            self.job["running"] = False


# --------------------------------------------------------------------------- HTTP


def _make_handler(state: DashboardState, access_token: str, allowed_hosts: set[str], stop: threading.Event):
    web = resources.files("apply_and_sort").joinpath("web")
    page = web.joinpath("dashboard.html").read_bytes()
    icon = web.joinpath("icon.png").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        server_version = "apply-and-sort"

        def log_message(self, fmt, *args):
            log.debug("%s - " + fmt, self.address_string(), *args)

        def _send(self, status: int, body: bytes, content_type: str, extra_headers=()) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for name, value in extra_headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: dict[str, Any]) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _host_ok(self) -> bool:
            # DNS rebinding 방지: 우리가 연 주소로 들어온 요청만 받는다
            return self.headers.get("Host", "") in allowed_hosts

        def _cookie_ok(self) -> bool:
            try:
                cookie = SimpleCookie(self.headers.get("Cookie", ""))
            except CookieError:
                return False
            morsel = cookie.get(COOKIE_NAME)
            return bool(morsel) and hmac.compare_digest(morsel.value, access_token)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError("요청이 너무 커요.")
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("잘못된 요청이에요.")
            return data

        def do_GET(self):
            if not self._host_ok():
                return self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
            url = urlparse(self.path)
            if url.path == "/icon.png":  # 캐릭터 이미지 (공개해도 되는 정적 파일)
                return self._send(HTTPStatus.OK, icon, "image/png")
            if url.path == "/":
                token = parse_qs(url.query).get("token", [""])[0]
                if token and hmac.compare_digest(token, access_token):
                    cookie = f"{COOKIE_NAME}={access_token}; HttpOnly; SameSite=Strict; Path=/"
                    return self._send(HTTPStatus.FOUND, b"", "text/plain", [("Location", "/"), ("Set-Cookie", cookie)])
                if not self._cookie_ok():
                    return self._send(HTTPStatus.FORBIDDEN, "프로그램을 다시 실행해 주세요.".encode(), "text/plain; charset=utf-8")
                return self._send(HTTPStatus.OK, page, "text/html; charset=utf-8")
            if not self._cookie_ok():
                return self._json(HTTPStatus.FORBIDDEN, {"error": "접속 토큰이 없어요. 프로그램을 다시 실행해 주세요."})
            try:
                if url.path == "/api/status":
                    return self._json(HTTPStatus.OK, state.status())
                if url.path == "/api/summary":
                    return self._json(HTTPStatus.OK, state.summary())
                if url.path == "/api/job":
                    return self._json(HTTPStatus.OK, state.job)
            except (ConfigError, AuthError, SheetsApiError, SheetFormatError) as exc:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok() or not self._cookie_ok():
                return self._json(HTTPStatus.FORBIDDEN, {"error": "접속 토큰이 없어요. 프로그램을 다시 실행해 주세요."})
            path = urlparse(self.path).path
            try:
                payload = self._read_json()
                if path == "/api/credentials":
                    state.save_credentials(str(payload.get("text") or ""))
                elif path == "/api/settings":
                    state.save_settings(payload)
                elif path == "/api/claude-key":
                    state.save_claude_key(str(payload.get("key") or ""))
                elif path == "/api/connect":
                    state.start_oauth()
                elif path == "/api/disconnect":
                    state.disconnect()
                elif path == "/api/classify":
                    state.start_classify()
                elif path == "/api/quit":
                    self._json(HTTPStatus.OK, {"ok": True})
                    stop.set()
                    return
                else:
                    return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except (ValueError, ConfigError, AuthError) as exc:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return self._json(HTTPStatus.OK, {"ok": True, "status": state.status()})

    return Handler


def serve(config_path: str | Path, *, port: int = 8766, open_browser: bool = True, window: bool = False) -> None:
    state = DashboardState(config_path)
    access_token = secrets.token_urlsafe(32)
    stop = threading.Event()
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), None)
    except OSError:  # 포트가 사용 중이면 아무 빈 포트
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    actual = httpd.server_address[1]
    allowed = {f"127.0.0.1:{actual}", f"localhost:{actual}"}
    httpd.RequestHandlerClass = _make_handler(state, access_token, allowed, stop)
    url = f"http://127.0.0.1:{actual}/?token={access_token}"

    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"apply-and-sort 대시보드: http://127.0.0.1:{actual}/  (종료: Ctrl+C 또는 화면의 [종료])")
    try:
        if window and _open_window(url, stop):
            return
        if open_browser:
            webbrowser.open(url)
        else:
            print(f"브라우저에서 이 주소를 여세요: {url}")
        stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()


def _open_window(url: str, stop: threading.Event) -> bool:
    """pywebview 가 있으면 프로그램 창으로 연다. 창을 닫으면 종료. 없으면 False."""
    try:
        import webview
    except ImportError:
        return False
    win = webview.create_window("apply-and-sort", url, width=1180, height=860, min_size=(420, 600))
    stop_watcher = threading.Thread(target=lambda: (stop.wait(), win.destroy()), daemon=True)
    stop_watcher.start()
    webview.start()
    return True
