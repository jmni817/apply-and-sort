from datetime import date

import pytest

from apply_and_sort.records import parse_applications, parse_date


@pytest.mark.parametrize(
    "value, expected",
    [
        ("26-11-01", date(2026, 11, 1)),
        ("2026-11-01", date(2026, 11, 1)),
        ("2026.11.01", date(2026, 11, 1)),
        ("2026. 11. 1.", date(2026, 11, 1)),  # 구글 시트 한국어 날짜 서식
        ("26년 11월 1일", date(2026, 11, 1)),
        ("2026/1/5", date(2026, 1, 5)),
        (" 26-10-20 ", date(2026, 10, 20)),
        ("26-13-01", None),  # 없는 달
        ("26-02-30", None),  # 없는 날
        ("11/01", None),  # 연도 없음
        ("미정", None),
        ("", None),
    ],
)
def test_parse_date(value, expected):
    assert parse_date(value) == expected


def test_parse_applications_reads_applied_date_and_note(sample_values, config):
    apps = parse_applications(sample_values, config["columns"])

    first, last = apps[0], apps[-1]
    assert first.applied == date(2026, 11, 1) and first.applied_raw == "26-11-01"
    assert last.note == "결과 대기"


def test_missing_date_and_note_columns_are_optional(config):
    apps = parse_applications([["회사", "서류"], ["가나다랩", "합격"]], config["columns"])

    assert apps[0].applied is None and apps[0].applied_raw == "" and apps[0].note == ""
