import io
import json
import threading

import pytest

from apply_and_sort import updates
from apply_and_sort.server import DashboardState
from apply_and_sort.updates import UpdateError, UpdateInfo, Updater, check_latest, clean_notes, download, is_newer

EXE_URL = "https://github.com/jmni817/apply-and-sort/releases/download/v0.3.0/apply-and-sort.exe"


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, url: str = EXE_URL):
        super().__init__(data)
        self._url = url

    def geturl(self):
        return self._url


def release(tag="v0.3.0", assets=None, body="## 새 기능\n- **표**를 `추가`\n\n---\n다운로드 안내"):
    if assets is None:
        assets = [{"name": "apply-and-sort.exe", "browser_download_url": EXE_URL, "size": 10}]
    return {"tag_name": tag, "body": body, "html_url": "https://github.com/jmni817/apply-and-sort/releases/tag/" + tag, "assets": assets}


def opener_for(data, seen=None):
    def opener(request, timeout=None):
        if seen is not None:
            seen.append((request, timeout))
        if isinstance(data, Exception):
            raise data
        return FakeResponse(data if isinstance(data, bytes) else json.dumps(data).encode())

    return opener


INFO = UpdateInfo("0.3.0", "v0.3.0", "노트", "https://github.com/x", EXE_URL, 10)


# ---- 버전 비교


@pytest.mark.parametrize(
    "latest, current, expected",
    [
        ("v0.2.1", "0.2.1", False),  # 같음
        ("v0.2.2", "0.2.1", True),  # 더 높음
        ("v0.1.12", "0.1.9", True),  # 문자열이 아니라 숫자로 비교
        ("v0.2.0", "0.2.1", False),  # 더 낮음
        ("v0.3", "0.2.9", True),  # 자릿수 다름
        ("v0.2", "0.2.0", False),  # 0 채우면 같음
        ("v0.2.0.1", "0.2", True),
        ("latest", "0.2.1", False),  # 이상한 형식
        ("v0.3.0-beta", "0.2.1", False),
        ("", "0.2.1", False),
    ],
)
def test_is_newer(latest, current, expected):
    assert is_newer(latest, current) is expected


def test_clean_notes_strips_markdown_and_download_footer():
    assert clean_notes("## 제목\n- **굵게** `코드`\n\n---\n**다운로드:** 안내") == "제목\n- 굵게 코드"
    long = clean_notes("가" * 2000)
    assert len(long) == 1200 and long.endswith("…")


# ---- 확인


def test_check_latest_returns_info_without_personal_headers():
    seen = []
    info = check_latest("0.2.1", opener=opener_for(release(), seen))

    assert info.version == "0.3.0" and info.tag == "v0.3.0"
    assert info.download_url == EXE_URL and info.size == 10
    assert info.notes == "새 기능\n- 표를 추가"
    request, timeout = seen[0]
    assert timeout == 8
    assert request.full_url == "https://api.github.com/repos/jmni817/apply-and-sort/releases/latest"
    assert request.get_header("User-agent") == "apply-and-sort/0.2.1"
    assert not request.has_header("Authorization") and not request.has_header("Cookie")


def test_check_latest_none_when_not_newer():
    assert check_latest("0.3.0", opener=opener_for(release())) is None


@pytest.mark.parametrize("failure", [OSError("오프라인"), b"not json", {"no_tag": 1}])
def test_check_latest_network_or_format_failure_is_none(failure):
    assert check_latest("0.2.1", opener=opener_for(failure)) is None


def test_check_latest_without_exe_asset_has_no_download_url():
    assets = [{"name": "apply-and-sort-source.zip", "browser_download_url": EXE_URL, "size": 10}]
    info = check_latest("0.2.1", opener=opener_for(release(assets=assets)))

    assert info is not None and info.download_url == "" and info.page_url.startswith("https://github.com/")


def test_check_latest_ignores_asset_on_other_host():
    assets = [{"name": "apply-and-sort.exe", "browser_download_url": "https://evil.example/apply-and-sort.exe", "size": 10}]
    assert check_latest("0.2.1", opener=opener_for(release(assets=assets))).download_url == ""


# ---- 다운로드


def test_download_writes_file_and_reports_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "CHUNK_SIZE", 4)
    calls = []
    dest = download(INFO, tmp_path / "new.exe", progress=lambda d, t: calls.append((d, t)), opener=opener_for(b"0123456789"))

    assert dest.read_bytes() == b"0123456789"
    assert calls == [(0, 10), (4, 10), (8, 10), (10, 10)]
    assert not (tmp_path / "new.exe.part").exists()


@pytest.mark.parametrize(
    "url",
    ["http://github.com/a.exe", "https://evil.example/apply-and-sort.exe", "https://github.com.evil.example/a.exe", ""],
)
def test_download_rejects_disallowed_host(tmp_path, url):
    info = UpdateInfo("0.3.0", "v0.3.0", "", "", url, 10)
    with pytest.raises(UpdateError):
        download(info, tmp_path / "new.exe", opener=opener_for(b"0123456789"))
    assert not (tmp_path / "new.exe").exists()


