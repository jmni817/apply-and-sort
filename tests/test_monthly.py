from apply_and_sort.monthly import current_stage, month_label, monthly_reports
from apply_and_sort.records import parse_applications

HEADER = ["지원형태", "회사", "직무", "지원일", "서류", "1차면접", "2차면접", "최종 결과", "비고"]


def reports(rows, config, overall=None):
    apps = parse_applications([HEADER, *rows], config["columns"])
    return monthly_reports(apps, config["columns"], overall)


def test_month_label():
    assert month_label(2026, 11) == "26년 11월"
    assert month_label(2027, 1) == "27년 1월"


def test_groups_by_month_newest_first_and_skips_empty_months(config):
    rows = [
        ["간편", "가나다랩", "마케터", "26-09-03", "합격", "", "", "", ""],
        ["일반", "라마바", "기획", "26-11-20", "불합격", "", "", "", ""],
        ["간편", "에이비씨", "PM", "26-11-02", "", "", "", "", ""],
    ]
    result = reports(rows, config)

    assert [m["label"] for m in result["months"]] == ["26년 11월", "26년 9월"]  # 10월은 기록이 없어 빠짐
    assert [a["company"] for a in result["months"][0]["apps"]] == ["라마바", "에이비씨"]  # 최근 지원이 위로
    assert [a["channel"] for a in result["months"][0]["apps"]] == ["일반", "간편"]  # 지원형태도 함께


def test_rows_without_readable_date_are_counted_as_undated(config):
    rows = [
        ["간편", "가나다랩", "마케터", "", "합격", "", "", "", ""],
        ["간편", "라마바", "기획", "미정", "합격", "", "", "", ""],
        ["간편", "에이비씨", "PM", "26-11-02", "합격", "", "", "", ""],
    ]
    result = reports(rows, config)

    assert result["undated"] == 2 and len(result["months"]) == 1


def test_monthly_summary_numbers(config):
    rows = [
        ["간편", "가", "마케터", "26-11-01", "합격", "합격", "결과 대기중", "", ""],
        ["간편", "나", "마케터", "26-11-02", "합격", "불합격", "", "", ""],
        ["일반", "다", "기획", "26-11-03", "불합격", "", "", "", ""],
        ["일반", "라", "기획", "26-11-04", "결과 대기중", "", "", "", ""],
        ["간편", "마", "PM", "26-11-05", "합격", "합격", "합격", "최종합격", ""],
    ]
    m = reports(rows, config)["months"][0]

    assert m["applied"] == 5
    assert m["document"] == {"decided": 4, "passed": 3, "waiting": 1, "rate": 0.75}
    assert m["interviews"] == 5  # 가(1·2차) + 나(1차) + 마(1·2차)
    assert m["final_passed"] == 1


def test_current_stage(config):
    rows = [
        ["", "서류대기", "", "26-11-01", "", "", "", "", ""],
        ["", "서류탈락", "", "26-11-01", "불합격", "", "", "", ""],
        ["", "면접대기", "", "26-11-01", "합격", "진행중", "", "", ""],
        ["", "면접포기", "", "26-11-01", "합격", "면접포기", "", "", ""],
        ["", "최종합격", "", "26-11-01", "합격", "합격", "-", "최종합격", ""],
        ["", "2차합격", "", "26-11-01", "합격", "합격", "합격", "", ""],
    ]
    apps = parse_applications([HEADER, *rows], config["columns"])

    assert [current_stage(a) for a in apps] == [
        ("서류 대기", "pending"),
        ("서류 불합격", "fail"),
        ("1차면접 대기", "pending"),
        ("1차면접 포기", "dropped"),
        ("최종 합격", "pass"),
        ("2차면접 합격", "pass"),
    ]


def test_notes_and_insights(config):
    rows = [
        ["간편", "가", "마케터", "26-11-01", "합격", "결과 대기중", "", "", "면접 12/2"],
        ["간편", "나", "마케터", "26-11-02", "불합격", "", "", "", ""],
        ["일반", "다", "기획", "26-11-03", "불합격", "", "", "", "피드백: 경험 부족"],
        ["간편", "라", "기획", "26-11-04", "", "", "", "", ""],
    ]
    m = reports(rows, config, overall=0.5)["months"][0]

    assert m["notes"] == [{"company": "다", "note": "피드백: 경험 부족"}, {"company": "가", "note": "면접 12/2"}]
    assert m["insights"] == [
        "서류 결과가 나온 3건 중 1건 합격했어요 (33.3%). 전체 평균(50.0%)보다 낮아요.",
        "서류 결과를 기다리는 곳이 1곳 있어요.",
        "면접까지 간 곳: 가",
        "'간편' 지원이 3건으로 가장 많았어요.",
    ]


def test_insights_skip_tie_and_small_sample(config):
    rows = [
        ["간편", "가", "마케터", "26-11-01", "합격", "", "", "", ""],
        ["일반", "나", "마케터", "26-11-02", "불합격", "", "", "", ""],
    ]
    m = reports(rows, config, overall=0.2)["months"][0]

    assert m["insights"] == ["서류 결과가 나온 2건 중 1건 합격했어요 (50.0%)."]  # 3건 미만은 평균 비교 안 함, 동점은 1위 없음


def test_no_apps_gives_empty_list(config):
    assert monthly_reports([], config["columns"]) == {"months": [], "undated": 0}
