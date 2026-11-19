import pytest

from apply_and_sort.records import StageStatus, classify_stage_value, parse_applications, resolve_stages
from apply_and_sort.stats import format_summary, stage_stats, summarize

S = StageStatus
HEADER = ["회사", "서류", "인적성/AI/과제", "1차면접", "2차면접", "최종 결과"]


def stats_by_key(apps, columns):
    return {s.key: s for s in stage_stats(apps, columns)}


@pytest.mark.parametrize(
    "value, expected",
    [
        ("합격", S.PASS),
        (" 최종 합격 ", S.PASS),
        ("통과", S.PASS),
        ("불합격", S.FAIL),
        ("서류 탈락", S.FAIL),
        ("최종불합격", S.FAIL),
        ("전형 포기", S.DROPPED),
        ("면접포기", S.DROPPED),
        ("진행중", S.PENDING),
        ("결과 대기중", S.PENDING),
        ("예비합격", S.PENDING),  # '합격'이 들어 있어도 예비는 아직 확정이 아님
        ("보류", S.PENDING),
        ("?", S.PENDING),  # 모르는 표기는 대기
        ("-", S.SKIPPED),
        ("해당없음", S.SKIPPED),
        ("N/A", S.SKIPPED),
        ("", None),
        ("   ", None),
    ],
)
def test_classify_stage_value(value, expected):
    assert classify_stage_value(value) == expected


def test_custom_stage_values():
    rules = {"pass": ["합격", "PASS"], "dropped": ["포기", "취소"]}

    assert classify_stage_value("pass", rules) == S.PASS
    assert classify_stage_value("지원 취소", rules) == S.DROPPED


def test_resolve_blank_before_later_record_is_skipped():
    # 서류 합격 → 인적성 빈칸 → 1차면접 불합격: 인적성이 없는 공고
    assert resolve_stages([S.PASS, None, S.FAIL, None, None]) == [S.PASS, S.SKIPPED, S.FAIL, S.NOT_REACHED, S.NOT_REACHED]


def test_resolve_blank_after_pass_without_later_record_is_not_reached():
    # 서류 합격 후 아직 아무것도 없음: 대기로 부풀리지 않고 미진행
    assert resolve_stages([S.PASS, None, None, None, None]) == [S.PASS] + [S.NOT_REACHED] * 4


def test_resolve_explicit_na_does_not_count_as_later_record():
    assert resolve_stages([S.PASS, None, S.SKIPPED, None, None]) == [S.PASS] + [S.NOT_REACHED, S.SKIPPED] + [S.NOT_REACHED] * 2


def test_stage_stats_counts_each_bucket(config):
    values = [
        HEADER,
        ["가", "합격", "", "불합격", "", ""],
        ["나", "합격", "합격", "결과 대기중", "", ""],
        ["다", "합격", "", "전형 포기", "", ""],
        ["라", "합격", "진행중", "", "", ""],
        ["마", "불합격", "", "", "", ""],
        ["바", "", "", "", "", ""],
    ]
    stats = stats_by_key(parse_applications(values, config["columns"]), config["columns"])

    doc = stats["document"]
    assert (doc.passed, doc.failed, doc.not_reached) == (4, 1, 1)
    assert doc.rate == 0.8

    apt = stats["aptitude"]
    assert (apt.passed, apt.pending, apt.skipped, apt.not_reached) == (1, 1, 2, 2)
    assert apt.decided == 1 and apt.rate == 1.0

    i1 = stats["interview1"]
    assert (i1.passed, i1.failed, i1.pending, i1.dropped, i1.not_reached) == (0, 1, 1, 1, 3)
    assert i1.rate == 0.0 and i1.reached == 3

    final = stats["final"]
    assert final.decided == 0 and final.rate is None  # 확정 0건이면 None
    assert final.not_reached == 6


def test_stage_stats_marks_missing_columns(config):
    values = [["회사", "서류", "1차면접"], ["가", "합격", "합격"]]
    stats = stats_by_key(parse_applications(values, config["columns"]), config["columns"])

    assert stats["interview1"].passed == 1 and not stats["interview1"].column_missing
    assert stats["aptitude"].column_missing and stats["final"].column_missing
    assert stats["aptitude"].decided == 0 and stats["aptitude"].rate is None


def test_stage_stats_with_no_rows_does_not_break(config):
    stats = stage_stats([], config["columns"])

    assert [s.title for s in stats] == ["서류", "인적성/AI/과제", "1차면접", "2차면접", "최종 결과"]
    assert all(s.rate is None and not s.column_missing for s in stats)


def test_custom_stage_headers(config):
    config["columns"].update({"interview1": "1차 인터뷰", "final": "최종"})
    values = [["회사", "서류", "1차 인터뷰", "최종"], ["가", "합격", "합격", "최종합격"]]
    stats = stats_by_key(parse_applications(values, config["columns"]), config["columns"])

    assert stats["interview1"].title == "1차 인터뷰" and stats["interview1"].passed == 1
    assert stats["final"].title == "최종" and stats["final"].passed == 1


def test_document_group_stats_unchanged(config):
    # 기존 서류 합격률 집계(정확히 '합격'/'불합격'만 결과로 봄)는 그대로
    values = [HEADER, ["가", "합격", "", "", "", ""], ["나", "결과 대기중", "", "", "", ""]]
    summary = summarize(parse_applications(values, config["columns"]), config["columns"])

    assert summary["overall"]["decided"] == 1 and summary["overall"]["waiting"] == 1
    assert [s["key"] for s in summary["stages"]][0] == "document"


def test_format_summary_includes_stage_table(config):
    values = [HEADER, ["가", "합격", "", "불합격", "", ""], ["나", "불합격", "", "", "", ""]]
    text = format_summary(summarize(parse_applications(values, config["columns"]), config["columns"]))

    assert "[전형별 합격률]" in text
    assert "1차면접" in text and "0/1" in text
    assert "해당없음 1" in text
    assert "[서류 합격률 · 기준별]" in text
