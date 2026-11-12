from apply_and_sort.company import AIError, CompanyInfo
from apply_and_sort.tracker import CACHE_HEADER, Tracker

from .conftest import FakeSheets


class FakeClassifier:
    def __init__(self, results=None, error=None):
        self.results = results or {}
        self.error = error
        self.calls = []

    def classify(self, company, role=""):
        self.calls.append((company, role))
        if self.error:
            raise self.error
        return self.results.get(company, CompanyInfo("알수없음"))


def make_tracker(values, config, cache_rows=None):
    sheets = {"지원현황": values}
    if cache_rows is not None:
        sheets["기업정보"] = [CACHE_HEADER] + cache_rows
    fake = FakeSheets(sheets)
    return Tracker(fake, config), fake


def size_column(fake):
    return fake.sheets["지원현황"][0].index("기업규모")


def test_fill_creates_size_column_and_searches_each_company_once(sample_values, config):
    tracker, fake = make_tracker(sample_values, config)
    classifier = FakeClassifier({"가나다랩": CompanyInfo("중소기업", "IT", "근거"), "라마바전자": CompanyInfo("대기업")})

    report = tracker.fill_sizes(classifier)

    col = size_column(fake)
    sizes = [row[col] for row in fake.sheets["지원현황"][1:5]]
    assert sizes == ["중소기업", "대기업", "알수없음", "중소기업"]
    assert report.filled == 4 and report.searched == 3
    assert [c[0] for c in classifier.calls] == ["가나다랩", "라마바전자", "사아자커머스"]  # 가나다랩은 한 번만
    assert fake.sheets["기업정보"][1][:4] == ["가나다랩", "중소기업", "IT", "근거"]


def test_fill_uses_cache_sheet_first(sample_values, config):
    cache = [["가나다랩", "중견기업", "교육"], [" 라마바 전자 ", "대기업"], ["사아자커머스", "중소기업"]]
    tracker, fake = make_tracker(sample_values, config, cache)
    classifier = FakeClassifier()

    report = tracker.fill_sizes(classifier)

    assert classifier.calls == []
    assert report.searched == 0 and report.filled == 4
    assert fake.sheets["지원현황"][1][size_column(fake)] == "중견기업"


def test_fill_without_classifier_only_uses_cache(sample_values, config):
    tracker, fake = make_tracker(sample_values, config, [["가나다랩", "중견기업"]])

    report = tracker.fill_sizes(None)

    assert report.filled == 2 and report.skipped == 2


def test_fill_skips_rows_that_already_have_size(config):
    values = [["회사", "서류", "기업규모"], ["가나다랩", "합격", "대기업"], ["라마바전자", "", ""]]
    tracker, fake = make_tracker(values, config)
    classifier = FakeClassifier({"라마바전자": CompanyInfo("중소기업")})

    report = tracker.fill_sizes(classifier)

    assert classifier.calls == [("라마바전자", "")]
    assert fake.sheets["지원현황"][1][2] == "대기업"
    assert report.filled == 1


def test_fill_stops_calling_ai_after_error(sample_values, config):
    tracker, _ = make_tracker(sample_values, config)
    classifier = FakeClassifier(error=AIError("AI API 키가 올바르지 않거나 권한이 없습니다."))

    report = tracker.fill_sizes(classifier)

    assert len(classifier.calls) == 1
    assert report.filled == 0 and report.skipped == 4
    assert "키가 올바르지" in report.errors[0]


def test_fill_respects_time_limit(sample_values, config):
    tracker, _ = make_tracker(sample_values, config)
    classifier = FakeClassifier({"가나다랩": CompanyInfo("중소기업")})
    ticks = iter([0, 0, 100, 100, 100])

    report = tracker.fill_sizes(classifier, time_limit=10, clock=lambda: next(ticks))

    assert [c[0] for c in classifier.calls] == ["가나다랩"]
    assert report.filled == 2 and report.skipped == 2


def test_wrong_tab_name_lists_real_tabs(sample_values, config):
    import pytest

    from apply_and_sort.records import SheetFormatError

    config["data_sheet"] = "취준기록"  # 시트 제목을 탭 이름으로 잘못 넣은 경우
    tracker, _ = make_tracker(sample_values, config)

    with pytest.raises(SheetFormatError, match="'취준기록' 탭이 없어요.*지원현황"):
        tracker.summary()


def test_summary_reads_data_sheet(sample_values, config):
    tracker, _ = make_tracker(sample_values, config)

    assert tracker.summary()["overall"]["passed"] == 1
