import urllib.error

from apply_and_sort.saramin import (
    SaraminCompany,
    SaraminLookup,
    exact_match,
    normalize_name,
    parse_company_page,
    search_terms,
)


def company_page(name, company_type, industry):
    return (
        f'<script type="application/ld+json">{{"name":"{name} 기업정보",'
        f'"description":"{name} 기업소개 - 업력 : -년차, 기업형태 : {company_type}, 업종 : {industry} | ...",'
        f'"legalName":"{name}"}}</script>'
    )


def search_page(*csns):
    return "".join(f'<a href="/zf_user/company-info/view?csn={c}">회사</a>' for c in csns)


class FakeFetch:
    def __init__(self, pages):
        self.pages = pages
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        for key, html in self.pages.items():
            if key in url:
                if isinstance(html, Exception):
                    raise html
                return html
        return ""


def test_parse_company_page_reads_type_and_industry():
    info = parse_company_page(company_page("(주)발렌라이프", "중소기업", "광고 대행업"))
    assert (info.name, info.company_type, info.industry) == ("(주)발렌라이프", "중소기업", "광고 대행업")


def test_parse_company_page_takes_first_type_when_tagged():
    html = company_page("(주)케이에프씨코리아", "대기업, 1000대기업", "치킨 전문점")
    assert parse_company_page(html).company_type == "대기업"


def test_parse_company_page_without_info_is_none():
    assert parse_company_page("<html>없음</html>") is None


def test_search_terms_split_parentheses():
    assert search_terms("피츠 (블랑네이처)") == ["피츠 (블랑네이처)", "피츠", "블랑네이처"]
    assert search_terms("snow") == ["snow"]


def test_normalize_name_ignores_corp_marks():
    assert normalize_name("(주)발렌라이프") == normalize_name("발렌라이프") == normalize_name("주식회사 발렌 라이프")
    assert normalize_name("스노우(주)") == "스노우"


def test_lookup_collects_candidates_from_search():
    fetch = FakeFetch({
        "searchword=": search_page("A", "B"),
        "csn=A": company_page("(주)발렌라이프", "중소기업", "광고 대행업"),
        "csn=B": company_page("발렌상사", "중소기업", "도매업"),
    })

    results = SaraminLookup(fetch=fetch, sleep=lambda s: None).search("발렌라이프")

    assert [r.name for r in results] == ["(주)발렌라이프", "발렌상사"]
    assert results[0].url.endswith("csn=A")


def test_lookup_takes_candidates_from_each_search_term():
    # 괄호가 든 원래 이름 검색 결과가 많아도, 괄호를 뗀 이름의 결과가 밀려나지 않는다
    fetch = FakeFetch({
        "searchword=%ED%94%BC%EC%B8%A0%20%28": search_page("X1", "X2", "X3", "X4", "X5"),  # '피츠 (블랑네이처)'
        "searchword=%ED%94%BC%EC%B8%A0": search_page("P"),  # '피츠'
        "csn=P": company_page("(주)피츠", "중소기업", "화장품 제조업"),
        "csn=X": company_page("(주)엉뚱한회사", "중견기업", "기타"),
    })

    results = SaraminLookup(fetch=fetch, sleep=lambda s: None).search("피츠 (블랑네이처)")

    assert "(주)피츠" in [r.name for r in results]
    assert exact_match("피츠 (블랑네이처)", results).name == "(주)피츠"


def test_lookup_skips_branch_stores():
    fetch = FakeFetch({
        "searchword=": search_page("A", "B"),
        "csn=A": company_page("케이에프씨(KFC) 아산터미널투자점", "-", "외식업"),
        "csn=B": company_page("케이에프씨동탄호수공원점", "중소기업", "음식점업"),
    })

    assert SaraminLookup(fetch=fetch, sleep=lambda s: None).search("kfC") == []


def test_lookup_returns_empty_on_network_error():
    fetch = FakeFetch({"searchword=": urllib.error.URLError("offline")})

    assert SaraminLookup(fetch=fetch, sleep=lambda s: None).search("발렌라이프") == []


def test_exact_match_handles_corp_marks_and_parentheses():
    candidates = [SaraminCompany("(주)엘티엔터테인먼트", "중견기업"), SaraminCompany("(주)피츠", "중소기업")]

    assert exact_match("피츠 (블랑네이처)", candidates).name == "(주)피츠"
    assert exact_match("snow", [SaraminCompany("스노우(주)", "대기업")]) is None  # 영문·한글이 다르면 AI 가 판단
