import pytest

from apply_and_sort.records import SheetFormatError, normalize_company, parse_applications
from apply_and_sort.stats import format_summary, group_stats, summarize


def test_parse_skips_blank_rows_and_keeps_sheet_row_numbers(sample_values, config):
    apps = parse_applications(sample_values, config["columns"])

    assert [a.company for a in apps] == ["가나다랩", "라마바전자", "사아자커머스", "가나다랩"]
    assert [a.row for a in apps] == [2, 3, 4, 5]
    assert apps[0].channel == "간편" and apps[0].is_intern
    assert apps[0].size == ""  # 기업규모 열이 아직 없음


def test_parse_handles_short_rows(config):
    values = [["회사", "서류", "기업규모"], ["가나다랩"]]

    app = parse_applications(values, config["columns"])[0]

    assert app.document == "" and app.size == ""


def test_parse_requires_company_and_document_columns(config):
    with pytest.raises(SheetFormatError, match="'서류'"):
        parse_applications([["회사", "직무"]], config["columns"])
    with pytest.raises(SheetFormatError):
        parse_applications([], config["columns"])


def test_custom_column_names(config):
    config["columns"]["company"] = "기업명"
    apps = parse_applications([["기업명", "서류"], ["가나다랩", "합격"]], config["columns"])

    assert apps[0].company == "가나다랩" and apps[0].document_passed


def test_normalize_company_ignores_case_and_spaces():
    assert normalize_company(" KT is ") == normalize_company("kt  IS")


def test_group_stats_counts_waiting_separately(sample_values, config):
    apps = parse_applications(sample_values, config["columns"])

    stats = {s.name: s for s in group_stats(apps, lambda a: a.channel)}

    assert (stats["간편"].applied, stats["간편"].decided, stats["간편"].passed, stats["간편"].waiting) == (2, 1, 1, 1)
    assert stats["간편"].rate == 1.0
    assert stats["일반"].rate == 0.0


def test_group_stats_rate_is_none_without_results(config):
    apps = parse_applications([["회사", "서류"], ["가나다랩", ""]], config["columns"])

    assert group_stats(apps, lambda a: "전체")[0].rate is None


def test_group_stats_follows_given_order():
    from apply_and_sort.records import Application

    apps = [Application(row=2, company="a", size="중소기업"), Application(row=3, company="b", size="대기업")]

    names = [s.name for s in group_stats(apps, lambda a: a.size, order=["대기업", "중견기업", "중소기업"])]

    assert names == ["대기업", "중소기업"]


def test_summarize_intern_group_excludes_full_time(sample_values, config):
    apps = parse_applications(sample_values, config["columns"])

    summary = summarize(apps)
    groups = {g["title"]: g["rows"] for g in summary["groups"]}

    assert summary["overall"]["applied"] == 4
    assert summary["unclassified"] == 4
    assert sum(r["applied"] for r in groups["기업규모별 · 인턴만"]) == 3


def test_format_summary_mentions_unclassified(sample_values, config):
    text = format_summary(summarize(parse_applications(sample_values, config["columns"])))

    assert "전체: 지원 4건" in text
    assert "[지원형태별]" in text
    assert "apply-and-sort classify" in text
