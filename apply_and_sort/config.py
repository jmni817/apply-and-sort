"""설정 파일(config.yaml) 읽기/쓰기."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """설정 파일이 없거나 형식이 잘못됨."""


DEFAULT_CONFIG: dict[str, Any] = {
    # 구글 시트 주소 (브라우저 주소창의 https://docs.google.com/spreadsheets/d/... 전체)
    "spreadsheet_url": "",
    "data_sheet": "지원현황",
    # 회사별 기업규모를 저장해 두는 시트. 없으면 자동으로 만든다. 사람이 고친 값이 우선.
    "cache_sheet": "기업정보",
    "credentials_path": "credentials.json",
    "token_path": "token.json",
    # 데이터 시트 1행의 헤더 이름. 시트 헤더가 다르면 여기만 바꾸면 된다.
    "columns": {
        "company": "회사",
        "role": "직무",
        "channel": "지원형태",
        "employment": "고용형태",
        "document": "서류",
        "size": "기업규모",
    },
    "claude": {
        "model": "claude-opus-5-5",
        "api_key_path": "claude_api_key.txt",
        # 회사 하나를 분류할 때 허용하는 웹 검색 횟수
        "max_searches": 3,
    },
}

_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def default_config() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_CONFIG)


def load_config(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"설정 파일({path})이 없습니다. `apply-and-sort` 를 실행해 대시보드에서 설정해 주세요.")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"설정 파일 형식 오류: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("설정 파일 최상위는 key: value 형식이어야 합니다.")
    return _deep_merge(DEFAULT_CONFIG, raw)


def save_config(path: str | Path, config: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")


def extract_spreadsheet_id(url_or_id: str) -> str:
    """시트 주소 전체 또는 ID만 받아 ID를 돌려준다."""
    value = (url_or_id or "").strip()
    match = _SHEET_ID_RE.search(value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", value):
        return value
    raise ConfigError("구글 시트 주소를 확인해 주세요. (https://docs.google.com/spreadsheets/d/... 형식)")


def resolve_path(config_path: str | Path, value: str) -> Path:
    """설정 파일 기준 상대 경로를 절대 경로로."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else Path(config_path).resolve().parent / path
