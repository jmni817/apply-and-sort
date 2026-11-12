"""CLI 진입점: `apply-and-sort [dashboard | auth | summary | classify]`."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, extract_spreadsheet_id, load_config, resolve_path

EXIT_OK, EXIT_PARTIAL, EXIT_FATAL = 0, 1, 2
# PyInstaller 로 만든 exe 로 실행 중인지 여부
FROZEN = bool(getattr(sys, "frozen", False))


def app_data_dir() -> Path:
    """exe 사용자의 설정 폴더. (exe 를 어디에 두든 같은 곳에 저장)"""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "apply-and-sort"


def default_config_path() -> str:
    if os.environ.get("APPLY_AND_SORT_CONFIG"):
        return os.environ["APPLY_AND_SORT_CONFIG"]
    return str(app_data_dir() / "config.yaml") if FROZEN else "config.yaml"


DEFAULT_CONFIG_PATH = default_config_path()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apply-and-sort",
        description="구글 시트 취준 기록을 AI로 정리하고 서류 합격률을 보여주는 대시보드",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="디버그 로그 출력")
    sub = parser.add_subparsers(dest="command")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=DEFAULT_CONFIG_PATH, help=f"설정 파일 경로 (기본: {DEFAULT_CONFIG_PATH})")

    dash = sub.add_parser("dashboard", parents=[common], help="대시보드 열기 (설정도 여기서)")
    dash.add_argument("--port", type=int, default=8766, help="대시보드 포트 (사용 중이면 자동)")
    dash.add_argument("--no-browser", action="store_true", help="브라우저 자동 실행 안 함")
    dash.add_argument("--window", action="store_true", help="브라우저 대신 프로그램 창으로 열기 (exe 더블클릭 시 기본)")

    auth = sub.add_parser("auth", parents=[common], help="터미널에서 구글 로그인만 수행")
    auth.add_argument("--no-browser", action="store_true", help="로그인 주소만 출력")

    sub.add_parser("summary", parents=[common], help="서류 합격률 요약을 터미널에 출력")

    classify = sub.add_parser("classify", parents=[common], help="비어 있는 기업규모 칸을 AI로 채우기")
    classify.add_argument("--time-limit", type=float, default=None, help="AI 호출에 쓸 최대 시간(초)")
    return parser


def _tracker(config_path: str, *, interactive: bool):
    from .sheets_client import SheetsClient
    from .tracker import Tracker

    config = load_config(config_path)
    if not config.get("spreadsheet_url"):
        raise ConfigError("config.yaml 의 spreadsheet_url 이 비어 있어요. 대시보드에서 시트 주소를 저장해 주세요.")
    sheets = SheetsClient.from_files(
        resolve_path(config_path, config["credentials_path"]),
        resolve_path(config_path, config["token_path"]),
        extract_spreadsheet_id(config["spreadsheet_url"]),
        interactive=interactive,
    )
    return Tracker(sheets, config), config


def _cmd_dashboard(args) -> int:
    from .server import serve

    serve(args.config, port=args.port, open_browser=not args.no_browser, window=args.window)
    return EXIT_OK


def _cmd_auth(args) -> int:
    from .config import default_config
    from .sheets_client import load_credentials

    try:
        config = load_config(args.config)
    except ConfigError:
        config = default_config()
    token = resolve_path(args.config, config["token_path"])
    load_credentials(resolve_path(args.config, config["credentials_path"]), token, open_browser=not args.no_browser)
    print(f"구글 계정 연결 완료 (토큰 저장 위치: {token})")
    return EXIT_OK


def _cmd_summary(args) -> int:
    from .stats import format_summary

    tracker, _ = _tracker(args.config, interactive=not os.environ.get("CI"))
    print(format_summary(tracker.summary()))
    return EXIT_OK


def _cmd_classify(args) -> int:
    from .company import load_classifier

    tracker, config = _tracker(args.config, interactive=not os.environ.get("CI"))
    classifier = load_classifier(config, args.config)
    if classifier is None:
        raise ConfigError("AI 연결이 설정되지 않았어요. `apply-and-sort` 대시보드의 4단계에서 API 주소·모델·키를 저장해 주세요.")
    report = tracker.fill_sizes(classifier, time_limit=args.time_limit, progress=print)
    print(report.message())
    for error in report.errors:
        print(f"  - {error}", file=sys.stderr)
    return EXIT_PARTIAL if report.errors else EXIT_OK


def _ensure_output_streams() -> None:
    """창 모드 exe(콘솔 없음)는 stdout/stderr 가 None 이라, 로그 파일로 돌려 기록을 남긴다."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        log_dir = app_data_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        stream = open(log_dir / "apply-and-sort.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    except OSError:
        stream = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def _show_error(message: str) -> None:
    """더블클릭 실행 중 오류를 Windows 메시지 창으로 알린다."""
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "apply-and-sort", 0x10)  # MB_ICONERROR
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    _ensure_output_streams()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # Windows 콘솔에서 한글 출력 오류 방지
        except (AttributeError, ValueError):
            pass
    raw_args = sys.argv[1:] if argv is None else argv
    # 인자 없이 실행(= exe 더블클릭) 하면 대시보드를 연다
    double_clicked = not raw_args
    default = ["dashboard", "--window"] if FROZEN else ["dashboard"]
    args = build_parser().parse_args(raw_args or default)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    from .records import SheetFormatError
    from .sheets_client import AuthError, SheetsApiError

    handlers = {"dashboard": _cmd_dashboard, "auth": _cmd_auth, "summary": _cmd_summary, "classify": _cmd_classify}
    try:
        return handlers[args.command](args)
    except (ConfigError, AuthError, SheetsApiError, SheetFormatError, OSError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        if FROZEN and double_clicked:
            _show_error(f"오류: {exc}")
        return EXIT_FATAL
    except KeyboardInterrupt:
        return EXIT_FATAL


if __name__ == "__main__":
    sys.exit(main())