def test_download_rejects_redirect_to_disallowed_host(tmp_path):
    def opener(request, timeout=None):
        return FakeResponse(b"0123456789", url="https://evil.example/x.exe")

    with pytest.raises(UpdateError):
        download(INFO, tmp_path / "new.exe", opener=opener)
    assert not (tmp_path / "new.exe").exists() and not (tmp_path / "new.exe.part").exists()


@pytest.mark.parametrize("data", [b"short", b"0123456789-too-long"])
def test_download_size_mismatch_removes_part(tmp_path, data):
    with pytest.raises(UpdateError, match="크기"):
        download(INFO, tmp_path / "new.exe", opener=opener_for(data))
    assert not (tmp_path / "new.exe.part").exists() and not (tmp_path / "new.exe").exists()


def test_target_path_next_to_exe_or_downloads(tmp_path, monkeypatch):
    exe = tmp_path / "app" / "apply-and-sort.exe"
    exe.parent.mkdir()
    assert updates.target_path("0.3.0", exe) == exe.parent / "apply-and-sort-v0.3.0.exe"

    monkeypatch.setattr(updates, "_writable", lambda folder: False)
    downloads = tmp_path / "Downloads"
    assert updates.target_path("0.3.0", exe, downloads) == downloads / "apply-and-sort-v0.3.0.exe"


# ---- Updater (서버 상태)


def make_updater(tmp_path, *, exe="frozen", info=INFO, downloader=None, launcher=None, on_exit=None):
    exe_path = None
    if exe == "frozen":
        exe_path = tmp_path / "apply-and-sort.exe"
        exe_path.write_bytes(b"old")
    up = Updater(
        current="0.2.1",
        checker=lambda current: info,
        downloader=downloader or (lambda i, dest, progress: (progress(10, 10), dest.write_bytes(b"new"), dest)[-1]),
        launcher=launcher or (lambda path: None),
        exe=exe_path,
        sleep=lambda s: None,
        on_exit=on_exit,
    )
    up.check_now()
    return up


def wait_until(predicate):
    for _ in range(200):
        if predicate():
            return
        threading.Event().wait(0.01)
    raise AssertionError("시간 안에 끝나지 않음")


def test_can_install_only_when_frozen_with_download_url(tmp_path):
    assert make_updater(tmp_path).can_install is True
    assert make_updater(tmp_path, exe=None).can_install is False  # 소스 실행
    no_exe = UpdateInfo("0.3.0", "v0.3.0", "", "https://github.com/x", "", 0)
    assert make_updater(tmp_path, info=no_exe).can_install is False

    status = make_updater(tmp_path, exe=None).status()
    assert status["can_install"] is False and status["current_exe"] == "" and status["page_url"]


def test_status_is_none_without_update(tmp_path):
    assert make_updater(tmp_path, info=None).status() is None


def test_start_download_refused_when_cannot_install(tmp_path):
    with pytest.raises(ValueError):
        make_updater(tmp_path, exe=None).start_download()


def test_download_then_launch_then_exit(tmp_path):
    launched, exited = [], threading.Event()
    up = make_updater(tmp_path, launcher=launched.append, on_exit=exited.set)
    up.start_download()
    wait_until(exited.is_set)

    assert up.status()["download"]["state"] == "done"
    assert launched == [tmp_path / "apply-and-sort-v0.3.0.exe"]
    assert (tmp_path / "apply-and-sort-v0.3.0.exe").read_bytes() == b"new"


def test_duplicate_download_is_ignored(tmp_path):
    gate, calls = threading.Event(), []

    def slow(info, dest, progress):
        calls.append(dest)
        gate.wait(2)
        dest.write_bytes(b"new")
        return dest

    up = make_updater(tmp_path, downloader=slow)
    up.start_download()
    up.start_download()  # 받는 중: 무시
    gate.set()
    wait_until(lambda: up.download_state["state"] == "done")
    up.start_download()  # 완료 후: 무시
    assert len(calls) == 1


def test_download_failure_sets_error_and_allows_retry(tmp_path):
    def broken(info, dest, progress):
        raise UpdateError("받은 파일 크기가 맞지 않아요.")

    exited = threading.Event()
    up = make_updater(tmp_path, downloader=broken, on_exit=exited.set)
    up.start_download()
    wait_until(lambda: up.download_state["state"] == "error")

    assert "크기" in up.status()["download"]["error"] and not exited.is_set()
    up._downloader = lambda i, dest, progress: (dest.write_bytes(b"new"), dest)[-1]
    up.start_download()  # 실패 뒤에는 다시 시도할 수 있다
    wait_until(exited.is_set)


def test_dashboard_status_includes_update(tmp_path):
    state = DashboardState(tmp_path / "config.yaml", make_updater(tmp_path))
    status = state.status()

    assert status["update"]["version"] == "0.3.0"
    assert status["update"]["download"] == {"state": "idle", "done": 0, "total": 0, "error": ""}
    assert DashboardState(tmp_path / "config.yaml").status()["update"] is None  # 기본은 네트워크 안 씀
