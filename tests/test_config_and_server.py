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
    assert config["claude"]["model"] == "claude-opus-5-5"


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
    state.save_settings({"spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit", "data_sheet": "시트1"})
    state.save_claude_key("sk-ant-test-key")
    status = state.status()

    assert status["credentials"] and status["claude_key"] and not status["connected"]
    assert status["data_sheet"] == "시트1"
    assert (tmp_path / "claude_api_key.txt").read_text(encoding="utf-8") == "sk-ant-test-key"
    with pytest.raises(ValueError):
        state.save_claude_key("not-a-key")
    with pytest.raises(ConfigError):
        state.save_settings({"spreadsheet_url": "hello"})

    state.save_claude_key("")
    assert not state.status()["claude_key"]


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

    res, _ = request(server, "GET", "/?token=secret-token")
    assert res.status == 302
    cookie = res.getheader("Set-Cookie").split(";")[0]

    res, body = request(server, "GET", "/api/status", {"Cookie": cookie})
    assert res.status == 200 and json.loads(body)["credentials"] is False

    res, body = request(server, "GET", "/", {"Cookie": cookie})
    assert res.status == 200 and b"apply-and-sort" in body


def test_server_rejects_unknown_host(server):
    res, _ = request(server, "GET", "/?token=secret-token", {"Host": "evil.example:80"})
    assert res.status == 403


def test_server_reports_validation_errors(server):
    cookie = "aas_session=secret-token"
    res, body = request(
        server, "POST", "/api/settings", {"Cookie": cookie, "Content-Type": "application/json"},
        json.dumps({"spreadsheet_url": "nope"}),
    )
    assert res.status == 400 and "시트 주소" in json.loads(body)["error"]
