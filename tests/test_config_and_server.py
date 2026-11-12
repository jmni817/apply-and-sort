import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from apply_and_sort.config import ConfigError, extract_spreadsheet_id, load_config, save_config
from apply_and_sort.server import DashboardState, _make_handler
from apply_and_sort.sheets_client import AuthError, column_letter, validate_client_secrets

SHEET_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_abcd"
CLIENT = {"installed": {"client_id": "abc.apps.googleusercontent.com", "client_secret": "secret"}}


def test_extract_spreadsheet_id_from_url_or_id():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit?gid=0#gid=0"
    assert extract_spreadsheet_id(url) == SHEET_ID
    assert extract_spreadsheet_id(SHEET_ID) == SHEET_ID
    with pytest.raises(ConfigError):
        extract_spreadsheet_id("https://example.com")


def test_config_roundtrip_keeps_defaults(tmp_path):
    path = tmp_path / "config.yaml"
    save_config(path, {"spreadsheet_url": "x", "columns": {"company": "기업명"}})

    config = load_config(path)

    assert config["columns"]["company"] == "기업명"
    assert config["columns"]["document"] == "서류"
    assert config["llm"]["api_key_path"] == "llm_api_key.txt"


def test_load_config_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "none.yaml")


def test_column_letter():
    assert [column_letter(i) for i in (0, 25, 26, 27, 701)] == ["A", "Z", "AA", "AB", "ZZ"]


def test_validate_client_secrets():
    validate_client_secrets(CLIENT)
    with pytest.raises(AuthError, match="웹 애플리케이션"):
        validate_client_secrets({"web": {}})
    with pytest.raises(AuthError):
        validate_client_secrets({"installed": {"client_id": "YOUR_ID", "client_secret": "x"}})


def test_state_saves_settings_and_keys(tmp_path):
    state = DashboardState(tmp_path / "config.yaml")

    state.save_credentials(json.dumps(CLIENT))
    found = state.save_settings({"spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"})
    state.save_llm({"base_url": "http://127.0.0.1:31415/v1", "model": "auto", "api_key": "test-key"})
    status = state.status()

    assert found == ""  # 구글 계정 연결 전에는 기록 탭을 찾지 않고 주소만 저장
    assert status["credentials"] and not status["connected"]
    assert status["spreadsheet_url"].endswith("/edit")
    assert status["llm"] == {"base_url": "http://127.0.0.1:31415/v1", "model": "auto", "has_key": True, "ready": True}
    assert "test-key" not in json.dumps(status)  # 키 자체는 화면으로 보내지 않음
    assert (tmp_path / "llm_api_key.txt").read_text(encoding="utf-8") == "test-key"
    assert "test-key" not in (tmp_path / "config.yaml").read_text(encoding="utf-8")
    with pytest.raises(ConfigError):
        state.save_settings({"spreadsheet_url": "hello"})


def test_state_llm_keeps_saved_key_when_blank(tmp_path):
    state = DashboardState(tmp_path / "config.yaml")
    state.save_llm({"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "api_key": "first"})

    state.save_llm({"base_url": "https://api.openai.com/v1", "model": "gpt-4.1-mini", "api_key": ""})

    assert (tmp_path / "llm_api_key.txt").read_text(encoding="utf-8") == "first"
    assert state.status()["llm"]["model"] == "gpt-4.1-mini"


def test_state_llm_is_required(tmp_path):
    state = DashboardState(tmp_path / "config.yaml")
    assert state.status()["llm"]["ready"] is False

    with pytest.raises(ValueError, match="API 주소"):
        state.save_llm({"base_url": "", "model": "auto", "api_key": "k"})
    with pytest.raises(ValueError, match="모델 이름"):
        state.save_llm({"base_url": "https://api.openai.com/v1", "model": "", "api_key": "k"})
    with pytest.raises(ValueError, match="API 키"):
        state.save_llm({"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"})
    with pytest.raises(ValueError, match="https"):
        state.save_llm({"base_url": "http://example.com/v1", "model": "m", "api_key": "k"})
    with pytest.raises(ValueError, match="공백"):
        state.save_llm({"base_url": "https://api.openai.com/v1", "model": "m", "api_key": "a b"})
    with pytest.raises(ValueError, match="먼저 저장"):
        state.test_llm()
    assert not (tmp_path / "llm_api_key.txt").exists()


@pytest.fixture
def server(tmp_path):
    state = DashboardState(tmp_path / "config.yaml")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    stop = threading.Event()
    httpd.RequestHandlerClass = _make_handler(state, "secret-token", {f"127.0.0.1:{port}"}, stop)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield port
    httpd.shutdown()


def request(port, method, path, headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request(method, path, body=body, headers=headers or {})
    res = conn.getresponse()
    return res, res.read()


def test_server_requires_access_token(server):
    res, _ = request(server, "GET", "/api/status")
    assert res.status == 403

    res, _ = request(server, "GET", "/?token=wrong")
    assert res.status == 403

    res, _ = request(server, "GET", "/")
    assert res.status == 403

    # 첫 접속: 리다이렉트 없이 바로 페이지를 주고, 토큰을 페이지에 심는다 (프로그램 창에서도 동작)
    res, body = request(server, "GET", "/?token=secret-token")
    assert res.status == 200
    assert b'<meta name="aas-token" content="secret-token">' in body
    cookie = res.getheader("Set-Cookie").split(";")[0]

    res, body = request(server, "GET", "/api/status", {"X-AAS-Token": "secret-token"})
    assert res.status == 200 and json.loads(body)["credentials"] is False
    res, _ = request(server, "GET", "/api/status", {"X-AAS-Token": "wrong"})
    assert res.status == 403

    # 새로고침: 쿠키로도 열린다
    res, body = request(server, "GET", "/", {"Cookie": cookie})
    assert res.status == 200 and b"apply-and-sort" in body
    res, _ = request(server, "GET", "/api/status", {"Cookie": cookie})
    assert res.status == 200


def test_server_serves_icon_without_token(server):
    res, body = request(server, "GET", "/icon.png")
    assert res.status == 200 and res.getheader("Content-Type") == "image/png"
    assert body.startswith(b"\x89PNG")


def test_server_rejects_unknown_host(server):
    res, _ = request(server, "GET", "/?token=secret-token", {"Host": "evil.example:80"})
    assert res.status == 403


def test_server_reports_validation_errors(server):
    res, body = request(
        server, "POST", "/api/settings", {"X-AAS-Token": "secret-token", "Content-Type": "application/json"},
        json.dumps({"spreadsheet_url": "nope"}),
    )
    assert res.status == 400 and "시트 주소" in json.loads(body)["error"]
