"""새 버전 확인과 원클릭 업데이트.

- GitHub 의 최신 릴리스를 인증 없이 조회한다. User-Agent 에 프로그램 이름·버전만 보내고,
  메일·설정·개인 정보는 보내지 않는다. 어떤 키·토큰도 쓰지 않는다.
- 인터넷이 끊겼거나 응답이 이상하면 조용히 넘어간다. (업데이트 확인 때문에 프로그램이 멈추면 안 됨)
- exe 는 github.com 계열 https 주소에서만 받고, 크기가 릴리스 정보와 같을 때만 저장한다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from . import __version__

log = logging.getLogger(__name__)

REPO = "jmni817/apply-and-sort"
APP_NAME = "apply-and-sort"
EXE_NAME = f"{APP_NAME}.exe"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
ALLOWED_DOWNLOAD_HOSTS = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
CHECK_TIMEOUT = 8
DOWNLOAD_TIMEOUT = 30
CHUNK_SIZE = 256 * 1024
CHECK_INTERVAL = 12 * 60 * 60  # 오래 켜 두면 12시간마다 다시 확인
LAUNCH_DELAY = 1.5  # '설치 완료'를 화면에서 볼 시간
NOTES_LIMIT = 1200

Opener = Callable[..., Any]


class UpdateError(Exception):
    """다운로드 실패 (화면에 그대로 보여 줄 문장)."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str  # "0.2.2"
    tag: str  # "v0.2.2"
    notes: str
    page_url: str
    download_url: str  # exe 에셋이 없으면 ""
    size: int


# ---------------------------------------------------------------- 버전 비교


def parse_version(text: str | None) -> tuple[int, ...] | None:
    """'v0.1.12' → (0, 1, 12). 형식이 이상하면 None."""
    match = re.fullmatch(r"\s*v?(\d+(?:\.\d+)*)\s*", str(text or ""))
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def is_newer(latest: str | None, current: str | None) -> bool:
    """latest 가 current 보다 높을 때만 True. 자릿수가 다르면 0으로 채워 비교하고, 형식이 이상하면 False."""
    new, cur = parse_version(latest), parse_version(current)
    if new is None or cur is None:
        return False
    width = max(len(new), len(cur))
    return new + (0,) * (width - len(new)) > cur + (0,) * (width - len(cur))


def clean_notes(body: str | None) -> str:
    """릴리스 설명에서 '---' 아래(다운로드 안내)를 빼고, 마크다운 기호를 지운 짧은 글로 만든다."""
    text = str(body or "").replace("\r\n", "\n").split("\n---")[0]
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.MULTILINE)
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text if len(text) <= NOTES_LIMIT else text[: NOTES_LIMIT - 1].rstrip() + "…"


# ---------------------------------------------------------------- 확인


def check_latest(current: str = __version__, *, opener: Opener | None = None, timeout: float = CHECK_TIMEOUT) -> UpdateInfo | None:
    """새 버전이 있으면 UpdateInfo, 없거나 확인할 수 없으면 None."""
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(
        LATEST_API,
        headers={"User-Agent": f"{APP_NAME}/{current}", "Accept": "application/vnd.github+json"},
    )
    try:
        with opener(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        tag = str(data["tag_name"])
    except Exception as exc:  # 네트워크·JSON·형식 오류 모두 조용히 넘어감
        log.info("새 버전 확인 실패: %s", exc)
        return None
    if not is_newer(tag, current):
        return None

    download_url, size = "", 0
    for asset in data.get("assets") or []:
        if isinstance(asset, dict) and asset.get("name") == EXE_NAME:
            url = str(asset.get("browser_download_url") or "")
            asset_size = asset.get("size")
            if is_allowed_url(url) and isinstance(asset_size, int) and asset_size > 0:
                download_url, size = url, asset_size
            break
    page_url = str(data.get("html_url") or "")
    if not page_url.startswith(f"https://github.com/{REPO}/"):
        page_url = RELEASES_PAGE
    return UpdateInfo(
        version=".".join(map(str, parse_version(tag) or ())),
        tag=tag,
        notes=clean_notes(data.get("body")),
        page_url=page_url,
        download_url=download_url,
        size=size,
    )


# ---------------------------------------------------------------- 다운로드


def is_allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "") in ALLOWED_DOWNLOAD_HOSTS


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """github.com → 에셋 서버로 넘어가는 리다이렉트도 허용된 호스트일 때만 따라간다."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_allowed_url(newurl):
            raise UpdateError("허용되지 않은 주소로 이동하려고 해서 다운로드를 멈췄어요.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_download_opener() -> Opener:
    return urllib.request.build_opener(_SafeRedirect).open


def download(
    info: UpdateInfo,
    dest: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    opener: Opener | None = None,
    timeout: float = DOWNLOAD_TIMEOUT,
) -> Path:
    """exe 를 dest 로 받는다. '<dest>.part' 에 쓰고 크기가 맞을 때만 이름을 바꾼다."""
    if not is_allowed_url(info.download_url):
        raise UpdateError("GitHub 릴리스 주소가 아니어서 다운로드하지 않았어요.")
    if info.size <= 0:
        raise UpdateError("릴리스에 파일 크기 정보가 없어 다운로드하지 않았어요.")
    opener = opener or _default_download_opener()
    dest = Path(dest)
    part = dest.with_name(dest.name + ".part")
    request = urllib.request.Request(info.download_url, headers={"User-Agent": f"{APP_NAME}/{__version__}"})
    received = 0
    try:
        with opener(request, timeout=timeout) as response:
            final_url = getattr(response, "geturl", lambda: info.download_url)()
            if not is_allowed_url(final_url):
                raise UpdateError("허용되지 않은 주소에서 받으려고 해서 다운로드를 멈췄어요.")
            with open(part, "wb") as out:
                if progress:
                    progress(0, info.size)
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    out.write(chunk)
                    received += len(chunk)
                    if received > info.size:
                        break  # 예상보다 크면 더 받지 않는다
                    if progress:
                        progress(received, info.size)
        if received != info.size:
            raise UpdateError(f"받은 파일 크기가 맞지 않아요. ({received:,} / {info.size:,} 바이트) 다시 시도해 주세요.")
        os.replace(part, dest)
        return dest
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except Exception as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(f"다운로드하지 못했어요: {exc}") from exc


def current_exe() -> Path | None:
    """PyInstaller exe 로 실행 중이면 그 exe 경로, 소스 실행이면 None."""
    return Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None


def _writable(folder: Path) -> bool:
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".aas-write-test-"):
            return True
    except OSError:
        return False


def target_path(version: str, exe: Path | None, downloads: Path | None = None) -> Path:
    """새 exe 저장 위치: 실행 중인 exe 옆, 쓸 수 없으면 다운로드 폴더."""
    name = f"{APP_NAME}-v{version}.exe"
    if exe is not None and _writable(exe.parent):
        return exe.parent / name
    folder = downloads or Path.home() / "Downloads"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


def launch(path: Path) -> None:
    """새 exe 를 독립된 프로세스로 실행한다."""
    env = dict(os.environ)
    # PyInstaller onefile exe 끼리: 새 exe 가 지금 프로그램의 임시 폴더를 이어 쓰지 않고 새로 시작하게 한다
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    for key in [k for k in env if k.startswith("_PYI") or k == "_MEIPASS2"]:
        env.pop(key)
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(path)], cwd=str(path.parent), env=env, close_fds=True, creationflags=flags)


# ---------------------------------------------------------------- 상태 관리


class Updater:
    """대시보드 서버가 쓰는 업데이트 상태. 확인·다운로드는 백그라운드 스레드에서 한다."""

    def __init__(
        self,
        *,
        current: str = __version__,
        checker: Callable[[str], UpdateInfo | None] = check_latest,
        downloader: Callable[..., Path] = download,
        launcher: Callable[[Path], None] = launch,
        exe: Path | None | str = "auto",
        downloads: Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
        on_exit: Callable[[], None] | None = None,
    ):
        self.current = current
        self._checker = checker
        self._downloader = downloader
        self._launcher = launcher
        self._exe = current_exe() if exe == "auto" else exe
        self._downloads = downloads
        self._sleep = sleep
        self.on_exit = on_exit
        self._lock = threading.Lock()
        self.info: UpdateInfo | None = None
        self.dest: Path | None = None
        self.download_state: dict[str, Any] = {"state": "idle", "done": 0, "total": 0, "error": ""}
        self._stop = threading.Event()

    # 확인

    def check_now(self) -> UpdateInfo | None:
        info = self._checker(self.current)
        with self._lock:
            if self.download_state["state"] not in ("downloading", "done"):  # 받는 중에는 정보를 바꾸지 않음
                self.info = info
        return info

    def start_checks(self, interval: float = CHECK_INTERVAL) -> None:
        def loop() -> None:
            while True:
                try:
                    self.check_now()
                except Exception:  # 확인 실패로 스레드가 죽지 않게
                    log.exception("새 버전 확인 중 오류")
                if self._stop.wait(interval):
                    return

        threading.Thread(target=loop, daemon=True, name="update-check").start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def can_install(self) -> bool:
        return self._exe is not None and bool(self.info and self.info.download_url)

    def status(self) -> dict[str, Any] | None:
        info = self.info
        if info is None:
            return None
        return {
            "version": info.version,
            "tag": info.tag,
            "notes": info.notes,
            "page_url": info.page_url,
            "can_install": self.can_install,
            "current_exe": str(self._exe) if self._exe else "",
            "file_name": f"{APP_NAME}-v{info.version}.exe",
            "download": dict(self.download_state),
        }

    # 다운로드 → 실행 → 종료

    def start_download(self) -> None:
        with self._lock:
            if self.download_state["state"] in ("downloading", "done"):
                return  # 이미 받는 중이거나 끝났으면 다시 시작하지 않는다
            if not self.can_install:
                raise ValueError("이 실행 방식에서는 자동 설치를 할 수 없어요. 릴리스 페이지에서 받아 주세요.")
            self.download_state = {"state": "downloading", "done": 0, "total": self.info.size, "error": ""}
        threading.Thread(target=self._download_worker, daemon=True, name="update-download").start()

    def _progress(self, done: int, total: int) -> None:
        self.download_state = {**self.download_state, "done": done, "total": total}

    def _download_worker(self) -> None:
        info = self.info
        try:
            dest = target_path(info.version, self._exe, self._downloads)
            if self._exe is not None and dest.resolve() == Path(self._exe).resolve():
                raise UpdateError("새 파일 이름이 지금 실행 중인 파일과 같아요. 릴리스 페이지에서 직접 받아 주세요.")
            self.dest = self._downloader(info, dest, progress=self._progress)
            self.download_state = {**self.download_state, "state": "done", "done": info.size}
        except Exception as exc:
            log.warning("업데이트 다운로드 실패: %s", exc)
            message = str(exc) if isinstance(exc, UpdateError) else f"다운로드하지 못했어요: {exc}"
            self.download_state = {**self.download_state, "state": "error", "error": message}
            return
        self._sleep(LAUNCH_DELAY)
        try:
            self._launcher(self.dest)
        except Exception as exc:
            log.warning("새 버전 실행 실패: %s", exc)
            self.download_state = {
                **self.download_state,
                "state": "error",
                "error": f"새 버전을 받았지만 실행하지 못했어요. 직접 실행해 주세요: {self.dest}",
            }
            return
        if self.on_exit:
            self.on_exit()
